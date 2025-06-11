#!/usr/bin/env python3
"""
Test script to verify cell creation functionality
"""
import asyncio
import uuid
from backend.ai.chat_router import ChatRouter
from backend.services.notebook_manager import NotebookManager
from backend.db.database import get_db_session
from backend.config import get_settings

async def test_cell_creation():
    """Test the cell creation flow"""
    settings = get_settings()
    
    # Create a test notebook ID
    notebook_id = str(uuid.uuid4())
    print(f"Testing with notebook ID: {notebook_id}")
    
    # Initialize notebook manager
    notebook_manager = NotebookManager(redis_url=settings.redis_url)
    
    # Create a test notebook
    async with get_db_session() as db:
        await notebook_manager.create_notebook(
            db=db,
            notebook_id=uuid.UUID(notebook_id),
            title="Test Notebook for Cell Creation"
        )
    
    # Initialize chat router
    chat_router = ChatRouter(notebook_id, notebook_manager)
    
    # Test query classification
    test_queries = [
        "Create a markdown cell with the title 'Test'",
        "Add a python cell that prints hello world",
        "What is this notebook for?",
        "Analyze the logs for errors"
    ]
    
    for query in test_queries:
        print(f"\nTesting query: {query}")
        classification = await chat_router.classify_query(query)
        print(f"Classification: {classification.classification} (confidence: {classification.confidence})")
        print(f"Reasoning: {classification.reasoning}")
    
    # Test actual cell creation
    print("\n\nTesting actual cell creation...")
    cell_creation_query = "Create a markdown cell with the content '# Hello World'"
    
    async for msg_type, msg_data in chat_router.handle_message(
        prompt=cell_creation_query,
        session_id="test-session-123",
        message_history=[]
    ):
        print(f"\n{msg_type}: {msg_data}")
    
    # Check if cell was created
    async with get_db_session() as db:
        notebook = await notebook_manager.get_notebook(db=db, notebook_id=uuid.UUID(notebook_id))
        print(f"\nNotebook has {len(notebook.cells)} cells")
        for cell_id, cell in notebook.cells.items():
            print(f"Cell {cell_id}: type={cell.type.value}, content={cell.content[:50]}...")

if __name__ == "__main__":
    asyncio.run(test_cell_creation())