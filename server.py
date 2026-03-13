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
from instance_lock import InstanceLock
import portalocker

# Global file watcher reference
_file_watcher_observer = None
_cleanup_timer_task = None
_move_processor_task = None
_heartbeat_task = None

# Global sync status tracking
_initial_sync_complete = False
_initial_sync_running = False


# Helper function for debug logging
def debug_log(msg: str):
    """Print debug message if DEBUG is enabled"""
    if Config.DEBUG:
        print(msg, file=sys.stderr)


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
    try:
        result = await tool_handlers.handle_tool_call(name, arguments)

        # Run orphan cleanup after each tool call
        if Config.SYNC_ENABLED:
            try:
                from obsidian import ObsidianManager

                obsidian_manager = ObsidianManager(
                    Config.OBSIDIAN_VAULT_PATH, db_manager=tool_handlers.db_manager
                )
                sync_result = obsidian_manager.get_last_sync_result()
                await obsidian_manager.remove_orphaned_supabase_entries(
                    exclude_ids=sync_result.get("ids", []) if sync_result else []
                )
            except Exception as e:
                print(
                    f"[WARNING] Orphan cleanup after tool call failed: {e}",
                    file=sys.stderr,
                )

        return [TextContent(type="text", text=str(result))]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def _heartbeat_loop(lock_manager: InstanceLock, interval: int):
    """Update heartbeat timestamp periodically"""
    while True:
        try:
            await asyncio.sleep(interval)
            lock_manager.update_heartbeat()
        except asyncio.CancelledError:
            break


async def _periodic_orphan_cleanup_loop(interval: int):
    """Periodically clean up orphaned Supabase entries"""
    from obsidian import ObsidianManager
    import tools

    while True:
        try:
            await asyncio.sleep(interval)
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
        # Wait for initial sync to complete (poll every 5 seconds, up to 10 minutes)
        max_wait_seconds = 600
        poll_interval = 5
        elapsed = 0
        while not _initial_sync_complete and elapsed < max_wait_seconds:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        if not _initial_sync_complete:
            print(
                f"[SYNC] Initial sync still running after {max_wait_seconds}s, proceeding with orphan cleanup anyway",
                file=sys.stderr,
            )

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


async def _lock_retry_loop(
    lock_manager: InstanceLock,
    interval: int,
    jitter: int,
    is_primary: dict,
    background_tasks: list,
):
    """Periodically attempt to acquire lock if secondary instance"""
    while True:
        try:
            # Add random jitter to avoid race conditions
            wait_time = interval + random.randint(0, jitter)
            await asyncio.sleep(wait_time)

            # Check if lock is free
            lock_status = lock_manager.is_locked()
            debug_log(f"[LOCK] Retry check: lock_is_held={lock_status}")

            # If lock is held, check if it's stale before attempting takeover
            if lock_status:
                is_stale, last_heartbeat = lock_manager.is_lock_stale()
                debug_log(
                    f"[LOCK] Lock is held, stale={is_stale}, last_heartbeat={last_heartbeat}"
                )

                if not is_stale:
                    # Lock is held by active primary, skip this cycle
                    continue

                # Lock is stale - attempt cleanup and acquisition
                debug_log("[LOCK] Lock is stale, attempting to clean up and acquire...")

                if not lock_manager.cleanup_stale_lock():
                    # Cleanup failed, primary might have recovered
                    debug_log("[LOCK] Stale lock cleanup failed, will retry next cycle")
                    continue
            else:
                debug_log("[LOCK] Lock appears free, attempting to acquire...")

            # Try to acquire lock (either it was free, or we cleaned up stale lock)
            try:
                lock_manager.acquire_lock()
                debug_log("[LOCK] Acquired lock after retry - starting sync takeover")

                # Get the event loop
                loop = asyncio.get_running_loop()

                # Start sync takeover
                try:
                    await _sync_takeover(
                        lock_manager, loop, is_primary, background_tasks
                    )
                    debug_log("[LOCK] Sync takeover completed successfully")
                except Exception as e:
                    print(
                        f"[ERROR] Sync takeover failed: {e}",
                        file=sys.stderr,
                    )
                    # Release lock since takeover failed
                    lock_manager.release_lock()
                    raise

            except portalocker.LockException:
                # Another instance beat us to it
                debug_log("[LOCK] Another instance acquired lock first")
                continue
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(
                f"[ERROR] Lock retry loop error: {e}",
                file=sys.stderr,
            )
            # Continue retrying even on other errors
            await asyncio.sleep(5)
            continue


