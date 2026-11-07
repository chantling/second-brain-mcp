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
---

## Supabase Egress Overages — Resolution (2026-11-07)

**Issues addressed:** E1, E2 (decision), E3 from `FoundIssues.md` (2026-11-07 supplemental audit)
**Trigger:** Supabase egress 7.361GB vs 5GB limit (Oct cycle); ~400-500MB/day in Nov cycle; DB only 184MB.

### Root cause confirmed

Supabase API logs showed ~700 `GET /rest/v1/thoughts?select=*&id=eq.X` requests in a ~100s startup burst from `python-httpx/0.28.1` (this server), bracketed by `acquire_lock` / `PATCH server_lock`. `sync_existing_notes_to_supabase()` (startup) and the file watcher call `get_thought()` / `get_thought_by_obsidian_path()`, both of which used `select("*")` and therefore downloaded the `embedding` column (~10-30KB JSON per row) for every note, while the callers only use `id`, `obsidian_path`, `file_hash`, or truthiness. One startup pass ≈ 17k rows x ~2 lookups ≈ 300-500MB.

### Changes made

| File | Change |
|------|--------|
| `database.py` | `get_thought()`: `select("*")` → explicit columns `id, content, thought_type, topics, people, action_items, obsidian_path, file_hash, metadata, source, created_at, updated_at, deleted, deleted_at` (all columns except `embedding`; `content_tsv` also omitted, server-side only) |
| `database.py` | `get_thought_by_obsidian_path()`: same explicit column list |
| `links.py` | `find_related_notes()`: same explicit column list |

### Deliberately NOT changed

- **E2 / L7 (duplicate path lookup in `watcher.py` `_handle_create`, lines 1334 & 1353):** kept. It narrows a real concurrent-create race window; after the column fix each lookup is ~1KB, so the cost is negligible. Removing control flow in the watcher is the highest-risk class of change in this codebase.
- **E4 (`check_for_duplicates` Tier 2/3):** pre-existing logic defect, untouched (out of scope).
- **Batched startup sync:** rejected. Egress savings come from removing the embedding payload, not the request count; batching only speeds startup and restructures the most fragile path for ~zero byte savings.

### Pre-flight verification

Queried the LIVE `thoughts` table with the exact explicit column list before editing: all 14 columns exist and the response returns without `embedding`. Confirms the live schema matches `CreateDatabase.sql` (no unknown-column 400 risk).

### Testing performed (2026-11-07)

1. **Direct `DatabaseManager` test:** `get_thought(16663)` → 14 keys, no `embedding`; `get_thought_by_obsidian_path(...)` → no `embedding`; `semantic_search([0.0]*1536)` → 2 results (RPC path intact).
2. **Direct tool handler test:** `ToolHandlers.get_thought(16663)` → returns note with `obsidian_url`, no `embedding`; `search_by_topic("health")` → 2 results.
3. **End-to-end MCP Inspector:** `tools/call get_thought` → server boots, tool invoked, `isError: false`. Network trace confirms the new selection on the wire (`select=id%2Ccontent%2C...%2Cdeleted_at`) and a `200 OK` for a row fetched with it.
4. **Regression A/B:** behavior of the sporadic Cloudflare 400s (see E5) is identical on old and new code, proving they are pre-existing and unrelated.

**Expected outcome:** startup/watcher egress drops from ~400MB to ~5-15MB per pass (~95-97% reduction); daily egress should return to the previous 0-30MB baseline. Startup should also be faster.

**Rollback:** single commit touching only three `select(...)` calls; `git revert` is sufficient.

---

## Supabase Egress - Follow-up: skin-deep sync queries (2026-11-07, later same day)

**Issues addressed:** E1b (from FoundIssues.md)

### Measured baseline after the first fix

- Old `select("*")`: 32.1 KB/row (embedding ~24 KB of it)
- First fix (all columns except embedding): 8.1 KB/row -> **74.6% reduction only**
- Composition: content 6.33 KB + metadata 0.85 KB + rest ~0.9 KB

### Changes made

