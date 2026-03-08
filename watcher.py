"""
File watcher for monitoring Obsidian vault changes.
Hybrid approach: watchdog (real-time) + periodic polling (reliability)
"""

import asyncio
import hashlib
import sys
import time
import weakref
from pathlib import Path
from typing import Dict, Set, Optional, Tuple
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from config import Config


# Import managers to avoid circular dependency
class LazyImport:
    """Lazy import for managers to avoid circular dependency"""

    _db_manager = None
    _obsidian_manager = None
    _embedding_generator = None
    _metadata_extractor = None
    _event_loop_ref: Optional[weakref.ref] = None

    @classmethod
    def set_event_loop(cls, loop):
        """Set event loop with weak reference for auto-cleanup"""
        cls._event_loop_ref = weakref.ref(loop)
        if Config.DEBUG:
            print(f"[LAZY] Event loop set (ref: {cls._event_loop_ref})", file=sys.stderr)

    @classmethod
    def get_event_loop(cls) -> asyncio.AbstractEventLoop:
        """Get event loop, with cleanup of dead references"""
        loop_ref = cls._event_loop_ref

        if loop_ref is None:
            # No loop set yet
            loop = asyncio.get_event_loop()
            cls._event_loop_ref = weakref.ref(loop)
            if Config.DEBUG:
                print(f"[LAZY] Created new event loop", file=sys.stderr)
            return loop

        loop = loop_ref()
        if loop is None:
            # Loop was garbage collected, get new one
            loop = asyncio.get_event_loop()
            cls._event_loop_ref = weakref.ref(loop)
            if Config.DEBUG:
                print(f"[LAZY] Event loop was GC'd, created new one", file=sys.stderr)

        return loop

    @classmethod
    def cleanup(cls):
        """Explicitly release event loop and manager references"""
        if Config.DEBUG:
            print("[LAZY] Cleanup: Releasing references", file=sys.stderr)

        # Clear event loop reference
        cls._event_loop_ref = None

        # Clear manager references
        cls._db_manager = None
        cls._obsidian_manager = None
        cls._embedding_generator = None
        cls._metadata_extractor = None

        if Config.DEBUG:
            print("[LAZY] Cleanup complete", file=sys.stderr)

    @classmethod
    def get_db_manager(cls):
        if cls._db_manager is None:
            from database import DatabaseManager

            cls._db_manager = DatabaseManager()
        return cls._db_manager

    @classmethod
    def get_obsidian_manager(cls):
        if cls._obsidian_manager is None:
            from obsidian import ObsidianManager

            cls._obsidian_manager = ObsidianManager(
                Config.OBSIDIAN_VAULT_PATH, cls.get_db_manager()
            )
        return cls._obsidian_manager

    @classmethod
    def get_embedding_generator(cls):
        if cls._embedding_generator is None:
            from embeddings import EmbeddingGenerator

            cls._embedding_generator = EmbeddingGenerator()
        return cls._embedding_generator

    @classmethod
    def get_metadata_extractor(cls):
        if cls._metadata_extractor is None:
            from metadata import MetadataExtractor

            cls._metadata_extractor = MetadataExtractor()
        return cls._metadata_extractor


DEBUG = False  # DEPRECATED - use Config.DEBUG instead (kept for backward compatibility)

# Helper function for debug logging
def debug_log(msg: str):
    """Print debug message if DEBUG is enabled"""
    if Config.DEBUG:
        print(msg, file=sys.stderr)

# Event sequence counter for tracing
_EVENT_COUNTER = 0

# Log file for debugging
_LOG_FILE = Path(__file__).parent / "watcher_debug.log"

