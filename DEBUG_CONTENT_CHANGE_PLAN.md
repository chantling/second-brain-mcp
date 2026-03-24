# Content Change Detection Debug Plan

## Problem Analysis

### Root Cause Identification

**Issue**: File content changes are not being synced to the database when the server is shut down before the debounce delay completes.

**Test 6 Analysis**:
1. File edited: `!To-Do!\AUTOTEST01.md` content changed from "elephants" to "dandelions"
2. Server started with initial sync running
3. on_modified event detected at `11:01:29.666`
4. Debounce scheduled at `11:01:41.136` with 2-second delay
5. Debounce started at `11:01:43.140`
6. Server shutdown occurred before delay completed at `11:01:45.xxx`

**Conclusion**: The `_handle_modify` never executed because the server shut down during the 2-second debounce delay. The content change was lost.

### Current Flow Analysis

```
on_modified → _debounce_event (2s delay) → _process_event_after_delay → _handle_modify
```

**Problem Points**:
1. No shutdown hook to complete pending debounce tasks
2. 2-second delay makes shutdown vulnerable
3. No verification that pending changes were synced before shutdown

## Implementation Plan

### Phase 1: Add Shutdown Hook (HIGH PRIORITY)

**Objective**: Ensure all pending debounce tasks complete before shutdown

**Implementation**:

1. Create shutdown handler in `watcher.py`:
```python
async def _await_pending_tasks(self):
    """Wait for all pending debounce tasks to complete before shutdown"""
    if not self._debounce_queue:
        return
    
    pending_tasks = []
    for file_path, event_data in self._debounce_queue.items():
        task = event_data.get("task")
        if task and not task.done():
            pending_tasks.append(task)
    
    if pending_tasks:
        print(f"[SHUTDOWN] Waiting for {len(pending_tasks)} pending tasks to complete...", file=sys.stderr)
        # Wait up to 5 seconds for tasks to complete
        try:
            await asyncio.wait_for(
                asyncio.gather(*[asyncio.wrap_future(t) for t in pending_tasks], return_exceptions=True),
                timeout=5.0
            )
            print(f"[SHUTDOWN] All pending tasks completed", file=sys.stderr)
        except asyncio.TimeoutError:
            print(f"[SHUTDOWN] Timeout waiting for tasks, {len([t for t in pending_tasks if not t.done()])} tasks incomplete", file=sys.stderr)
```

2. Modify `server.py` shutdown sequence:
```python
async def _cleanup_tasks(self):
    """Clean up tasks before shutdown"""
    from watcher import get_file_watcher
    watcher = get_file_watcher()
    if watcher:
        await watcher._await_pending_tasks()
```

3. Add signal handler:
```python
async def _shutdown_handler(self, signum, frame):
    """Handle shutdown signals"""
    global shutdown_requested
    if shutdown_requested:
        return
    shutdown_requested = True
    
    print(f"\nReceived signal {signum}, waiting for pending tasks...", file=sys.stderr)
    
    # Wait for pending tasks
    await self._cleanup_tasks()
    
    # Original shutdown logic
    if _file_watcher_observer:
        _file_watcher_observer.stop()
```

### Phase 2: Reduce Debounce Delay (MEDIUM PRIORITY)

**Objective**: Reduce window for shutdown vulnerability

**Implementation**:

1. Change debounce delay from 2.0s to 1.0s in `config.py`:
```python
SYNC_DEBOUNCE_SECONDS: float = 1.0  # Reduced from 2.0s
```

2. Update environment variable documentation

### Phase 3: Add Content Change Verification (MEDIUM PRIORITY)

**Objective**: Verify content sync on startup and shutdown

**Implementation**:

1. Add verification function in `obsidian.py`:
```python
async def verify_file_sync_status(self):
    """Verify that all files are in sync with database"""
    markdown_files = list(self.vault_path.rglob("*.md"))
    out_of_sync = []
    
    for md_file in markdown_files:
        rel_path = str(md_file.relative_to(self.vault_path))
        
        # Skip special files
        if any(skip in rel_path for skip in [".obsidian", "!Folder_Embeddings.md", ".trash"]):
            continue
        
        content = md_file.read_text(encoding="utf-8")
        file_hash = self._compute_hash(content)
        
        # Check if file has supabase_id
        metadata = self._extract_frontmatter(content, rel_path)
        if not metadata or not metadata.get("supabase_id"):
            continue
        
        supabase_id = metadata["supabase_id"]
        
        # Get database entry
        if self.db_manager:
            db_entry = await self.db_manager.get_thought(supabase_id)
            if not db_entry:
                continue
            
            # Compare hashes
            if db_entry.get("file_hash") != file_hash:
                out_of_sync.append({
                    "path": rel_path,
                    "file_hash": file_hash,
                    "db_hash": db_entry.get("file_hash")
                })
                print(f"[VERIFY] Out of sync: {rel_path}", file=sys.stderr)
    
    return out_of_sync
```

