#!/usr/bin/env python3
"""
Test cell creation via API
"""
import requests
import json
import uuid

# API configuration
API_BASE_URL = "http://localhost:9091/api/v1"

def test_cell_creation():
    # First, create a notebook
    notebook_id = str(uuid.uuid4())
    
    # Create notebook
    response = requests.post(
        f"{API_BASE_URL}/notebooks",
        json={
            "id": notebook_id,
            "title": "Test Notebook for Cell Creation"
        }
    )
    print(f"Create notebook response: {response.status_code}")
    if response.status_code != 200:
        print(f"Error: {response.text}")
        return
    
    # Test chat endpoint with cell creation query
    chat_url = f"{API_BASE_URL}/notebooks/{notebook_id}/chat"
    
    queries = [
        "Create a markdown cell with the content '# Test Header'",
        "Add a python cell that prints 'Hello, World!'",
        "What cells are in this notebook?"
    ]
    
    for query in queries:
        print(f"\n\nTesting query: {query}")
        
        response = requests.post(
            chat_url,
            json={
                "prompt": query,
                "session_id": "test-session-" + str(uuid.uuid4())
            },
            stream=True
        )
        
        print(f"Response status: {response.status_code}")
        
        if response.status_code == 200:
            for line in response.iter_lines():
                if line:
                    try:
                        # Skip 'data: ' prefix if present
                        line_str = line.decode('utf-8')
                        if line_str.startswith('data: '):
                            line_str = line_str[6:]
                        
                        # Parse JSON
                        data = json.loads(line_str)
                        print(f"Event: {json.dumps(data, indent=2)}")
                    except json.JSONDecodeError as e:
                        print(f"Failed to parse line: {line}")
        else:
            print(f"Error: {response.text}")
    
    # Get notebook cells
    print("\n\nFetching notebook cells...")
    response = requests.get(f"{API_BASE_URL}/notebooks/{notebook_id}/cells")
    if response.status_code == 200:
        cells = response.json()
        print(f"Notebook has {len(cells)} cells:")
        for cell in cells:
            print(f"  - Cell {cell['id']}: type={cell['type']}, content preview: {cell.get('content', '')[:50]}...")
    else:
        print(f"Error fetching cells: {response.text}")

if __name__ == "__main__":
    test_cell_creation()