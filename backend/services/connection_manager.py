"""
Connection Manager Service

Manages connections to data sources via MCP servers
"""

import logging
import os
from typing import Dict, List, Optional, Tuple, Any
from uuid import uuid4
import asyncio
from asyncio import Lock  # For Log-AI tool list cache locking

from pydantic import BaseModel, Field, ValidationError

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from backend.config import get_settings
from backend.db.database import get_db_session
from backend.db.repositories import ConnectionRepository

from backend.core.types import MCPToolInfo

# Cache for expensive Log-AI tool discovery
# --------------------------------------------------
#   We keep the discovered tool list in-memory for the
#   lifetime of the process so subsequent requests can be
#   served instantly without spinning up the docker image
#   again.  A very small async Lock is used to ensure only
#   one coroutine performs the initial discovery.
# --------------------------------------------------

_logai_tools_cache: Optional[list['MCPToolInfo']] = None  # Populated lazily
_logai_tools_cache_lock: Lock = Lock()

# Import handler registry functions
from backend.services.connection_handlers.registry import get_handler, get_all_handler_types

# Configure logging
logger = logging.getLogger(__name__)

# Make sure correlation_id is set for all logs
class CorrelationIdFilter(logging.Filter):
    def filter(self, record):
        # Instead of requiring correlation_id, just add it if missing
        if not hasattr(record, 'correlation_id'):
            record.correlation_id = 'N/A'
        return True

# Add the filter to our logger
logger.addFilter(CorrelationIdFilter())

# --- Simplified Connection Config ---
# BaseConnectionConfig remains the same
class BaseConnectionConfig(BaseModel):
    """Base connection configuration"""
    id: str
    name: str
    type: str
    config: Dict[str, Any] = Field(default_factory=dict)


ConnectionConfig = BaseConnectionConfig

# Singleton instance
_connection_manager_instance = None


def get_connection_manager():
    """Get the singleton ConnectionManager instance"""
    global _connection_manager_instance
    if _connection_manager_instance is None:
        _connection_manager_instance = ConnectionManager()
    return _connection_manager_instance


