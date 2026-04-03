import asyncio
import os
import random
import signal
import sys
from pathlib import Path
from typing import Any
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from config import Config
from tools import ToolHandlers
import logging
from datetime import datetime

# Global file watcher reference
_file_watcher_observer = None
_cleanup_timer_task = None
_move_processor_task = None
_heartbeat_task = None

# Global sync status tracking
_orphan_cleanup_enabled = False
_initial_sync_complete = False
_initial_sync_running = False


# Helper function for debug logging
def debug_log(msg: str):
    """Print debug message if DEBUG is enabled"""
    if Config.DEBUG:
        print(msg, file=sys.stderr)


# Setup file logging with timestamps (toggleable via FILE_LOGGING config)
def setup_logging():
    """Setup file logging to Logs directory with timestamps
    
    Controlled by Config.FILE_LOGGING:
    - True: Log to both file and stderr
    - False: Log to stderr only (default behavior)
    """
    log_dir = Path("Logs")
    
    if Config.FILE_LOGGING:
        # Create Logs directory if it doesn't exist
        log_dir.mkdir(exist_ok=True)
        
        # Create log filename with current date
        log_filename = log_dir / f"second_brain_{datetime.now().strftime('%Y-%m-%d')}.log"
        
        # Configure logging with file handler
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            handlers=[
                logging.FileHandler(log_filename, encoding='utf-8'),
                logging.StreamHandler(sys.stderr)
            ],
            force=True
        )
        
        print(f"[LOGGING] File logging enabled: {log_filename}", file=sys.stderr)
    else:
        # Configure logging to stderr only
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            handlers=[logging.StreamHandler(sys.stderr)],
            force=True
        )
        
        print("[LOGGING] File logging disabled (set FILE_LOGGING=true to enable)", file=sys.stderr)
    
    return logging.getLogger('second_brain')

# Initialize logger
logger = setup_logging()


