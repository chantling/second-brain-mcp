#!/usr/bin/env python3
"""
Test server watcher with proper async setup

This test will:
1. Set up the event loop properly
2. Start the server watcher
3. Perform file operations
4. Check which events are received
"""

import asyncio
import sys
from pathlib import Path
from watcher import ObsidianEventHandler, start_file_watcher
from config import Config

async def test_server_watcher():
    """Test server watcher with proper async setup"""
    
    print("=" * 80)
    print("SERVER WATCHER TEST WITH ASYNC SETUP")
    print("=" * 80)
    print()
    
    # Setup
    vault_path = Path(r"C:\Users\John\Documents\#Obisidian#\John")
    test_folder = vault_path / "TestServerWatcher"
    test_folder.mkdir(exist_ok=True)
    
    test_file = test_folder / "TEST_SERVER.md"
    test_file_renamed = test_folder / "TEST_SERVER_RENAMED.md"
    
    # Clean up
    if test_file.exists():
        test_file.unlink()
    if test_file_renamed.exists():
        test_file_renamed.unlink()
    
    print(f"Test path: {test_folder}")
    print()
    
    # Start watcher with proper event loop
    print("Starting file watcher...")
    event_loop = asyncio.get_event_loop()
    observer, cleanup_task, move_processor_task, heartbeat_task, deferred_move_task = start_file_watcher(vault_path, event_loop)
    
    print(f"Observer type: {type(observer).__name__}")
    print(f"Observer is alive: {observer.is_alive()}")
    print()
    
    # Give watcher time to start
    await asyncio.sleep(3)
    
    print("=" * 80)
    print("PERFORMING FILE OPERATIONS")
    print("=" * 80)
    print()
    
    # Test 1: Create file
    print("[TEST 1] Creating file...")
    test_file.write_text(f"# Test Server Watcher\n\nCreated: {asyncio.get_event_loop().time()}\n")
    await asyncio.sleep(3)
    print()
    
    # Test 2: Modify file
    print("[TEST 2] Modifying file...")
    test_file.write_text(f"# Test Server Watcher\n\nCreated: {asyncio.get_event_loop().time()}\n\nModified\n")
    await asyncio.sleep(3)
    print()
    
    # Test 3: Move file (rename)
    print("[TEST 3] Moving file (rename)...")
    import shutil
    shutil.move(str(test_file), str(test_file_renamed))
    print(f"Moved: {test_file} -> {test_file_renamed}")
    await asyncio.sleep(5)
    print()
    
    # Test 4: Delete file
    print("[TEST 4] Deleting file...")
    test_file_renamed.unlink()
    await asyncio.sleep(3)
    print()
    
    # Stop watcher
    print("Stopping watcher...")
    observer.stop()
    observer.join()
    
    # Cancel tasks
    cleanup_task.cancel()
    move_processor_task.cancel()
    heartbeat_task.cancel()
    deferred_move_task.cancel()
    
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    
    try:
        await move_processor_task
    except asyncio.CancelledError:
        pass
    
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass
    
    try:
        await deferred_move_task
    except asyncio.CancelledError:
        pass
    
    print()
    print("=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)
    print()
    print("Check logs above for:")
    print("  - [RAW EVENT] tags showing events received")
    print("  - [FILTER] tags showing which events were filtered")
    print("  - [CREATE], [DELETE], [MOVE] tags showing event processing")
    print()
    print("Expected events:")
    print("  1. on_created for TEST_SERVER.md")
    print("  2. on_modified for TEST_SERVER.md")
    print("  3. on_moved OR (on_deleted + on_created) for move operation")
    print("  4. on_deleted for TEST_SERVER_RENAMED.md")

if __name__ == "__main__":
    print()
    asyncio.run(test_server_watcher())
    print()
