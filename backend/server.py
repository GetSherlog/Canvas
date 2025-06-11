import os
import time
from typing import Dict
from uuid import UUID, uuid4
from pathlib import Path
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import redis.asyncio as redis

from backend.config import get_settings
from backend.core.execution import CellExecutor, ExecutionQueue
from backend.routes.connections import router as connections_router
from backend.routes.notebooks import router as notebooks_router
from backend.routes.chat import router as chat_router
from backend.routes.models import router as models_router
from backend.services.connection_manager import ConnectionManager
from backend.services.notebook_manager import NotebookManager
from backend.db.chat_db import ChatDatabase
from backend.core.logging import setup_logging, get_logger
from backend.services.connection_handlers.registry import get_all_handler_types
from backend.websockets import WebSocketManager
from backend.db.database import init_db, async_session_factory # Import the factory directly

# Initialize loggers
app_loggers = setup_logging()
app_logger = get_logger('app')
request_logger = get_logger('request')
websocket_logger = get_logger('websocket')
execution_logger = get_logger('execution')
notebook_logger = get_logger('notebook')
connection_logger = get_logger('connection')

settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application startup and shutdown events.
    - Initialize database connection
    - Initialize services with correct dependencies
    - Start background tasks (like execution queue)
    - Clean up resources on shutdown
    """
    app_logger.info(f"Application starting up in environment: {settings.environment}")
    
    # --- Clear initial incorrect state setup ---
    app.state.chat_agents = {} 
    app.state.redis = None 
    app.state.chat_db = None 
    app_logger.info("Initialized basic shared application state attributes.")
    
    # Import connection handlers to trigger registration
    try:
        # Import the workspace handler which is the only one we need now
        from backend.services.connection_handlers import workspace_handler  # noqa: F401
        app_logger.info(f"Successfully imported and registered connection handlers: {get_all_handler_types()}")
    except ImportError as e:
        app_logger.error(f"Failed to import connection handlers: {e}", exc_info=True)
        # Depending on requirements, you might want to raise here to prevent startup
        # if connection handlers are critical.

    # Create data directory if it doesn't exist
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    app_logger.info(f"Ensured data directory exists at {data_dir.absolute()}")
    
    # --- Initialize database ---
    app_logger.info("Initializing database tables")
    try:
        await init_db() # This creates tables
        # Store the imported async_session_factory in app.state
        app.state.async_session_factory = async_session_factory # Use the directly imported factory
        app_logger.info("Database initialized (tables checked/created) and async_session_factory stored in app.state.")
    except Exception as e:
        app_logger.error(f"Database initialization failed: {e}", exc_info=True)
        raise 
    
    # --- Initialize chat database ---
    app_logger.info("Initializing chat database connection")
    try:
        chat_db_ctx = ChatDatabase.connect(Path("data")) # Use Path object
        app.state.chat_db = await chat_db_ctx.__aenter__()
        app_logger.info("Chat database initialized successfully")
    except Exception as e:
        app_logger.error(f"Failed to initialize chat database: {str(e)}", exc_info=True)
        raise
    
    # --- Initialize Redis client ---
    app_logger.info(f"Initializing Redis connection to {settings.redis_host}:{settings.redis_port}")
    try:
        redis_client = await redis.from_url(
            f"redis://{settings.redis_host}:{settings.redis_port}/{settings.redis_db}",
            password=settings.redis_password,
            encoding="utf-8",
            decode_responses=True
        )
        await redis_client.ping() 
        app.state.redis = redis_client
        app_logger.info("Redis connection pool created and attached to app state.")
    except redis.RedisError as e:
        app_logger.error(f"Failed to initialize Redis connection: {str(e)}", exc_info=True)
        app.state.redis = None
    except Exception as e: 
        app_logger.error(f"An unexpected error occurred during Redis initialization: {str(e)}", exc_info=True)
        app.state.redis = None

    # --- Correctly Initialize Core Services (Singletons in app.state) ---
    connection_manager = ConnectionManager()
    app.state.connection_manager = connection_manager
    app_logger.info("ConnectionManager initialized.")

    execution_queue = ExecutionQueue()
    app.state.execution_queue = execution_queue # Assign BEFORE using it
    app_logger.info("ExecutionQueue initialized.")
    
    cell_executor = CellExecutor(notebook_manager=None, connection_manager=connection_manager)
    app.state.cell_executor = cell_executor
    app_logger.info("CellExecutor initialized (without NotebookManager initially).")

    notebook_manager = NotebookManager(
        execution_queue=execution_queue, 
        cell_executor=cell_executor
    )
    app.state.notebook_manager = notebook_manager
    app_logger.info("NotebookManager initialized and linked with ExecutionQueue and CellExecutor.")
    
    cell_executor.notebook_manager = notebook_manager
    app_logger.info("CellExecutor updated with NotebookManager reference.")
    
    app_logger.info("Application services initialization completed")
    
    # --- Initialize WebSocket Manager with Redis & Set Callback ---
    # Pass the initialized redis client (ensure it's not None, handle error if needed)
    redis_client_instance = getattr(app.state, 'redis', None)
    if not redis_client_instance:
        # This case should ideally be handled during Redis init, but double-check
        app_logger.error("Redis client is not initialized. WebSocketManager cannot use Pub/Sub.")
        # Decide on behavior: raise error, or let ws_manager init without redis?
        # For now, let it init but log error. Broadcasting will fail later.
        ws_manager = WebSocketManager(redis_client=None)
    else:
        ws_manager = WebSocketManager(redis_client=redis_client_instance)
        
    app.state.ws_manager = ws_manager
    app_logger.info("WebSocketManager initialized.")

    async def notify_clients(notebook_id: UUID, cell_data: Dict):
        app_logger.debug(f"Notify callback triggered for notebook {notebook_id}, cell {cell_data.get('id')}")
        if hasattr(app.state, 'ws_manager') and app.state.ws_manager: 
            await app.state.ws_manager.broadcast(notebook_id, {"type": "cell_update", "data": cell_data})
        else:
            app_logger.error("WebSocketManager not found in app.state during notify call")

    if hasattr(app.state, 'notebook_manager') and app.state.notebook_manager:
        app.state.notebook_manager.set_notify_callback(notify_clients)
        app_logger.info("Set notify_callback for NotebookManager.")
    else:
        app_logger.error("NotebookManager not found in app.state when setting notify callback.")

    # --- Start Execution Queue Processing (AFTER setup) --- 
    app_logger.info("Starting ExecutionQueue processing.")
    try:
        # Use the queue instance already assigned to app.state
        await app.state.execution_queue.start() 
        app_logger.info("ExecutionQueue processing started successfully.")
    except Exception as e:
        app_logger.error(f"Failed to start ExecutionQueue processing: {e}", exc_info=True)
        raise 

    # --- Start WebSocket Listener (if Redis is available) ---
    if hasattr(app.state, 'ws_manager') and app.state.ws_manager and app.state.ws_manager.redis_client:
        app_logger.info("Starting WebSocketManager Redis listener...")
        try:
            await app.state.ws_manager.start_listener()
            app_logger.info("WebSocketManager Redis listener started.")
        except Exception as e:
            app_logger.error(f"Failed to start WebSocketManager Redis listener: {e}", exc_info=True)
    else:
        app_logger.warning("WebSocketManager Redis listener not started (Redis client unavailable).")

    # --- Initialize Chat Agents Cache ---
    app.state.chat_agents = {} 
    app_logger.info("Chat agents cache initialized.")

    app_logger.info("Application startup fully completed")

    yield
    
    # --- Shutdown ---
    app_logger.info("Application shutdown initiated")
    
    # --- Stop Execution Queue --- 
    # Remove explicit task cancellation
    if hasattr(app.state, 'execution_queue') and app.state.execution_queue:
        app_logger.info("Stopping execution queue...")
        try:
             await app.state.execution_queue.stop()
             app_logger.info("Execution queue stopped.")
        except Exception as e:
             app_logger.error(f"Error stopping execution queue: {e}", exc_info=True)
    
    # --- Stop WebSocket Listener ---
    if hasattr(app.state, 'ws_manager') and app.state.ws_manager:
        app_logger.info("Stopping WebSocketManager Redis listener...")
        try:
            await app.state.ws_manager.stop_listener()
        except Exception as e:
            app_logger.error(f"Error stopping WebSocketManager Redis listener: {e}", exc_info=True)
    
    # --- Close chat database connection ---
    if hasattr(app.state, "chat_db") and app.state.chat_db:
        app_logger.info("Closing chat database connection")
        try:
            # Assuming _asyncify exists or adapt if needed
            await app.state.chat_db._asyncify(app.state.chat_db.con.close) 
            app_logger.info("Chat database connection closed")
        except Exception as e:
            app_logger.error(f"Error closing chat database connection: {str(e)}", exc_info=True)
    
    # --- Close Redis connection ---
    if hasattr(app.state, "redis") and app.state.redis:
        app_logger.info("Closing Redis connection pool")
        try:
            await app.state.redis.close()
            app_logger.info("Redis connection pool closed")
        except Exception as e:
            app_logger.error(f"Error closing Redis connection pool: {str(e)}", exc_info=True)
    
    # --- Clear agent cache ---
    if hasattr(app.state, "chat_agents"):
         app_logger.info(f"Clearing chat agent cache ({len(app.state.chat_agents)} instances).")
         app.state.chat_agents.clear()
    
    app_logger.info("Application shutdown completed")

# Initialize FastAPI app
app = FastAPI(
    title="Sherlog Canvas",
    description="Reactive notebook for software engineering investigations",
    version="0.1.0",
    lifespan=lifespan
)
# logfire.instrument_fastapi(app)

# Remove global manager instances - now managed in app.state via lifespan
# notebook_manager = NotebookManager()
# connection_manager = ConnectionManager()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Update with production origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Remove direct state assignment - handled by lifespan
# app.state.notebook_manager = notebook_manager
# app.state.connection_manager = connection_manager

# Register routers
app.include_router(notebooks_router, prefix="/api/notebooks", tags=["notebooks"])
app.include_router(connections_router, prefix="/api/connections", tags=["connections"])
app.include_router(chat_router, prefix="/api/v1/chat", tags=["chat"])
app.include_router(models_router, prefix="/api/models", tags=["models"])

# Enhanced request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid4()))
    start_time = time.time()
    
    # Add correlation ID to request state
    request.state.correlation_id = request_id
    
    request_logger.info(
        "Request started",
        extra={
            'correlation_id': request_id,
            'method': request.method,
            'url': str(request.url),
            'client_host': request.client.host if request.client else None,
            'headers': dict(request.headers)
        }
    )
    
    try:
        response = await call_next(request)
        process_time = time.time() - start_time
        request_logger.info(
            "Request completed",
            extra={
                'correlation_id': request_id,
                'status_code': response.status_code,
                'processing_time_ms': round(process_time * 1000, 2)
            }
        )
        return response
    except Exception as e:
        process_time = time.time() - start_time
        request_logger.error(
            "Request failed",
            extra={
                'correlation_id': request_id,
                'error': str(e),
                'error_type': type(e).__name__,
                'processing_time_ms': round(process_time * 1000, 2)
            },
            exc_info=True
        )
        raise

# Remove old global queue init: # execution_queue = ExecutionQueue()

@app.get("/api/health")
def health_check():
    """Simple health check endpoint"""
    return {"status": "running", "version": "0.1.0"}

# Remove old websocket endpoint (lines 360-434)

if __name__ == "__main__":
    # Check if inside Docker to determine host
    if os.path.exists('/.dockerenv'):
        host = "0.0.0.0"
    else:
        host = "127.0.0.1"
        
    # Run the uvicorn server
    uvicorn.run(
        "backend.server:app",
        host=host,
        port=8000,
        reload=True,
        log_level=os.environ.get("LOG_LEVEL", "info").lower()
    )