async def _sync_takeover(
    lock_manager: InstanceLock, event_loop, is_primary: dict, background_tasks: list
):
    """Handle sync takeover when acquiring lock"""
    global _file_watcher_observer
    from obsidian import ObsidianManager
    from watcher import start_file_watcher
    import tools

    try:
        # Start file watcher
        debug_log("[SYNC] Starting file watcher for takeover...")
        vault_path = Path(Config.OBSIDIAN_VAULT_PATH)
        (
            _file_watcher_observer,
            _cleanup_timer_task,
            _move_processor_task,
            _heartbeat_task,
            _deferred_move_task,
        ) = start_file_watcher(
            vault_path,
            event_loop,
            db_manager=tools.db_manager,
            embedding_generator=tools.embedding_generator,
            metadata_extractor=tools.metadata_extractor,
        )
        debug_log("[SYNC] File watcher started successfully")

        # Add watcher tasks to background_tasks for proper shutdown
        background_tasks.append(_move_processor_task)
        background_tasks.append(_cleanup_timer_task)
        background_tasks.append(_heartbeat_task)
        background_tasks.append(_deferred_move_task)

        # Run hash-based sync to catch changes during gap period
        if Config.SYNC_ENABLED:
            try:
                debug_log("[SYNC] Running hash-based sync to catch changes...")
                obsidian_manager = ObsidianManager(
                    Config.OBSIDIAN_VAULT_PATH, db_manager=tools.db_manager
                )
                await obsidian_manager.sync_changed_notes_to_supabase()

                # Clean up orphaned entries after sync
                sync_result = obsidian_manager.get_last_sync_result()
                debug_log("[SYNC] Removing orphaned entries...")
                await obsidian_manager.remove_orphaned_supabase_entries(
                    exclude_ids=sync_result.get("ids", []) if sync_result else []
                )
                debug_log("[SYNC] Orphan cleanup completed")
            except Exception as e:
                print(
                    f"[ERROR] Sync operations failed during takeover: {e}",
                    file=sys.stderr,
                )
                raise

        # Start heartbeat task for new primary
        debug_log("[LOCK] Starting heartbeat for new primary instance...")
        takeover_heartbeat = event_loop.create_task(
            _heartbeat_loop(lock_manager, Config.LOCK_HEARTBEAT_INTERVAL_SECONDS)
        )
        background_tasks.append(takeover_heartbeat)

        # Mark as primary
        is_primary["value"] = True
        debug_log("[LOCK] Takeover completed - this instance is now primary")

    except Exception as e:
        print(
            f"[ERROR] Sync takeover failed: {e}",
            file=sys.stderr,
        )
        # Stop watcher if it was started
        if _file_watcher_observer:
            try:
                _file_watcher_observer.stop()
                _cleanup_timer_task.cancel()
                if _move_processor_task:
                    _move_processor_task.cancel()
                if _heartbeat_task:
                    _heartbeat_task.cancel()
                if _deferred_move_task:
                    _deferred_move_task.cancel()
                _file_watcher_observer.join()
                _file_watcher_observer = None
                _cleanup_timer_task = None
                _move_processor_task = None
                _heartbeat_task = None
                _deferred_move_task = None
            except Exception as cleanup_error:
                print(
                    f"[ERROR] Failed to cleanup file watcher: {cleanup_error}",
                    file=sys.stderr,
                )
        raise

        # Start heartbeat task
        debug_log("[LOCK] Starting heartbeat for new primary instance...")
        heartbeat_task = event_loop.create_task(
            _heartbeat_loop(lock_manager, Config.LOCK_HEARTBEAT_INTERVAL_SECONDS)
        )

        # Store heartbeat task for cleanup
        if not hasattr(_sync_takeover, "heartbeat_task"):
            _sync_takeover.heartbeat_task = []
        _sync_takeover.heartbeat_task.append(heartbeat_task)

        debug_log("[LOCK] Takeover completed - this instance is now primary")

    except Exception as e:
        print(
            f"[ERROR] Sync takeover failed: {e}",
            file=sys.stderr,
        )
        # Stop watcher if it was started
        if _file_watcher_observer:
            try:
                _file_watcher_observer.stop()
                _cleanup_timer_task.cancel()
                if _move_processor_task:
                    _move_processor_task.cancel()
                if _heartbeat_task:
                    _heartbeat_task.cancel()
                if _deferred_move_task:
                    _deferred_move_task.cancel()
                _file_watcher_observer.join()
                _file_watcher_observer = None
                _cleanup_timer_task = None
                _move_processor_task = None
                _heartbeat_task = None
                _deferred_move_task = None
            except Exception as cleanup_error:
                print(
                    f"[ERROR] Failed to cleanup file watcher: {cleanup_error}",
                    file=sys.stderr,
                )
        raise


