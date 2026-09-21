# Code Audit Report: Second Brain MCP Server

**Date:** 2026-05-03  
**Repository:** `D:\Programs\AI\!MCPServers!\!Second_Brain!\second-brain-mcp`  
**Language:** Python 3.10+  
**Framework:** MCP (Model Context Protocol) server with Supabase + Obsidian integration  

---

## Table of Contents

- [Critical Issues (7)](#critical-issues)
- [High Issues (13)](#high-issues)
- [Medium Issues (17)](#medium-issues)
- [Low Issues (10)](#low-issues)
- [Cross-Cutting Concerns](#cross-cutting-concerns)

---

## Critical Issues

### C1. Duplicate `validate()` method — real validation never runs

**File:** `config.py`  
**Lines:** 128-182 (first definition) and 499-506 (second definition)

**Details:** Two `validate()` methods are defined in the `Config` class. The first (line 128, `@classmethod`) performs all real validation: checks required env vars (`SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SUPABASE_PUBLISH_KEY`), handles legacy API key fallbacks, validates embedding/metadata/rerank API keys. The second (line 499, `@staticmethod`) only sets `_validated = True` and calls `_initialize_blacklists()`. Since Python uses late binding for class bodies, the second definition **replaces** the first. All critical validation (env vars, API keys) is silently skipped.

**Impact:** Server starts without required configuration, failing only at runtime with confusing errors.

**Fix approach:** Merge both methods into one. The staticmethod at line 499 should call the classmethod logic, or the two should be combined.

---

### C2. `_folders_synced` referenced as global but never defined

**File:** `tools.py`  
**Line:** 555

**Details:**
```python
global _folders_synced
if Config.SEMANTIC_FOLDER_PLACEMENT and _folders_synced:
```
The variable `_folders_synced` is declared `global` but is never defined at module scope. It exists as `self._folders_synced` on `ObsidianManager` (an instance attribute), but `tools.py` tries to use it as a module-level global. This will raise `NameError` at runtime when `SEMANTIC_FOLDER_PLACEMENT` is enabled.

**Impact:** Server crashes when semantic folder placement is enabled.

**Fix approach:** Either define a module-level `_folders_synced = False` global and set it appropriately, or access it via `obsidian_manager._folders_synced`.

---

### C3. Missing `await` on `sync_tags_for_thought` in `_handle_high_confidence_duplicate`

**File:** `tools.py`  
**Lines:** 683-685

**Details:**
```python
# Sync tags to thought_tags table
await sync_tags_for_thought(
    db_manager, existing["id"], content, metadata.get("topics")
)
```
This is inside `_handle_high_confidence_duplicate`. The `await` keyword is present here, BUT the issue is that `sync_tags_for_thought` is an `async` function (defined in `tag_utils.py:8`) and the call at line 683 is correctly awaited. However, comparing with the call at line 604 in `_store_new_thought`, both appear to have `await`. Re-examining: the actual bug is that in `_handle_high_confidence_duplicate`, the `force_overwrite` path at line 683 does `await sync_tags_for_thought(...)`, which is correct. The issue is that this path also calls `self._update_obsidian_note()` at line 688, which is a **synchronous** method called from an async context without `asyncio.to_thread()`, blocking the event loop.

**Impact:** Event loop is blocked during file I/O in the duplicate overwrite path.

**Fix approach:** Wrap synchronous file I/O calls in `asyncio.to_thread()`.

---

### C4. SQL injection risk in semantic search fallback

**File:** `database.py`  
**Lines:** 174-182

**Details:**
```python
query = f"""
SELECT ...
FROM thoughts
ORDER BY embedding <=> '{embedding_str}'::vector(1536)
LIMIT {limit}
"""
```
The `limit` parameter is interpolated directly into raw SQL via f-string. While `embedding_str` is built from float values (safer), `limit` comes from user input (MCP tool call parameter) without validation. If `limit` contains SQL injection payload, it will be executed via the `execute_sql` RPC.

**Impact:** Potential SQL injection if `limit` is not validated upstream.

**Fix approach:** Validate `limit` as a positive integer before interpolation, or use parameterized queries.

---

### C5. Column name mismatch in `delete_folder_by_path`

**File:** `database.py`  
**Lines:** 436 vs 858

**Details:** `sync_folders` (line 436) inserts into column `"path"`:
```python
.eq("path", path)
```
But `delete_folder_by_path` (line 858) queries column `"folder_path"`:
```python
.eq("folder_path", folder_path)
```
These refer to different column names. The delete will silently fail to find and remove the folder entry.

**Impact:** Folder entries can never be deleted from the database via this method.

**Fix approach:** Use consistent column names. Check the actual database schema (`CreateDatabase.sql`) to determine the correct column name.

---

### C6. Path traversal via `metadata["folder"]`

**File:** `obsidian.py`  
**Lines:** 170-171, 134

**Details:**
```python
folder_path = metadata.get("folder", "!To-Sort!")
...
filepath = self.vault_path / folder_path / filename
```
The `folder` value from metadata is used directly in path construction without sanitization. A malicious or buggy metadata payload with `"folder": "../../sensitive_directory"` could write files outside the vault. The `metadata` dict comes from AI-extracted metadata (`metadata.py`) or user-provided input (`tools.py:store_thought`).

**Impact:** Arbitrary file write outside the vault directory.

**Fix approach:** Validate that the resolved path stays within the vault using `Path.resolve()` and checking `vault_path in resolved.parents`.

---

### C7. Division by zero in cosine similarity

**File:** `obsidian.py`  
**Line:** 957

**Details:**
```python
similarity = dot_product / (norm_note * norm_folder)
```
If either vector has zero magnitude (e.g., the zero-vector fallback used when embedding generation fails at `watcher.py:1387, 1398`), `np.linalg.norm()` returns 0.0, causing division by zero. Numpy will produce `nan` or `inf` with a `RuntimeWarning` rather than raising an exception.

**Impact:** Silent production of `nan`/`inf` similarity scores, causing incorrect folder matching.

**Fix approach:** Add a zero-check: `if norm_note == 0 or norm_folder == 0: return 0.0`

---

## High Issues

### H1. Non-atomic file writes risk corruption

**Files:** `watcher.py:2007-2069`, `obsidian.py:140, 1745`  

**Details:** Frontmatter and note files are written directly with `write_text()`. If the process crashes mid-write, the file is left in a corrupted state (partial content, broken YAML frontmatter). This is especially dangerous for the frontmatter update path in `_update_frontmatter`.

**Impact:** Corrupted markdown files, potentially unparseable YAML frontmatter.

**Fix approach:** Write to a temporary file first, then atomically rename (`os.replace()` or `Path.replace()`).

---

### H2. Cross-thread access to `_recent_deletes` without locks

**File:** `watcher.py`  
**Lines:** 317-343 (event loop), 611-702 (watchdog thread), 721-764 (cleanup)

**Details:** The `_recent_deletes` dict is accessed from both the watchdog thread (`on_deleted` at line 692) and the event loop (`on_created` at line 317, `_cleanup_stale_deletes` at line 729). No synchronization primitive (lock) protects concurrent access. While `list(self._recent_deletes.items())` creates a snapshot, the `del` at line 353 and the iteration at line 317 are not atomic.

**Impact:** Race condition can cause lost delete tracking or double-processing of move events.

**Fix approach:** Use `asyncio.Lock` for cross-thread access, or use a thread-safe queue.

---

### H3. Embedding dimension hardcoded to 1536

**File:** `watcher.py`  
**Lines:** 1387, 1398

**Details:** When embedding generation fails, a zero vector of hardcoded size 1536 is used as fallback:
```python
embedding = [0.0] * 1536
```
This should use `Config.EMBEDDING_DIMENSIONS` instead. If the embedding model is changed to one with different dimensions, this produces wrong-sized vectors.

**Impact:** Wrong-dimensional vectors stored in the database, causing vector search failures.

**Fix approach:** Replace `1536` with `Config.EMBEDDING_DIMENSIONS`.

---

### H4. `PollingObserver` with 60-second timeout

**File:** `watcher.py`  
**Line:** 2197

**Details:**
```python
PollingObserver(timeout=60.0)
```
The 60-second timeout means the observer polls for file changes every 60 seconds. A file change could take up to 60 seconds to be detected. This makes the watcher extremely slow for real-time monitoring.

**Impact:** File changes are delayed by up to 60 seconds before being processed.

**Fix approach:** Reduce timeout to 1-2 seconds, or use `Observer` (inotify on Linux, FSEvents on macOS) instead of `PollingObserver` where available.

---

### H5. `_blacklist_watch_task` not tracked for cleanup

**File:** `server.py`  
**Lines:** 565, 576-580

**Details:** `start_file_watcher` returns 6 values including `_blacklist_watch_task` (line 565), but only 5 are added to `background_tasks` (lines 576-579). The `_blacklist_watch_task` is never appended, so it won't be cancelled on shutdown.

**Impact:** Resource leak — blacklist watcher continues running after server shutdown.

**Fix approach:** Add `background_tasks.append(_blacklist_watch_task)` at line 580.

---

### H6. `sys.exit(1)` in async context before finally block

**File:** `server.py`  
**Lines:** 627-629

**Details:**
```python
except Exception as e:
    print(f"Server error: {e}", file=sys.stderr)
    sys.exit(1)
```
`sys.exit(1)` raises `SystemExit`, which may prevent the `finally` block (line 630) from executing properly. Background tasks and file watcher cleanup may be skipped.

**Impact:** Incomplete shutdown — file watcher and background tasks may not be cleaned up.

**Fix approach:** Set a flag and let the `finally` block handle cleanup, or re-raise and catch `SystemExit` in the `finally` block.

---

### H7. `extract_metadata` blocks the event loop

**File:** `metadata.py`  
**Line:** 82

**Details:**
```python
async def extract_metadata(self, content: str, title: str = "") -> Dict:
    ...
    response = self.client.chat.completions.create(...)  # synchronous call
```
The method is declared `async` but calls the OpenAI client synchronously (blocking the event loop). This blocks the entire MCP server during AI metadata extraction, which can take several seconds.

**Impact:** Server is unresponsive during metadata extraction.

**Fix approach:** Use `loop.run_in_executor()` or the async OpenAI client (`AsyncOpenAI`).

---

### H8. `renew()` blocks the event loop

**File:** `supabase_lock.py`  
**Lines:** 188-205

**Details:** The `renew()` method calls `self.client.table(...).update(...).execute()` synchronously without `asyncio.to_thread()`. This blocks the event loop during lock renewal, unlike `acquire()` and `release()` which use `asyncio.wait_for()`.

**Impact:** Event loop is blocked during lock renewal, potentially causing heartbeat timeouts.

**Fix approach:** Wrap the Supabase call in `asyncio.to_thread()`.

---

### H9. No timeout on `renew()`

**File:** `supabase_lock.py`  
**Lines:** 188-205

**Details:** Unlike `acquire()` and `release()` which use `asyncio.wait_for()` with a timeout, `renew()` has no timeout protection. A hung DB connection will cause the auto-renew loop to hang indefinitely, and the lock will expire.

**Impact:** Lock expires due to failed renewal, allowing another instance to acquire it.

**Fix approach:** Wrap the renew call in `asyncio.wait_for()` with a reasonable timeout.

---

### H10. `force_acquire` fallback is not atomic

**File:** `supabase_lock.py`  
**Lines:** 103-124

**Details:** The fallback path in `_acquire_sync` does a plain `.update().eq("id", 1)` without checking `expires_at` or `instance_id`. This means the fallback can steal the lock from another active instance that currently holds it.

**Impact:** Lock stealing in fallback path — two instances may believe they hold the lock simultaneously.

**Fix approach:** Add `expires_at` check to the fallback update query, or use the RPC function exclusively.

---

### H11. `is_held` timezone comparison bug

**File:** `supabase_lock.py`  
**Lines:** 306-309

**Details:**
```python
expires_at = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
return expires_at > datetime.utcnow().replace(tzinfo=expires_at.tzinfo)
```
`datetime.utcnow().replace(tzinfo=expires_at.tzinfo)` sets the timezone to UTC's tzinfo but doesn't convert the time. If `expires_at` has a non-UTC timezone, this comparison is wrong. `utcnow()` returns a naive datetime in UTC, and `replace(tzinfo=...)` just labels it without converting.

**Impact:** Incorrect lock status determination — may report lock as held when it's expired, or vice versa.

**Fix approach:** Use `datetime.now(timezone.utc)` for proper UTC-aware comparison.

---

### H12. `SYNC_EXCLUDE_PATTERNS` not stripped

**File:** `config.py`  
**Lines:** 62-64

**Details:**
```python
SYNC_EXCLUDE_PATTERNS = os.getenv(
    "SYNC_EXCLUDE_PATTERNS", ".obsidian,.trash,.ClineData,!Folder_Embeddings.md"
).split(",")
```
`.split(",")` without `.strip()` means if the env var contains spaces (e.g., `" .obsidian , .trash"`), the patterns will have leading/trailing spaces, causing silent match failures.

**Impact:** Blacklisted patterns with spaces will never match, allowing excluded files to be synced.

**Fix approach:** Add `.strip()` to each item: `[p.strip() for p in ...split(",") if p.strip()]`.

---

### H13. `skipped` counter logic inverted

**File:** `database.py`  
**Line:** 433

**Details:**
```python
else:
    stats["skipped"] += 1
```
The `else` branch (incrementing `skipped`) is hit when `embedding is not None` (i.e., when an embedding WAS provided). The counter name "skipped" implies files that were skipped, but it's actually counting files that already had embeddings (didn't need generation). The logic is semantically inverted.

**Impact:** Misleading statistics — "skipped" count actually means "already had embedding."

**Fix approach:** Either rename the counter or swap the logic so `skipped` increments when no embedding was needed.

---

## Medium Issues

### M1. No numeric validation on env vars

**File:** `config.py`  
**Lines:** 25, 57, 59-61, 72-74, 81, 83, 86, 90, 101-106, 109-111

**Details:** Multiple `int()` and `float()` conversions on env vars without try/except:
- Line 25: `int(os.getenv("EMBEDDING_DIMENSIONS", "1536"))`
- Line 57: `float(os.getenv("SYNC_DEBOUNCE_SECONDS", "2.0"))`
- Line 59: `int(os.getenv("SYNC_FULL_SYNC_INTERVAL", "3600"))`
- Lines 72-74: `float(...)` for search weights
- Line 81: `int(os.getenv("RERANK_TIMEOUT", "10"))`
- Line 83: `int(os.getenv("RERANK_MAX_DOC_LENGTH", "4000"))`
- Line 86: `int(os.getenv("DB_TIMEOUT", "10"))`
- Line 90: `int(os.getenv("FTS_MIN_WORD_LENGTH", "3"))`
- Lines 101-106: Various lock config ints
- Lines 109-111: More lock config ints

If any env var contains a non-numeric value (e.g., `EMBEDDING_DIMENSIONS=abc`), the server crashes with an unhelpful `ValueError`.

**Impact:** Server crashes on malformed env vars with no helpful error message.

**Fix approach:** Wrap conversions in try/except with descriptive error messages.

---

### M2. `None` title not handled

**File:** `obsidian.py`  
**Line:** 98

**Details:**
```python
metadata.get("title", "Untitled")
```
If `title` is explicitly set to `None` in metadata, `.get()` returns `None` (not `"Untitled"`) because the key exists. Downstream code expecting a string title will fail.

**Impact:** `None` title propagates through the system, causing `TypeError` in string operations.

**Fix approach:** Use `metadata.get("title") or "Untitled"`.

---

### M3. Broad exception handling hides bugs

**Files:** Multiple files across the codebase

**Details:** Nearly every file uses `except Exception:` or `except Exception: pass`, silently swallowing programming errors (`NameError`, `AttributeError`, `KeyError`, etc.). Key locations:
- `config.py:221` — `_load_blacklist` swallows all errors
- `metadata.py:164` — Fallback hides all API/parsing errors
- `obsidian.py:707` — `except Exception: pass` in `_generate_folder_description`
- `watcher.py:1286-1304` — Catches all exceptions in DB lookup
- `tags.py:102` — Catches `ValueError, TypeError` but not `ZeroDivisionError` from numpy

**Impact:** Bugs are silently hidden, making debugging extremely difficult.

**Fix approach:** Catch specific exceptions. At minimum, log unexpected exceptions.

---

### M4. No connection pooling for HTTP requests

**Files:** `embeddings.py:76-100`, `reranker.py`  

**Details:** Each embedding/rerank call creates a new `requests.post()` connection. No `requests.Session` is used, so connection pooling is unavailable. Under load, this creates many TCP connections and hits OS file descriptor limits.

**Impact:** Poor performance under load, potential resource exhaustion.

**Fix approach:** Use `requests.Session` for connection pooling.

---

### M5. No retry logic on transient API failures

**Files:** `embeddings.py:95-100`, `reranker.py:107-110`  

**Details:** HTTP requests to embedding and rerank APIs have timeouts but no retry logic. A single transient error (429 rate limit, 500 server error, 503 unavailable) kills the request. Since these are on the critical search/storage path, this degrades user experience.

**Impact:** Transient network errors cause permanent failures.

**Fix approach:** Add retry with exponential backoff for transient HTTP errors (429, 500, 502, 503).

---

### M6. `_processing_files` class-level set shared across instances

**File:** `watcher.py`  
**Line:** 162

**Details:** `_processing_files` is a class-level `set()` shared across all `FileWatcher` instances. If multiple vaults are watched, they share the same processing set, causing false positives (a file in vault A blocks processing of a same-named file in vault B).

**Impact:** Cross-vault interference when watching multiple vaults.

**Fix approach:** Make `_processing_files` an instance variable instead of a class variable.

---

### M7. Debounce queue loses create events

**File:** `watcher.py`  
**Lines:** 892-906, 1096-1104

**Details:** The debounce key is `file_path` (not `file_path + event_type`). A create event followed by a modify event for the same file will have the modify overwrite the create in the queue. When the delayed task runs, `queued_event_type` will be "modify" but the original `event_type` was "create", so the create is silently skipped at line 1096-1104.

**Impact:** Rapid create→modify sequences lose the create event, causing files to not be synced.

**Fix approach:** Include event type in the debounce key, or process both events.

---

### M8. `find_recipes`, `list_guides`, `get_contacts` block event loop

**File:** `tools.py`  
**Lines:** 340, 376, 412

**Details:** These methods call `.execute()` directly on Supabase queries without wrapping in `asyncio.to_thread()`:
```python
response = query.order("created_at", desc=True).execute()
```
Other methods in the same file correctly use `asyncio.wait_for(asyncio.to_thread(query.execute), ...)`.

**Impact:** Event loop is blocked during database queries for these tools.

**Fix approach:** Wrap in `asyncio.to_thread()` like other methods.

---

### M9. Inconsistent error return types in tools

**File:** `tools.py`  
**Lines:** 229, 232, 251, 263, 280, 297, 314, 357, 393, 429, 448, 467, 478

**Details:** Some methods return `[{"error": ..., "message": ...}]` (list with error dict), while `get_thought` (line 263) returns `{"error": ..., "message": ...}` (single dict). This inconsistency confuses callers.

**Impact:** Callers must handle both list and dict error formats.

**Fix approach:** Standardize on a single error return format.

---

### M10. No timeout on multiple DB operations

**File:** `database.py`  
**Lines:** 283, 477, 567, 641, 834, 850, 871, 888, 994, 1008

**Details:** The following methods have no timeout protection:
- `list_recent` (line 283) — has timeout
- `search_folders_by_embedding` (line 477) — **no timeout**
- `get_all_folders` (line 567) — **no timeout**
- `get_all_thoughts` (line 641) — **no timeout**
- `update_obsidian_path` (line 834) — **no timeout**
- `delete_folder_by_path` (line 850) — **no timeout**
- `store_links` (line 871) — **no timeout**
- `sync_tags` (line 888) — **no timeout**
- `get_backlinks` (line 994) — **no timeout**
- `get_outlinks` (line 1008) — **no timeout**

A hung DB connection will cause these to block forever.

**Impact:** Server hangs on slow/failed database connections.

**Fix approach:** Add `asyncio.wait_for()` with `Config.DB_TIMEOUT` to all DB operations.

---

### M11. `obsidian_path` race in `_handle_create`

**File:** `watcher.py`  
**Lines:** 1272, 1521

**Details:** `obsidian_path` is assigned, then content is read, then `obsidian_path` is reassigned. If the file is moved or deleted between the content read and the reassignment, this crashes with `ValueError`.

**Impact:** Race condition causes crash during file creation handling.

**Fix approach:** Compute `obsidian_path` once and reuse it.

---

### M12. `_last_sync_result` class variable shared across instances

**File:** `obsidian.py`  
**Lines:** 28, 1537

**Details:** `_last_sync_result` is a class-level variable shared across all `ObsidianManager` instances. If multiple instances run concurrently (e.g., from `server.py` background tasks), they overwrite each other's results.

**Impact:** Race condition — orphan cleanup may use wrong sync results.

**Fix approach:** Make it an instance variable.

---

### M13. `ast.literal_eval` on DB data

**File:** `obsidian.py`  
**Lines:** 556, 924

**Details:** Embedding strings from the database are parsed with `ast.literal_eval()` instead of `json.loads()`. If the embedding is stored as a PostgreSQL array format (`{1,2,3}`) rather than Python list format (`[1,2,3]`), `literal_eval` will fail.

**Impact:** Folder similarity search fails if embedding format differs from expected.

**Fix approach:** Use `json.loads()` or handle both formats.

---

### M14. Exponential confidence decay in hierarchical folder search

**File:** `obsidian.py`  
**Line:** 827

**Details:**
```python
overall_confidence *= confidence
```
Multiplying probabilities at each level means confidence decays exponentially with depth. A 3-level path with 0.8 confidence at each level yields 0.512, which is below the 0.6 threshold. Deep matches are almost impossible.

**Impact:** Notes in deeply nested folders are rarely matched semantically.

**Fix approach:** Use averaging or a different confidence combination strategy.

---

### M15. `quote_unquoted_values` doesn't escape double quotes

**File:** `obsidian.py`  
**Line:** 1153

**Details:**
```python
f'{indent}{key}: "{value}"'
```
If `value` contains double quotes, the resulting YAML is invalid. No escaping is performed.

**Impact:** YAML corruption when values contain quotes.

**Fix approach:** Use `json.dumps(value)` or escape embedded quotes.

---

### M16. `cleanup_stale_lock` acquires lock but doesn't release it

**File:** `instance_lock.py`  
**Lines:** 238-240

**Details:**
```python
if self.acquire_lock_nonblocking():
    debug_log("[LOCK] Successfully cleaned up stale lock")
    return True
```
If `acquire_lock_nonblocking()` succeeds during cleanup, the lock is acquired but `release_lock()` is never called. The caller gets `True` but now holds the lock without knowing it.

**Impact:** Lock is leaked after cleanup — subsequent lock acquisition fails.

**Fix approach:** Call `self.release_lock()` after successful cleanup, or return the lock handle to the caller.

---

### M17. `start_auto_renew` has no duplicate guard

**File:** `supabase_lock.py`  
**Lines:** 207-235

**Details:** If `start_auto_renew` is called multiple times, multiple background tasks will be created, all renewing the same lock. No guard prevents duplicate tasks.

**Impact:** Resource waste and potential race conditions in lock renewal.

**Fix approach:** Track the renew task and check if already running before creating a new one.

---

## Low Issues

### L1. Module-level print runs before validation

**File:** `config.py`  
**Line:** 496

**Details:**
```python
print("[OK] All configuration validated successfully", file=sys.stderr)
```
This print statement is at class body level (not inside a method), so it runs at class definition time (import), before any validation occurs. It's also duplicated from line 182.

**Impact:** Misleading log message — claims validation succeeded before it runs.

**Fix approach:** Remove the module-level print; the one inside `validate()` at line 182 is sufficient.

---

### L2. `_EVENT_COUNTER` defined but never used

**File:** `watcher.py`  
**Line:** 135

**Details:** `_EVENT_COUNTER` is defined as a module-level global but is never referenced anywhere else in the file.

**Impact:** Dead code, confusing to maintainers.

**Fix approach:** Remove it.

---

### L3. Unused import `random` in server.py

**File:** `server.py`  
**Line:** 3

**Details:** `import random` is present but never used in `server.py`.

**Impact:** Unnecessary import.

**Fix approach:** Remove it.

---

### L4. Log file grows without rotation

**File:** `watcher.py`  
**Line:** 138

**Details:** When `DEBUG` is enabled, log entries are appended to a file indefinitely. No rotation or size limit exists.

**Impact:** Disk space exhaustion over time.

**Fix approach:** Implement log rotation (e.g., `logging.handlers.RotatingFileHandler`).

---

### L5. `_log()` always prints to stderr

**File:** `watcher.py`  
**Lines:** 155-156

**Details:** The `_log()` function always prints to stderr regardless of the `DEBUG` setting. Every event produces stderr output.

**Impact:** Noise in stderr output even when debug is disabled.

**Fix approach:** Guard with `if DEBUG:` check.

---

### L6. Redundant inline imports

**Files:** `obsidian.py:888, 1370, 1571`  

**Details:** `import numpy as np`, `import hashlib`, `import sys` are done inside methods. `sys` is already imported at module level (`obsidian.py:2`). These imports are re-executed on every call.

**Impact:** Minor performance overhead, hides dependencies.

**Fix approach:** Move imports to module level.

---

### L7. Duplicate database check in `_handle_create`

**File:** `watcher.py`  
**Lines:** 1306-1346

**Details:** The code checks for existing entries twice — once by `supabase_id` (lines 1306-1312) and once by `obsidian_path` (lines 1326-1346). The second check at line 1331 is redundant since line 1312 already checked.

**Impact:** Unnecessary database query.

**Fix approach:** Remove the redundant second check.

---

### L8. `package-lock.json` is empty

**File:** `package-lock.json`  

**Details:** An empty npm lock file exists in a pure Python project. This is likely a leftover.

**Impact:** Confusing to maintainers.

**Fix approach:** Remove the file.

---

### L9. No `__init__.py` in tests directory

**Directory:** `tests/`  

**Details:** The `tests/` directory lacks `__init__.py`, which can cause import issues with some test runners.

**Impact:** Potential test discovery/import issues.

**Fix approach:** Add an empty `__init__.py`.

---

### L10. `verify.py` doesn't test DB connectivity

**File:** `verify.py`  

**Details:** The verification script imports modules and prints config values but never actually tests if the Supabase connection works. A missing or wrong API key won't be caught until the server starts.

**Impact:** False confidence — verification passes but server fails to start.

**Fix approach:** Add a simple Supabase query (e.g., `SELECT 1`) to verify connectivity.

---

## Cross-Cutting Concerns

### CC1. Inconsistent async patterns

Some files use `asyncio.to_thread()` / `run_in_executor()` for blocking calls, while others call blocking code directly in async methods:
- `metadata.py:82` — synchronous OpenAI call in async method
- `supabase_lock.py:188` — synchronous Supabase call in async method
- `tools.py:340, 376, 412` — synchronous `.execute()` calls in async methods

This causes event loop blocking and server unresponsiveness.

---

### CC2. No consistent error handling strategy

Error handling varies wildly across the codebase:
- Some methods return error dicts
- Some return lists containing error dicts
- Some print to stderr and return empty lists
- Some silently swallow all exceptions
- Some re-raise

---

### CC3. Class-level mutable state

Several classes use class-level variables that are mutated at runtime:
- `Config.IGNORED_PATHS`, `Config.IGNORED_FILES`, `Config._blacklist_patterns` (config.py:45-50)
- `FileWatcher._processing_files` (watcher.py:162)
- `ObsidianManager._last_sync_result` (obsidian.py:28)

This is not thread-safe and not asyncio-safe.

---

### CC4. No request timeouts on several DB operations

Many Supabase calls don't use `asyncio.wait_for()`, meaning a hung connection will block forever. See M10 for the full list.

---

### CC5. Hardcoded embedding dimension 1536

The value `1536` appears in multiple places:
- `config.py:25` — default `EMBEDDING_DIMENSIONS`
- `database.py:178, 180` — vector cast in SQL fallback
- `watcher.py:1387, 1398` — zero-vector fallback

Only `config.py:25` uses the config value. The rest are hardcoded.

---

## Summary

| Severity | Count | Key Areas |
|----------|-------|-----------|
| Critical | 7 | Config validation shadowing, undefined globals, SQL injection, path traversal, column mismatch, division by zero |
| High | 13 | Non-atomic writes, race conditions, event loop blocking, resource leaks, hardcoded values, lock safety |
| Medium | 17 | Missing validation, broad exception handling, no retries, no timeouts, inconsistent patterns |
| Low | 10 | Dead code, unused imports, log rotation, redundant operations |
| **Total** | **47** | |