# Create server instance
server = Server("second-brain")
tool_handlers = ToolHandlers()


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools"""
    return [
        Tool(
            name="store_thought",
            description="Store a thought in both Supabase and Obsidian. Note: This tool may take up to 240 seconds due to AI metadata extraction. Please wait for completion before retrying.",
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The thought content"},
                    "title": {
                        "type": "string",
                        "description": "Optional title for the thought",
                    },
                    "metadata": {
                        "type": "object",
                        "description": "Optional metadata dictionary",
                        "additionalProperties": True,
                    },
                    "source": {
                        "type": "string",
                        "description": "Source of the thought",
                    },
                },
                "required": ["content"],
            },
        ),
        Tool(
            name="semantic_search",
            description="Search thoughts by semantic similarity. The server is immediately available, though search results may be incomplete during initial background sync. Subsequent calls are fast.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "description": "Maximum results"},
                    "topics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by topics",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="list_recent",
            description="List recent thoughts from both systems. The server is immediately available, though results may be incomplete during initial background sync. Subsequent calls are fast.",
            inputSchema={
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "Number of days to look back",
                    },
                    "thought_type": {
                        "type": "string",
                        "description": "Filter by thought type",
                    },
                },
            },
        ),
        Tool(
            name="get_thought",
            description="Get a specific thought by ID. The server is immediately available, though results may be incomplete during initial background sync. Subsequent calls are fast.",
            inputSchema={
                "type": "object",
                "properties": {
                    "thought_id": {"type": "integer", "description": "Thought ID"}
                },
                "required": ["thought_id"],
            },
        ),
        Tool(
            name="search_by_topic",
            description="Search thoughts by specific topic. The server is immediately available, though results may be incomplete during initial background sync. Subsequent calls are fast.",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Topic to search for"},
                    "limit": {"type": "integer", "description": "Maximum results"},
                },
                "required": ["topic"],
            },
        ),
        Tool(
            name="get_todos",
            description="Get todo items. The server is immediately available, though results may be incomplete during initial background sync. Subsequent calls are fast.",
            inputSchema={
                "type": "object",
                "properties": {
                    "completed": {
                        "type": "boolean",
                        "description": "Include completed todos",
                    }
                },
            },
        ),
        Tool(
            name="find_recipes",
            description="Find recipes based on criteria. The server is immediately available, though results may be incomplete during initial background sync. Subsequent calls are fast.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ingredients": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Required ingredients",
                    },
                    "category": {"type": "string", "description": "Recipe category"},
                    "max_time": {
                        "type": "integer",
                        "description": "Maximum total time in minutes",
                    },
                },
            },
        ),
        Tool(
            name="list_guides",
            description="List guides by category and difficulty. The server is immediately available, though results may be incomplete during initial background sync. Subsequent calls are fast.",
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Guide category"},
                    "difficulty": {
                        "type": "string",
                        "description": "Difficulty level (easy, medium, hard)",
                    },
                },
            },
        ),
        Tool(
            name="get_contacts",
            description="Get contact information. The server is immediately available, though results may be incomplete during initial background sync. Subsequent calls are fast.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name to search for"},
                    "category": {"type": "string", "description": "Contact category"},
                },
            },
        ),
        Tool(
            name="get_backlinks",
            description="Get all notes that link to a given note. The server is immediately available, though results may be incomplete during initial background sync. Subsequent calls are fast.",
            inputSchema={
                "type": "object",
                "properties": {
                    "thought_id": {"type": "integer", "description": "Thought ID"},
                    "limit": {"type": "integer", "description": "Max results"},
                },
                "required": ["thought_id"],
            },
        ),
        Tool(
            name="find_related_notes",
            description="Find related notes via shared links and tags. The server is immediately available, though results may be incomplete during initial background sync. Subsequent calls are fast.",
            inputSchema={
                "type": "object",
                "properties": {
                    "thought_id": {"type": "integer", "description": "Thought ID"},
                    "limit": {"type": "integer", "description": "Max results"},
                },
                "required": ["thought_id"],
            },
        ),
        Tool(
            name="suggest_tags",
            description="Suggest tags for a note based on content. The server is immediately available, though results may be incomplete during initial background sync. Subsequent calls are fast.",
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Note content"},
                    "limit": {"type": "integer", "description": "Max suggestions"},
                },
                "required": ["content"],
            },
        ),
        Tool(
            name="hybrid_search",
            description="Advanced search with vector + keywords + filters. The server is immediately available, though results may be incomplete during initial background sync. Subsequent calls are fast.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "description": "Max results"},
                    "filters": {
                        "type": "object",
                        "description": "Filters (type, folder, tags)",
                    },
                    "weights": {"type": "object", "description": "Scoring weights"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="search_by_keyword",
            description="Search for exact words or phrases in note content using full-text search. Finds exact matches regardless of topic tags. The server is immediately available, though results may be incomplete during initial background sync. Subsequent calls are fast.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Exact word or phrase to search for",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 10)",
                    },
                },
                "required": ["query"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """Handle tool calls"""
    start_time = datetime.now()
    logger.info(f"[TOOL] Starting tool call: {name}")

    try:
        # Wrap tool handler with overall timeout (45s to beat MCP Inspector's 60s)
        result = await asyncio.wait_for(
            tool_handlers.handle_tool_call(name, arguments),
            timeout=45.0,
        )

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"[TOOL] Completed tool call: {name} in {elapsed:.2f}s")

        # Run orphan cleanup after each tool call (non-blocking, best effort)
        if Config.SYNC_ENABLED:
            asyncio.ensure_future(_run_orphan_cleanup_after_tool_call())

        return [TextContent(type="text", text=str(result))]
    except asyncio.TimeoutError:
        elapsed = (datetime.now() - start_time).total_seconds()
        logger.error(f"[TOOL] Tool call timed out: {name} after {elapsed:.2f}s")
        return [TextContent(type="text", text=f"Error: Tool call '{name}' timed out")]
    except Exception as e:
        elapsed = (datetime.now() - start_time).total_seconds()
        logger.error(f"[TOOL] Tool call failed: {name} after {elapsed:.2f}s - {e}")
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def _periodic_orphan_cleanup_loop(interval: int):
    """Periodically clean up orphaned Supabase entries"""
    from obsidian import ObsidianManager
    import tools

    while True:
        try:
            await asyncio.sleep(interval)
            # Skip if orphan cleanup is not yet enabled
            if not _orphan_cleanup_enabled:
                continue
            # Run orphan cleanup
            obsidian_manager = ObsidianManager(
                Config.OBSIDIAN_VAULT_PATH, db_manager=tools.db_manager
            )
            sync_result = obsidian_manager.get_last_sync_result()
            await obsidian_manager.remove_orphaned_supabase_entries(
                exclude_ids=sync_result.get("ids", []) if sync_result else []
            )
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(
                f"[WARNING] Periodic orphan cleanup failed: {e}",
                file=sys.stderr,
            )


async def _run_orphan_cleanup_after_tool_call():
    """Run orphan cleanup after a tool call (non-blocking).

    Waits for initial sync to complete before running to prevent race condition
    where orphan cleanup deletes entries that haven't been synced yet.
    """
    try:
        # Wait for orphan cleanup to be enabled (initial sync must complete first)
        if not _orphan_cleanup_enabled:
            return

        from obsidian import ObsidianManager
        import tools

        obsidian_manager = ObsidianManager(
            Config.OBSIDIAN_VAULT_PATH, db_manager=tools.db_manager
        )
        sync_result = obsidian_manager.get_last_sync_result()
        await obsidian_manager.remove_orphaned_supabase_entries(
            exclude_ids=sync_result.get("ids", []) if sync_result else []
        )
    except Exception as e:
        logger.warning(f"Orphan cleanup after tool call failed: {e}")


async def _run_warmup_background():
    """Run embedding warmup in background (non-blocking)"""
    import tools

    start_time = datetime.now()
    logger.info("[WARMUP] Starting embedding warmup in background...")

    try:
        await tools.embedding_generator.warmup()
        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"[WARMUP] Embedding warmup completed successfully in {elapsed:.2f}s")
    except Exception as e:
        elapsed = (datetime.now() - start_time).total_seconds()
        logger.error(f"[WARMUP] Background warmup failed after {elapsed:.2f}s: {e}")


async def _run_folder_sync_startup():
    """Run folder sync on server startup (non-blocking background task)"""
    try:
        print("[SYNC] Starting folder sync on startup...", file=sys.stderr)
        await tool_handlers._sync_folders()
        print("[SYNC] Folder sync completed on startup", file=sys.stderr)
    except Exception as e:
        print(f"[ERROR] Folder sync failed on startup: {e}", file=sys.stderr)


async def _run_orphan_cleanup_startup():
    """Run orphan cleanup on server startup (non-blocking background task)"""
    print(
        "[SYNC] Orphan cleanup task started, waiting for initial sync...",
        file=sys.stderr,
    )
    try:
        # Wait for orphan cleanup to be enabled (poll every 5 seconds, up to 10 minutes)
        max_wait_seconds = 600
        poll_interval = 5
        elapsed = 0
        while not _orphan_cleanup_enabled and elapsed < max_wait_seconds:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        if not _orphan_cleanup_enabled:
            print(
                f"[SYNC] Orphan cleanup still disabled after {max_wait_seconds}s, skipping",
                file=sys.stderr,
            )
            return

        print("[SYNC] Running orphan cleanup on startup...", file=sys.stderr)
        from obsidian import ObsidianManager
        import tools

        obsidian_manager = ObsidianManager(
            Config.OBSIDIAN_VAULT_PATH, db_manager=tools.db_manager
        )
        sync_result = obsidian_manager.get_last_sync_result()
        await obsidian_manager.remove_orphaned_supabase_entries(
            exclude_ids=sync_result.get("ids", []) if sync_result else []
        )
        print("[SYNC] Orphan cleanup completed on startup", file=sys.stderr)
    except Exception as e:
        print(f"[ERROR] Orphan cleanup failed on startup: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()


async def _run_initial_sync():
    """Run initial sync as a background task"""
    global _initial_sync_running, _initial_sync_complete, _orphan_cleanup_enabled

    try:
        _initial_sync_running = True
        debug_log("[SYNC] Starting initial sync in background...")

        from obsidian import ObsidianManager
        import tools

        obsidian_manager = ObsidianManager(
            Config.OBSIDIAN_VAULT_PATH, db_manager=tools.db_manager
        )
        await obsidian_manager.sync_existing_notes_to_supabase()

        _initial_sync_complete = True
        debug_log("[SYNC] Initial sync complete. Server is fully operational.")

        # Enable orphan cleanup ONLY after initial sync is fully complete
        # This prevents orphan cleanup from racing with the sync
        _orphan_cleanup_enabled = True
        debug_log("[SYNC] Orphan cleanup enabled.")
    except Exception as e:
        print(f"[ERROR] Initial sync failed: {e}", file=sys.stderr)
    finally:
        _initial_sync_running = False


async def main():
    """Main MCP server entry point with file watcher"""
    from watcher import start_file_watcher
    import tools

    main_start_time = datetime.now()
    logger.info(f"[MAIN] main() function started at {main_start_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}")
    print(f"[MAIN] main() function started at {main_start_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}", file=sys.stderr)

    # Flag to track shutdown request
    shutdown_requested = False

    # Initialize status variables
    background_tasks = []

    # Set up signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        nonlocal shutdown_requested, background_tasks
        global _file_watcher_observer
        if not shutdown_requested:
            shutdown_requested = True
            signal_msg = f"\nReceived signal {signum}, shutting down gracefully..."
            print(signal_msg, file=sys.stderr)
            logger.info(f"[MAIN] {signal_msg}")
            if _file_watcher_observer:
                _file_watcher_observer.stop()
            # Cancel background tasks
            for task in background_tasks:
                task.cancel()
            # Cancel all running tasks in the current event loop
            loop = asyncio.get_event_loop()
            for task in asyncio.all_tasks(loop):
                task.cancel()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Get or create event loop
        logger.info("[MAIN] Getting or creating event loop...")
        loop = asyncio.get_running_loop()
        if loop is None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            logger.info("[MAIN] Created new event loop")
        else:
            logger.info("[MAIN] Using existing event loop")

        # Server is ready immediately - warmup runs in background
        ready_msg = "[INIT] Server ready to accept requests (warmup in background)"
        print(ready_msg, file=sys.stderr)
        logger.info(ready_msg)

        # Initialize background tasks
        global _file_watcher_observer
        background_tasks = []

        # Run warmup in background (non-blocking)
        logger.info("[MAIN] Creating warmup background task...")
        warmup_task = loop.create_task(_run_warmup_background())
        background_tasks.append(warmup_task)
        logger.info("[MAIN] Warmup task added to background tasks")

        # All instances run the file watcher (distributed lock coordinates writes)
        if Config.SYNC_ENABLED:
            try:
                vault_path = Path(Config.OBSIDIAN_VAULT_PATH)
                (
                    _file_watcher_observer,
                    _cleanup_timer_task,
                    _move_processor_task,
                    _heartbeat_task,
                    _deferred_move_task,
                    _blacklist_watch_task,
                ) = start_file_watcher(
                    vault_path,
                    loop,
                    db_manager=tools.db_manager,
                    embedding_generator=tools.embedding_generator,
                    metadata_extractor=tools.metadata_extractor,
                )
                debug_log("[SYNC] File watcher enabled")

                # Add watcher tasks to background tasks for proper shutdown
                background_tasks.append(_move_processor_task)
                background_tasks.append(_cleanup_timer_task)
                background_tasks.append(_heartbeat_task)
                background_tasks.append(_deferred_move_task)

                # Initial sync of existing notes (runs in background)
                if Config.SYNC_INITIAL_SYNC:
                    print(
                        "[SYNC] Initial sync will run in background. Server accepting requests immediately.",
                        file=sys.stderr,
                    )
                    initial_sync_task = loop.create_task(_run_initial_sync())
                    background_tasks.append(initial_sync_task)

                # Initial sync of folders (runs in background, non-blocking)
                print(
                    "[SYNC] Folder sync will run on startup. Server accepting requests immediately.",
                    file=sys.stderr,
                )
                folder_sync_task = loop.create_task(_run_folder_sync_startup())
                background_tasks.append(folder_sync_task)

                # Run orphan cleanup shortly after startup (after initial sync completes)
                print(
                    "[SYNC] Creating orphan cleanup startup task...",
                    file=sys.stderr,
                )
                orphan_startup_task = loop.create_task(
                    _run_orphan_cleanup_startup()
                )
                background_tasks.append(orphan_startup_task)

                # Start periodic orphan cleanup task (every 10 minutes)
                orphan_cleanup_task = loop.create_task(
                    _periodic_orphan_cleanup_loop(600)
                )
                background_tasks.append(orphan_cleanup_task)
            except Exception as e:
                print(f"[WARNING] Failed to start file watcher: {e}", file=sys.stderr)
        else:
            print("[SYNC] File watcher disabled (SYNC_ENABLED=false)", file=sys.stderr)

        # Start MCP server
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream, write_stream, server.create_initialization_options()
            )
    except asyncio.CancelledError:
        print("\nServer shutdown requested", file=sys.stderr)
    except KeyboardInterrupt:
        print("\nServer interrupted by user", file=sys.stderr)
    except Exception as e:
        print(f"Server error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        print("[SERVER] Shutdown sequence starting", file=sys.stderr)

        # Stop file watcher
        if _file_watcher_observer:
            try:
                print("[SYNC] Stopping file watcher...", file=sys.stderr)
                _file_watcher_observer.stop()
                _file_watcher_observer.join()
                print("[SYNC] File watcher stopped", file=sys.stderr)
            except Exception as e:
                print(f"[ERROR] Error stopping file watcher: {e}", file=sys.stderr)

        # Cancel background tasks
        for task in background_tasks:
            if not task.done():
                task.cancel()

        # Supabase lock auto-expires via TTL — no explicit release needed on shutdown

        await shutdown()


async def shutdown():
    """Graceful shutdown"""
    print("Cleaning up resources...", file=sys.stderr)
    await tool_handlers.cleanup()

    # ✅ FIX #2: Cleanup LazyImport references
    from watcher import LazyImport

    LazyImport.cleanup()

    print("Shutdown complete", file=sys.stderr)


if __name__ == "__main__":
    # Entry point - start timing and logging
    entry_start_time = datetime.now()
    print(f"[ENTRY] Server entry point reached at {entry_start_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}", file=sys.stderr)
    logger.info(f"[ENTRY] Server entry point reached at {entry_start_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}")
    
    # Validate configuration before starting
    try:
        print("[ENTRY] Validating configuration...", file=sys.stderr)
        logger.info("[ENTRY] Validating configuration...")
        Config.validate()
        
        print("Starting Second Brain MCP Server...", file=sys.stderr)
        logger.info("[ENTRY] Configuration validated successfully, starting main()...")
        
        # Run the main server
        asyncio.run(main())
        
    except Exception as e:
        elapsed = (datetime.now() - entry_start_time).total_seconds()
        error_msg = f"[ENTRY] Configuration error after {elapsed:.2f}s: {e}"
        print(error_msg, file=sys.stderr)
        logger.error(error_msg)
        sys.exit(1)
