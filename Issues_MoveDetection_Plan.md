# Move Detection Diagnostic and Fix Plan

## Problem Summary
Server watcher receives NO move events while standalone watchdog test receives them correctly. The WindowsApiObserver in standalone test detects 30 events including moves (detected as delete+create pattern on Windows).

## Diagnostic Plan

### Phase 1: Verify Observer Configuration
1. Check observer type in server watcher
2. Confirm WindowsApiObserver is being used
3. Compare observer settings between standalone test and server

### Phase 2: Add Synchronized Logging
1. Add identical logging patterns to both server and standalone test
2. Log event types as soon as they're received
3. Log all event attributes (src_path, dest_path, event_type, is_directory)

### Phase 3: Check Filter Chain
1. Add logging before and after each filter in _should_process
2. Verify move events aren't being filtered out by extension or path checks
3. Check if the move is happening within the same watched directory

### Phase 4: Verify Move Processor Startup
1. Add logging to confirm move processor task starts
2. Check if the move queue is being initialized correctly
3. Verify the task is running in the background

### Phase 5: Test File Operations
1. Test move using different methods (Windows Explorer, Python shutil.move, git mv)
2. Test moves within same directory vs across directories
3. Test moves of files with different extensions

### Phase 6: Minimal Reproduction
1. Create minimal server watcher matching standalone test
2. Gradually add server features one by one
3. Identify which feature breaks move detection

## Implementation Plan

### Step 1: Enhanced Logging in watcher.py
- Add observer backend type logging at startup
- Log ALL events received at the handler level (before any filtering)
- Log move queue processor status
- Add logging to move processor task creation

### Step 2: Add Debug Mode for Events
- Create DEBUG_EVENT_LOGGING flag
- When enabled, log every event with full details
- Include event type, paths, timestamps

### Step 3: Verify Event Handler Registration
- Ensure all handlers are properly registered with observer
- Check if move handler is attached
- Verify event dispatch is working

### Step 4: Check Threading/Async Issues
- Ensure observer thread is running
- Check if asyncio event loop is interfering
- Verify background tasks are starting correctly

### Step 5: Fix Identified Issues
- Based on diagnostics, implement appropriate fixes
- Common fixes may include:
  - Changing observer backend
  - Adjusting event filtering
  - Fixing async/task issues
  - Changing move detection strategy

## Testing Plan

1. Run enhanced logging version
2. Perform move operation
3. Check logs for:
   - Observer type
   - Event reception at handler level
   - Filter results
   - Move processor status
4. Compare with standalone test logs
5. Implement fixes based on findings
6. Retest until moves are detected

## Success Criteria
- Move events are received by server watcher
- Move queue processor processes moves correctly
- Test 5 (move operation) passes
- All 7 required tests pass