class ConnectionManager:
    """
    Manages connections to data sources via MCP servers using Connection Handlers.
    """
    def __init__(self):
        self.connections: Dict[str, ConnectionConfig] = {}
        self.default_connections: Dict[str, str] = {}
        self.settings = get_settings()
        # Handler registration should happen automatically when handler modules are imported.
        # If doing explicit registration, it should ideally occur during app startup (e.g., in main.py).
        logger.info(f"ConnectionManager initialized. Registered handlers: {get_all_handler_types()}")
    
    async def initialize(self) -> None:
        """Initialize and load connections"""
        correlation_id = str(uuid4())
        logger.info("Initializing ConnectionManager", extra={'correlation_id': correlation_id})
        await self._load_connections()
        logger.info(f"ConnectionManager initialized successfully with {len(self.connections)} connections loaded.", extra={'correlation_id': correlation_id})
    
    async def close(self) -> None:
        """Close all connections and cleanup resources"""
        correlation_id = str(uuid4())
        logger.info("Closing ConnectionManager", extra={'correlation_id': correlation_id})
        # Add cleanup logic here if necessary (e.g., closing MCP processes)
        logger.info("ConnectionManager closed successfully", extra={'correlation_id': correlation_id})
    
    async def get_connection(self, connection_id: str) -> Optional[ConnectionConfig]:
        """Get a connection by ID (logic remains mostly the same)"""
        logger.info(f"Getting connection {connection_id}")
        # Prioritize cache
        if connection_id in self.connections:
            return self.connections[connection_id]
        # Fallback to DB
        try:
            async with get_db_session() as session:
                repo = ConnectionRepository(session)
                db_connection = await repo.get_by_id(connection_id)
                if db_connection:
                    connection_dict = db_connection.to_dict()
                    # Use the simplified ConnectionConfig
                    connection = ConnectionConfig(**connection_dict)
                    # Update cache
                    self.connections[connection_id] = connection
                    return connection
            # Not found in DB either
            logger.warning(f"Connection {connection_id} not found in cache or DB.")
            return None
        except Exception as e:
            logger.error(f"Error retrieving connection {connection_id} from database: {str(e)}", exc_info=True)
            return None # Propagate None on error

    async def get_connections_by_type(self, connection_type: str) -> List[ConnectionConfig]:
        """Get all connections for a specific type (logic remains mostly the same)"""
        try:
            # Query the database directly
            async with get_db_session() as session:
                repo = ConnectionRepository(session)
                db_connections = await repo.get_by_type(connection_type)
                
                connections = []
                for db_conn in db_connections:
                    conn_dict = db_conn.to_dict()
                    # Use simplified ConnectionConfig
                    connection = ConnectionConfig(**conn_dict)
                    # Update cache as we load
                    self.connections[conn_dict["id"]] = connection
                    connections.append(connection)
                
                return connections
        except Exception as e:
            logger.error(f"Error retrieving connections by type '{connection_type}' from database: {str(e)}", exc_info=True)
            return [] # Return empty list on error

    async def get_all_connections(self) -> List[Dict]:
        """Get all connections (uses _redact_sensitive_fields which now uses handlers)"""
        try:
            # Always fetch fresh from DB to get current state including `is_default`
            async with get_db_session() as session:
                repo = ConnectionRepository(session)
                db_connections = await repo.get_all()
                
                # Update cache with any changes/new connections
                for db_conn in db_connections:
                    conn_dict = db_conn.to_dict()
                    # Use simplified ConnectionConfig
                    self.connections[conn_dict["id"]] = ConnectionConfig(**conn_dict)
                
                # Prepare response DTOs
                response_list = []
                for conn in db_connections:
                    try:
                        conn_dict = conn.to_dict()
                        # Redaction uses handler via _redact_sensitive_fields (updated call)
                        redacted_config = self._redact_sensitive_fields(conn_dict["config"], str(conn_dict["type"]))
                        response_list.append({
                            "id": conn_dict["id"],
                            "name": conn_dict["name"],
                            "type": conn_dict["type"],
                            # Check against the cached default connections
                            "is_default": self.default_connections.get(conn_dict["type"]) == conn_dict["id"],
                            "config": redacted_config
                        })
                    except Exception as redact_err:
                         logger.error(f"Error redacting config for connection {conn.id} ({conn.type}): {redact_err}", exc_info=True)
                         # Also use the cache logic here for consistency
                         response_list.append({
                             "id": conn.id, "name": conn.name, "type": conn.type, 
                             "is_default": self.default_connections.get(str(conn.type)) == conn.id,
                             "config": {"error": "Failed to redact configuration"}
                         })

                return response_list
        except Exception as e:
            logger.error(f"Error retrieving all connections from database: {str(e)}", exc_info=True)
            # Fallback uses cache
            logger.warning("Falling back to cached connections due to DB error.")
            response_list = []
            for conn in self.connections.values(): # Iterate over cached ConnectionConfig objects
                 try:
                      # Use simplified ConnectionConfig format
                      redacted_config = self._redact_sensitive_fields(conn.config, str(conn.type))
                      response_list.append({
                          "id": conn.id, "name": conn.name, "type": conn.type,
                          "is_default": self.default_connections.get(str(conn.type)) == conn.id,
                          "config": redacted_config
                      })
                 except Exception as redact_err:
                      logger.error(f"Error redacting cached config for connection {conn.id} ({conn.type}): {redact_err}", exc_info=True)
                      response_list.append({
                          "id": conn.id, "name": conn.name, "type": conn.type,
                          "is_default": self.default_connections.get(str(conn.type)) == conn.id,
                          "config": {"error": "Failed to redact configuration"}
                      })
            return response_list


    async def get_default_connection(self, connection_type: str) -> Optional[ConnectionConfig]:
        """Get the default connection for a given type (logic remains mostly the same)"""
        # Check environment variable override first
        env_var_name = f"SHERLOG_CONNECTION_DEFAULT_{connection_type.upper()}"
        default_conn_name = os.environ.get(env_var_name)
        
        if default_conn_name:
            logger.info(f"Attempting to find default {connection_type} connection named '{default_conn_name}' from env var.")
            try:
                async with get_db_session() as session:
                    repo = ConnectionRepository(session)
                    db_connection = await repo.get_by_name_and_type(default_conn_name, connection_type)
                    if db_connection:
                        conn_dict = db_connection.to_dict()
                        # Use simplified ConnectionConfig
                        connection = ConnectionConfig(**conn_dict)
                        self.connections[conn_dict["id"]] = connection # Update cache
                        logger.info(f"Found default connection via env var: {connection.id}")
                        return connection
                    else:
                         logger.warning(f"Default connection name '{default_conn_name}' from env var not found in DB for type {connection_type}.")
            except Exception as e:
                logger.error(f"Error finding default connection by name '{default_conn_name}': {str(e)}", exc_info=True)
        
        # Then check DB flag
        try:
            async with get_db_session() as session:
                repo = ConnectionRepository(session)
                db_connection = await repo.get_default_connection(connection_type)
                if db_connection:
                    conn_dict = db_connection.to_dict()
                    # Use simplified ConnectionConfig
                    connection = ConnectionConfig(**conn_dict)
                    # Update cache and in-memory default tracking
                    self.connections[conn_dict["id"]] = connection
                    self.default_connections[connection_type] = conn_dict["id"]
                    logger.info(f"Found default connection via DB flag: {connection.id}")
                    return connection
                    
                # Fallback: if no default is set, return the *first* connection of the type found
                logger.info(f"No explicit default found for {connection_type}, checking for any connection of this type.")
                # Use the already defined method which queries DB
                connections = await self.get_connections_by_type(connection_type)
                if connections:
                     first_connection = connections[0]
                     logger.warning(f"Returning first available connection '{first_connection.name}' ({first_connection.id}) as implicit default for {connection_type}.")
                     return first_connection
        except Exception as e:
            logger.error(f"Error retrieving default connection for {connection_type} from database: {str(e)}", exc_info=True)
        
        logger.warning(f"No connection of type '{connection_type}' found.")
        return None # No connection found

    async def create_connection(self, name: str, type: str, connection_data: BaseModel) -> ConnectionConfig:
        """
        Create a new connection using the appropriate handler.

        Args:
            name: The name for the connection.
            type: The type of connection.
            connection_data: Validated Pydantic model instance containing type-specific data.

        Returns:
            The created ConnectionConfig.
            
        Raises:
            ValueError: If connection validation or preparation fails.
            TypeError: If connection_data is not a Pydantic BaseModel.
        """
        correlation_id = str(uuid4())
        logger.info(f"Attempting to create new {type} connection: {name}", extra={'correlation_id': correlation_id})

        if not isinstance(connection_data, BaseModel):
             raise TypeError("connection_data must be a Pydantic BaseModel instance")

        try:
            # Get the handler for the specified type
            handler = get_handler(type)
            logger.info(f"Using handler {handler.__class__.__name__} for type {type}", extra={'correlation_id': correlation_id})
            
            # Prepare the configuration using the handler
            # This now includes validation logic (like the MCP check)
            logger.info(f"Preparing configuration for {name} ({type})...", extra={'correlation_id': correlation_id})
            prepared_config = await handler.prepare_config(
                connection_id=None, 
                input_data=connection_data, 
                existing_config=None
            )
            logger.info(f"Configuration prepared successfully for {name}", extra={'correlation_id': correlation_id})

        except (ValueError, TypeError, ValidationError) as e:
            # Handles errors from get_handler and prepare_config (incl. MCP validation failures)
            logger.error(f"Handler configuration preparation failed for {name} ({type}): {e}", extra={'correlation_id': correlation_id}, exc_info=True) # Log stack trace for unexpected type errors
            raise ValueError(f"Configuration failed: {str(e)}") from e # Raise ValueError consistent with API expectations
        except Exception as e: # Catch truly unexpected handler errors
            logger.error(f"Unexpected error during handler configuration preparation for {name} ({type}): {e}", extra={'correlation_id': correlation_id}, exc_info=True)
            raise ValueError(f"An unexpected error occurred during configuration: {str(e)}") from e


        # Create the connection in the database with the prepared config
        async with get_db_session() as session:
            repo = ConnectionRepository(session)
            try:
                # Check if name already exists for this type
                existing_by_name = await repo.get_by_name_and_type(name, type)
                if existing_by_name:
                    raise ValueError(f"A connection named '{name}' of type '{type}' already exists.")

                db_connection = await repo.create(name, type, prepared_config)
                # Convert to ConnectionConfig model
                connection_dict = db_connection.to_dict()
                # Use simplified ConnectionConfig
                connection = ConnectionConfig(**connection_dict)
            except Exception as db_e: # Catch potential DB errors (incl. unique constraints)
                 logger.error(f"Database error creating connection {name} ({type}): {db_e}", extra={'correlation_id': correlation_id}, exc_info=True)
                 # Make common DB errors more user-friendly if possible
                 if "unique constraint" in str(db_e).lower():
                      raise ValueError("Database error: A connection with similar properties might already exist.")
                 raise ValueError(f"Database error creating connection: {str(db_e)}") from db_e

        # Add to in-memory cache
        self.connections[connection.id] = connection

        # Perform post-creation actions
        try:
            logger.info(f"Executing post-create actions for connection {connection.id} of type {type}", extra={'correlation_id': correlation_id})
            # Schedule as a background task so it doesn't block the API response
            asyncio.create_task(handler.post_create_actions(connection))
            # If direct await is needed and acceptable for API response time:
            # await handler.post_create_actions(connection) 
            logger.info(f"Successfully scheduled/executed post-create actions for {connection.id}", extra={'correlation_id': correlation_id})
        except Exception as post_create_err:
            # Log error but don't let it fail the connection creation response
            logger.error(f"Error during post-create actions for connection {connection.id}: {post_create_err}", extra={'correlation_id': correlation_id}, exc_info=True)

        # Set as default if first of its type (check *after* creation)
        # Use the existing method which queries DB
        connections_of_type = await self.get_connections_by_type(type)
        if len(connections_of_type) == 1: # If this newly created one is the only one
            logger.info(f"Setting {name} ({connection.id}) as default {type} connection (first of its type).", extra={'correlation_id': correlation_id})
            await self.set_default_connection(connection.id)

        logger.info(f"Successfully created connection {name} ({connection.id})", extra={'correlation_id': correlation_id})
        return connection

    async def update_connection(self, connection_id: str, name: Optional[str], connection_data: BaseModel) -> ConnectionConfig:
        """
        Update an existing connection using the appropriate handler.
        Name update is handled separately from config update via the handler.

        Args:
            connection_id: The ID of the connection to update.
            name: The new name for the connection (optional, if None, name is not changed).
            connection_data: Validated Pydantic model instance containing update data for the config.

        Returns:
            The updated ConnectionConfig.
            
        Raises:
            ValueError: If connection not found, or validation/preparation fails.
             TypeError: If connection_data is not a Pydantic BaseModel.
        """
        correlation_id = str(uuid4())
        logger.info(f"Attempting to update connection {connection_id} (New name: {name or 'unchanged'})", extra={'correlation_id': correlation_id})
        
        if not isinstance(connection_data, BaseModel):
             raise TypeError("connection_data must be a Pydantic BaseModel instance")

        # Get existing connection (use await)
        existing_connection = await self.get_connection(connection_id)
        if not existing_connection:
            logger.error(f"Connection not found for update: {connection_id}", extra={'correlation_id': correlation_id})
            raise ValueError(f"Connection not found: {connection_id}")

        final_name = name if name is not None else existing_connection.name
        existing_config = existing_connection.config
        connection_type = existing_connection.type # Type cannot be changed

        prepared_config = existing_config # Start with existing config
        config_changed = False

        # Check if there's actual config data to update in the input model
        # Use model_dump with exclude_unset=True to see if any fields were provided
        update_payload = connection_data.model_dump(exclude_unset=True)

        if update_payload: # Only run handler prepare if there are config changes
            config_changed = True
            logger.info(f"Config changes detected for {connection_id}, preparing new config...", extra={'correlation_id': correlation_id})
            try:
                # Get the handler for the existing connection type
                handler = get_handler(connection_type)
                logger.info(f"Using handler {handler.__class__.__name__} for update ({connection_type})", extra={'correlation_id': correlation_id})

                # Prepare the updated configuration using the handler
                prepared_config = await handler.prepare_config(
                    connection_id=connection_id, 
                    input_data=connection_data, # Pass the Pydantic model
                    existing_config=existing_config
                )
                logger.info(f"Updated configuration prepared successfully for {connection_id}", extra={'correlation_id': correlation_id})

            except (ValueError, TypeError, ValidationError) as e:
                logger.error(f"Handler configuration preparation failed for update {final_name} ({connection_id}): {e}", extra={'correlation_id': correlation_id}, exc_info=True)
                raise ValueError(f"Update configuration failed: {str(e)}") from e
            except Exception as e: # Catch unexpected handler errors
                logger.error(f"Unexpected error during handler configuration preparation for update {final_name} ({connection_id}): {e}", extra={'correlation_id': correlation_id}, exc_info=True)
                raise ValueError(f"An unexpected error occurred during update configuration: {str(e)}") from e
        else:
             logger.info(f"No config changes detected for {connection_id}, only name might be updated.", extra={'correlation_id': correlation_id})


        # Update the connection in the database (only if name or config changed)
        if final_name != existing_connection.name or config_changed:
            logger.info(f"Saving updates to DB for {connection_id} (Name: {final_name}, Config changed: {config_changed})", extra={'correlation_id': correlation_id})
            async with get_db_session() as session:
                repo = ConnectionRepository(session)
                try:
                    # Check if new name conflicts with another connection of the same type
                    if final_name != existing_connection.name:
                         existing_by_name = await repo.get_by_name_and_type(final_name, connection_type)
                         # Explicitly check if an object was returned, then check its ID from the dict
                         if existing_by_name is not None and existing_by_name.to_dict()['id'] != connection_id:
                             raise ValueError(f"A connection named '{final_name}' of type '{connection_type}' already exists.")

                    db_connection = await repo.update(connection_id, final_name, prepared_config)
                    if not db_connection:
                        # This case might indicate a concurrent delete or other issue
                        logger.error(f"Failed to update connection {connection_id} in database (not found after check?)", extra={'correlation_id': correlation_id})
                        raise ValueError(f"Failed to update connection (not found): {connection_id}")

                    # Convert to ConnectionConfig model
                    connection_dict = db_connection.to_dict()
                    # Use simplified ConnectionConfig
                    updated_connection = ConnectionConfig(**connection_dict)

                except Exception as db_e: # Catch potential DB errors
                    logger.error(f"Database error updating connection {final_name} ({connection_id}): {db_e}", extra={'correlation_id': correlation_id}, exc_info=True)
                    if "unique constraint" in str(db_e).lower():
                         raise ValueError(f"Database error: A connection named '{final_name}' might already exist.")
                    raise ValueError(f"Database error updating connection: {str(db_e)}") from db_e
        else:
             # No changes to save, return the existing connection object
             logger.info(f"No changes to save for connection {connection_id}.", extra={'correlation_id': correlation_id})
             updated_connection = existing_connection # Return the original object

        # Update the in-memory cache with the potentially updated object
        self.connections[connection_id] = updated_connection

        logger.info(f"Successfully updated connection {final_name} ({connection_id})", extra={'correlation_id': correlation_id})
        return updated_connection
    
    async def delete_connection(self, connection_id: str) -> None:
        """Delete a connection (logic remains mostly the same) - Ensure get_connection is awaited"""
        logger.info(f"Attempting to delete connection {connection_id}")
        # Use await to get the connection object
        connection = await self.get_connection(connection_id) 
        if not connection:
            logger.error(f"Connection not found for deletion: {connection_id}")
            # Keep raising ValueError for consistency with update/get
            raise ValueError(f"Connection not found: {connection_id}")
        
        connection_type_deleted = connection.type # Store type before deletion

        # Delete from database
        async with get_db_session() as session:
            repo = ConnectionRepository(session)
            success = await repo.delete(connection_id)
            if not success:
                # This could happen if deleted between get and delete, or DB error
                logger.error(f"Failed to delete connection {connection_id} from database (already gone or DB error?)")
                # Decide whether to raise or log and continue
                raise ValueError(f"Failed to delete connection from database: {connection_id}")
        
        # Remove from in-memory cache
        if connection_id in self.connections:
            del self.connections[connection_id]
            logger.info(f"Removed connection {connection_id} from cache.")
        
        # Update default connections if needed (check memory first)
        if self.default_connections.get(connection_type_deleted) == connection_id:
            logger.info(f"Removing deleted connection {connection_id} as default for type {connection_type_deleted}")
            del self.default_connections[connection_type_deleted] # Remove from memory immediately

            # Find and set a new default in the DB
            async with get_db_session() as session:
                repo = ConnectionRepository(session)
                # Fetch remaining directly from DB
                connections = await repo.get_by_type(connection_type_deleted)
                if connections:
                    # Get the ID from the dictionary representation of the first connection
                    first_connection_dict = connections[0].to_dict()
                    new_default_id = first_connection_dict['id'] 
                    
                    logger.info(f"Setting new default connection for type {connection_type_deleted} in DB: {new_default_id}")
                    try:
                        # Pass the string ID to the repository method
                        await repo.set_default_connection(connection_type_deleted, new_default_id)
                        # Update memory tracking as well
                        self.default_connections[connection_type_deleted] = new_default_id
                    except Exception as set_default_err:
                         logger.error(f"Failed to set new default connection {new_default_id} after deleting {connection_id}: {set_default_err}", exc_info=True)
                         # State might be inconsistent here
                else:
                    logger.info(f"No remaining connections for type {connection_type_deleted}, default cleared.")
                    # Ensure no default flag remains in DB (set_default_connection with None ID?)
                    # Assuming repo.set_default_connection handles clearing if ID is invalid/None or a dedicated method exists
                    # For now, we rely on the fact that no connection has the flag set.
        
        logger.info(f"Successfully deleted connection {connection_id}")


    async def set_default_connection(self, connection_id: str) -> None:
        """Set a connection as the default for its type (logic remains mostly the same) - Ensure get_connection is awaited"""
        # Use await to get the connection object
        connection = await self.get_connection(connection_id)
        if not connection:
            raise ValueError(f"Connection not found: {connection_id}")
        
        connection_type = connection.type
        logger.info(f"Setting connection {connection_id} ({connection.name}) as default for type {connection_type}")
        
        # Set as default in database - this handles unsetting the old default
        async with get_db_session() as session:
            repo = ConnectionRepository(session)
            try:
                await repo.set_default_connection(connection_type, connection_id)
            except Exception as e:
                logger.error(f"Failed to set default connection {connection_id} in DB: {e}", exc_info=True)
                raise ValueError(f"Database error setting default connection: {str(e)}") from e

        # Update in-memory default tracking AFTER successful DB operation
        self.default_connections[connection_type] = connection_id
        logger.info(f"Updated in-memory default for {connection_type} to {connection_id}")

    
    async def test_connection(self, connection_type: str, config_data: BaseModel) -> Tuple[bool, str]:
        """
        Test a connection configuration using the appropriate handler's test logic.

        Args:
            connection_type: The type of connection.
            config_data: Validated Pydantic model instance containing test data.
                         Note: This model should come from the handler's get_test_model().

        Returns:
            Tuple (is_valid: bool, message: str)
        """
        correlation_id = str(uuid4())
        logger.info(f"Testing {connection_type} connection configuration", extra={'correlation_id': correlation_id})

        if not isinstance(config_data, BaseModel):
             # This check might be redundant if FastAPI/Pydantic handles validation upstream
             raise TypeError("config_data must be a Pydantic BaseModel instance")

        try:
            # Get the handler
            handler = get_handler(connection_type)
            logger.info(f"Using handler {handler.__class__.__name__} for test ({connection_type})", extra={'correlation_id': correlation_id})

            # Use the handler's prepare_config logic as the test mechanism.
            # This ensures the same validation path (including MCP checks) is used.
            # Pass the validated test_data model directly.
            logger.info("Attempting prepare_config via handler for test...", extra={'correlation_id': correlation_id})
            await handler.prepare_config(
                connection_id=None, # Not updating an existing connection
                input_data=config_data, 
                existing_config=None
            )
            
            # If prepare_config succeeded without raising ValueError, it's valid
            logger.info(f"Test successful for {connection_type}", extra={'correlation_id': correlation_id})
            return True, f"{connection_type.capitalize()} connection configuration is valid."

        except (ValueError, TypeError, ValidationError) as e:
            # Catch errors from get_handler or prepare_config
            error_message = f"Validation failed: {str(e)}"
            logger.warning(f"Test failed for {connection_type}: {error_message}", extra={'correlation_id': correlation_id}) # Log as warning, don't need full trace for expected validation errors
            return False, error_message
        except Exception as e:
            # Catch unexpected errors during handler execution
            logger.error(f"Unexpected error testing {connection_type} connection: {str(e)}", extra={'correlation_id': correlation_id}, exc_info=True)
            return False, f"An unexpected error occurred during testing: {str(e)}"

    def _redact_sensitive_fields(self, config: Dict, connection_type: Optional[str] = None) -> Dict:
        """
        Redact sensitive fields from a connection configuration using the handler.
        Handles cases where the handler or config might be missing.
        """
        sensitive_keys: List[str] = []
        # Define a comprehensive fallback list for safety
        fallback_keys = [
            "password", "secret", "key", "token", "api_key", 
            "aws_secret_access_key", "private_key", 
            "github_pat", "github_personal_access_token", 
            "jira_api_token", "jira_personal_token"
        ] 

        if not isinstance(config, dict):
             logger.error(f"Config passed to _redact_sensitive_fields is not a dict: {type(config)}. Returning empty.")
             return {} # Return empty if input is invalid

        if not connection_type:
            logger.warning("Connection type not provided for redaction. Falling back to generic list.")
            sensitive_keys = fallback_keys
        else:
            try:
                # Get sensitive keys from the handler
                handler = get_handler(connection_type)
                sensitive_keys = handler.get_sensitive_fields()
            except ValueError:
                # Handler not found for the type
                logger.warning(f"No handler found for type '{connection_type}' during redaction. Falling back to generic list.")
                sensitive_keys = fallback_keys
            except Exception as e:
                 # Unexpected error getting fields from handler
                 logger.error(f"Error getting sensitive fields from handler for type '{connection_type}': {e}. Falling back to generic list.", exc_info=True)
                 sensitive_keys = fallback_keys

        # Add fallback keys to handler keys to be safe, avoid duplicates
        combined_sensitive_keys = list(set(sensitive_keys + fallback_keys))
        sensitive_keys_lower = [sk.lower() for sk in combined_sensitive_keys]

        redacted_config = {}
        for key, value in config.items():
            lower_key = key.lower()
            # Check if the exact key (case-insensitive) or parts of the key match sensitive keys
            is_sensitive = lower_key in sensitive_keys_lower
            if not is_sensitive:
                 # Check if any sensitive key is a distinct part of the current key (e.g., _pat, token_)
                 for sk_lower in sensitive_keys_lower:
                      # Check for common separators or exact match
                      if f"_{sk_lower}" in lower_key or f"{sk_lower}_" in lower_key:
                           is_sensitive = True
                           break 

            if is_sensitive and value is not None: 
                redacted_config[key] = "********"
            # Also redact common nested env vars (less dependent on handler providing nested keys)
            elif key == "env" and isinstance(value, dict):
                 redacted_env = {}
                 for env_key, env_value in value.items():
                     lower_env_key = env_key.lower()
                     is_env_sensitive = lower_env_key in sensitive_keys_lower
                     if not is_env_sensitive:
                         for sk_lower in sensitive_keys_lower:
                             if f"_{sk_lower}" in lower_env_key or f"{sk_lower}_" in lower_env_key:
                                 is_env_sensitive = True
                                 break
                                 
                     redacted_env[env_key] = "********" if is_env_sensitive and env_value is not None else env_value
                 redacted_config[key] = redacted_env
            else:
                redacted_config[key] = value

        # Remove internal MCP fields (these are not sensitive but shouldn't be exposed)
        redacted_config.pop("mcp_command", None)
        redacted_config.pop("mcp_args_template", None)

        return redacted_config

    async def _load_connections(self) -> None:
        """Load connections from storage (DB)"""
        correlation_id = str(uuid4())
        try:
            logger.info("Loading connections from database storage", extra={'correlation_id': correlation_id})
            await self._load_connections_from_db()
            logger.info(f"Successfully loaded {len(self.connections)} connections from DB.", extra={'correlation_id': correlation_id})
        except Exception as e:
            logger.error(f"Error loading connections from DB: {str(e)}", extra={'correlation_id': correlation_id}, exc_info=True)
            # Decide if this is fatal or if the app can continue with an empty cache
            # For now, let the error propagate if needed by the caller (initialize)
            raise
    
    async def _load_connections_from_db(self) -> None:
        """Load connections from database into cache"""
        async with get_db_session() as session:
            repo = ConnectionRepository(session)
            db_connections = await repo.get_all()
            
            loaded_connections: Dict[str, ConnectionConfig] = {}
            loaded_defaults: Dict[str, str] = {}

            for conn in db_connections:
                conn_dict = conn.to_dict()
                # Use simplified ConnectionConfig
                connection_obj = ConnectionConfig(**conn_dict)
                loaded_connections[connection_obj.id] = connection_obj
                if conn_dict['is_default']: # Use dict value for bool check
                     conn_type_from_dict = conn_dict['type'] # Use dict value
                     conn_id_from_dict = conn_dict['id'] # Use dict value
                     if conn_type_from_dict in loaded_defaults:
                         logger.error(f"Multiple defaults found for type {conn_type_from_dict} in DB! Using {conn_id_from_dict} over {loaded_defaults[conn_type_from_dict]}")
                     loaded_defaults[conn_type_from_dict] = conn_id_from_dict # Assign str ID

            # Atomically update the cache and defaults
            self.connections = loaded_connections
            self.default_connections = loaded_defaults
            logger.debug(f"Loaded {len(self.connections)} connections and {len(self.default_connections)} defaults into memory.")

    # --- Tool Discovery (Uses Handler) --- 
    async def get_tools_for_connection_type(self, connection_type: str) -> List[MCPToolInfo]:
        """
        List available tools for a given connection type using its default connection and handler,
        or provide predefined tools for special types like "python".
        """
        correlation_id = str(uuid4())
        logger.info(f"Fetching tools for connection type: {connection_type}", extra={'correlation_id': correlation_id})

        if connection_type == "python":
            logger.info("Handling special case for 'python' tool type discovery.", extra={'correlation_id': correlation_id})
            # Define tools and their schemas directly here.
            # This schema should align with what PythonCell.tsx expects for its form rendering.
            python_tools = [
                MCPToolInfo(
                    name="run_script",
                    description="Runs a Python script.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "script": {
                                "type": "string",
                                "title": "Python Script",
                                "description": "The Python script to execute.",
                                "format": "textarea" # Suggests a textarea in the frontend
                            }
                        },
                        "required": ["script"]
                    }
                ),
                MCPToolInfo(
                    name="load_csv",
                    description="Loads a CSV file into a Pandas DataFrame.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "csv_path": {
                                "type": "string",
                                "title": "CSV File Path",
                                "description": "The path to the CSV file to load."
                            },
                            "df_name": {
                                "type": "string",
                                "title": "DataFrame Name",
                                "description": "The name to assign to the loaded DataFrame.",
                                "default": "df"
                            }
                        },
                        "required": ["csv_path", "df_name"]
                    }
                )
                # Add other built-in Python tools here if they exist
            ]
            logger.info(f"Returning {len(python_tools)} predefined Python tools.", extra={'correlation_id': correlation_id})
            return python_tools


        # --- LogAI (FastMCP) virtual connection type --------------------------------------
        if connection_type == "log_ai":
            logger.info(
                "Handling virtual 'log_ai' connection-type tool discovery via direct FastMCP stdio call.",
                extra={'correlation_id': correlation_id}
            )

            # If we've already fetched the LogAI tool list once during the
            # lifetime of this process just return the cached copy straight
            # away – no need to spin up the Docker container again.
            global _logai_tools_cache
            global _logai_tools_cache_lock
            if _logai_tools_cache is not None:
                logger.debug(
                    "Returning cached list of %d Log-AI tools.",
                    len(_logai_tools_cache),
                    extra={'correlation_id': correlation_id},
                )
                return _logai_tools_cache

            # Ensure only one coroutine performs the expensive discovery the
            # first time while others wait on the result.
            async with _logai_tools_cache_lock:
                # Another coroutine might have already populated the cache
                # while we were waiting for the lock.
                if _logai_tools_cache is not None:
                    logger.debug(
                        "Log-AI tools cache was populated by another task while waiting for lock.",
                        extra={'correlation_id': correlation_id},
                    )
                    return _logai_tools_cache

            try:
                # Prepare Docker arguments
                docker_args = [
                    "run",
                    "--rm",
                    "-i",  # attach STDIN for stdio transport,
                    "--volume=/var/run/docker.sock:/var/run/docker.sock",
                ]
                
                # Add volume mount if SHERLOG_HOST_FS_ROOT is set
                host_fs_root = os.environ.get("SHERLOG_HOST_FS_ROOT")
                if host_fs_root:
                    docker_args.append("-v")
                    docker_args.append(f"{host_fs_root}:{host_fs_root}:ro")

                docker_args.append("ghcr.io/navneet-mkr/logai-mcp:0.1.5")

                # Run the Log-AI MCP via published Docker image instead of building it on the fly
                server_params = StdioServerParameters(
                    command="docker",
                    args=docker_args,
                    env=os.environ.copy(),
                )

                async with stdio_client(server_params) as (read, write):
                    async with ClientSession(read, write) as session:
                        logger.info(
                            "Initializing MCP session for Log-AI list_tools…",
                            extra={'correlation_id': correlation_id},
                        )
                        await asyncio.wait_for(session.initialize(), timeout=90.0)
                        response = await asyncio.wait_for(session.list_tools(), timeout=30.0)

                        parsed_tools: List[MCPToolInfo] = []
                        for mcp_tool in getattr(response, "tools", []) or []:
                            try:
                                parsed_tools.append(
                                    MCPToolInfo(
                                        name=getattr(mcp_tool, "name", "unknown"),
                                        description=getattr(mcp_tool, "description", None),
                                        inputSchema=getattr(mcp_tool, "inputSchema", {}) or {},
                                    )
                                )
                            except Exception as tool_parse_err:
                                logger.error(
                                    "Failed parsing tool from Log-AI list_tools response: %s",
                                    tool_parse_err,
                                    extra={'correlation_id': correlation_id},
                                    exc_info=True,
                                )
                                continue

                        logger.info(
                            "Retrieved %d Log-AI tools via MCP list_tools.",
                            len(parsed_tools),
                            extra={'correlation_id': correlation_id},
                        )

                        # Populate the cache so the next call is instantaneous.
                        _logai_tools_cache = parsed_tools

                        return parsed_tools
            except asyncio.TimeoutError:
                raise ValueError("Timeout communicating with Log-AI MCP server while listing tools.")
            except FileNotFoundError as e:
                raise ValueError(f"Log-AI MCP server command not found: {e}")
            except Exception as e:
                logger.error(
                    "Unexpected error during Log-AI MCP list_tools: %s",
                    e,
                    extra={'correlation_id': correlation_id},
                    exc_info=True,
                )
                raise ValueError(f"Failed to communicate with Log-AI MCP server: {e}")

        # Special handling for workspace configuration - no tools needed
        if connection_type == "logai_workspace":
            logger.info("Workspace configuration doesn't provide tools - tools are available when notebooks are opened", extra={'correlation_id': correlation_id})
            return []  # Empty list - no tools for workspace config itself

        # Existing logic for MCP-based connections:
        default_conn = await self.get_default_connection(connection_type)
        if not default_conn:
            # Log clearly, return empty list - API caller handles 'no connection' case.
            logger.warning(f"No default connection found for type '{connection_type}'. Cannot list tools.", extra={'correlation_id': correlation_id})
            return [] 

        config_dict = default_conn.config
        if not isinstance(config_dict, dict):
             # This indicates corrupted data for the default connection
             logger.error(f"Default connection {default_conn.id} for {connection_type} has invalid config format. Cannot list tools.", extra={'correlation_id': correlation_id})
             # Raise an error as this is an internal inconsistency
             raise ValueError(f"Invalid config format for default connection {default_conn.id}") 

        try:
            # Get handler and stdio parameters
            handler = get_handler(connection_type)
            logger.info(f"Using handler {handler.__class__.__name__} for tool discovery ({connection_type})", extra={'correlation_id': correlation_id})
            
            server_params = handler.get_stdio_params(config_dict)
            
            # Redact sensitive info before logging params 
            sensitive_keys_lower = [sk.lower() for sk in handler.get_sensitive_fields()]
            redacted_args = []
            if server_params.args:
                 for arg in server_params.args:
                      lower_arg = arg.lower()
                      # Simple check if sensitive key is part of the arg
                      is_sensitive_arg = any(sk in lower_arg for sk in sensitive_keys_lower if sk in lower_arg)
                      if is_sensitive_arg:
                           if "=" in arg: # Attempt to redact value part of "KEY=VALUE"
                                parts = arg.split("=", 1)
                                redacted_args.append(f"{parts[0]}=********")
                           else: # Redact whole arg if no '=' found
                                redacted_args.append("********")
                      else:
                           redacted_args.append(arg)
            else: # Handle case where args might be None
                redacted_args = []

            # Also redact sensitive env vars
            redacted_env = {}
            if server_params.env:
                for env_key, env_val in server_params.env.items():
                    lower_env_key = env_key.lower()
                    is_sensitive_env = any(sk in lower_env_key for sk in sensitive_keys_lower if sk in lower_env_key)
                    redacted_env[env_key] = "********" if is_sensitive_env and env_val is not None else env_val
            
            logger.info(f"Attempting MCP connection for {connection_type} tool discovery. Command='{server_params.command}', Args='{' '.join(redacted_args)}', Env={redacted_env}", extra={'correlation_id': correlation_id})

            # Connect and list tools
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    logger.info(f"Initializing MCP session for {connection_type} tool discovery...", extra={'correlation_id': correlation_id})
                    try: 
                        await asyncio.wait_for(session.initialize(), timeout=90.0) # Increased timeout for process startup
                    except asyncio.TimeoutError: 
                        logger.error(f"Timeout initializing MCP session for {connection_type} tool discovery.", extra={'correlation_id': correlation_id})
                        raise ValueError(f"Timeout initializing MCP session for {connection_type}")
                    except Exception as init_err: 
                        logger.error(f"MCP Initialization error during tool discovery for {connection_type}: {init_err}", extra={'correlation_id': correlation_id})
                        raise ValueError(f"Error initializing MCP session for {connection_type}: {init_err}")

                    logger.info(f"Listing tools via MCP session for {connection_type}...", extra={'correlation_id': correlation_id})
                    try:
                         response = await asyncio.wait_for(session.list_tools(), timeout=20.0) # Shorter timeout for list_tools call
                         
                         # --- Parse MCP Tool Info --- 
                         parsed_tools: List[MCPToolInfo] = []
                         mcp_tools_list = getattr(response, 'tools', [])
                         if not isinstance(mcp_tools_list, list): 
                             logger.warning(f"MCP list_tools response for {connection_type} lacked a list in 'tools' attribute.", extra={'correlation_id': correlation_id})
                             mcp_tools_list = [] # Treat as empty

                         for mcp_tool in mcp_tools_list:
                             try:
                                 # Use MCPToolInfo directly if the structure matches, otherwise adapt
                                 # Assuming mcp_tool has 'name', 'description', 'inputSchema' attributes
                                 tool_info = MCPToolInfo(
                                     name=getattr(mcp_tool, 'name', 'Unknown Tool'),
                                     description=getattr(mcp_tool, 'description', None),
                                     inputSchema=getattr(mcp_tool, 'inputSchema', {}) # Ensure schema is a dict
                                 )
                                 if not isinstance(tool_info.inputSchema, dict):
                                      logger.warning(f"Tool '{tool_info.name}' has invalid inputSchema format (not a dict), using empty schema.", extra={'correlation_id': correlation_id})
                                      tool_info.inputSchema = {}

                                 parsed_tools.append(tool_info)
                             except AttributeError as attr_err:
                                  logger.error(f"Tool object from MCP list_tools response missing expected attribute: {attr_err}. Skipping tool.", extra={'correlation_id': correlation_id})
                                  continue
                             except Exception as tool_parse_err:
                                 logger.error(f"Skipping tool parsing due to unexpected error: {tool_parse_err}", extra={'correlation_id': correlation_id}, exc_info=True)
                                 continue 
                         # --- End Parsing --- 
                         
                         logger.info(f"Retrieved {len(parsed_tools)} tools info for {connection_type}", extra={'correlation_id': correlation_id})
                         return parsed_tools
                         
                    except asyncio.TimeoutError: 
                        logger.error(f"Timeout listing tools via MCP for {connection_type}.", extra={'correlation_id': correlation_id})
                        raise ValueError(f"Timeout listing tools via MCP for {connection_type}")
                    except Exception as list_err: 
                        logger.error(f"MCP list_tools error during tool discovery for {connection_type}: {list_err}", extra={'correlation_id': correlation_id})
                        raise ValueError(f"Error listing tools via MCP for {connection_type}: {list_err}")
        
        except FileNotFoundError as e: 
             logger.error(f"Command not found error during tool discovery for {connection_type}: {e}", extra={'correlation_id': correlation_id})
             raise ValueError(f"Command not found for {connection_type}: {str(e)}") 
        except ValueError as e:
             # Catch ValueErrors raised by get_handler, get_stdio_params, or within the MCP communication block
             logger.error(f"Configuration or communication error during tool discovery for {connection_type}: {e}", extra={'correlation_id': correlation_id})
             raise # Re-raise the specific ValueError
        except Exception as e: 
             logger.error(f"Unexpected error during tool discovery for {connection_type}: {e}", extra={'correlation_id': correlation_id}, exc_info=True)
             raise ValueError(f"Failed to communicate with MCP for {connection_type}: {str(e)}")
