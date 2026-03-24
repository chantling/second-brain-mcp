# Second Brain MCP Server -- Comprehensive Codebase Analysis

## 1. Directory Structure

```
D:\programs\AI\!MCPServers!\!Second_Brain!\second-brain-mcp\
|-- __init__.py                  # Package version marker (1.0.0)
|-- server.py                    # MAIN ENTRY POINT: MCP server startup, lock management, background tasks
|-- config.py                    # Configuration class (env vars, blacklists, defaults)
|-- tools.py                     # MCP tool handlers (store, search, list, etc.)
|-- database.py                  # Supabase database manager
|-- embeddings.py                # OpenAI-compatible embedding generator
|-- metadata.py                  # AI-powered metadata extraction
|-- obsidian.py                  # Obsidian vault manager (note CRUD, folder sync)
|-- watcher.py                   # File system watcher (watchdog) + LazyImport manager
|-- instance_lock.py             # Cross-process file locking (portalocker)
|-- links.py                     # Wiki-link and backlink management
|-- search.py                    # Hybrid vector + keyword search
|-- tags.py                      # Tag management and suggestions
|-- config.py                    # Configuration class
|-- .blacklist                   # Path/file ignore patterns
|-- .env                         # Environment variables (not in repo)
|-- requirements.txt             # Python dependencies
|-- CreateDatabase.sql           # Database schema
|-- Tests/                       # Test files directory
|-- venv/                        # Python virtual environment
|-- server.log                   # Server runtime log
|-- .server_lock                 # Lock file for multi-instance coordination
|-- watcher_debug.log            # Watcher debug log
|-- database_debug.log           # Database debug log
```

## 2. Server Entry Point and Startup

**Key file:** `server.py`

The server starts at line 764-771:
```python
if __name__ == "__main__":
    Config.validate()
    asyncio.run(main())
```

The `main()` function (line 531-749) does the following in sequence:

1. Sets up signal handlers for graceful shutdown (lines 545-565)
2. Warms up the embedding generator connection (lines 575-598)
3. Acquires an instance lock via `InstanceLock` (lines 602-634)
4. If **primary** instance: starts file watcher, background sync tasks, heartbeat (lines 637-697)
5. If **secondary** instance: starts lock retry loop to attempt takeover (lines 688-697)
6. Starts MCP server on stdio: `server.run(read_stream, write_stream, ...)` (lines 702-705)
7. On exit: runs `finally` block for cleanup (lines 713-749)

## 3. TaskGroup Usage

**Finding: NO `TaskGroup` is used anywhere in the codebase.**

All background tasks are created using individual `loop.create_task()` or `asyncio.create_task()` calls. There are 14 `create_task` invocations across the codebase:

**In `server.py`:**
- Line 458: `_heartbeat_loop` (for takeover)
- Line 655: `_run_initial_sync()`
- Line 664: `_run_folder_sync_startup()`
- Line 670: `_run_orphan_cleanup_startup()`
- Line 674: `_heartbeat_loop` (for primary)
- Line 682: `_periodic_orphan_cleanup_loop()`
- Line 690: `_lock_retry_loop` (for secondary)

**In `watcher.py`:**
- Line 785: `_process_event_after_delay` (debounce task)
- Line 824: `_process_move_after_delay` (debounce task)
- Line 1798: `_event_processor()`
- Line 1801: `_process_move_queue()`
- Line 1806: `_cleanup_timer_loop()`
- Line 1809: `_observer_heartbeat_loop()`
- Line 1812: `_process_deferred_moves()`

**Note:** The "TaskGroup" error in the user's crash log comes from the MCP SDK internals (`mcp/server/stdio.py`), not from this codebase. The MCP SDK's `stdio_server()` uses `anyio.create_task_group()` internally. When any server operation fails, the TaskGroup propagates the error, causing the "unhandled errors in a TaskGroup" message.

