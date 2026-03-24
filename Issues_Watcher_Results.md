# Watcher Testing Results & Diagnostics

## Summary of Issues Found

### Root Cause Identified: Orphan Cleanup Timing Issue

**Primary Issue**: Orphan cleanup on startup was running after only 5 seconds, which was NOT enough time for the initial sync to complete.

**Sequence of Events:**
1. Server starts
2. Initial sync begins processing files (async, takes ~15-20 seconds)
3. Orphan cleanup runs after 5 seconds
4. Orphan cleanup deletes newly created entries because they haven't been fully stored yet
5. Watcher events arrive but entries no longer exist
6. New entries created by watcher instead of updating existing ones

### Test Results with 60s Orphan Cleanup Delay

After increasing orphan cleanup delay from 5 seconds to 60 seconds:

**✅ Test 6 PASSED**: File content changes detected
- AUTOTEST02.md modified from "hyenas" to "dandelions"
- Watcher detected modify event
- Database content was updated correctly

**✅ Test 7 PASSED**: File deletion detected  
- AUTOTEST01.md in !To-Do! folder was deleted
- Orphan cleanup removed entry correctly

**❌ Test 5 FAILED**: File move detection
- AUTOTEST01.md moved from vault root to !To-Do! folder
- Database obsidian_path NOT updated
- Move events not received by watcher

### Diagnostics Summary

**Stand-Alone Watchdog Test**: ✅ PASSED
- WindowsApiObserver working correctly
- Received 30 events (created, modified, deleted)
- Move detected as delete + create events (Windows behavior)

**Server Watcher with Enhanced Logging**:
- Events ARE being received ✅
- Events ARE passing _should_process ✅
- Events ARE being debounced ✅
- Events ARE being queued for processing ✅
- Modify handler IS being called ✅

**Critical Discovery**: The watcher IS WORKING!

The initial failures were due to:
1. Race condition between initial sync and orphan cleanup (5s delay too short)
2. Not waiting long enough for watcher events to process

### Issues Found

1. **Orphan Cleanup Too Aggressive** (FIXED)
   - Was running at 5 seconds
   - Changed to 60 seconds to allow initial sync to complete

2. **Move Events Not Detected** (STILL INVESTIGATING)
   - Standalone test shows moves work (as delete+create)
   - Server watcher not receiving move events
   - May be related to:
     - Observer configuration issue
     - Event filtering in on_moved handler
     - Move queue processing issue

3. **Move Queue Not Receiving Events**
   - Move queue processor started
   - But no events logged in queue
   - on_moved handler may not be queuing events

### Files Modified

**watcher.py**:
- Added extensive logging to all event handlers (on_created, on_modified, on_deleted, on_moved)
- Added detailed _should_process logging
- Added move queue size logging
- Added observer heartbeat check

**server.py**:
- Increased orphan cleanup delay from 5s to 60s
- Added heartbeat task to verify observer alive
- Fixed task cleanup on shutdown

### Next Steps

**Priority 1**: Investigate why move events aren't being received
- Check if on_moved is being called
- Verify move events are being queued
- Check if there's an issue with the move queue processor

**Priority 2**: Test with more file operations
- Test create operations (should work now with 60s delay)
- Test delete operations (should work now)
- Test modify operations (confirmed working)

**Priority 3**: Consider fallback if move detection continues to fail
- Implement polling-based move detection
- Use Windows-specific APIs if needed
