import asyncio
import json
from typing import Dict, Set, Optional
from uuid import UUID, uuid4 # Import uuid4

from pydantic import BaseModel # Added for Pydantic models

from fastapi import WebSocket, WebSocketDisconnect
import redis.asyncio as redis
from redis.asyncio.client import PubSub # Correct import for PubSub type

from backend.core.logging import get_logger

websocket_logger = get_logger('websocket')

# Enhanced WebSocket manager with Redis Pub/Sub
class WebSocketManager:
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.active_connections: Dict[UUID, Set[WebSocket]] = {}
        self.logger = websocket_logger
        self.redis_client = redis_client
        self._listener_task: Optional[asyncio.Task] = None
        self._pubsub: Optional[PubSub] = None

    def _get_channel_name(self, notebook_id: UUID) -> str:
        """Generates the Redis channel name for a given notebook."""
        return f"ws:notebook:{notebook_id}"

    async def connect(self, websocket: WebSocket, notebook_id: UUID):
        """Accepts a WebSocket connection and adds it to the local pool for this worker."""
        await websocket.accept()
        if notebook_id not in self.active_connections:
            self.active_connections[notebook_id] = set()
        self.active_connections[notebook_id].add(websocket)
        self.logger.info(
            "WebSocket connected locally",
            extra={'notebook_id': str(notebook_id), 'client': websocket.client}
        )
        # Note: Subscription to Redis happens globally in start_listener

    def disconnect(self, websocket: WebSocket, notebook_id: UUID):
        """Removes a WebSocket connection from the local pool."""
        if notebook_id in self.active_connections:
            self.active_connections[notebook_id].discard(websocket) # Use discard for safety
            if not self.active_connections[notebook_id]:
                del self.active_connections[notebook_id]
                self.logger.info(f"Last local WebSocket disconnected for notebook {notebook_id}, removing entry.")
            else:
                 self.logger.info(
                    "WebSocket disconnected locally",
                    extra={'notebook_id': str(notebook_id), 'client': websocket.client}
                 )
        else:
             self.logger.debug( # Changed to debug as it might just be a different worker
                f"Attempted local disconnect for WebSocket from notebook ID {notebook_id} not managed by this worker.",
                extra={'notebook_id': str(notebook_id)}
            )

    async def broadcast(self, notebook_id: UUID, message_payload: Dict): # Renamed message to message_payload
        """Publish a message to the Redis channel for the specific notebook."""
        if not self.redis_client:
            self.logger.error("Redis client not available, cannot broadcast message via Pub/Sub.")
            return

        # Ensure message_payload is a dictionary (it should be from model_dump)
        if not isinstance(message_payload, dict):
            self.logger.error(f"Broadcast message_payload is not a dict: {type(message_payload)}. Skipping broadcast.")
            return

        # Add a unique message ID to the envelope
        # The original message_payload (e.g., cell data) is wrapped.
        # The frontend currently expects the raw cell data directly in `message.data` for `cell_update`.
        # So, the `message_payload` itself should be what's in `event.data`.
        # The `type` (e.g., "cell_update") is usually part of the `message_payload` already.
        # Let's ensure the structure sent to Redis is what the frontend expects, plus our debug ID.
        
        # The frontend's useWebSocket.ts expects: { type: string, [key: string]: any }
        # And useInvestigationEvents.ts expects: { type: "cell_update", data: CellData }
        # The notify_callback in NotebookManager sends the CellData directly.
        # So, we need to wrap this CellData.

        # Let's assume the `message_payload` IS the `data` part of a "cell_update" event.
        # The `type` like "cell_update" is added by the caller of notify_callback or needs to be.
        # NotebookManager calls: self.notify_callback(notebook_id, updated_cell_model.model_dump(mode='json'))
        # This means `message_payload` is the cell data.
        # The WebSocketManager should construct the full event structure.

        # Let's assume the `message_payload` is the *entire* message including its type.
        # Example: message_payload = {"type": "cell_update", "data": {...cell_data...}}
        # If not, this needs adjustment where notify_callback is called.
        # For now, let's assume `message_payload` is the full event.
        
        event_to_send = {
            **message_payload, # Spread the original event (e.g. {"type": "cell_update", "data": ...})
            "ws_message_id": str(uuid4()) # Add our unique ID
        }

        channel_name = self._get_channel_name(notebook_id)
        message_json = json.dumps(event_to_send)
        try:
            await self.redis_client.publish(channel_name, message_json)
            self.logger.info(f"Published message to Redis channel '{channel_name}' for notebook {notebook_id} with ws_message_id: {event_to_send['ws_message_id']}")
        except redis.RedisError as e:
            self.logger.error(f"Failed to publish message to Redis channel '{channel_name}': {e}", exc_info=True)
        except Exception as e:
             self.logger.error(f"Unexpected error publishing message to Redis channel '{channel_name}': {e}", exc_info=True)

    async def _send_to_local_clients(self, notebook_id: UUID, message_json: str):
        """Sends a message received from Redis to locally connected clients for a notebook."""
        if notebook_id not in self.active_connections:
             # This is expected if no clients for this notebook are connected to *this* worker
             self.logger.debug(f"No local clients connected for notebook {notebook_id} on this worker. Skipping send.")
             return

        disconnected_clients = set()
        # Create a list of tasks for sending messages to local clients
        tasks = []
        
        # Iterate over a copy of the set to allow modification during iteration
        # Use .get() for safety, though check already happened
        connections = list(self.active_connections.get(notebook_id, set()))
        self.logger.debug(f"Sending message via Redis to {len(connections)} local clients for notebook {notebook_id}")
        
        for connection in connections:
            tasks.append(self._send_message(connection, message_json, notebook_id, disconnected_clients))

        # Wait for all send tasks to complete
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                 if isinstance(result, Exception):
                      self.logger.error(f"Error sending message to local client {connections[i].client}: {result}", exc_info=result)

        # Remove disconnected clients from this worker's pool
        if disconnected_clients:
            self.logger.info(f"Removing {len(disconnected_clients)} disconnected local clients for notebook {notebook_id}")
            if notebook_id in self.active_connections:
                 self.active_connections[notebook_id].difference_update(disconnected_clients)
                 if not self.active_connections[notebook_id]:
                     del self.active_connections[notebook_id]

    async def _redis_listener(self):
        """Listens for messages on subscribed Redis channels and forwards them."""
        if not self.redis_client:
             self.logger.error("Redis client not configured. Cannot start Redis listener.")
             return

        try:
            self._pubsub = self.redis_client.pubsub(ignore_subscribe_messages=True)
            # Subscribe to a pattern matching all notebook channels
            await self._pubsub.psubscribe("ws:notebook:*")
            self.logger.info("WebSocketManager Redis listener subscribed to 'ws:notebook:*'")

            while True:
                try:
                    message = await self._pubsub.get_message(timeout=1.0) # Use timeout to allow periodic checks/exit
                    if message and isinstance(message, dict) and message.get("type") == "pmessage":
                        channel = message.get("channel")
                        data = message.get("data")
                        if channel and data:
                             self.logger.debug(f"Received message from Redis channel: {channel}")
                             try:
                                 # Extract notebook_id from channel name ws:notebook:<uuid>
                                 notebook_id_str = channel.split(':')[-1]
                                 notebook_id = UUID(notebook_id_str)
                                 # Send to local clients connected to this worker for this notebook
                                 await self._send_to_local_clients(notebook_id, data)
                             except (ValueError, IndexError) as e:
                                 self.logger.error(f"Could not parse notebook ID from channel '{channel}': {e}")
                             except Exception as e_inner:
                                 self.logger.error(f"Error processing message from Redis channel '{channel}': {e_inner}", exc_info=True)
                    # Add a small sleep to prevent tight looping if timeout is very short or None
                    await asyncio.sleep(0.01)
                except asyncio.CancelledError:
                     self.logger.info("Redis listener task cancelled.")
                     break
                except redis.RedisError as e:
                    self.logger.error(f"Redis error in listener loop: {e}. Attempting to reconnect/resubscribe...", exc_info=True)
                    # Implement basic reconnection logic
                    await asyncio.sleep(5) # Wait before retrying
                    try:
                        if self._pubsub: 
                            await self._pubsub.punsubscribe("ws:notebook:*")  # Attempt unsubscribe first
                        if not self.redis_client:
                             self.logger.error("Redis client unavailable during reconnect attempt.")
                             break
                        self._pubsub = self.redis_client.pubsub(ignore_subscribe_messages=True)
                        if self._pubsub:
                            await self._pubsub.psubscribe("ws:notebook:*")
                            self.logger.info("Re-subscribed to Redis channels after error.")
                        else:
                            self.logger.error("Failed to create PubSub object during reconnect attempt.")
                            break
                    except Exception as recon_e:
                         self.logger.error(f"Failed to re-subscribe to Redis after error: {recon_e}. Stopping listener.", exc_info=True)
                         break # Exit loop if reconnection fails badly
                except Exception as e:
                    self.logger.error(f"Unexpected error in Redis listener loop: {e}. Stopping listener.", exc_info=True)
                    break # Exit loop on unexpected errors
        finally:
            if self._pubsub:
                 try:
                     await self._pubsub.punsubscribe()
                     await self._pubsub.close()
                     self.logger.info("Redis PubSub connection closed.")
                 except Exception as e_close:
                      self.logger.error(f"Error closing Redis PubSub connection: {e_close}", exc_info=True)
            self._pubsub = None

    async def start_listener(self):
        """Starts the Redis listener background task."""
        if not self.redis_client:
            self.logger.warning("Cannot start Redis listener: Redis client not provided.")
            return
        if self._listener_task is None or self._listener_task.done():
            self.logger.info("Starting Redis Pub/Sub listener task...")
            self._listener_task = asyncio.create_task(self._redis_listener())
        else:
             self.logger.warning("Redis listener task already running.")

    async def stop_listener(self):
        """Stops the Redis listener background task gracefully."""
        if self._listener_task and not self._listener_task.done():
             self.logger.info("Stopping Redis Pub/Sub listener task...")
             self._listener_task.cancel()
             try:
                 await self._listener_task
                 self.logger.info("Redis listener task stopped successfully.")
             except asyncio.CancelledError:
                  self.logger.info("Redis listener task cancellation confirmed.")
             except Exception as e:
                  self.logger.error(f"Error encountered while stopping Redis listener task: {e}", exc_info=True)
        else:
             self.logger.info("Redis listener task not running or already stopped.")
        self._listener_task = None # Clear the task reference

    # _send_message remains largely the same, handles sending to a single websocket
    async def _send_message(self, websocket: WebSocket, message_json: str, notebook_id: UUID, disconnected_clients: Set[WebSocket]):
        """Helper function to send a message and handle potential disconnections."""
        try:
            await websocket.send_text(message_json)
            # Reduced verbosity, log only if needed or on error
            # self.logger.debug(
            #     f"Sent message to WebSocket",
            #     extra={'notebook_id': str(notebook_id), 'client': websocket.client}
            # )
        except WebSocketDisconnect:
            self.logger.info(
                "WebSocket disconnected during send",
                extra={'notebook_id': str(notebook_id), 'client': websocket.client}
            )
            disconnected_clients.add(websocket)
            # Also perform local disconnect immediately
            self.disconnect(websocket, notebook_id)
        except Exception as e:
            # Catch other potential exceptions during send
            self.logger.error(
                f"Error sending message to WebSocket: {str(e)}",
                extra={'notebook_id': str(notebook_id), 'client': websocket.client},
                exc_info=True
            )
            disconnected_clients.add(websocket) # Assume client is lost if send fails
            # Also perform local disconnect immediately
            self.disconnect(websocket, notebook_id)

# Remove the global singleton instance and getter function
# ws_manager = WebSocketManager()
# def get_ws_manager() -> WebSocketManager:
#    """Dependency function to get the WebSocket manager instance."""
#    return ws_manager

# --- WebSocket Message Types and Payloads ---

# Message type constants
RERUN_INVESTIGATION_CELL = "rerun_investigation_cell"

class RerunInvestigationCellPayload(BaseModel):
    """Payload for the RERUN_INVESTIGATION_CELL message."""
    notebook_id: UUID
    cell_id: UUID
    session_id: str # To track the origin of the request

# Example of how other message types could be structured:
# class ClientToServerMessage(BaseModel):
#     type: str
#     payload: Union[RerunInvestigationCellPayload, OtherPayloadType, ...]

# class ServerToClientMessage(BaseModel):
#     type: str # e.g., "cell_updated", "status_update"
#     data: Dict[str, Any]