def _log(msg: str, level: str = "INFO"):
    """Log to both file and stderr with timestamp (file only if DEBUG enabled)"""
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    log_msg = f"[{ts}] [{level}] {msg}"
    
    # Write to file only if DEBUG is enabled
    if Config.DEBUG:
        try:
            with open(_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(log_msg + "\n")
                f.flush()
        except Exception as e:
            print(f"[LOG ERROR] Failed to write to log file: {e}", file=sys.stderr)
    
    # Always print to stderr
    print(log_msg, file=sys.stderr)


class ObsidianEventHandler(FileSystemEventHandler):
    """Handle file system events in Obsidian vault"""

    _running = True  # Flag to control event processor
    
    # Track files being processed to prevent duplicate handling
    _processing_files = set()
    _processing_lock = None  # Will be initialized in __init__

    def __init__(self, vault_path: Path):
        self.vault_path = vault_path

        # Debounce tracking with asyncio queue
        self._debounce_queue: Dict[str, Dict] = {}
        self._debounce_delay = Config.SYNC_DEBOUNCE_SECONDS

        # Exclusion patterns
        self._exclude_patterns = Config.SYNC_EXCLUDE_PATTERNS

        # Polling state
        self._last_full_sync_time = time.time()
        self._known_files: Set[str] = set()

        # Task queue for processing
        self._task_queue = asyncio.Queue()

        # Track files where we shouldn't process the next modify event
        # (because we're writing frontmatter ourselves)
        self._skip_next_modify: Set[str] = set()

        # Track files currently being moved to suppress delete/create events
        # Maps src_path -> (dest_path, timestamp) for files in transit
        self._files_being_moved: Dict[str, Tuple[str, float]] = {}

        # Track recently deleted files to correlate with creates (since on_moved doesn't fire on Windows)
        # Maps deleted_path -> (filename, rel_path, timestamp) for detection of move events
        self._recent_deletes: Dict[str, Tuple[str, str, float]] = {}

        # ✅ NEW: Move event queue for async-safe coordination
        self._move_event_queue: asyncio.Queue = asyncio.Queue()
        self._active_moves: Set[str] = set()
        self._move_event_lock: asyncio.Lock = asyncio.Lock()

        # Initialize processing lock
        if ObsidianEventHandler._processing_lock is None:
            try:
                ObsidianEventHandler._processing_lock = asyncio.Lock()
            except RuntimeError:
                # No event loop yet, will create lock in async context
                ObsidianEventHandler._processing_lock = None

        print(
            f"[WATCHER] Initialized with {self._debounce_delay}s debounce",
            file=sys.stderr,
        )

    def stop(self):
        """Stop the event processor"""
        self._running = False

    def _decode_path(self, path) -> str:
        """Decode path if bytes (Windows)"""
        if isinstance(path, bytes):
            return path.decode("utf-8")
        return path
    
    async def _is_processing(self, obsidian_path: str) -> bool:
        """Check if file is currently being processed"""
        # Initialize lock if not already done
        if ObsidianEventHandler._processing_lock is None:
            try:
                ObsidianEventHandler._processing_lock = asyncio.Lock()
            except RuntimeError:
                return False  # Can't check without lock
        
        async with ObsidianEventHandler._processing_lock:
            return obsidian_path in ObsidianEventHandler._processing_files
    
    async def _mark_processing(self, obsidian_path: str, processing: bool):
        """Mark file as currently being processed"""
        # Initialize lock if not already done
        if ObsidianEventHandler._processing_lock is None:
            try:
                ObsidianEventHandler._processing_lock = asyncio.Lock()
            except RuntimeError:
                return  # Can't mark without lock
        
        async with ObsidianEventHandler._processing_lock:
            if processing:
                ObsidianEventHandler._processing_files.add(obsidian_path)
            else:
                ObsidianEventHandler._processing_files.discard(obsidian_path)

    def on_created(self, event: FileSystemEvent):
        """Handle file creation events"""
        if not self._should_process(event):
            return

        src_path = self._decode_path(event.src_path)

        # Clean up any stale move tracking entries
        self._cleanup_stale_moves()
        self._cleanup_stale_deletes()

        # ✅ Check if destination is part of an active move
        try:
            loop = LazyImport.get_event_loop()
            is_active = asyncio.run_coroutine_threadsafe(
                self._is_in_active_moves(src_path),
                loop
            ).result(timeout=0.1)

            if is_active:
                if Config.DEBUG:
                    print(f"[CREATE] Skipping create for active move: {src_path}", file=sys.stderr)
                return
        except (RuntimeError, asyncio.TimeoutError):
            pass

        rel_path = self._get_relative_path(src_path)
        filename = Path(src_path).name  # Just the filename (e.g., "My Note.md")
        _log(f"[CREATE] File created: {rel_path} (filename={filename})", "CREATE")

        # CRITICAL FIX: Detect moves by correlating with recent deletes
        # On Windows, watchdog fires delete + create for moves, not on_moved()
        # Check if this create has matching filename with recent delete -> it's a move!

        _log(f"[CREATE] Checking {len(self._recent_deletes)} recent deletes for move detection", "CREATE")

        matching_delete = None
        current_time = time.time()

        for deleted_path, (deleted_filename, deleted_rel_path, delete_time) in list(self._recent_deletes.items()):
            time_diff = current_time - delete_time
            is_filename_match = deleted_filename == filename  # Same filename = likely a move
            is_time_match = time_diff < 2.0  # Create must happen within 2 seconds of delete

            _log(f"[CREATE] Comparing: deleted_file={deleted_filename}, created_file={filename}, filename_match={is_filename_match}, time_diff={time_diff:.2f}s", "CREATE")

            if is_filename_match and is_time_match:
                matching_delete = (deleted_path, deleted_filename, deleted_rel_path, delete_time)
                _log(f"[CREATE] ✓ MOVE DETECTED: {deleted_rel_path} → {rel_path}", "CREATE")
                break

        if matching_delete:
            # This is a move! Handle it as a path update instead of a new entry
            deleted_path, deleted_filename, deleted_rel_path, delete_time = matching_delete

            # Remove from recent_deletes tracking
            del self._recent_deletes[deleted_path]

            if Config.DEBUG:
                print(f"[WATCHER] MOVE detected: {deleted_rel_path} → {rel_path}", file=sys.stderr)

            # Queue move event for processing
            asyncio.run_coroutine_threadsafe(
                self._debounce_move_event(deleted_path, src_path), LazyImport.get_event_loop()
            )
        else:
            # This is a genuine new file creation
            _log(f"[CREATE] No matching delete found - treating as new file creation", "CREATE")

            if Config.DEBUG:
                print(f"[WATCHER] File created (new): {src_path}", file=sys.stderr)

            # FIX #1: Use debouncing instead of directly queuing
            # This prevents multiple create events for the same file
            asyncio.run_coroutine_threadsafe(
                self._debounce_event(src_path, "create"), LazyImport.get_event_loop()
            )

    async def _process_event(self, event):
        """Process event from queue (handles both 2-tuple and 3-tuple for moves)"""
        if len(event) == 3:
            # Move event: (src_path, dest_path, "move")
            src_path, dest_path, event_type = event
            if event_type == "move":
                await self._handle_move(src_path, dest_path)
            else:
                await self._process_event_after_delay(dest_path, event_type)
        else:
            # Regular event: (file_path, event_type)
            file_path, event_type = event
            await self._process_event_after_delay(file_path, event_type)

    async def _handle_move(self, src_path: str, dest_path: str):
        """Handle file move/rename events"""
        try:
            src_obsidian_path = self._get_relative_path(src_path)
            dest_obsidian_path = self._get_relative_path(dest_path)
            _log(f"[MOVE] Starting _handle_move: {src_obsidian_path} → {dest_obsidian_path}", "MOVE")

            # Try to read frontmatter from destination to get supabase_id
            _log(f"[MOVE] Checking if dest file exists and has supabase_id in frontmatter", "MOVE")
            if Path(dest_path).exists():
                content = Path(dest_path).read_text(encoding="utf-8")
                metadata = self._extract_frontmatter(content, dest_obsidian_path)

                if metadata and metadata.get("supabase_id"):
                    # FIX #3: Successfully found supabase_id - update existing entry's path
                    _log(f"[MOVE] Found supabase_id in dest frontmatter: {metadata.get('supabase_id')}", "MOVE")
                    db_manager = LazyImport.get_db_manager()
                    await db_manager.update_obsidian_path(
                        metadata["supabase_id"], dest_obsidian_path
                    )
                    _log(f"[MOVE] Updated obsidian_path for entry {metadata.get('supabase_id')}", "MOVE")
                    print(
                        f"[SYNC] Moved: {src_obsidian_path} → {dest_obsidian_path} (updated path)",
                        file=sys.stderr,
                    )
                    return
                else:
                    _log(f"[MOVE] No supabase_id found in dest frontmatter", "MOVE")
            else:
                _log(f"[MOVE] Dest file doesn't exist anymore", "MOVE")

            # If no supabase_id found, check if there's an existing entry by old path
            # FIX #3: Instead of delete + recursive _handle_create, just update the path if it exists
            _log(f"[MOVE] Looking for entry with old path: {src_obsidian_path}", "MOVE")
            db_manager = LazyImport.get_db_manager()
            existing = await db_manager.get_thought_by_obsidian_path(src_obsidian_path)
            
            if existing:
                # Entry exists with old path - just update the path
                supabase_id = existing["id"]
                _log(f"[MOVE] Found entry with old path (ID: {supabase_id}), updating path", "MOVE")
                print(
                    f"[SYNC] Moved: {src_obsidian_path} → {dest_obsidian_path} (updated path from old entry)",
                    file=sys.stderr,
                )
                await db_manager.update_obsidian_path(supabase_id, dest_obsidian_path)
                _log(f"[MOVE] Path updated for entry {supabase_id}", "MOVE")
                
                # CRITICAL FIX: Update the moved file's frontmatter with supabase_id
                # This ensures the note and Supabase entry remain linked
                _log(f"[MOVE] Updating frontmatter with supabase_id={supabase_id}", "MOVE")
                try:
                    self._skip_next_modify.add(dest_path)
                    self._update_frontmatter(dest_path, supabase_id)
                    print(f"[WATCHER] Updated moved note's frontmatter with supabase_id: {supabase_id}", file=sys.stderr)
                    _log(f"[MOVE] Frontmatter updated successfully", "MOVE")
                except Exception as fm_err:
                    _log(f"[MOVE] Failed to update frontmatter: {str(fm_err)}", "MOVE")
                    print(f"[WARNING] Failed to update frontmatter for moved note: {fm_err}", file=sys.stderr)
                
                return
            
            # No entry found at all - this shouldn't happen during a move operation
            # but if it does, we should not create a new entry via recursion
            _log(f"[MOVE] WARNING: No entry found for move operation, doing nothing", "MOVE")
            print(
                f"[SYNC] Moved: {src_obsidian_path} → {dest_obsidian_path} (no entry found to update)",
                file=sys.stderr,
            )
            
        except FileNotFoundError:
            _log(f"[MOVE] File move target no longer exists: {dest_obsidian_path}", "MOVE")
            print(
                f"[WATCHER] File move target no longer exists: {dest_path}",
                file=sys.stderr,
            )
        except Exception as e:
            print(f"[ERROR] Failed to handle move: {e}", file=sys.stderr)
            import traceback

            traceback.print_exc()

    def _cleanup_stale_moves(self):
        """Remove stale entries from _files_being_moved (older than 30 seconds)"""
        current_time = time.time()
        stale_threshold = 30  # seconds
        
        stale_paths = []
        for src_path, (dest_path, timestamp) in self._files_being_moved.items():
            if current_time - timestamp > stale_threshold:
                stale_paths.append(src_path)
        
        for src_path in stale_paths:
            del self._files_being_moved[src_path]
            if self._files_being_moved:  # Only log if there were stale entries
                if Config.DEBUG:
                    print(f"[WATCHER] Cleaned up stale move entry: {src_path}", file=sys.stderr)
    
    def on_modified(self, event: FileSystemEvent):
        """Handle file modification events"""
        if not self._should_process(event):
            return

        src_path = self._decode_path(event.src_path)
        
        # Check if we should skip this modify event (because we just wrote it ourselves)
        if src_path in self._skip_next_modify:
            self._skip_next_modify.discard(src_path)
            if Config.DEBUG:
                print(f"[WATCHER] Skipping modify event (self-inflicted): {src_path}", file=sys.stderr)
            return
        
        if Config.DEBUG:
            print(f"[WATCHER] File modified: {src_path}", file=sys.stderr)

        # FIX #1: Use debouncing instead of directly queuing
        # This prevents multiple modify events from queuing during rapid changes
        asyncio.run_coroutine_threadsafe(
            self._debounce_event(src_path, "modify"), LazyImport.get_event_loop()
        )

    def on_deleted(self, event: FileSystemEvent):
        """Handle file/directory deletion events"""
        if not self._should_process(event):
            return

        src_path = self._decode_path(event.src_path)

        # Clean up any stale move tracking entries
        self._cleanup_stale_moves()
        self._cleanup_stale_deletes()

        # ✅ Check if file is part of an active move
        # Use synchronous check here since we're in watchdog thread
        # Get event loop and run coroutine synchronously for checking
        try:
            loop = LazyImport.get_event_loop()
            is_active = asyncio.run_coroutine_threadsafe(
                self._is_in_active_moves(src_path),
                loop
            ).result(timeout=0.1)  # 100ms timeout

            if is_active:
                if Config.DEBUG:
                    print(f"[DELETE] Skipping delete for active move: {src_path}", file=sys.stderr)
                return
        except (RuntimeError, asyncio.TimeoutError):
            # Event loop not ready or check timed out, proceed with delete
            pass

        # Handle directory deletions separately (for folders table cleanup)
        if event.is_directory:
            self._handle_directory_deleted(src_path)
            return

        # CRITICAL FIX: Track recent deletes to correlate with creates
        # On Windows, watchdog fires delete + create for moves, not on_moved()
        # We use filename matching: if filename is same, it's likely a move (folder change)

        rel_path = self._get_relative_path(src_path) if Path(src_path).exists() else src_path
        filename = Path(src_path).name  # Just filename (e.g., "My Note.md")

        # Store in recent_deletes for potential move correlation
        # We'll do DB lookup later when we detect move
        self._recent_deletes[src_path] = (filename, rel_path, time.time())
        _log(f"[DELETE] Tracking recent delete: {rel_path} (filename={filename})", "DELETE")

        if Config.DEBUG:
            print(f"[WATCHER] File marked as recently deleted (waiting for create to detect move): {src_path}", file=sys.stderr)
    
    async def _handle_directory_deleted(self, dir_path: str):
        """Handle folder deletion (for folders table cleanup)"""
        try:
            rel_path = self._get_relative_path(dir_path)
            _log(f"[DELETE] Directory deleted: {rel_path}", "DELETE")
            
            # Delete folder entry from database
            db_manager = LazyImport.get_db_manager()
            await db_manager.delete_folder_by_path(rel_path)
            
            print(f"[SYNC] Deleted folder: {rel_path}", file=sys.stderr)
        except ValueError:
            # Path not in vault
            pass
        except Exception as e:
            print(f"[ERROR] Failed to handle directory deletion: {e}", file=sys.stderr)

    def _cleanup_stale_deletes(self):
        """Remove stale entries from _recent_deletes (older than 5 seconds)"""
        current_time = time.time()
        stale_threshold = 5  # seconds - wait this long to see if a create follows
        
        stale_paths = []
        for src_path, (filename, rel_path, timestamp) in self._recent_deletes.items():
            if current_time - timestamp > stale_threshold:
                stale_paths.append(src_path)
        
        for src_path in stale_paths:
            filename, rel_path, timestamp = self._recent_deletes[src_path]
            # Actually delete the entry from DB since no move follow-up detected
            _log(f"[DELETE] Stale delete timeout - deleting entry for {rel_path}", "DELETE")
            try:
                db_manager = LazyImport.get_db_manager()
                asyncio.run_coroutine_threadsafe(
                    db_manager.delete_thought_by_obsidian_path(rel_path),
                    LazyImport.get_event_loop()
                )
            except Exception as e:
                _log(f"[DELETE] Error deleting stale entry: {e}", "DELETE")
            del self._recent_deletes[src_path]
            if Config.DEBUG:
                print(f"[WATCHER] Cleaned up stale delete entry: {rel_path}", file=sys.stderr)

    def on_moved(self, event: FileSystemEvent):
        """Handle file move/rename events"""
        if not self._should_process(event):
            return

        src_path = self._decode_path(event.src_path)
        dest_path = self._decode_path(event.dest_path) if event.dest_path else ""

        # ✅ FIX #1: Push move notification to async queue (thread-safe)
        # This prevents race conditions with on_deleted/on_created
        try:
            loop = LazyImport.get_event_loop()
            asyncio.run_coroutine_threadsafe(
                self._move_event_queue.put({
                    'type': 'move',
                    'src_path': src_path,
                    'dest_path': dest_path,
                    'timestamp': time.time()
                }),
                loop
            )
        except RuntimeError:
            # Event loop not running yet
            print(f"[WATCHER] Event loop not running, queuing move: {src_path}", file=sys.stderr)
        except Exception as e:
            print(f"[ERROR] Failed to queue move event: {e}", file=sys.stderr)

        if Config.DEBUG:
            print(f"[WATCHER] File moved: {src_path} → {dest_path}", file=sys.stderr)

    def _should_process(self, event: FileSystemEvent) -> bool:
        """Check if event should be processed"""
        # Decode path if bytes (Windows)
        src_path = self._decode_path(event.src_path)

        # Only process markdown files
        if not src_path.endswith(".md"):
            return False

        # Skip directories
        if event.is_directory:
            # Only process directory DELETE events, not CREATE or MODIFY
            return event.event_type == EVENT_TYPE_DELETED
        
        # Skip excluded paths and files

        # Skip excluded paths and files
        rel_path = str(Path(src_path).relative_to(self.vault_path))
        for blacklisted_item in Config.IGNORED_PATHS:
            if self._is_path_blacklisted(rel_path, src_path, blacklisted_item):
                if Config.DEBUG:
                    print(f"[SKIP] Ignoring path in ignore list: {rel_path}", file=sys.stderr)
                return False
        for blacklisted_file in Config.IGNORED_FILES:
            filename = Path(src_path).name
            if filename == blacklisted_file or filename.startswith(blacklisted_file):
                if Config.DEBUG:
                    print(f"[SKIP] Ignoring file in ignore list: {filename}", file=sys.stderr)
                return False

                return True
    
    def _is_path_blacklisted(self, rel_path: str, abs_path: str, pattern: str) -> bool:
        """Check if path matches a blacklist pattern
        
        Supports:
        - Relative paths: copilot, Resources/Temp
        - Absolute paths: C:\\Users\\...\\Archive
        - Nested folders: -To-Do-\\secrets
        - Filenames: Untitled.md
        
        Returns: True if blacklisted
        """
        # Convert to consistent path format (forward slashes for matching)
        rel_normalized = rel_path.replace("\\", "/")
        abs_normalized = abs_path.replace("\\", "/")
        pattern_normalized = pattern.replace("\\", "/")
        
        # Exact filename match (for files like Untitled.md)
        filename = Path(abs_path).name
        if filename == pattern or filename == Path(pattern).name:
            return True
        
        # Relative path prefix match (e.g., copilot matches copilot/custom-prompts/file.md)
        if rel_normalized.startswith(pattern_normalized + "/"):
            return True
        
        # Absolute path match
        if abs_normalized.startswith(pattern_normalized + "/"):
            return True
        
        # Nested folder match (pattern: -To-Do-\\secrets matches -To-Do-\\secrets/sub)
        if pattern_normalized in rel_normalized:
            return True
        
        return False
    
    async def _debounce_event(self, file_path: str, event_type: str):
        """Debounce rapid successive events for same file"""
        rel_path = self._get_relative_path(file_path)
        _log(f"[DEBOUNCE] _debounce_event called: {rel_path} type={event_type}", "DEBOUNCE")
        
        current_time = time.time()

        # Check if we have a pending task for this file
        if file_path in self._debounce_queue:
            existing = self._debounce_queue[file_path]
            old_event_type = existing.get("event_type")
            _log(f"[DEBOUNCE] Existing pending event found for {rel_path}: old_type={old_event_type}, new_type={event_type}", "DEBOUNCE")
            # Cancel existing task if still pending
            task = existing.get("task")
            if task and not task.done():
                task.cancel()
                _log(f"[DEBOUNCE] Cancelled previous {old_event_type} task for: {rel_path}", "DEBOUNCE")
                if Config.DEBUG:
                    print(
                        f"[WATCHER] Cancelled previous task for: {file_path}",
                        file=sys.stderr,
                    )
        else:
            _log(f"[DEBOUNCE] No existing event for {rel_path}, creating new debounce entry", "DEBOUNCE")

        # Create new task with delay
        task = asyncio.create_task(
            self._process_event_after_delay(file_path, event_type)
        )
        self._debounce_queue[file_path] = {
            "timestamp": current_time,
            "event_type": event_type,
            "task": task,
        }
        _log(f"[DEBOUNCE] Scheduled {event_type} for {rel_path} in {self._debounce_delay}s", "DEBOUNCE")

    async def _debounce_move_event(self, src_path: str, dest_path: str):
        """FIX #1: Debounce move events using destination path as key"""
        current_time = time.time()
        
        # Note: _files_being_moved[src_path] was already set synchronously in on_moved()
        # to ensure it's present before on_deleted/on_created fire
        
        # Use destination path as the debounce key since that is the final state
        debounce_key = f"move:{dest_path}"

        # Check if we have a pending task for this move
        if debounce_key in self._debounce_queue:
            existing = self._debounce_queue[debounce_key]
            # Cancel existing task if still pending
            task = existing.get("task")
            if task and not task.done():
                task.cancel()
                if Config.DEBUG:
                    print(
                        f"[WATCHER] Cancelled previous move task for: {dest_path}",
                        file=sys.stderr,
                    )

        # Create new task with delay
        task = asyncio.create_task(
            self._process_move_after_delay(src_path, dest_path)
        )
        self._debounce_queue[debounce_key] = {
            "timestamp": current_time,
            "src_path": src_path,
            "dest_path": dest_path,
            "event_type": "move",
            "task": task,
        }

    async def _process_move_after_delay(self, src_path: str, dest_path: str):
        """FIX #1: Process move event after debounce delay"""
        await asyncio.sleep(self._debounce_delay)
        
        # Convert both paths to obsidian paths
        src_obsidian_path = self._get_relative_path(src_path)
        dest_obsidian_path = self._get_relative_path(dest_path)
        
        # Check if destination file is already being processed by another event
        if await self._is_processing(dest_obsidian_path):
            if Config.DEBUG:
                print(f"[WATCHER] File already processing, skipping move: {dest_obsidian_path}", file=sys.stderr)
            return
        
        # CRITICAL FIX: Mark BOTH source and destination paths as processing
        # This prevents the delete handler from running concurrently
        # (delete would mark src as processing, move marks dest as processing - we need to lock both)
        await self._mark_processing(src_obsidian_path, True)
        await self._mark_processing(dest_obsidian_path, True)
        
        try:
            await self._handle_move(src_path, dest_path)
        finally:
            # Always clean up both processing flags
            await self._mark_processing(src_obsidian_path, False)
            await self._mark_processing(dest_obsidian_path, False)
            
            # CRITICAL FIX: Remove from files being moved to allow delete/create events
            # (they were suppressed while the move was in flight)
            if src_path in self._files_being_moved:
                del self._files_being_moved[src_path]

    async def _process_event_after_delay(self, file_path: str, event_type: str):
        """Process event after debounce delay"""
        rel_path = self._get_relative_path(file_path) if Path(file_path).exists() else file_path
        _log(f"[PROCESS] Starting debounce delay ({self._debounce_delay}s) for {rel_path} type={event_type}", "PROCESS")
        
        await asyncio.sleep(self._debounce_delay)
        
        _log(f"[PROCESS] Debounce delay complete, processing {event_type} for {rel_path}", "PROCESS")

        # Convert to obsidian path for processing lock
        try:
            obsidian_path = self._get_relative_path(file_path)
        except ValueError:
            # File path is not relative to vault (probably deleted file)
            obsidian_path = file_path

        # FIX #2: Use file-level locking to prevent concurrent processing
        is_processing = await self._is_processing(obsidian_path)
        if is_processing:
            _log(f"[PROCESS] SKIP: File already being processed: {obsidian_path} type={event_type}", "PROCESS")
            if Config.DEBUG:
                print(f"[WATCHER] File already being processed, skipping: {obsidian_path}", file=sys.stderr)
            return

        # Mark as processing
        _log(f"[PROCESS] Marking as processing: {obsidian_path} type={event_type}", "PROCESS")
        await self._mark_processing(obsidian_path, True)

        try:
            # Verify this is still the latest event for this file
            if file_path in self._debounce_queue:
                queue_entry = self._debounce_queue[file_path]
                queued_event_type = queue_entry.get("event_type")
                _log(f"[PROCESS] Checking if still latest event: queued={queued_event_type} current={event_type}", "PROCESS")
                
                if queued_event_type == event_type:
                    # Process the event
                    try:
                        _log(f"[PROCESS] EXECUTING {event_type} handler for {obsidian_path}", "PROCESS")
                        if event_type == "create":
                            await self._handle_create(file_path)
                        elif event_type == "modify":
                            await self._handle_modify(file_path)
                        elif event_type == "delete":
                            await self._handle_delete(file_path)
                        _log(f"[PROCESS] COMPLETED {event_type} handler for {obsidian_path}", "PROCESS")
                    except Exception as e:
                        _log(f"[PROCESS] ERROR in {event_type} handler: {str(e)}", "ERROR")
                        print(
                            f"[ERROR] Failed to process {event_type} for {file_path}: {e}",
                            file=sys.stderr,
                        )
                        import traceback
                        traceback.print_exc()
                else:
                    _log(f"[PROCESS] SKIP: Event type mismatch - was {queued_event_type}, now {event_type}", "PROCESS")
            else:
                _log(f"[PROCESS] SKIP: No debounce queue entry for {obsidian_path}", "PROCESS")
            
            # After processing, always clean up the debounce queue entry
            if file_path in self._debounce_queue:
                del self._debounce_queue[file_path]
                _log(f"[PROCESS] Cleaned up debounce queue entry for {obsidian_path}", "PROCESS")
        finally:
            # Always mark as done processing
            _log(f"[PROCESS] Marking as done processing: {obsidian_path} type={event_type}", "PROCESS")
            await self._mark_processing(obsidian_path, False)

    async def _process_move_queue(self):
        """Process move events from queue in correct order"""
        while self._running:
            try:
                event = await asyncio.wait_for(
                    self._move_event_queue.get(),
                    timeout=1.0
                )

                src_path = event['src_path']
                dest_path = event['dest_path']

                if Config.DEBUG:
                    print(f"[MOVE_QUEUE] Processing move: {src_path} → {dest_path}", file=sys.stderr)

                # Mark move in progress (async-protected)
                async with self._move_event_lock:
                    self._active_moves.add(src_path)
                    self._active_moves.add(dest_path)

                try:
                    # Check if file still exists at destination
                    if Path(dest_path).exists():
                        await self._handle_move(src_path, dest_path)
                    else:
                        if Config.DEBUG:
                            print(f"[MOVE_QUEUE] Destination no longer exists: {dest_path}", file=sys.stderr)
                finally:
                    # Remove from active moves
                    async with self._move_event_lock:
                        self._active_moves.discard(src_path)
                        self._active_moves.discard(dest_path)

            except asyncio.TimeoutError:
                # No events in queue, continue loop
                continue
            except Exception as e:
                print(f"[ERROR] Failed to process move from queue: {e}", file=sys.stderr)
                import traceback
                traceback.print_exc(file=sys.stderr)

    async def _is_in_active_moves(self, file_path: str) -> bool:
        """Check if file path is in active moves"""
        async with self._move_event_lock:
            return file_path in self._active_moves

    async def _handle_create(self, file_path: str):
        """Handle new note creation in Obsidian"""
        obsidian_path = None
        try:
            obsidian_path = self._get_relative_path(file_path) if Path(file_path).exists() else file_path
            _log(f"[CREATE] Starting _handle_create for {obsidian_path}", "CREATE")
            
            # Check if file still exists (may have been moved/deleted after event was queued)
            if not Path(file_path).exists():
                _log(f"[CREATE] File no longer exists, skipping: {obsidian_path}", "CREATE")
                print(
                    f"[WATCHER] File no longer exists, skipping: {file_path}",
                    file=sys.stderr,
                )
                return

            # Read file content
            _log(f"[CREATE] Reading file content for {obsidian_path}", "CREATE")
            content = Path(file_path).read_text(encoding="utf-8")
            
            # CRITICAL FIX: Don't sync empty files on create
            # New files start empty, wait for user to add content via modify event
            if not content.strip():
                _log(f"[CREATE] SKIP: File is empty (user hasn't added content yet): {obsidian_path}", "CREATE")
                print(
                    f"[WATCHER] Skipping empty file (will sync on first modify): {obsidian_path}",
                    file=sys.stderr,
                )
                return
            obsidian_path = self._get_relative_path(file_path)

            # Extract frontmatter
            _log(f"[CREATE] Extracting frontmatter for {obsidian_path}", "CREATE")
            metadata = self._extract_frontmatter(content, obsidian_path)

            # Check if already synced by supabase_id in frontmatter
            if metadata and metadata.get("supabase_id"):
                supabase_id = metadata["supabase_id"]
                _log(f"[CREATE] Found supabase_id in frontmatter: {supabase_id}", "CREATE")
                db_manager = LazyImport.get_db_manager()
                try:
                    existing = await db_manager.get_thought(supabase_id)
                    if existing:
                        _log(f"[CREATE] SKIP: Entry already synced with ID {supabase_id}", "CREATE")
                        print(
                            f"[WATCHER] Already synced (supabase_id: {supabase_id}), skipping: {obsidian_path}",
                            file=sys.stderr,
                        )
                        return
                except Exception as e:
                    # Row was deleted (e.g., file was moved), proceed with create
                    _log(f"[CREATE] supabase_id lookup failed (probably deleted row): {str(e)}", "CREATE")
                    pass

            # Check if already synced (in case of file move or duplicate)
            _log(f"[CREATE] Checking if entry already exists for {obsidian_path}", "CREATE")
            db_manager = LazyImport.get_db_manager()
            existing = await db_manager.get_thought_by_obsidian_path(obsidian_path)
            if existing:
                _log(f"[CREATE] SKIP: Entry already exists for {obsidian_path} (ID: {existing.get('id')})", "CREATE")
                if Config.DEBUG:
                    print(
                        f"[WATCHER] Already exists, treating as modify: {obsidian_path}",
                        file=sys.stderr,
                    )
                # Don't call _handle_modify since we're already processing
                return

            # Check if already in database by path (duplicate check)
            _log(f"[CREATE] Double-checking for entry by path: {obsidian_path}", "CREATE")
            db_manager = LazyImport.get_db_manager()
            existing_by_path = await db_manager.get_thought_by_obsidian_path(
                obsidian_path
            )

            if existing_by_path:
                # Entry exists with this path - treat as modify instead of create
                _log(f"[CREATE] SKIP: Duplicate check found existing entry (ID: {existing_by_path.get('id')})", "CREATE")
                if Config.DEBUG:
                    print(
                        f"[WATCHER] Entry already exists for {obsidian_path}, treating as modify",
                        file=sys.stderr,
                    )
                return

            print(f"[WATCHER] Creating new entry for: {obsidian_path}", file=sys.stderr)
            _log(f"[CREATE] PROCEEDING: Will create new Supabase entry for {obsidian_path}", "CREATE")

            # Extract metadata if not in frontmatter
            if not metadata or not metadata.get("topics"):
                _log(f"[CREATE] Extracting AI metadata for {obsidian_path}", "CREATE")
                metadata_extractor = LazyImport.get_metadata_extractor()
                ai_metadata = await metadata_extractor.extract_metadata(
                    content, metadata.get("title", "")
                )
                # MERGE: Keep original frontmatter fields and add/override with AI metadata
                # This ensures video_id, url, and other frontmatter fields are preserved
                metadata = {**ai_metadata, **metadata}

            # Generate embedding
            _log(f"[CREATE] Generating embedding for {obsidian_path}", "CREATE")
            try:
                embedding_generator = LazyImport.get_embedding_generator()
                # Add timeout to prevent embedding generation from hanging
                import asyncio
                try:
                    embedding = await asyncio.wait_for(
                        embedding_generator.create_embedding(content),
                        timeout=30.0  # 30 second timeout
                    )
                    _log(f"[CREATE] ✓ Embedding generated successfully (vector size: {len(embedding)})", "CREATE")
                except asyncio.TimeoutError:
                    _log(f"[CREATE] ✗ Embedding generation TIMEOUT (>30s) for {obsidian_path}", "CREATE")
                    # Use a zero vector as fallback
                    embedding = [0.0] * 1536
                    _log(f"[CREATE] Using zero vector fallback for embedding", "CREATE")
            except Exception as embed_err:
                _log(f"[CREATE] ✗ Embedding generation EXCEPTION: {str(embed_err)}", "CREATE")
                import traceback
                _log(f"[CREATE] Traceback: {traceback.format_exc()}", "CREATE")
                # Use a zero vector as fallback
                embedding = [0.0] * 1536
                _log(f"[CREATE] Using zero vector fallback due to exception", "CREATE")

            # Compute file hash
            file_hash = self._compute_hash(content)

            # Store in Supabase
            _log(f"[CREATE] Calling db_manager.store_thought() for {obsidian_path}", "CREATE")
            try:
                supabase_id = await db_manager.store_thought(
                    content,
                    embedding,
                    {
                        **metadata,
                        "obsidian_path": obsidian_path,
                        "file_hash": file_hash,
                        "source": "obsidian",
                    },
                )
                _log(f"[CREATE] ✓✓✓ NEW ENTRY CREATED ✓✓✓ ID={supabase_id} for {obsidian_path}", "CREATE")
            except Exception as store_err:
                _log(f"[CREATE] ✗ store_thought EXCEPTION: {str(store_err)}", "CREATE")
                import traceback
                _log(f"[CREATE] Traceback: {traceback.format_exc()}", "CREATE")
                raise

            # Update frontmatter with supabase_id
            # Add to skip_next_modify BEFORE writing to prevent triggering modify handler
            _log(f"[CREATE] Adding {file_path} to skip_next_modify", "CREATE")
            self._skip_next_modify.add(file_path)
            print(f"[WATCHER] Added to skip_next_modify: {file_path}", file=sys.stderr)
            
            _log(f"[CREATE] Updating frontmatter with supabase_id={supabase_id}", "CREATE")
            self._update_frontmatter(file_path, supabase_id)
            print(f"[WATCHER] Updated frontmatter with supabase_id: {supabase_id}", file=sys.stderr)
            
            _log(f"[CREATE] COMPLETED: {obsidian_path} → Supabase ID: {supabase_id}", "CREATE")

            print(
                f"[SYNC] Created: {obsidian_path} → Supabase ID: {supabase_id}",
                file=sys.stderr,
            )

        except Exception as e:
            obsidian_path_for_error = obsidian_path if obsidian_path else file_path
            _log(f"[CREATE] ✗✗✗ EXCEPTION in _handle_create ✗✗✗ for {obsidian_path_for_error}: {str(e)}", "CREATE")
            _log(f"[CREATE] Traceback: {traceback.format_exc()}", "CREATE")
            print(
                f"[ERROR] Failed to handle create for {file_path}: {e}", file=sys.stderr
            )
            import traceback

            traceback.print_exc()
        finally:
            # Cleanup is handled by _process_event_after_delay
            pass

    async def _handle_modify(self, file_path: str):
        """Handle note modification in Obsidian"""
        try:
            # Get path first for logging
            try:
                obsidian_path = self._get_relative_path(file_path)
            except ValueError:
                obsidian_path = file_path
            
            _log(f"[MODIFY] Starting _handle_modify for {obsidian_path}", "MODIFY")
            
            # Check if file still exists
            if not Path(file_path).exists():
                _log(f"[MODIFY] File no longer exists, skipping: {obsidian_path}", "MODIFY")
                print(
                    f"[WATCHER] File no longer exists, skipping modify: {file_path}",
                    file=sys.stderr,
                )
                return
            
            obsidian_path = self._get_relative_path(file_path)
            
            # Mark as processing
            _log(f"[MODIFY] Marking as processing: {obsidian_path}", "MODIFY")
            await self._mark_processing(obsidian_path, True)

            content = Path(file_path).read_text(encoding="utf-8")
            file_hash = self._compute_hash(content)

            # Extract frontmatter to get supabase_id
            metadata = self._extract_frontmatter(content, obsidian_path)

            # Check if note has a supabase_id in frontmatter
            if metadata and metadata.get("supabase_id"):
                supabase_id = metadata["supabase_id"]
                db_manager = LazyImport.get_db_manager()

                try:
                    # Try to get the entry with this supabase_id
                    entry_by_id = await db_manager.get_thought(supabase_id)

                    if entry_by_id:
                        # Entry exists with this supabase_id - verify it matches by path
                        if entry_by_id.get("obsidian_path") == obsidian_path:
                            # This is the correct entry - update it
                            # Check if content actually changed
                            if entry_by_id.get("file_hash") == file_hash:
                                if Config.DEBUG:
                                    print(
                                        f"[WATCHER] No content change detected: {obsidian_path}",
                                        file=sys.stderr,
                                    )
                                return

                            # Extract metadata if not in frontmatter
                            if not metadata.get("topics"):
                                metadata_extractor = LazyImport.get_metadata_extractor()
                                ai_metadata = await metadata_extractor.extract_metadata(
                                    content, metadata.get("title", "")
                                )
                                # MERGE: Keep original frontmatter fields and add AI metadata
                                metadata = {**ai_metadata, **metadata}

                            # Generate new embedding
                            embedding_generator = LazyImport.get_embedding_generator()
                            embedding = await embedding_generator.create_embedding(
                                content
                            )

                            # Update in Supabase
                            await db_manager.update_thought(
                                entry_by_id["id"],
                                content,
                                embedding,
                                file_hash,
                                metadata,
                            )

                            print(
                                f"[SYNC] Modified: {obsidian_path} (supabase_id: {supabase_id})",
                                file=sys.stderr,
                            )
                            return
                        else:
                            # Entry exists but has different path - this is a moved note
                            # Don't create new entry, let orphan cleanup handle path update
                            print(
                                f"[WATCHER] Modified note has supabase_id {supabase_id} but different path, skipping: {obsidian_path}",
                                file=sys.stderr,
                            )
                            return
                except Exception:
                    # Entry doesn't exist (was deleted) - recreate it
                    pass

            # Check if already tracked by path
            db_manager = LazyImport.get_db_manager()
            _log(f"[MODIFY] Checking if entry exists by obsidian_path: {obsidian_path}", "MODIFY")
            existing = await db_manager.get_thought_by_obsidian_path(obsidian_path)
            if not existing:
                # FIX #3: Do not recursively call _handle_create (causes duplicate entries)
                # Instead, create the entry directly here in this context
                _log(f"[MODIFY] *** NO EXISTING ENTRY *** Will create new entry inline", "MODIFY")
                if Config.DEBUG:
                    print(f"[WATCHER] No existing entry found for {obsidian_path}, creating new entry", file=sys.stderr)
                
                # Extract metadata if not already done
                if not metadata or not metadata.get("topics"):
                    _log(f"[MODIFY] Extracting metadata for new entry", "MODIFY")
                    metadata_extractor = LazyImport.get_metadata_extractor()
                    ai_metadata = await metadata_extractor.extract_metadata(
                        content, metadata.get("title", "")
                    )
                    # MERGE: Keep original frontmatter fields and add AI metadata
                    metadata = {**ai_metadata, **metadata}

                # Generate embedding
                _log(f"[MODIFY] Generating embedding for new entry", "MODIFY")
                embedding_generator = LazyImport.get_embedding_generator()
                embedding = await embedding_generator.create_embedding(content)

                # Store in Supabase
                _log(f"[MODIFY] Calling db_manager.store_thought() for new entry", "MODIFY")
                supabase_id = await db_manager.store_thought(
                    content,
                    embedding,
                    {
                        **metadata,
                        "obsidian_path": obsidian_path,
                        "file_hash": file_hash,
                        "source": "obsidian",
                    },
                )
                _log(f"[MODIFY] *** NEW ENTRY CREATED FROM MODIFY *** ID={supabase_id}", "MODIFY")

                # Update frontmatter with supabase_id
                _log(f"[MODIFY] Updating frontmatter with new supabase_id={supabase_id}", "MODIFY")
                self._skip_next_modify.add(file_path)
                self._update_frontmatter(file_path, supabase_id)

                print(
                    f"[SYNC] Created (from modify): {obsidian_path} → Supabase ID: {supabase_id}",
                    file=sys.stderr,
                )
                return

            # Check if content actually changed
            _log(f"[MODIFY] Checking if content changed for existing entry (ID: {existing.get('id')})", "MODIFY")
            if existing.get("file_hash") == file_hash:
                _log(f"[MODIFY] SKIP: Content unchanged, hash matches", "MODIFY")
                if Config.DEBUG:
                    print(
                        f"[WATCHER] No content change detected: {obsidian_path}",
                        file=sys.stderr,
                    )
                return

            # Extract updated metadata
            if not metadata or not metadata.get("topics"):
                metadata_extractor = LazyImport.get_metadata_extractor()
                ai_metadata = await metadata_extractor.extract_metadata(
                    content, metadata.get("title", "")
                )
                # MERGE: Keep original frontmatter fields and add AI metadata
                metadata = {**ai_metadata, **metadata}

            # Generate new embedding
            embedding_generator = LazyImport.get_embedding_generator()
            embedding = await embedding_generator.create_embedding(content)

            # Update in Supabase
            await db_manager.update_thought(
                existing["id"], content, embedding, file_hash, metadata
            )

            print(f"[SYNC] Modified: {obsidian_path}", file=sys.stderr)

        except Exception as e:
            print(
                f"[ERROR] Failed to handle modify for {file_path}: {e}", file=sys.stderr
            )
            import traceback

            traceback.print_exc()
        finally:
            # Mark as done processing
            obsidian_path = self._get_relative_path(file_path)
            await self._mark_processing(obsidian_path, False)

    async def _handle_delete(self, file_path: str):
        """Handle note deletion in Obsidian (HARD DELETE)"""
        try:
            obsidian_path = self._get_relative_path(file_path)

            # Hard delete from Supabase
            db_manager = LazyImport.get_db_manager()
            await db_manager.delete_thought_by_obsidian_path(obsidian_path)

            print(f"[SYNC] Deleted: {obsidian_path}", file=sys.stderr)
        except FileNotFoundError:
            # File already gone, just log
            print(f"[SYNC] File already deleted: {file_path}", file=sys.stderr)

        except Exception as e:
            print(
                f"[ERROR] Failed to handle delete for {file_path}: {e}", file=sys.stderr
            )
            import traceback

            traceback.print_exc()

    async def _extract_and_store_links(self, thought_id: int, content: str):
        """Extract wiki-links and embeds from content and store in links table"""
        import re

        # Find all [[wiki-links]] and ![[embeds]]
        wiki_links = re.findall(r"\[\[(.+?)\]\]", content)
        embed_links = re.findall(r"!\[\[(.+?)\]\]", content)

        links = []
        db_manager = LazyImport.get_db_manager()

        # Process wiki-links
        for link in wiki_links:
            link_text = link.split("|")[0]  # Extract display name if present
            target_path = self._find_note_path_by_title(link_text)
            if target_path:
                target_thought = await db_manager.get_thought_by_obsidian_path(
                    target_path
                )
                if target_thought:
                    links.append(
                        {
                            "source_thought_id": thought_id,
                            "target_thought_id": target_thought["id"],
                            "link_type": "wiki",
                            "link_text": link_text,
                        }
                    )

        # Process embed links
        for link in embed_links:
            link_text = link.split("|")[0]
            target_path = self._find_note_path_by_title(link_text)
            if target_path:
                target_thought = await db_manager.get_thought_by_obsidian_path(
                    target_path
                )
                if target_thought:
                    links.append(
                        {
                            "source_thought_id": thought_id,
                            "target_thought_id": target_thought["id"],
                            "link_type": "embed",
                            "link_text": link_text,
                        }
                    )

        # Store links
        if links:
            await db_manager.store_links(thought_id, links)

    async def _sync_tags(self, thought_id: int, content: str, metadata: Dict):
        """Sync tags from content and frontmatter to database"""
        import re

        tags = set()

        # Extract from frontmatter
        if metadata.get("topics"):
            tags.update(metadata["topics"])

        # Extract inline tags (#tag)
        inline_tags = re.findall(r"#(\w[\w-]*)", content)
        tags.update(inline_tags)

        # Store tags
        db_manager = LazyImport.get_db_manager()
        await db_manager.sync_tags(thought_id, list(tags))

    def _find_note_path_by_title(self, title: str) -> Optional[str]:
        """Find note path by title (for link resolution)"""
        obsidian_manager = LazyImport.get_obsidian_manager()

        # Try exact match first
        for md_file in self.vault_path.rglob("*.md"):
            if md_file.stem == title:
                return str(md_file.relative_to(self.vault_path))

        # Try fuzzy match (case-insensitive)
        for md_file in self.vault_path.rglob("*.md"):
            if md_file.stem.lower() == title.lower():
                return str(md_file.relative_to(self.vault_path))

        return None

    def _get_relative_path(self, file_path: str) -> str:
        """Get path relative to vault"""
        return str(Path(file_path).relative_to(self.vault_path))

    def _compute_hash(self, content: str) -> str:
        """Compute SHA-256 hash of content"""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _extract_frontmatter(self, content: str, file_identifier: str = None) -> Dict:
        """Extract YAML frontmatter from note content and make JSON-serializable

        Args:
            content: The note content
            file_identifier: Optional file name/path for logging (helps identify which file has issues)
        """
        try:
            import yaml
            from datetime import datetime
            import re
        except ImportError:
            print(
                "[WARNING] PyYAML not installed, frontmatter extraction disabled",
                file=sys.stderr,
            )
            return {}

        if not content.startswith("---"):
            return {}

        end_marker = content.find("\n---", 4)
        if end_marker == -1:
            return {}

        frontmatter_text = content[4:end_marker]

        def parse_with_fallback(yaml_text: str):
            """Try parsing, with fallback to quote unquoted values on failure"""

            def parse_yaml(text: str):
                try:
                    data = yaml.load(text, Loader=yaml.SafeLoader) or {}
                    return data, None
                except Exception as e:
                    return None, str(e)

            def quote_unquoted_values(text: str) -> str:
                """Quote unquoted scalar values that might contain colons"""
                lines = text.split("\n")
                fixed = []

                for line in lines:
                    stripped = line.strip()

                    # Skip empty lines, comments, list items, and already quoted values
                    if not stripped or stripped.startswith("#"):
                        fixed.append(line)
                        continue
                    if (
                        stripped.startswith('"')
                        or stripped.startswith("'")
                        or stripped.startswith("-")
                        or stripped.startswith("[")
                        or ":" not in stripped
                    ):
                        fixed.append(line)
                        continue

                    # Match key: value pattern and quote value
                    match = re.match(r"^(\s*)(\w+):\s*(.+)$", line)
                    if match:
                        indent, key, value = match.groups()
                        fixed.append(f'{indent}{key}: "{value}"')
                        continue

                    fixed.append(line)

                return "\n".join(fixed)

            data, error = parse_yaml(yaml_text)

            if error and "mapping values are not allowed here" in error:
                file_info = f" [{file_identifier}]" if file_identifier else ""
                print(
                    f"[WARNING] Auto-fixing malformed frontmatter{file_info} (quoting values): {error.split('in')[0]}",
                    file=sys.stderr,
                )

                fixed_text = quote_unquoted_values(yaml_text)
                data, error2 = parse_yaml(fixed_text)

                if error2:
                    print(
                        f"[WARNING] Frontmatter auto-fix failed{file_info}, using empty metadata",
                        file=sys.stderr,
                    )
                    return {}, True

                print(
                    f"[WARNING] Frontmatter was auto-fixed{file_info}. File content needs to be saved to persist the fix.",
                    file=sys.stderr,
                )
                return data, True

            return data, False

        data, was_fixed = parse_with_fallback(frontmatter_text)

        if not data:
            return {}

        def make_json_serializable(obj):
            """Recursively convert Python types to JSON-serializable formats"""
            if isinstance(obj, datetime):
                return obj.isoformat()
            elif isinstance(obj, dict):
                return {k: make_json_serializable(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [make_json_serializable(item) for item in obj]
            else:
                return obj

        return make_json_serializable(data)

    def _update_frontmatter(self, file_path: str, supabase_id: int):
        """Update note's frontmatter with supabase_id"""
        try:
            import yaml
        except ImportError:
            print(
                "[WARNING] PyYAML not installed, cannot update frontmatter",
                file=sys.stderr,
            )
            return

        content = Path(file_path).read_text(encoding="utf-8")
        lines = content.split("\n")

        if lines[0].strip() != "---":
            # No frontmatter, add it
            frontmatter = f"---\nsupabase_id: {supabase_id}\n---\n\n"
            new_content = frontmatter + content
        else:
            # Insert into existing frontmatter
            frontmatter_end = content.find("\n---", 4)
            if frontmatter_end != -1:
                frontmatter = content[: frontmatter_end + 4]
                if "supabase_id" not in frontmatter:
                    updated_frontmatter = (
                        frontmatter.rstrip() + f"\nsupabase_id: {supabase_id}\n---"
                    )
                    new_content = updated_frontmatter + content[frontmatter_end + 4 :]
                else:
                    # Already has supabase_id, don't modify
                    new_content = content
            else:
                # Malformed frontmatter, just append
                new_content = content

        Path(file_path).write_text(new_content, encoding="utf-8")

    async def _event_processor(self):
        """Process events from queue (background task)"""
        while self._running:
            event = await self._task_queue.get()

            # Check for stop signal (None value)
            if event[0] is None:
                print("Event processor stopping...", file=sys.stderr)
                break

            try:
                # Handle both 2-tuple and 3-tuple events
                if len(event) == 3:
                    src_path, dest_path, event_type = event
                    if event_type == "move":
                        await self._handle_move(src_path, dest_path)
                else:
                    file_path, event_type = event
                    if event_type == "create":
                        await self._handle_create(file_path)
                    elif event_type == "modify":
                        await self._handle_modify(file_path)
                    elif event_type == "delete":
                        await self._handle_delete(file_path)
            except Exception as e:
                file_path = event[0] if len(event) >= 2 else event[1]
                print(
                    f"[ERROR] Failed to process event: {e}",
                    file=sys.stderr,
                )
                import traceback
        
                traceback.print_exc()

        print("Event processor stopped", file=sys.stderr)


async def _cleanup_timer_loop():
    """Run cleanup of stale deletes/moves every 30 seconds"""
    while True:
        try:
            await asyncio.sleep(30)
            if hasattr(ObsidianEventHandler, '_instance'):
                handler = ObsidianEventHandler._instance
                handler._cleanup_stale_deletes()
                handler._cleanup_stale_moves()
                print("[CLEANUP] Running periodic cleanup at " + datetime.now().isoformat(), file=sys.stderr)
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[ERROR] Cleanup timer failed: {e}", file=sys.stderr)


def start_file_watcher(vault_path: Path, event_loop: asyncio.AbstractEventLoop):
    """Start the file watcher observer"""
    import asyncio

    event_handler = ObsidianEventHandler(vault_path)

    # Set event loop for async operations
    LazyImport.set_event_loop(event_loop)

    # Start event processor background task
    event_loop.create_task(event_handler._event_processor())

    # ✅ FIX #1: Start move queue processor
    move_processor_task = event_loop.create_task(event_handler._process_move_queue())
    if Config.DEBUG:
        print("[WATCHER] Started move queue processor", file=sys.stderr)

    # Start periodic cleanup timer (every 30 seconds)
    cleanup_task = event_loop.create_task(_cleanup_timer_loop())

    observer = Observer()
    observer.schedule(event_handler, str(vault_path), recursive=True)
    observer.start()
    print(f"[WATCHER] File watcher started for: {vault_path}", file=sys.stderr)
    # ✅ Return move processor task as well so it can be cancelled on shutdown
    return observer, cleanup_task, move_processor_task
