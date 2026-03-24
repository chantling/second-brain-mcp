# File Watcher Issues - Diagnostic & Fix Plan

## Test Results Summary

### ✅ PASSED Tests

1. **Test 1**: Server detects notes created when not running
   - AUTOTEST01.md created with "Test note about elephants"
   - Server synced and added frontmatter with supabase_id=1154
   - Database entry created matching file's supabase_id

2. **Test 2**: Server detects notes created while running
   - AUTOTEST02.md created with "Test note about hyenas"
   - Server synced and added frontmatter with supabase_id=1155
   - Database entry created correctly

3. **Test 3**: Server search tools work
   - Semantic search for "animal" returned both AUTOTEST01.md and AUTOTEST02.md
   - Keyword search for "elephant" returned AUTOTEST01.md

4. **Test 4**: Server detects files deleted when not running
   - AUTOTEST02.md deleted (server not running)
   - Server started, ran orphan cleanup after 5 seconds
   - Database entry for AUTOTEST02.md (ID: 1155) was removed

### ❌ FAILED Tests

5. **Test 5**: File movement detection
   - AUTOTEST01.md moved from vault root to `!To-Do!\` folder
   - Expected: Database obsidian_path updated from `AUTOTEST01.md` to `!To-Do!\AUTOTEST01.md`
   - Actual: Database obsidian_path still `AUTOTEST01.md`, no update occurred
   - Log shows: `[WATCHER] Started move queue processor` but no move events logged
   - Created duplicate entry at new path (ID: 1170) instead of updating existing entry

6. **Test 6**: File content change detection
   - AUTOTEST01.md content changed from "elephants" to "dandelions"
   - Expected: Database content updated
   - Actual: Database content still "Test note about elephants"
   - Log shows file processed during initial sync but no modify events logged

7. **Test 7**: File deletion while server is running
   - `!To-Do!\AUTOTEST01.md` deleted
   - Expected: Database entry removed
   - Actual: Database entry still exists (ID: 1178)
   - Log shows: No deletion events, no "File deleted:" messages
   - Orphan cleanup on startup removed entries but not real-time deletions

## Root Cause Analysis

**Primary Issue**: Watchdog file observer is not emitting file system events (move, modify, delete)

**Evidence:**
- Move queue processor starts but receives no events
- No "File moved:", "File modified:", or "File deleted:" messages in logs
- Initial sync processes files correctly, but subsequent changes produce no watcher events
- Orphan cleanup on startup handles changes (5s delay) but real-time detection fails

**Potential Causes:**
1. Watchdog observer not actually monitoring despite "started" message
2. Windows path handling issues preventing event detection
3. File system events filtered out by `_should_process` logic
4. Git Bash environment interfering with watchdog event detection
5. Observer scheduled but not properly attached to event loop
6. Events being queued but not processed

## Diagnostic & Fix Plan

### Phase 1: Enhanced Observer Diagnostics

**Goal**: Determine if observer is actually receiving events

**Add logging at:**

1. **Observer initialization** (`watcher.py:1544-1569`)
   - Log observer class being used
   - Log exact vault path being monitored
   - Verify observer.start() succeeded
   - Add observer heartbeat (poll observer.is_alive() every 30s)

2. **Event handlers** (`watcher.py:145-542`)
   - Add logging at VERY TOP of `on_moved`, `on_modified`, `on_deleted`
   - Log ALL events before any filtering
   - Log event object details: type, paths, is_directory, event_type
   - Log return value of `_should_process` for each event

3. **Queue operations** (`watcher.py:184-848`)
   - Log when events are added to `_move_event_queue`
   - Log queue size every 10 seconds
   - Log when events are dequeued for processing
   - Log `_files_being_moved` set contents

### Phase 2: Standalone Watchdog Test

**Goal**: Verify if issue is server integration or watchdog itself

**Create `test_watchdog.py`**
- Simple standalone script to test watchdog in isolation
- Perform create/modify/move/delete operations
- Verify events are received

### Phase 3: Investigate `_should_process` Logic

**Potential filtering issues in `watcher.py:573-603`:**

1. **Line 579**: `.endswith(".md")` - Check case sensitivity
2. **Line 583-585**: Directory handling may incorrectly filter
3. **Lines 588-601**: Blacklist logic might be too aggressive
4. **Lines 597-601**: Filename matching issues

**Diagnostic steps:**
1. Temporarily disable `_should_process` to accept all events
2. Add logging for each check in `_should_process`
3. Verify path normalization (Windows backslash vs forward slash)
4. Check if `.git`, `.obsidian`, or other dirs are incorrectly skipped

### Phase 4: Investigate Move Processing

**Move queue issues in `watcher.py:184-848`:**

1. Verify events are being queued (`on_moved` line 543-568)
2. Verify queue is being consumed (`_process_move_queue` line 811-848)
3. Check if `_files_being_moved` blocks legitimate moves
4. Verify debounce delay (2 seconds) isn't too long

### Phase 5: Test Different File Operations

**Alternative test approaches:**
1. Use Python file operations instead of Git Bash commands
2. Test with Obsidian open (vs closed)
3. Test with different file sizes
4. Test in different subdirectories

### Phase 6: Fallback Solutions

**If watchdog cannot be made to work:**

1. **Increase orphan cleanup frequency**
   - Change from every 10 minutes to every 2 minutes
   - Change startup delay from 5 seconds to 30 seconds

2. **Implement polling-based watcher**
   - Poll file system every 5 seconds
   - Compare file states with last known state
   - Less efficient but more reliable

3. **Use Windows-specific APIs**
   - ReadDirectoryChangesW from Windows API
   - More robust on Windows but requires Win32 bindings

4. **Hybrid approach**
   - Keep watchdog for initial detection
   - Poll as backup if no events for extended period

## Priority Order

1. **High**: Phase 1 (Enhanced logging) - This will tell us what's happening
2. **High**: Phase 2 (Standalone test) - Isolate watchdog from server
3. **Medium**: Phase 4 (Move processing) - Investigate why moves aren't working
4. **Medium**: Phase 5 (Different operations) - Test if it's file operation method
5. **Low**: Phase 6 (Fallback) - Implement if needed