**Concern:** Without `TaskGroup`, there is no structured concurrency. If a background task fails silently, the server continues without knowledge of the failure. Tasks are fire-and-forget.

## 4. Client/Connection Handling

**Key file:** `database.py` (line 54-66)

The `DatabaseManager` class creates a single Supabase client:
```python
class DatabaseManager:
    def __init__(self):
        self.client: Client = create_client(self.supabase_url, self.supabase_secret_key)
```

**Singleton pattern in `tools.py` (lines 17-20):**
```python
db_manager = DatabaseManager()
obsidian_manager = ObsidianManager(Config.OBSIDIAN_VAULT_PATH, db_manager=db_manager)
embedding_generator = EmbeddingGenerator()
metadata_extractor = MetadataExtractor()
```

**Multi-client handling:** The MCP server runs in stdio mode (one client per process). There is no explicit session management or multi-client multiplexing. The locking mechanism (`InstanceLock`) ensures only one primary instance runs the file watcher at a time.

**Embedding/LLM clients** (`embeddings.py` line 23, `metadata.py` line 28): Both use OpenAI-compatible clients with connection pooling (240s timeout, 3 retries).

## 5. Locking Mechanisms

**File:** `instance_lock.py`

### A. Cross-Process Lock (InstanceLock class)

- Uses `portalocker` for OS-level file locking (line 83: `portalocker.lock(self.lock_file, portalocker.LOCK_EX | portalocker.LOCK_NB)`)
- Lock file: `.server_lock` in the same directory as `instance_lock.py`
- Contains JSON metadata: PID, instance_id, start_time, last_heartbeat, status
- Heartbeat mechanism: updates `last_heartbeat` periodically (default 20s)
- Stale lock detection: if heartbeat older than threshold (default 60s), secondary can takeover

### B. Async Processing Locks in watcher.py

- `ObsidianEventHandler._processing_lock` (class-level `asyncio.Lock`, lines 154, 194-199) -- guards `_processing_files` set
- `self._move_event_lock` (instance-level `asyncio.Lock`, line 188) -- guards `_active_moves` set

### C. Key variable `is_primary` in server.py

- Set once at startup (line 614 or 623)
- **UPDATED during takeover** via mutable dict: `is_primary["value"] = True` (line 506 in `_sync_takeover`)
- The `finally` block's lock release logic (line 734: `lock_held = lock_manager and lock_manager.lock_file is not None`) provides a backup check

## 6. Cleanup and Shutdown Logic

**File:** `server.py` (lines 713-761)

```python
finally:
    # 1. Stop file watcher
    if _file_watcher_observer:
        _file_watcher_observer.stop()
        _file_watcher_observer.join()

    # 2. Cancel background tasks
    for task in background_tasks:
        if not task.done():
            task.cancel()

    # 3. Release lock (checks both is_primary AND lock_file is not None)
    lock_held = lock_manager and lock_manager.lock_file is not None
    if is_primary or lock_held:
        lock_manager.release_lock()

    # 4. Call shutdown() for resource cleanup
    await shutdown()
```

The `shutdown()` function (lines 752-761):
```python
async def shutdown():
    await tool_handlers.cleanup()  # Closes DB, embeddings, metadata
    from watcher import LazyImport
    LazyImport.cleanup()  # Clears lazy reference cache
```

**LazyImport.cleanup()** (watcher.py lines 63-78): Releases all manager references (`_db_manager`, `_obsidian_manager`, `_embedding_generator`, `_metadata_extractor`) and clears the event loop weak reference.

**Signal handler** (lines 545-562): On SIGINT/SIGTERM, stops file watcher and cancels all tasks in the event loop.

## 7. Lazy Reference Management

**File:** `watcher.py` (lines 23-112)

`LazyImport` class manages singleton references to avoid circular imports:
```python
class LazyImport:
    _db_manager = None
    _obsidian_manager = None
    _embedding_generator = None
    _metadata_extractor = None
    _event_loop_ref: Optional[weakref.ref] = None  # Weak reference to event loop
```

