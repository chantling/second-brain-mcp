import asyncio
import signal
import sys
from typing import Any
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from config import Config
from tools import ToolHandlers

# Create server instance
server = Server("second-brain")
tool_handlers = ToolHandlers()

@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools"""
    return [
        Tool(
            name="store_thought",
            description="Store a thought in both Supabase and Obsidian. Note: This tool may take up to 150 seconds due to AI metadata extraction. Please wait for completion before retrying.",
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The thought content"},
                    "title": {"type": "string", "description": "Optional title for the thought"},
                    "metadata": {"type": "object", "description": "Optional metadata dictionary", "additionalProperties": True},
                    "source": {"type": "string", "description": "Source of the thought"}
                },
                "required": ["content"]
            }
        ),
        Tool(
            name="semantic_search",
            description="Search thoughts by semantic similarity",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "description": "Maximum results"},
                    "topics": {"type": "array", "items": {"type": "string"}, "description": "Filter by topics"}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="list_recent",
            description="List recent thoughts from both systems",
            inputSchema={
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Number of days to look back"},
                    "thought_type": {"type": "string", "description": "Filter by thought type"}
                }
            }
        ),
        Tool(
            name="get_thought",
            description="Get a specific thought by ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "thought_id": {"type": "integer", "description": "Thought ID"}
                },
                "required": ["thought_id"]
            }
        ),
        Tool(
            name="search_by_topic",
            description="Search thoughts by specific topic",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Topic to search for"},
                    "limit": {"type": "integer", "description": "Maximum results"}
                },
                "required": ["topic"]
            }
        ),
        Tool(
            name="get_todos",
            description="Get todo items",
            inputSchema={
                "type": "object",
                "properties": {
                    "completed": {"type": "boolean", "description": "Include completed todos"}
                }
            }
        ),
        Tool(
            name="find_recipes",
            description="Find recipes based on criteria",
            inputSchema={
                "type": "object",
                "properties": {
                    "ingredients": {"type": "array", "items": {"type": "string"}, "description": "Required ingredients"},
                    "category": {"type": "string", "description": "Recipe category"},
                    "max_time": {"type": "integer", "description": "Maximum total time in minutes"}
                }
            }
        ),
        Tool(
            name="list_guides",
            description="List guides by category and difficulty",
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Guide category"},
                    "difficulty": {"type": "string", "description": "Difficulty level (easy, medium, hard)"}
                }
            }
        ),
        Tool(
            name="get_contacts",
            description="Get contact information",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name to search for"},
                    "category": {"type": "string", "description": "Contact category"}
                }
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """Handle tool calls"""
    try:
        result = await tool_handlers.handle_tool_call(name, arguments)
        return [TextContent(type="text", text=str(result))]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]

async def main():
    """Main MCP server entry point"""
    # Set up signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        print(f"\nReceived signal {signum}, shutting down gracefully...", file=sys.stderr)
        asyncio.create_task(shutdown())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Start the server
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options()
            )
    except KeyboardInterrupt:
        print("\nServer interrupted by user", file=sys.stderr)
    except Exception as e:
        print(f"Server error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        await shutdown()

async def shutdown():
    """Graceful shutdown"""
    print("Cleaning up resources...", file=sys.stderr)
    await tool_handlers.cleanup()
    print("Shutdown complete", file=sys.stderr)
    sys.exit(0)

if __name__ == "__main__":
    # Validate configuration before starting
    try:
        Config.validate()
        print("Starting Second Brain MCP Server...", file=sys.stderr)
        asyncio.run(main())
    except Exception as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)