2. Run verification on startup:
```python
# In server.py main()
out_of_sync = await obsidian_manager.verify_file_sync_status()
if out_of_sync:
    print(f"[STARTUP] Found {len(out_of_sync)} out-of-sync files, will sync them", file=sys.stderr)
    # Sync each out-of-sync file
    for item in out_of_sync:
        obsidian_manager._handle_sync_file(item["path"])
```

### Phase 4: Add Comprehensive Logging (LOW PRIORITY)

**Objective**: Track all file operations for debugging

**Implementation**:

1. Add detailed logging to `_handle_modify`:
```python
async def _handle_modify(self, file_path: str):
    """Handle note modification in Obsidian"""
    try:
        # ... existing code ...
        
        # NEW: Log entry point
        _log(f"[MODIFY] === ENTRY POINT === {obsidian_path}", "MODIFY")
        
        # Log file state
        print(f"[MODIFY] File exists: {Path(file_path).exists()}", file=sys.stderr)
        print(f"[MODIFY] File size: {Path(file_path).stat().st_size if Path(file_path).exists() else 0}", file=sys.stderr)
        
        # Log database state before
        if metadata and metadata.get("supabase_id"):
            db_entry = await db_manager.get_thought(metadata["supabase_id"])
            if db_entry:
                print(f"[MODIFY] DB entry exists, hash: {db_entry.get('file_hash')}", file=sys.stderr)
        
        # ... rest of handler ...
        
        # NEW: Log exit point
        print(f"[MODIFY] === EXIT POINT === {obsidian_path}", "=file=sys.stderr)
```

2. Add logging to shutdown sequence:
```python
async def _cleanup_tasks(self):
    """Clean up tasks before shutdown"""
    print("[SHUTDOWN] Starting task cleanup", file=sys.stderr)
    # ... cleanup logic ...
    print("[SHUTDOWN] Task cleanup complete", file=sys.stderr)
```

## Testing Strategy

### Test 6 Redo

1. Modify AUTOTEST01.md content
2. Start server with 90-second timeout
3. Verify:
   - Database content updated
   - Frontmatter unchanged
   - Logs show modify handler completed

### Test 7: Rapid Shutdown

1. Modify AUTOTEST01.md content
2. Start server
3. Wait 1 second
4. Shutdown server (Ctrl+C)
5. Verify:
   - Pending tasks logged
   - Content eventually synced
   - No error messages

### Test 8: Multiple Rapid Changes

1. Modify AUTOTEST01.md 3 times rapidly
2. Start server
3. Wait 10 seconds
4. Verify:
   - Only final content in database
   - Debounce correctly handled multiple events
   - No duplicate entries

## Success Criteria

1. **Immediate**: All pending debounce tasks complete before shutdown
2. **Immediate**: Server logs show pending tasks being awaited
3. **Short-term**: Content changes detected and synced within 2 seconds of edit
4. **Medium-term**: Startup verification catches any out-of-sync files
5. **Long-term**: Comprehensive logging enables future debugging

## Risk Assessment

| Fix | Risk | Mitigation |
|-----|-------|------------|
| Shutdown hook | May delay shutdown | 5-second timeout prevents indefinite wait |
| Reduce debounce | More rapid events processed | 1.0s still provides good debouncing |
| Verification | May slow startup | Only runs on startup, minimal impact |
| Logging | Log bloat | Add DEBUG flag to disable verbose logs |

## Implementation Order

1. **Phase 1**: Add shutdown hook (highest priority, fixes immediate issue)
2. **Phase 2**: Reduce debounce (quick win, reduces vulnerability)
3. **Phase 3**: Add verification (safety net, catches missed changes)
4. **Phase 4**: Add logging (improves debuggability)
