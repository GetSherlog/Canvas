import asyncio
import json
import logging
import sqlite3
from concurrent.futures.thread import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any, Callable, List, Optional, TypeVar, AsyncGenerator, Dict

from pydantic import BaseModel, Field

# Initialize logger
chat_logger = logging.getLogger("chat.db")

# Add correlation ID filter to the logger
class CorrelationIdFilter(logging.Filter):
    def filter(self, record):
        # Instead of requiring correlation_id, just add it if missing
        if not hasattr(record, 'correlation_id'):
            record.correlation_id = 'N/A'
        return True

chat_logger.addFilter(CorrelationIdFilter())

# Type variables for async function
P = TypeVar('P', bound=Any)
R = TypeVar('R')

@dataclass
class ChatDatabase:
    """
    Database to store chat messages with SQLite.
    
    Uses a thread pool executor to run queries asynchronously
    since SQLite is synchronous.
    """
    con: sqlite3.Connection
    _loop: asyncio.AbstractEventLoop
    _executor: ThreadPoolExecutor
    
    @classmethod
    @asynccontextmanager
    async def connect(cls, data_dir: Path) -> AsyncGenerator['ChatDatabase', None]:
        """Connect to the chat database"""
        chat_logger.info("Connecting to chat database")
        loop = asyncio.get_event_loop()
        executor = ThreadPoolExecutor(max_workers=1)
        
        # Create data directory if it doesn't exist
        data_dir.mkdir(parents=True, exist_ok=True)
        db_file = data_dir / "chat_history.sqlite"
        
        try:
            # Run the connection in the executor
            con = await loop.run_in_executor(executor, cls._connect, db_file)
            chat_db = cls(con, loop, executor)
            chat_logger.info(f"Connected to chat database at {db_file}")
            yield chat_db
        finally:
            if 'chat_db' in locals():
                await chat_db._asyncify(con.close)
                chat_logger.info("Closed chat database connection")
    
    @staticmethod
    def _connect(file: Path) -> sqlite3.Connection:
        """Create SQLite connection and initialize tables"""
        con = sqlite3.connect(str(file))
        cur = con.cursor()
        
        # Create tables if they don't exist
        cur.execute('''
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id TEXT PRIMARY KEY,
            notebook_id TEXT UNIQUE,
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        );
        ''')

        # Add index for notebook_id if it doesn't exist
        cur.execute('CREATE INDEX IF NOT EXISTS idx_notebook_id ON chat_sessions (notebook_id);')
        
        cur.execute('''
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            message_json TEXT,
            created_at TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
        );
        ''')
        
        con.commit()
        return con
    
    async def create_session(self, session_id: str, notebook_id: Optional[str] = None) -> None:
        """Create a new chat session"""
        chat_logger.info(f"Creating chat session: {session_id}")
        now = datetime.now(timezone.utc).isoformat()
        
        await self._asyncify(
            self._execute,
            "INSERT INTO chat_sessions (id, notebook_id, created_at, updated_at) VALUES (?, ?, ?, ?);",
            session_id, notebook_id, now, now,
            commit=True
        )
    
    async def update_session_timestamp(self, session_id: str) -> None:
        """Update session's last activity timestamp"""
        now = datetime.now(timezone.utc).isoformat()
        await self._asyncify(
            self._execute,
            "UPDATE chat_sessions SET updated_at = ? WHERE id = ?;",
            now, session_id,
            commit=True
        )
    
    async def get_session(self, session_id: str) -> Optional[dict]:
        """Get a chat session by ID"""
        cursor = await self._asyncify(
            self._execute,
            "SELECT id, notebook_id, created_at, updated_at FROM chat_sessions WHERE id = ?;",
            session_id
        )
        row = await self._asyncify(cursor.fetchone)
        
        if not row:
            return None
        
        return {
            "id": row[0],
            "notebook_id": row[1],
            "created_at": row[2],
            "updated_at": row[3]
        }
    
    async def get_session_by_notebook_id(self, notebook_id: str) -> Optional[dict]:
        """Get the chat session associated with a notebook ID."""
        # Since notebook_id is UNIQUE, this should return at most one row
        cursor = await self._asyncify(
            self._execute,
            "SELECT id, notebook_id, created_at, updated_at FROM chat_sessions WHERE notebook_id = ?;",
            notebook_id
        )
        row = await self._asyncify(cursor.fetchone)

        if not row:
            return None

        return {
            "id": row[0],
            "notebook_id": row[1],
            "created_at": row[2],
            "updated_at": row[3]
        }
    
    async def add_message(self, session_id: str, message: Dict) -> None:
        """Add a message to a chat session"""
        # Get current timestamp
        now = datetime.now(timezone.utc).isoformat()

        # Serialize message to JSON
        message_json = json.dumps(message)
        content_preview = str(message)[:100] # Preview content
        chat_logger.info(f"Serializing message of type: {type(message).__name__}, content preview: {content_preview}...")
        chat_logger.info(f"Serialized JSON: {message_json}")

        # Insert message
        chat_logger.info(f"Inserting message for session {session_id}. Type: {type(message).__name__}, Details: {str(message)}")
        await self._asyncify(
            self._execute,
            "INSERT INTO chat_messages (session_id, message_json, created_at) VALUES (?, ?, ?);",
            session_id, message_json, now,
            commit=True
        )

        # Update session timestamp
        await self.update_session_timestamp(session_id)
    
    async def add_messages(self, session_id: str, messages_json: str) -> None:
        """Add a batch of messages to a chat session from JSON"""
        # Parse messages
        messages = json.loads(messages_json)
        
        # Get current timestamp
        now = datetime.now(timezone.utc).isoformat()
        
        # Insert each message
        for message in messages:
            content_type = type(message).__name__
            message_json = json.dumps(message)
            chat_logger.info(f"Saving message (type: {content_type}). JSON: {message_json}")
            await self._asyncify(
                self._execute,
                "INSERT INTO chat_messages (session_id, message_json, created_at) VALUES (?, ?, ?);",
                session_id, message_json, now,
                commit=True
            )
        
        # Update session timestamp
        await self.update_session_timestamp(session_id)
    
    async def get_messages(self, session_id: str, limit: int = 100) -> List[Dict]:
        """Get messages for a chat session"""
        cursor = await self._asyncify(
            self._execute,
            "SELECT message_json FROM chat_messages WHERE session_id = ? ORDER BY id ASC LIMIT ?;",
            session_id, limit
        )
        rows = await self._asyncify(cursor.fetchall)
        
        messages = []
        for row in rows:
            message_json = row[0]
            chat_logger.info(f"Message JSON from get_messages: {message_json}")
            message = json.loads(message_json)
            messages.append(message)
        
        return messages
    
    async def clear_session_messages(self, session_id: str) -> None:
        """Clear all messages for a chat session"""
        await self._asyncify(
            self._execute,
            "DELETE FROM chat_messages WHERE session_id = ?;",
            session_id,
            commit=True
        )
        
        chat_logger.info(f"Cleared messages for session: {session_id}")
    
    def _execute(self, sql: str, *args, commit: bool = False) -> sqlite3.Cursor:
        """Execute SQL with parameters"""
        cursor = self.con.cursor()
        cursor.execute(sql, args)
        
        if commit:
            self.con.commit()
            
        return cursor
    
    async def _asyncify(self, func: Callable[..., R], *args, **kwargs) -> R:
        """Run a synchronous function in the thread pool executor"""
        return await self._loop.run_in_executor(
            self._executor,
            partial(func, **kwargs),
            *args
        ) 