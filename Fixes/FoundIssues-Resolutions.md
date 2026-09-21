# Resolution Plan: Second Brain MCP Server Code Audit

**Date:** 2026-05-03
**Issues addressed:** 47 (7 Critical, 13 High, 17 Medium, 10 Low)

---

## Table of Contents

- [Critical Issues (C1-C7)](#critical-issues)
- [High Issues (H1-H13)](#high-issues)
- [Medium Issues (M1-M17)](#medium-issues)
- [Low Issues (L1-L10)](#low-issues)

---

## Critical Issues

### C1. [RESOLVED] Merge duplicate `validate()` methods in config.py

**File:** `config.py`
**Lines to modify:** 128-182, 496, 498-506

**Current state:** Two `validate()` methods exist. The first (classmethod, line 128) does all real validation. The second (staticmethod, line 499) replaces it and only calls `_initialize_blacklists()`. A module-level `print()` at line 496 runs at import time.

**Resolution:**
1. Remove the second `validate()` method entirely (lines 498-506)
2. Add `cls._initialize_blacklists()` as the last line of the first `validate()` method (after line 182)
3. Remove the module-level `print("[OK] All configuration validated successfully", file=sys.stderr)` at line 496
4. Keep the existing `print("[OK] All configuration validated successfully"` at line 182 (inside the classmethod)

**Result:** Single `@classmethod validate()` that does env-var validation, legacy key fallbacks, API key validation, AND blacklist initialization.

**Callers:** `server.py:676` and `verify.py:25` both call `Config.validate()` with no args — the classmethod decorator handles this correctly.

---

### C2. [RESOLVED] Define `_folders_synced` module-level global in tools.py

**File:** `tools.py`
**Line:** 555

**Current state:** `global _folders_synced` is declared but the variable is never defined in `tools.py` module scope. `ObsidianManager` has `self._folders_synced` as an instance attribute, but `tools.py` references a non-existent module global.

**Resolution:**
Add `_folders_synced = False` at module level in `tools.py` (after the global instances at line 27, before the `ToolHandlers` class). Then set it to `True` after a successful folder sync in `_sync_folders()`.

**Better alternative:** Access via `obsidian_manager._folders_synced` instead of a separate global. Change line 555 from:
```python
global _folders_synced
if Config.SEMANTIC_FOLDER_PLACEMENT and _folders_synced:
```
to:
```python
if Config.SEMANTIC_FOLDER_PLACEMENT and obsidian_manager._folders_synced:
```
This eliminates duplicate state entirely. **Recommended.**

---

### C3. [RESOLVED] Wrap synchronous file I/O in `_handle_high_confidence_duplicate`

**File:** `tools.py`
**Lines:** 686-690

**Current state:** `_update_obsidian_note()` at line 688 is a synchronous method that does file I/O but is called from the async `_handle_high_confidence_duplicate` without `asyncio.to_thread()`.

**Resolution:**
Wrap the call:
```python
obsidian_path = await asyncio.to_thread(
    self._update_obsidian_note,
    existing["obsidian_path"], content, metadata
)
```
Also wrap `_add_duplicate_warning_to_obsidian` (called at line 644 in `_store_new_thought`):
```python
await asyncio.to_thread(
    self._add_duplicate_warning_to_obsidian, obsidian_path, duplicate
)
```

---

### C4. [RESOLVED] Validate `limit` parameter in semantic search SQL

**File:** `database.py`
**Lines:** 174-182

**Current state:** `limit` is interpolated via f-string into raw SQL without validation.

**Resolution:**
Add validation before line 174:
```python
if not isinstance(limit, int) or limit < 1 or limit > 1000:
    limit = 10
```

---

### C5. [RESOLVED] Fix column name in `delete_folder_by_path`

**File:** `database.py`
**Line:** 858

**Current state:** `delete_folder_by_path` uses `.eq("folder_path", folder_path)` but the actual SQL column (per `CreateDatabase.sql:116`) is `"path"`. All other methods (`sync_folders` at lines 418, 445, 449) correctly use `"path"`.

**Resolution:**
Change line 858 from `.eq("folder_path", folder_path)` to `.eq("path", folder_path)`.

---

### C6. [RESOLVED] Add path traversal validation in `create_note`

**File:** `obsidian.py`
**Lines:** 134, 169-171, 340-343

**Current state:** `metadata["folder"]` is used directly in path construction without validation. `_ensure_folder_exists` also creates paths without checking they stay within the vault.

**Resolution:**
Add a validation helper to `ObsidianManager`:
```python
def _validate_folder_path(self, folder_path: str) -> str:
    if not folder_path:
        return "!To-Sort!"
    full = (self.vault_path / folder_path).resolve()
    vault_resolved = self.vault_path.resolve()
    if not str(full).startswith(str(vault_resolved)):
        return "!To-Sort!"
    return folder_path
```
Call it before using `folder_path` in `create_note` (around line 130) and in `_ensure_folder_exists` (line 340).

---

### C7. [RESOLVED] Add zero-check in cosine similarity

**File:** `obsidian.py`
**Line:** 957

**Current state:** Division by zero when either norm is zero (zero-vector embedding fallback).

**Resolution:**
Change lines 954-957 from:
```python
similarity = dot_product / (norm_note * norm_folder)
```
to:
```python
if norm_note == 0 or norm_folder == 0:
    similarity = 0.0
else:
    similarity = dot_product / (norm_note * norm_folder)
```
**Also apply the same fix in `tags.py:96-99`** where the same cosine similarity pattern exists.

---
## High Issues

### H1. [RESOLVED] Implement atomic file writes

**Files:** `obsidian.py:140-141`, `obsidian.py:1048-1049`, `obsidian.py:1689`, `obsidian.py:1745`, `watcher.py:2069`

**Current state:** All file writes use direct `write_text()` or `open(..., "w").write()`. A crash mid-write corrupts the file.

**Resolution:**
Create a utility function used by all write sites:
```python
import tempfile, os

def atomic_write(filepath: Path, content: str, encoding="utf-8"):
    tmp = filepath.with_suffix(filepath.suffix + ".tmp")
    try:
        tmp.write_text(content, encoding=encoding)
        tmp.replace(filepath)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise
```
Replace all 5 write sites:
1. `obsidian.py:140-141` — `create_note` frontmatter write
2. `obsidian.py:1048-1049` — embedding cache write
3. `obsidian.py:1689` — `_add_frontmatter` no-supabase path
4. `obsidian.py:1745` — `_add_frontmatter` supabase path
5. `watcher.py:2069` — `_update_frontmatter`

---

### H2. [RESOLVED] Add thread-safety to `_recent_deletes`

**File:** `watcher.py`
**Lines:** 194 (declaration), 310-353 (reads), 692 (writes), 729-759 (cleanup)

**Current state:** `_recent_deletes` is an instance dict accessed from both the watchdog thread and event loop without synchronization.

**Resolution:**
1. Add `import threading` at top of file
2. In `__init__`, add: `self._recent_deletes_lock = threading.Lock()`
3. Wrap all accesses with `with self._recent_deletes_lock:`:
   - Line 310: iteration in `on_created`
   - Line 353: `del` in `on_created`
   - Line 692: assignment in `on_deleted`
   - Line 732: iteration in `_cleanup_stale_deletes`
   - Line 759: `del` in `_cleanup_stale_deletes`

---

### H3. [RESOLVED] Replace hardcoded 1536 with Config.EMBEDDING_DIMENSIONS

**Files:** `watcher.py:1387,1398`, `database.py:178,180`

**Resolution:**
1. `watcher.py:1387` and `1398`: Change `[0.0] * 1536` to `[0.0] * Config.EMBEDDING_DIMENSIONS`
2. `database.py:178` and `180`: Change `::vector(1536)` to `::vector({Config.EMBEDDING_DIMENSIONS})` in the f-string, or simply remove the explicit dimension cast and use `::vector`

---

### H4. [RESOLVED] Reduce PollingObserver timeout

**File:** `watcher.py`
**Line:** 2197

**Resolution:**
Change `PollingObserver(timeout=60.0)` to `PollingObserver(timeout=2.0)`. On Windows, `PollingObserver` is the only option. A 2-second interval provides reasonable responsiveness without excessive CPU.

---

### H5. [RESOLVED] Add `_blacklist_watch_task` to background_tasks

**File:** `server.py`
**Lines:** 576-580

**Resolution:**
Add one line after line 579:
```python
background_tasks.append(_blacklist_watch_task)
```

---

### H6. [RESOLVED] Replace `sys.exit(1)` with graceful shutdown

**File:** `server.py`
**Lines:** 627-629

**Resolution:**
Replace:
```python
except Exception as e:
    print(f"Server error: {e}", file=sys.stderr)
    sys.exit(1)
```
with:
```python
except Exception as e:
    print(f"Server error: {e}", file=sys.stderr)
    shutdown_requested = True
```
This lets the `finally` block handle cleanup properly.

---

### H7. [RESOLVED] Make `extract_metadata` truly async

**File:** `metadata.py`
**Lines:** 82-101

**Current state:** The method is `async def` but calls the synchronous OpenAI client directly, blocking the event loop.

**Resolution:**
Wrap the synchronous call:
```python
loop = asyncio.get_running_loop()
response = await loop.run_in_executor(
    None,
    lambda: self.client.chat.completions.create(
        model=self.model,
        messages=[...],
        temperature=0.1,
        max_tokens=1000,
        extra_body={"thinking": {"type": "disabled"}}
    )
)
```

---

### H8/H9. [RESOLVED] Make `renew()` async-safe and add timeout

**File:** `supabase_lock.py`
**Lines:** 188-205

**Current state:** `renew()` is `async def` but calls Supabase synchronously (H8) and has no timeout (H9). Both `acquire()` and `release()` properly use `asyncio.to_thread()` + `asyncio.wait_for()`.

**Resolution:**
Follow the same pattern as `acquire()` and `release()`:
```python
async def renew(self, ttl_seconds: int = None) -> bool:
    if ttl_seconds is None:
        ttl_seconds = Config.LOCK_TTL_SECONDS
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(self._renew_sync, ttl_seconds),
            timeout=Config.DB_TIMEOUT,
        )
        return result
    except asyncio.TimeoutError:
        print(f"[LOCK] renew timed out after {Config.DB_TIMEOUT}s", file=sys.stderr)
        return False
```
Extract the sync logic into `_renew_sync(ttl_seconds)` (similar to `_acquire_sync` / `_release_sync` pattern).

---

### H10. [RESOLVED] Make `force_acquire` fallback atomic

**File:** `supabase_lock.py`
**Lines:** 99-117

**Current state:** The fallback UPDATE uses `.eq("id", 1)` without checking `expires_at` or `instance_id`, so it can steal a lock from another active instance.

**Resolution:**
Add an `expires_at` check to the fallback UPDATE:
```python
.eq("id", 1)
.lt("expires_at", datetime.utcnow().isoformat())
```
This ensures the fallback only succeeds if the lock has expired.

---

### H11. [RESOLVED] Fix timezone comparison in `is_held`

**File:** `supabase_lock.py`
**Lines:** 306-311

**Current state:** `datetime.utcnow().replace(tzinfo=expires_at.tzinfo)` sets the timezone label without converting, producing wrong comparisons.

**Resolution:**
Change line 311 from:
```python
return expires_at > datetime.utcnow().replace(tzinfo=expires_at.tzinfo)
```
to:
```python
from datetime import timezone
return expires_at > datetime.now(timezone.utc)
```

---

### H12. [RESOLVED] Strip whitespace from `SYNC_EXCLUDE_PATTERNS`

**File:** `config.py`
**Lines:** 62-64

**Resolution:**
Change from `.split(",")` to:
```python
SYNC_EXCLUDE_PATTERNS = [p.strip() for p in os.getenv(
    "SYNC_EXCLUDE_PATTERNS", ".obsidian,.trash,.ClineData,!Folder_Embeddings.md"
).split(",") if p.strip()]
```

---

### H13. [RESOLVED] Fix `skipped` counter semantics in `sync_folders`

**File:** `database.py`
**Line:** 433

**Current state:** `stats["skipped"]` is incremented when embedding IS provided (cache hit), which is semantically inverted from what "skipped" implies.

**Resolution:**
Rename the counter for clarity. Change `stats["skipped"]` to `stats["cached"]` throughout the method. This accurately counts folders that already had embeddings cached and didn't need generation.

---
## Medium Issues

### M1. Add numeric validation for env vars

**File:** `config.py`
**Lines:** 25, 57, 59-61, 72-74, 81-83, 86, 90, 101-106, 109-111 (18 conversions total)

**Current state:** All `int()` and `float()` conversions on `os.getenv()` have no try/except. A non-numeric value crashes the server at import time.

**Resolution:**
Create helper functions at module level:
```python
def _get_int_env(var_name: str, default: int) -> int:
    try:
        return int(os.getenv(var_name, str(default)))
    except ValueError:
        print(f"[CONFIG] Invalid integer for {var_name}, using default {default}", file=sys.stderr)
        return default

def _get_float_env(var_name: str, default: float) -> float:
    try:
        return float(os.getenv(var_name, str(default)))
    except ValueError:
        print(f"[CONFIG] Invalid float for {var_name}, using default {default}", file=sys.stderr)
        return default
```
Replace all 18 raw conversions with these helpers.

---

### M2. Handle `None` title in `create_note`

**File:** `obsidian.py`
**Line:** 98

**Current state:** `metadata.get("title", "Untitled")` returns `None` if the key exists with value `None`.

**Resolution:**
Change to `metadata.get("title") or "Untitled"`.

---

### M3. Narrow exception handling

**Files:** Multiple files

**Resolution (per file):**
- `config.py:221` — Change to `except (IOError, OSError, UnicodeDecodeError) as e`
- `metadata.py:164` — Change to `except (json.JSONDecodeError, KeyError, openai.APIError) as e`
- `obsidian.py:707` — Change to `except (IOError, OSError): pass`
- `watcher.py:1286-1304` — Add specific exception types and logging
- `tags.py:102` — Add `ZeroDivisionError` to caught: `except (ValueError, TypeError, ZeroDivisionError)`

---

### M4. Add connection pooling with `requests.Session`

**Files:** `embeddings.py:76-104`, `reranker.py:95-115`

**Current state:** Both use bare `requests.post()` — no connection pooling.

**Resolution for both files:**
1. In `__init__`, add: `self.session = requests.Session()`
2. Change `requests.post(...)` to `self.session.post(...)`
3. In `close()`, add: `self.session.close()`

---

### M5. Add retry logic for HTTP requests

**Files:** `embeddings.py:93-104`, `reranker.py:105-115`

**Current state:** Single `requests.post()` call with `raise_for_status()` and no retry.

**Resolution:**
Add a retry wrapper:
```python
def _request_with_retry(self, method, url, max_retries=3, **kwargs):
    for attempt in range(max_retries):
        try:
            resp = self.session.request(method, url, **kwargs)
            if resp.status_code in (429, 500, 502, 503):
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            return resp
        except requests.exceptions.ConnectionError:
            if attempt == max_retries - 1:
                raise
            time.sleep(2 ** attempt)
```

---

### M6. Make `_processing_files` an instance variable

**File:** `watcher.py`
**Lines:** 162-163

**Current state:** `_processing_files` is a class-level `set()` shared across all `FileWatcher` instances.

**Resolution:**
1. Remove class-level declarations at lines 162-163
2. Add to `__init__`: `self._processing_files = set()`
3. Update all references from `ObsidianEventHandler._processing_files` to `self._processing_files` (lines 241, 258, 260)

---

### M7. Fix debounce queue to preserve create events

**File:** `watcher.py`
**Lines:** 876, 892, 1096-1104

**Current state:** The debounce key is just `file_path`, so a create followed by modify overwrites the create in the queue.

**Resolution:**
Include event type in the debounce key. Change the key from `file_path` to `f"{file_path}:{event_type}"` at lines 876/892. This gives create and modify events separate queue entries.

---

### M8. Wrap blocking `.execute()` calls in `asyncio.to_thread()`

**File:** `tools.py`
**Lines:** 340, 376, 412

**Current state:** `find_recipes`, `list_guides`, and `get_contacts` call `.execute()` directly without `asyncio.to_thread()`.

**Resolution for each:**
```python
# find_recipes (line 340):
response = await asyncio.to_thread(query.order("created_at", desc=True).execute)

# list_guides (line 376):
response = await asyncio.to_thread(query.order("created_at", desc=True).execute)

# get_contacts (line 412):
response = await asyncio.to_thread(query.order("created_at", desc=True).execute)
```

---

### M9. Standardize error return types in tools.py

**File:** `tools.py`
**Lines:** 229, 232, 251, 263, 280, 297, 314, 357, 393, 429, 448, 467, 478

**Current state:** Most methods return `[{"error": ..., "message": ...}]` (list), but `get_thought` (line 263) returns `{"error": ..., "message": ...}` (bare dict).

**Resolution:**
Change `get_thought` error return to match the list format:
```python
return [{"error": str(e), "message": "Failed to get thought"}]
```

---

### M10. Add timeouts to all DB operations

**File:** `database.py`
**Lines:** 477, 567, 641, 834, 850, 871, 888, 994, 1008

**Current state:** 9 methods have no `asyncio.wait_for()` protection. A hung DB connection blocks forever.

**Resolution:**
Wrap each method's `_async_execute()` call:
```python
response = await asyncio.wait_for(
    self._async_execute(...),
    timeout=Config.DB_TIMEOUT,
)
```
For methods with loops (`store_links`, `sync_tags`), wrap the entire loop body.

---

### M11. Compute `obsidian_path` once in `_handle_create`

**File:** `watcher.py`
**Lines:** 1235-1272, 1502-1521

**Current state:** `obsidian_path` is assigned, then content is read, then `obsidian_path` is reassigned. A race condition if the file is deleted between read and reassignment.

**Resolution:**
In `_handle_create`, remove the second assignment at line 1272. The first assignment at lines 1237-1241 already handles the fallback correctly. In `_handle_modify`, remove the second assignment at line 1521.

---

### M12. Make `_last_sync_result` an instance variable

**File:** `obsidian.py`
**Lines:** 28, 1537

**Current state:** `_last_sync_result` is a class-level variable shared across all `ObsidianManager` instances.

**Resolution:**
1. Remove class-level declaration at line 28
2. Add to `__init__`: `self._last_sync_result = None`
3. Update `get_last_sync_result` to return `self._last_sync_result`
4. Update assignment at line 1537 to `self._last_sync_result = result`

---

### M13. Replace `ast.literal_eval` with `json.loads`

**File:** `obsidian.py`
**Lines:** 553-556, 921-924

**Current state:** Embedding strings from the database are parsed with `ast.literal_eval()`.

**Resolution:**
Change both occurrences to `json.loads(embedding)`. Add `import json` at module level if not present.

---

### M14. Fix exponential confidence decay

**File:** `obsidian.py`
**Line:** 827

**Current state:** `overall_confidence *= confidence` causes exponential decay with folder depth.

**Resolution:**
Use averaging instead:
```python
overall_confidence = (overall_confidence + confidence) / 2
```

---

### M15. Escape double quotes in `quote_unquoted_values`

**File:** `obsidian.py`
**Line:** 1154

**Current state:** `f'{indent}{key}: "{value}"'` does not escape embedded double quotes.

**Resolution:**
```python
escaped_value = value.replace('\\', '\\\\').replace('"', '\\"')
fixed.append(f'{indent}{key}: "{escaped_value}"')
```

---

### M16. Release lock after stale cleanup

**File:** `instance_lock.py`
**Lines:** 236-240

**Current state:** `cleanup_stale_lock` acquires the lock via `acquire_lock_nonblocking()` but never calls `release_lock()`.

**Resolution:**
Add `self.release_lock()` after successful acquisition:
```python
if self.acquire_lock_nonblocking():
    self.release_lock()
    debug_log("[LOCK] Successfully cleaned up stale lock")
    return True
```

---

### M17. Add duplicate guard to `start_auto_renew`

**File:** `supabase_lock.py`
**Lines:** 207-235

**Current state:** Multiple calls create multiple background tasks all renewing the same lock.

**Resolution:**
Add a guard at the top of the method:
```python
if self._renew_task is not None and not self._renew_task.done():
    return  # Already running
```

---
## Low Issues

### L1. Remove module-level print in config.py

**File:** `config.py`
**Line:** 496

**Resolution:**
Delete the line `print("[OK] All configuration validated successfully", file=sys.stderr)` at line 496. The same message is already printed inside the `validate()` method at line 182.

---

### L2. Remove unused `_EVENT_COUNTER`

**File:** `watcher.py`
**Line:** 135

**Resolution:**
Delete `_EVENT_COUNTER = 0`.

---

### L3. Remove unused `random` import

**File:** `server.py`
**Line:** 3

**Resolution:**
Delete `import random`.

---

### L4. Add log rotation

**File:** `watcher.py`
**Lines:** 138, 147-151

**Current state:** Log file grows unboundedly when DEBUG is enabled.

**Resolution:**
Add size-based rotation in the `_log` function:
```python
if _LOG_FILE.exists() and _LOG_FILE.stat().st_size > 10_000_000:  # 10MB
    backup = _LOG_FILE.with_suffix(".log.1")
    if backup.exists():
        backup.unlink()
    _LOG_FILE.rename(backup)
```

---

### L5. Guard stderr output with DEBUG check

**File:** `watcher.py`
**Line:** 155

**Current state:** `_log()` always prints to stderr regardless of DEBUG setting.

**Resolution:**
Change unconditional `print(log_msg, file=sys.stderr)` to:
```python
if Config.DEBUG:
    print(log_msg, file=sys.stderr)
```

---

### L6. Move inline imports to module level

**File:** `obsidian.py`
**Lines:** 888, 1370-1373, 1569-1572

**Current state:** `numpy`, `hashlib`, `sys` are imported inside methods. `sys` is already at module level.

**Resolution:**
1. Add to module-level imports: `import numpy as np`, `import hashlib`
2. Remove inline `import numpy as np` at line 888
3. Remove inline `import hashlib` and `import sys` at lines 1370-1371 and 1569-1570

---

### L7. Remove duplicate DB check in `_handle_create`

**File:** `watcher.py`
**Lines:** 1326-1346

**Current state:** The exact same `get_thought_by_obsidian_path` query is performed twice in succession.

**Resolution:**
Delete lines 1326-1346 (the second redundant check). The first check at lines 1306-1324 is sufficient.

---

### L8. Remove empty `package-lock.json`

**File:** `package-lock.json`

**Resolution:**
Delete the file. It is an empty npm lock file in a pure Python project.

---

### L9. Add `__init__.py` to tests directory

**Directory:** `tests/`

**Resolution:**
Create an empty `tests/__init__.py` file.

---

### L10. Add DB connectivity check to verify.py

**File:** `verify.py`

**Current state:** The verification script never tests if the Supabase connection actually works.

**Resolution:**
Add after config validation:
```python
try:
    from database import DatabaseManager
    db = DatabaseManager()
    db.client.table("thoughts").select("id").limit(1).execute()
    print("[OK] Database connection successful", file=sys.stderr)
except Exception as e:
    print(f"[FAIL] Database connection failed: {e}", file=sys.stderr)
```

---

## Implementation Order

To minimize risk and dependencies, implement in this order:

### Phase 1: Critical fixes (no dependencies between them)
1. C1 — Merge validate() methods
2. C2 — Fix _folders_synced global
3. C4 — Validate limit parameter
4. C5 — Fix column name mismatch
5. C6 — Add path traversal validation
6. C7 — Add zero-check in cosine similarity

### Phase 2: High-priority fixes
7. H5 — Add blacklist_watch_task to background_tasks (1 line)
8. H12 — Strip SYNC_EXCLUDE_PATTERNS (1 line)
9. H13 — Fix skipped counter name
10. H3 — Replace hardcoded 1536
11. H4 — Reduce PollingObserver timeout
12. H11 — Fix timezone comparison
13. H6 — Replace sys.exit(1)
14. H1 — Atomic file writes
15. H2 — Thread-safety for _recent_deletes
16. H7 — Make extract_metadata truly async
17. H8/H9 — Fix renew() async + timeout
18. H10 — Fix force_acquire atomicity

### Phase 3: Medium-priority fixes
19. M1 — Numeric env var validation
20. M2 — Handle None title
21. M6 — Make _processing_files instance variable
22. M7 — Fix debounce queue
23. M8 — Wrap blocking execute() calls
24. M10 — Add DB timeouts
25. M11 — Fix obsidian_path race
26. M12 — Make _last_sync_result instance variable
27. M13 — Replace ast.literal_eval
28. M14 — Fix confidence decay
29. M15 — Escape double quotes
30. M16 — Release lock after cleanup
31. M17 — Add auto-renew duplicate guard
32. M3 — Narrow exception handling
33. M4 — Add connection pooling
34. M5 — Add retry logic
35. M9 — Standardize error return types

### Phase 4: Low-priority fixes
36. L1 — Remove module-level print
37. L2 — Remove unused _EVENT_COUNTER
38. L3 — Remove unused random import
39. L4 — Add log rotation
40. L5 — Guard stderr output
41. L6 — Move inline imports
42. L7 — Remove duplicate DB check
43. L8 — Remove package-lock.json
44. L9 — Add tests/__init__.py
45. L10 — Add DB connectivity check to verify.py

---

## Files Modified Summary

| File | Issues | Change Count |
|------|--------|-------------|
| config.py | C1, H12, L1, M1 | 4 changes |
| tools.py | C2, C3, M8, M9 | 4 changes |
| database.py | C4, C5, H13, M10 | 4 changes |
| obsidian.py | C6, C7, H1, M2, M12, M13, M14, M15, L6 | 9 changes |
| watcher.py | H2, H3, H4, M6, M7, M11, L2, L4, L5, L7 | 10 changes |
| server.py | H5, H6, L3 | 3 changes |
| metadata.py | H7, M3 | 2 changes |
| supabase_lock.py | H8, H9, H10, H11, M17 | 5 changes |
| instance_lock.py | M16 | 1 change |
| tags.py | C7 (zero-check), M3 | 2 changes |
| embeddings.py | M4, M5 | 2 changes |
| reranker.py | M4, M5 | 2 changes |
| verify.py | L10 | 1 change |
| package-lock.json | L8 | Delete |
| tests/__init__.py | L9 | Create |