#!/usr/bin/env python3
"""Test MCP connection using various methods"""
import asyncio
import aiohttp
import json
import sys

async def test_raw_endpoints():
    """Test raw HTTP endpoints"""
    base_url = "http://localhost:8200"
    
    print("=== Testing Raw HTTP Endpoints ===")
    
    # Test different endpoint variations
    endpoints = ["/", "/mcp", "/sse", "/v1", "/api"]
    
    async with aiohttp.ClientSession() as session:
        for endpoint in endpoints:
            url = f"{base_url}{endpoint}"
            print(f"\nTesting {url}...")
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                    print(f"  Status: {response.status}")
                    print(f"  Headers: {dict(response.headers)}")
                    if response.status == 200:
                        try:
                            text = await response.text()
                            print(f"  Body preview: {text[:100]}...")
                        except:
                            pass
            except Exception as e:
                print(f"  Error: {type(e).__name__}: {e}")

async def test_mcp_client():
    """Test using MCP Python SDK client"""
    print("\n=== Testing MCP Python SDK Client ===")
    
    try:
        # Try importing MCP SDK
        from mcp.client.streamable_http import streamablehttp_client
        from mcp import ClientSession
        
        print("MCP SDK imported successfully")
        
        # Test with different URL variations
        urls = [
            "http://localhost:8200",
            "http://localhost:8200/mcp",
            "http://localhost:8200/sse"
        ]
        
        for url in urls:
            print(f"\nTrying MCP client with URL: {url}")
            try:
                async with streamablehttp_client(url) as (read_stream, write_stream, sse):
                    print("  Connected to streamable HTTP server")
                    
                    async with ClientSession(read_stream, write_stream) as session:
                        print("  Created client session")
                        
                        # Initialize the connection
                        result = await session.initialize()
                        print(f"  Initialize result: {result}")
                        
                        # List available tools
                        tools = await session.list_tools()
                        print(f"  Available tools: {len(tools.tools)} tools")
                        if tools.tools:
                            print(f"  First tool: {tools.tools[0].name}")
                        
            except Exception as e:
                print(f"  Error: {type(e).__name__}: {e}")
                
    except ImportError:
        print("MCP SDK not installed. Installing...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "mcp"])
        print("Please run the script again after installation")

async def test_agno_style():
    """Test Agno-style connection"""
    print("\n=== Testing Agno-style Connection ===")
    
    try:
        # Try importing Agno
        from agno.tools.mcp import MCPTools
        
        print("Agno imported successfully")
        
        urls = [
            "http://localhost:8200",
            "http://localhost:8200/mcp"
        ]
        
        for url in urls:
            print(f"\nTrying Agno MCPTools with URL: {url}")
            try:
                # Create MCPTools instance using async context manager
                async with MCPTools(
                    url=url,
                    transport="streamable-http",
                    timeout_seconds=30
                ) as mcp_tools:
                    print("  Created MCPTools instance in context")
                    
                    # Try to access tools
                    if hasattr(mcp_tools, 'available_tools'):
                        print(f"  Available tools: {mcp_tools.available_tools}")
                    else:
                        print("  MCPTools created but no available_tools attribute")
                    
                    # Try to list attributes
                    attrs = [attr for attr in dir(mcp_tools) if not attr.startswith('_')]
                    print(f"  MCPTools attributes: {attrs[:10]}...")
                    
            except Exception as e:
                print(f"  Error with context manager: {type(e).__name__}: {e}")
                import traceback
                traceback.print_exc()
                
    except ImportError:
        print("Agno not installed")

async def main():
    """Run all tests"""
    await test_raw_endpoints()
    await test_mcp_client()
    await test_agno_style()

if __name__ == "__main__":
    asyncio.run(main())