| File | Change |
|------|--------|
| `database.py` | Added `thought_exists()` -> `select("id")` (~0.03 KB/row) |
| `database.py` | Added `get_thought_sync_state()` -> `select("id, obsidian_path, file_hash")` (~0.18 KB/row) |
| `database.py` | `get_thought_by_obsidian_path()` -> `select("id, obsidian_path, file_hash")` (all callers use only these) |
| `obsidian.py` | Startup sync existence check now calls `thought_exists()` instead of `get_thought()` |
| `watcher.py` | `_handle_create` existence check -> `thought_exists()`; `_handle_modify` -> `get_thought_sync_state()` |

`get_thought()` deliberately left unchanged (minus embedding): the MCP `get_thought` tool and `links.get_link_graph()` need content/metadata.

Semantics preserved: `thought_exists()` returns `False` on error, exactly matching the previous behavior where `get_thought()` swallowed exceptions and returned `None` (callers then proceeded to create). No control flow changed.

### Expected outcome

Startup sync payload: ~8 KB/row -> ~0.03-0.18 KB/row, i.e. a ~1,000-2,000 lookup pass drops from ~8-16 MB to **~0.1-0.3 MB** (roughly 99% below the original `select("*")`). Remaining startup egress is the initial `select=id,obsidian_path` index plus folder metadata (unchanged, already cheap).

### Testing performed (2026-11-07)

1. `py_compile` on database.py, obsidian.py, watcher.py, links.py, tools.py - OK.
2. Direct DB tests: `thought_exists(real_id)=True`, `thought_exists(999999999)=False`; `get_thought_sync_state()` returns exactly `{id, obsidian_path, file_hash}` (0.18 KB); `get_thought_by_obsidian_path()` returns exactly the same 3 keys; `get_thought()` still returns 14 keys including content, no embedding.
3. Controlled startup-sync test: temporary 2-file vault whose notes reference real existing ids -> output `0 synced, 2 skipped, 0 errors`; no new rows and no rows for the temp file names (verified by query). A second 1-file run likewise gave `0 synced, 1 skipped, 0 errors`.
4. MCP end-to-end: server boots, `get_thought` tool invoked with `isError: false`. (The sporadic pre-existing Cloudflare 400 documented as E5 still occurs intermittently during startup bursts; unrelated to this change - A/B verified earlier.)

### Note discovered during testing

**Correction (2026-11-07, later):** this was a miscount. Four OS processes were **two** server instances - `venv\Scripts\python.exe` is a uv trampoline that re-executes the base interpreter, so every instance is two processes. A second `dmcp.exe` stack existed transiently from 10:50 and exited later. The startup sync takes no distributed lock, so overlapping instances can import the same notes concurrently. See corrected E6 in FoundIssues.md.

**Rollback:** single commit; only column lists and two added methods plus three call-site swaps.

---

## Blacklist lazy-initialization (2026-11-07, egress audit follow-up)

**Issue:** E7 in FoundIssues.md.

### Problem