async def _run_initial_sync():
    """Run initial sync as a background task"""
    global _initial_sync_running, _initial_sync_complete

    try:
        _initial_sync_running = True
        debug_log("[SYNC] Starting initial sync in background...")

        from obsidian import ObsidianManager
        import tools

        obsidian_manager = ObsidianManager(
            Config.OBSIDIAN_VAULT_PATH, db_manager=tools.db_manager
        )
        await obsidian_manager.sync_existing_notes_to_supabase()

        # CRITICAL FIX: Clean up orphaned Supabase entries after initial sync
        # This ensures the database is consistent (no entries without matching notes)
        sync_result = obsidian_manager.get_last_sync_result()
        debug_log("[SYNC] Cleaning up orphaned Supabase entries...")
        await obsidian_manager.remove_orphaned_supabase_entries(
            exclude_ids=sync_result.get("ids", []) if sync_result else []
        )

        _initial_sync_complete = True
        debug_log("[SYNC] Initial sync complete. Server is fully operational.")
    except Exception as e:
        print(f"[ERROR] Initial sync failed: {e}", file=sys.stderr)
    finally:
        _initial_sync_running = False


async def main():
    """Main MCP server entry point with file watcher"""
    from watcher import start_file_watcher
    import tools

    # Flag to track shutdown request
    shutdown_requested = False

    # Initialize lock manager and status variables
    lock_manager = None
    is_primary = {"value": False}  # Mutable dict so takeover can update it
    background_tasks = []

    # Set up signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        nonlocal shutdown_requested, background_tasks
        global _file_watcher_observer
        if not shutdown_requested:
            shutdown_requested = True
            print(
                f"\nReceived signal {signum}, shutting down gracefully...",
                file=sys.stderr,
            )
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
        loop = asyncio.get_running_loop()
        if loop is None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        # Warm up connections before accepting requests
        print("[INIT] Warming up connections...", file=sys.stderr)
        try:
            # Warm up embedding generator
            await tools.embedding_generator.warmup()
        except Exception as e:
            print(
                f"[WARNING] Failed to warmup embedding generator: {e}", file=sys.stderr
            )
        # COMMENTED OUT: Database warmup may be redundant with connection pooling
        # The Supabase client manages connection pooling automatically,
        # and the first real query will establish a connection just as quickly.
        # This also saves a database query on every server startup.
        # try:
        #     # Warm up database connection
        #     await tools.db_manager.list_recent(days=365)
        #     print("[INIT] Database connection warmup complete", file=sys.stderr)
        # except Exception as e:
        #     print(
        #         f"[WARNING] Failed to warmup database connection: {e}", file=sys.stderr
        #     )
        print(
            "[INIT] Connection warmup complete, server ready to accept requests",
            file=sys.stderr,
        )

        # Initialize lock manager and try to acquire lock
        global _file_watcher_observer
        lock_manager = InstanceLock(Config)
        is_primary["value"] = False
        background_tasks = []

        print(
            f"[LOCK] Lock file location: {lock_manager.lock_file_path}",
            file=sys.stderr,
        )
        print(f"[LOCK] Instance ID: {lock_manager.instance_id}", file=sys.stderr)

        try:
            lock_manager.acquire_lock()
            is_primary["value"] = True
            lock_info = lock_manager.get_lock_info()
            debug_log(f"[LOCK] Acquired primary lock (PID: {os.getpid()})")
            debug_log("[LOCK] Starting file watcher for sync")
        except portalocker.LockException:
            is_primary["value"] = False
            lock_info = lock_manager.get_lock_info()
            debug_log("[LOCK] Another instance running - file watcher disabled")
            if lock_info:
                debug_log(
                    f"[LOCK] Primary lock held by PID: {lock_info.get('pid')} (Instance: {lock_info.get('instance_id')})"
                )
            debug_log("[LOCK] Secondary instance operating in read-only mode")

        # Start file watcher if primary and enabled
        if is_primary["value"] and Config.SYNC_ENABLED:
            try:
                vault_path = Path(Config.OBSIDIAN_VAULT_PATH)
                # ✅ FIX #1: Handle new return value (5 values: observer, cleanup_task, move_processor_task, heartbeat_task, deferred_move_task)
                (
                    _file_watcher_observer,
                    _cleanup_timer_task,
                    _move_processor_task,
                    _heartbeat_task,
                    _deferred_move_task,
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
                if Config.SYNC_ENABLED:
                    print(
                        "[SYNC] Folder sync will run on startup. Server accepting requests immediately.",
                        file=sys.stderr,
                    )
                    folder_sync_task = loop.create_task(_run_folder_sync_startup())
                    background_tasks.append(folder_sync_task)

                # Run orphan cleanup shortly after startup (after initial sync completes)
                if Config.SYNC_ENABLED:
                    print(
                        "[SYNC] Creating orphan cleanup startup task...",
                        file=sys.stderr,
                    )
                    orphan_startup_task = loop.create_task(
                        _run_orphan_cleanup_startup()
                    )
                    background_tasks.append(orphan_startup_task)

                # Start heartbeat task for primary instance
                heartbeat_task = loop.create_task(
                    _heartbeat_loop(
                        lock_manager, Config.LOCK_HEARTBEAT_INTERVAL_SECONDS
                    )
                )
                background_tasks.append(heartbeat_task)

                # Start periodic orphan cleanup task (every 10 minutes)
                orphan_cleanup_task = loop.create_task(
                    _periodic_orphan_cleanup_loop(600)  # 600 seconds = 10 minutes
                )
                background_tasks.append(orphan_cleanup_task)
            except Exception as e:
                print(f"[WARNING] Failed to start file watcher: {e}", file=sys.stderr)
        elif not is_primary["value"] and Config.LOCK_RETRY_ENABLED:
            # Start lock retry task for secondary instance
            retry_task = loop.create_task(
                _lock_retry_loop(
                    lock_manager,
                    Config.LOCK_RETRY_INTERVAL_SECONDS,
                    Config.LOCK_RETRY_JITTER_SECONDS,
                    is_primary,
                    background_tasks,
                )
            )
            background_tasks.append(retry_task)
        else:
            print("[SYNC] File watcher disabled", file=sys.stderr)

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

        # Release lock if we have it
        # A secondary instance becomes primary only if it acquires the lock via takeover
        # In that case, is_primary["value"] will have been updated to True
        lock_held = lock_manager and lock_manager.lock_file is not None
        print(
            f"[LOCK] Checking lock cleanup: is_primary={is_primary['value']}, lock_held={lock_held}",
            file=sys.stderr,
        )

        if is_primary["value"] or lock_held:
            if lock_manager:
                try:
                    print("[LOCK] Releasing lock on shutdown", file=sys.stderr)
                    lock_manager.release_lock()
                    print("[LOCK] Lock released successfully", file=sys.stderr)
                except Exception as e:
                    print(f"[ERROR] Error releasing lock: {e}", file=sys.stderr)

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
    # Validate configuration before starting
    try:
        Config.validate()
        print("Starting Second Brain MCP Server...", file=sys.stderr)
        asyncio.run(main())
    except Exception as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)