The event loop is stored as a `weakref.ref` to allow GC (line 35):
```python
@classmethod
def set_event_loop(cls, loop):
    cls._event_loop_ref = weakref.ref(loop)
```

Manager instances are **no longer created lazily**. They are set by `start_file_watcher()` via the `db_manager`, `embedding_generator`, and `metadata_extractor` parameters. The `get_*` methods now raise an assertion error if the manager was not set, preventing accidental creation of duplicate clients.

---

## Issues Discovered and Resolution Status

### ISSUE 1: Fire-and-forget `run_coroutine_threadsafe` silently swallows errors [RESOLVED — HIGH SEVERITY]

**Location:** `watcher.py` lines 735-746 (formerly 740-744)

**Root Cause:** The stale-delete cleanup in `_cleanup_stale_deletes()` called `asyncio.run_coroutine_threadsafe()` to delete DB entries without awaiting the returned `Future`. Any exceptions from failed DB operations (network errors, auth failures, timeout) were silently lost. Over hours/days of operation, these silent failures corrupted the Supabase client's HTTP connection pool. When the pool was exhausted, the next MCP request would fail, crashing the MCP server's internal `TaskGroup` (from `anyio` in the stdio server), producing the "unhandled errors in a TaskGroup" error.

**Fix Applied:**
```python
future = asyncio.run_coroutine_threadsafe(
    db_manager.delete_thought_by_obsidian_path(rel_path),
    LazyImport.get_event_loop(),
)

def log_exception(f):
    try:
        f.result()
    except Exception as exc:
        _log(f"[DELETE] Stale delete failed: {exc}", "ERROR")

future.add_done_callback(log_exception)
```

A done callback is added to the Future that logs any exceptions from the DB operation. This ensures errors are visible and the Supabase client's connection state is not silently corrupted.

---

### ISSUE 2: `delete_thought_by_obsidian_path()` method missing from DatabaseManager [RESOLVED — HIGH SEVERITY]

**Location:** `database.py` (new method at lines 567-577)

**Root Cause:** The watcher code called `db_manager.delete_thought_by_obsidian_path()` in 3 places (`_cleanup_stale_deletes` at line 742, `_handle_delete` at line 1759, and the test cleanup scripts), but this method was **never defined** in `database.py`. Only `delete_thought_by_id()` existed. This meant all path-based delete operations silently failed with an `AttributeError`.

**Fix Applied:** Added the missing method to `database.py`:
```python
async def delete_thought_by_obsidian_path(self, obsidian_path: str) -> bool:
    """Delete thought by Obsidian file path"""
    _log(f"[DB:DELETE] Deleting thought by obsidian_path: {obsidian_path}", "DELETE")
    try:
        thought = await self.get_thought_by_obsidian_path(obsidian_path)
        if thought:
            return await self.delete_thought_by_id(thought["id"])
        else:
            _log(f"[DB:DELETE] No entry found for obsidian_path: {obsidian_path}", "DELETE")
            return False
    except Exception as e:
        _log(f"[DB:DELETE] ERROR deleting thought by obsidian_path {obsidian_path}: {e}", "DELETE")
        return False
```

---

### ISSUE 3: `_update_frontmatter` in obsidian.py corrupts frontmatter [RESOLVED — HIGH SEVERITY]

**Location:** `obsidian.py` lines 1650-1698 (formerly 1589-1630)

**Root Cause:** The `_update_frontmatter()` function in `obsidian.py` had two bugs:

1. **Substring match instead of exact match** (line 1594): `if "---" in lines[i]` matched any line containing "---" as a substring, not just the exact `---` delimiter line. This caused false positives.

2. **Broken depth-counting logic** (lines 1591-1598): The depth counter looked for `depth == 2` (two `---` lines found), but a well-formed frontmatter only has one closing `---` after the opening one. The depth would never reach 2, so `frontmatter_end_idx` stayed at -1, triggering the malformed frontmatter fallback that wrapped the entire content (including the corrupted frontmatter) inside a NEW frontmatter block. Each call added another `---\n---\n---\n` prefix.