`Config._blacklist_patterns` was empty until `Config.validate()` (or the watcher's 30 s reload) ran. `server.py:723` calls `validate()` before `main()`, so the server was correct, but `manual_sync.py` and ad-hoc scripts imported `Config` directly and scanned the entire vault, including `.trash`, `!Ticker-Analyses!` and `!To-Do!`. A 10-minute manual run during the audit created 88 `!Ticker-Analyses!` rows (15:59:45-16:09:20Z).

### Changes

| File | Change |
|------|--------|
| `config.py` | Added `_blacklist_initialized` flag; `_initialize_blacklists()` sets it; `is_blacklisted()` calls `_initialize_blacklists()` once when not yet initialized |
| `manual_sync.py` | Calls `Config.validate()` before creating managers |

No control flow changed in the server startup path: `validate()` still initializes first, so the lazy branch is a no-op there.

### Tests

1. `py_compile config.py manual_sync.py` - OK.
2. Fresh process importing `Config` without `validate()`: `_blacklist_patterns` = 0, then `is_blacklisted("!Ticker-Analyses!\\Fairly Valued\\X.md")` returns `.\!Ticker-Analyses!`, patterns = 8, initialized = True.
3. `.trash\old.md` matches `.trash`; `Resources\Recipes\x.md` returns empty.
4. Full vault with the blacklist active: 2,073/3,701 files skipped; all 1,628 remaining notes have `supabase_id`; 0 genuinely unsynced.

### Data cleanup

The 88 rows created by the audit were backed up (thoughts + 96 `thought_tags` rows, 2.97 MB) to `%TEMP%\opencode\ticker_rows_backup_2026-11-07.json`, then deleted through `delete_thought_by_id` (links/tags cleaned). Verified: 0 `!Ticker-Analyses!` rows remain; total rows 2,004 -> 1,916.

**Rollback:** revert the commit; restore the 88 rows from the JSON backup if needed (no links existed; 96 tag rows are in the backup).

---

## Orphan-cleanup pagination, data reconciliation, insert guards, JSON-safe metadata (2026-11-07)

**Issues addressed:** E8, E9, E10 (FoundIssues.md).

### Changes

| File | Change |
|------|--------|
| `database.py` | `get_all_thoughts()` now paginates: `.select(...).order("id").range(offset, offset+999)` until a short page |
| `database.py` | New `_json_safe()` helper; applied to `store_thought`, `update_thought`, `update_thought_content` payloads |
| `obsidian.py` | Startup sync takes the shared insert lock (`Config.LOCK_TTL_SECONDS`) only around the insert, then performs a final `get_thought_by_obsidian_path()` re-check |
| `obsidian.py` | Changed-note sync re-checks the path immediately before insert (it already holds the lock) |
| `watcher.py` | Create and modify-recreate re-check the path immediately after acquiring their existing lock |

### Why not hold the startup-sync lock for the whole scan

`SupabaseLock` is a **single global row** (`server_lock`, id=1) shared by every operation. Holding it for a 10-15 minute startup sync would make another instance's `modify_update` acquisition fail, and that path logs and **skips the note update**. The chosen guard holds the lock for ~1 second around the insert and adds a cheap final re-check, which removes the duplicate window without blocking edits.

### Data reconciliation performed

1. Reviewed dry-run (read-only): 290 deletions, 11 path updates, 91 duplicate groups -> 0.
2. Backed up the 290 rows + 791 `thought_tags` rows (7.4 MB) to `%TEMP%\opencode\orphan_cleanup_backup_2026-11-07.json`.
3. Ran the production cleanup (`ObsidianManager.remove_orphaned_supabase_entries`, lock-protected): **290 removed, 11 moved paths updated**.
4. Repaired one pre-existing inconsistency: row 17961 (`YouTube - Sharbel A.`) had an empty `obsidian_path`; set it to `Resources\Computer\AI\10 New Hermes Agent Skills to Install.md`.
5. Fixed E10 and re-ran the startup sync: **2 synced, 3699 skipped, 0 errors** (ids 18285, 18286).

### Final state (verified 2026-11-07)

- rows: **1,628**
- duplicate `obsidian_path` groups: **0**
- pathless rows: **0**
- rows whose stored path does not exist: **0**
- rows pointing at blacklisted paths: **0**
- non-blacklisted notes with `supabase_id`: 1,628; every one has a matching row

### Testing

1. `py_compile` on all touched files - OK.
2. `get_all_thoughts()` returns 1,626 (two pages) before the final imports and 1,628 after - full id range, no truncation.
3. `_json_safe()` converts `date`/`datetime` (nested in dicts/lists) to ISO strings; verified directly.
4. Production cleanup output: `Removed 290 orphaned Supabase entries`, `Updated 11 moved note paths`.
5. Startup sync after E10 fix: `0 errors`, both previously stuck notes imported and frontmatter updated.
6. Post-run audit confirms 0 duplicates, 0 orphan paths, 0 blacklisted rows.

### Backups

- `%TEMP%\opencode\ticker_rows_backup_2026-11-07.json` (88 audit rows, 96 tags)
- `%TEMP%\opencode\orphan_cleanup_backup_2026-11-07.json` (290 rows, 791 tags, moves list)
- `%TEMP%\opencode\orphan_cleanup_dryrun_2026-11-07.csv` (reviewed deletion list)

**Rollback:** revert the commit; restore rows from the JSON backups if needed. Note the cleanup deleted rows that `delete_thought_by_id` had already removed from `links`/`thought_tags`; those are included in the backup.
