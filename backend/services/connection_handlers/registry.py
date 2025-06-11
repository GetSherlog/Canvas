"""
Connection Handler Registry
"""

from typing import Dict, List
import logging

from .base import MCPConnectionHandler

logger = logging.getLogger(__name__)

# Global registry
_handler_registry: Dict[str, MCPConnectionHandler] = {}


def register_handler(handler_instance: MCPConnectionHandler):
    """Registers a connection handler instance."""
    connection_type = handler_instance.get_connection_type()
    if connection_type in _handler_registry:
        logger.warning(f"Handler for connection type '{connection_type}' is being overridden.")
    logger.info(f"Registering handler for connection type: {connection_type}")
    _handler_registry[connection_type] = handler_instance


def get_handler(connection_type: str) -> MCPConnectionHandler:
    """Retrieves a handler instance for the given connection type."""
    handler = _handler_registry.get(connection_type)
    if not handler:
        raise ValueError(f"No handler registered for connection type: {connection_type}")
    return handler

def get_all_handler_types() -> List[str]:
    """Returns a list of all registered connection handler types."""
    return list(_handler_registry.keys())

def get_all_handlers() -> Dict[str, MCPConnectionHandler]:
    """Returns the entire handler registry."""
    return _handler_registry.copy() 