3. **Missing newline before closing delimiter** (line 1630): `f"---\n{updated_fm}---\n\n"` concatenated the last YAML field value directly with `---` (e.g., `supabase_id: 1234---`), creating invalid YAML.

**Fix Applied:**
```python
# Changed from substring match to exact match:
if lines[i].strip() == "---":
    frontmatter_end_idx = i
    break

# Removed broken depth-counting (was looking for depth==2)
# Malformed fallback now returns without modifying:
if frontmatter_end_idx == -1:
    return  # Don't corrupt the file

# Added newline before closing delimiter:
new_content = f"---\n{updated_frontmatter}\n---\n\n" + "\n".join(...)
```

---

### ISSUE 4: `_update_frontmatter` in watcher.py fragile `content.find("\n---", 4)` pattern [RESOLVED — HIGH SEVERITY]

**Location:** `watcher.py` lines 2006-2021 (formerly 1980-2021)

**Root Cause:** The watcher's `_update_frontmatter()` used `content.find("\n---", 4)` to locate the closing frontmatter delimiter. This substring search could match `---` in the note's content (e.g., in code blocks, tables, or horizontal rules), causing incorrect frontmatter parsing. When paired with the corrupted files from Issue 3, this created a cascade of corruption.

**Fix Applied:** Rewrote the function to use YAML parsing (consistent with obsidian.py's approach):
- Line-based detection: `if lines[i].strip() == "---":`
- YAML parsing with `yaml.safe_load()` for frontmatter content
- Check for existing `supabase_id` using parsed dict instead of substring search
- Idempotent: if `supabase_id` already exists, returns without modification

---

### ISSUE 5: Stale-delete cleanup passes absolute path to DB lookup [RESOLVED — HIGH SEVERITY]

**Location:** `watcher.py` lines 675-682 (formerly 676)

**Root Cause:** In `on_deleted`, when the file no longer exists (which is always the case for delete events), the code set:
```python
rel_path = self._get_relative_path(src_path) if Path(src_path).exists() else src_path
```
Since the file was deleted, `Path(src_path).exists()` is always `False`, so `rel_path` was set to the absolute path `src_path` (e.g., `C:\Users\...\#Obsidian#\John\AUTOTEST01.md`). This absolute path was stored in `_recent_deletes` and later used by `_cleanup_stale_deletes` to call `delete_thought_by_obsidian_path(rel_path)`. But the DB stores relative paths (e.g., `AUTOTEST01.md`), so the lookup always failed.

**Fix Applied:**
```python
rel_path = str(Path(src_path).relative_to(self.vault_path))
```
This computes the relative path from the vault root without requiring the file to exist.

---

### ISSUE 6: Duplicate `DatabaseManager` and other managers via LazyImport [RESOLVED — MEDIUM SEVERITY]

**Location:** `watcher.py` lines 83-115 (formerly 81-112), `server.py` lines 713-723 and 460-470

**Root Cause:** `LazyImport.get_db_manager()` created a separate `DatabaseManager` instance than the one in `tools.py`, leading to two independent Supabase clients with separate connection pools. Same issue for `get_embedding_generator()`, `get_metadata_extractor()`, and `get_obsidian_manager()`. This wasted resources and could cause connection pool exhaustion.

**Fix Applied:**
- `start_file_watcher()` now accepts `embedding_generator` and `metadata_extractor` parameters in addition to `db_manager`
- These are set in `LazyImport` during startup: `LazyImport._embedding_generator = embedding_generator`
- The `get_*` methods now raise assertion errors instead of creating new instances:
  ```python
  assert cls._db_manager is not None, (
      "DatabaseManager not set. Ensure start_file_watcher() was called with db_manager."
  )
  ```
- Both call sites in `server.py` (primary startup and takeover) pass the additional managers

---

### ISSUE 7: Redundant `_mark_processing` calls in `_handle_modify` [RESOLVED — LOW SEVERITY]

**Location:** `watcher.py` formerly at lines 1538 and 1746

**Root Cause:** The wrapper `_process_event_after_delay` called `_mark_processing(obsidian_path, True)` before calling `_handle_modify`, but `_handle_modify` also called `_mark_processing(obsidian_path, True)` internally. While the lock was correctly released between calls (no deadlock), the double acquisition was wasteful. Similarly, both the handler's finally block and the wrapper's finally block called `_mark_processing(obsidian_path, False)`.

**Fix Applied:** Removed the redundant `_mark_processing(..., True)` call inside `_handle_modify` and the corresponding `_mark_processing(..., False)` from its finally block. The wrapper `_process_event_after_delay` handles both marking and unmarking.

---

### ISSUE 8: `is_primary` flag never updated after takeover [RESOLVED — HIGH SEVERITY]

**Location:** `server.py` lines 380-401 and 613-634

**Status:** Already fixed in current codebase. `_sync_takeover` receives `is_primary` as a mutable dict and sets `is_primary["value"] = True` at line 506.

---

### ISSUE 9: `ObsidianEventHandler._instance` referenced but never set [RESOLVED — HIGH SEVERITY]

**Location:** `watcher.py` lines 2068-2076, `start_file_watcher` line 2159

**Status:** Already fixed in current codebase. `_instance` is assigned in `start_file_watcher` at line 2159: `ObsidianEventHandler._instance = event_handler`. The `_cleanup_timer_loop` uses `getattr(ObsidianEventHandler, "_instance", None)` for safe access.

---

### ISSUE 10: `heartbeat_task` stored as function attribute, never cancelled [RESOLVED — MEDIUM SEVERITY]

**Location:** `server.py` lines 498-503

**Status:** Already fixed in current codebase. The takeover heartbeat task is appended to `background_tasks` list at line 503: `background_tasks.append(takeover_heartbeat)`.

---

### ISSUE 11: `_processing_lock` class variable race condition [OPEN — MEDIUM SEVERITY]

**Location:** `watcher.py` lines 194-199, 218-237

```python
if ObsidianEventHandler._processing_lock is None:
    try:
        ObsidianEventHandler._processing_lock = asyncio.Lock()
    except RuntimeError:
        ObsidianEventHandler._processing_lock = None
```

This pattern appears in `__init__`, `_is_processing`, and `_mark_processing`. If watchdog events fire before the event loop is running (which can happen), the lock remains `None`, and the processing guard is completely bypassed.

**Partially mitigated:** `start_file_watcher` sets `_processing_lock = asyncio.Lock()` explicitly before starting the observer (line 2158). However, the fallback code paths in `_is_processing` and `_mark_processing` that create the lock lazily are still present and could trigger if the class-level lock gets reset.

**Impact:** Without the processing lock, multiple handlers can process the same file concurrently, leading to duplicate database entries or corrupted frontmatter updates.

---

### ISSUE 12: `_running` is a class variable, not instance variable [OPEN — MEDIUM SEVERITY]

**Location:** `watcher.py` line 150

```python
class ObsidianEventHandler(FileSystemEventHandler):
    _running = True  # Class variable!
```

And in `_process_move_queue` (line 960) and `_event_processor` (line 1684):
```python
while self._running:
```

If multiple `ObsidianEventHandler` instances were ever created, calling `stop()` on one would stop all. While currently only one instance is created, this is a latent bug.

**Impact:** Not currently triggered but could cause issues if code is modified to create multiple event handler instances.

---

### ISSUE 13: Orphan cleanup race with initial sync [OPEN — LOW SEVERITY]

**Location:** `server.py` lines 315-334 and `obsidian.py` line 1149

The orphan cleanup on startup waits 60 seconds (line 320), but initial sync may take longer for large vaults. The `exclude_ids` mechanism protects against the race, but if the sync fails or takes longer than expected, orphan cleanup could delete newly created entries.

**Impact:** For vaults with many files (>100), the initial sync can take 15+ minutes due to embedding generation (8+ seconds per file). The orphan cleanup startup task waits only 60 seconds then waits for `_initial_sync_complete` flag, but if the server is restarted before sync completes, orphaned entries could be incorrectly deleted.

---

### ISSUE 14: Watchdog thread -> async loop thread safety [OPEN — LOW SEVERITY]

**Location:** `watcher.py` multiple `run_coroutine_threadsafe` calls

File system events fire on the watchdog thread but are pushed to the async event loop. There is no explicit synchronization for shared state like `_skip_next_modify` (a regular `set()`) between the watchdog thread and async tasks.

**Impact:** Potential race conditions where a modify event is incorrectly processed or skipped due to non-atomic set operations from different threads. Currently mitigated because `_skip_next_modify` is only accessed from the async thread in `on_modified`, but `on_created` does NOT check `_skip_next_modify`, creating an edge case.

---

### ISSUE 15: `Config.validate()` called twice [OPEN — COSMETIC]

**Location:** `config.py` line 240-241 and `server.py` line 767

`Config.validate()` is called once during module import (line 240) and again explicitly in `__main__` (line 767). This causes duplicate initialization messages.

---

## Summary of Changes Made (March 2026)

| File | Change | Issue |
|------|--------|-------|
| `database.py:567-577` | Added `delete_thought_by_obsidian_path()` method | ISSUE 2 |
| `obsidian.py:1654` | Changed substring match to exact match: `lines[i].strip() == "---"` | ISSUE 3 |
| `obsidian.py:1650-1660` | Simplified frontmatter boundary detection, removed broken depth-counting | ISSUE 3 |
| `obsidian.py:1696` | Added newline before closing `---` delimiter | ISSUE 3 |
| `watcher.py:735-746` | Added done callback to fire-and-forget Future for error logging | ISSUE 1 |
| `watcher.py:83-115` | Replaced lazy-creation in `get_*` methods with assertions | ISSUE 6 |
| `watcher.py:675` | Fixed stale-delete using absolute path: now uses `relative_to(vault_path)` | ISSUE 5 |
| `watcher.py:1538/1746` | Removed redundant `_mark_processing` calls in `_handle_modify` | ISSUE 7 |
| `watcher.py:2006-2044` | Rewrote `_update_frontmatter` to use YAML parsing instead of string search | ISSUE 4 |
| `watcher.py:2143-2169` | `start_file_watcher` now accepts and sets `embedding_generator` and `metadata_extractor` | ISSUE 6 |
| `server.py:713-723` | Primary startup passes `embedding_generator` and `metadata_extractor` to watcher | ISSUE 6 |
| `server.py:460-470` | Takeover startup passes `embedding_generator` and `metadata_extractor` to watcher | ISSUE 6 |

### Root Cause of Original Crash (Multi-Client Stability)

The "unhandled errors in a TaskGroup (1 sub-exception)" error was caused by a cascade of issues:

1. Fire-and-forget `run_coroutine_threadsafe` in `_cleanup_stale_deletes` silently swallowed DB operation errors
2. Over time, repeated failures corrupted the Supabase client's HTTP connection pool
3. When the pool was exhausted, the next MCP request would fail
4. The failure propagated to the MCP SDK's internal `TaskGroup` (in `anyio.create_task_group()` inside `stdio_server`)
5. The `ExceptionGroup` from the TaskGroup crashed the server

### Test Results

All 7 end-to-end tests pass:
1. ✅ Server detects notes created while offline
2. ✅ Server detects notes created while running  
3. ✅ Search tools work (semantic + keyword)
4. ✅ Server detects deleted files while offline (orphan cleanup)
5. ✅ Server detects file movements
6. ✅ Server detects content changes
7. ✅ Server detects deleted files while running (stale-delete cleanup)
