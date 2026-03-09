#!/usr/bin/env python3
"""
Direct observer backend test

This test will check what observer backend is being used
and verify if it receives file system events correctly
"""

import sys
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent
import time

class DebugEventHandler(FileSystemEventHandler):
    """Event handler with detailed logging"""

    def __init__(self, name):
        self.name = name
        self.events_received = []

    def on_created(self, event):
        event_type = "DIR_CREATED" if event.is_directory else "FILE_CREATED"
        path = str(event.src_path)
        self.events_received.append((event_type, path, time.time()))
        print(f"[{self.name}] {event_type}: {path}")

    def on_deleted(self, event):
        event_type = "DIR_DELETED" if event.is_directory else "FILE_DELETED"
        path = str(event.src_path)
        self.events_received.append((event_type, path, time.time()))
        print(f"[{self.name}] {event_type}: {path}")

    def on_modified(self, event):
        if not event.is_directory:  # Only log file modifications, not directory
            event_type = "FILE_MODIFIED"
            path = str(event.src_path)
            self.events_received.append((event_type, path, time.time()))
            print(f"[{self.name}] {event_type}: {path}")

    def on_moved(self, event):
        event_type = "DIR_MOVED" if event.is_directory else "FILE_MOVED"
        src_path = str(event.src_path)
        dest_path = str(event.dest_path) if event.dest_path else ""
        self.events_received.append((event_type, f"{src_path} -> {dest_path}", time.time()))
        print(f"[{self.name}] {event_type}: {src_path} -> {dest_path}")

def test_observer_backend(backend_name="default"):
    """Test observer backend with real file operations"""

    print("=" * 80)
    print(f"OBSERVER BACKEND TEST: {backend_name.upper()}")
    print("=" * 80)
    print()

    # Setup
    vault_path = Path(r"C:\Users\John\Documents\#Obisidian#\John")
    test_folder = vault_path / "TestObserver"
    test_folder.mkdir(exist_ok=True)
    test_file = test_folder / "TEST_OBSERVER.md"
    test_file2 = test_folder / "TEST_OBSERVER_RENAMED.md"

    # Clean up any existing test files
    if test_file.exists():
        test_file.unlink()
    if test_file2.exists():
        test_file2.unlink()

    print(f"Test path: {test_folder}")
    print()

    # Create observer
    print(f"Creating Observer...")
    observer = Observer()

    # Check observer backend
    print(f"Observer type: {type(observer).__name__}")
    print(f"Observer module: {type(observer).__module__}")

    # Check for emitter
    if hasattr(observer, '_emitter'):
        print(f"Emitter type: {type(observer._emitter).__name__}")
        print(f"Emitter module: {type(observer._emitter).__module__}")

    # Check for specific backend methods
    if hasattr(observer, 'on_thread_start'):
        print("Has on_thread_start method")
    if hasattr(observer, 'on_thread_stop'):
        print("Has on_thread_stop method")

    print()

    # Create event handler
    handler = DebugEventHandler(backend_name)

    # Schedule watch
    print(f"Scheduling watch on: {test_folder}")
    observer.schedule(handler, str(test_folder), recursive=True)

    # Start observer
    print(f"Starting observer...")
    observer.start()
    print(f"Observer is alive: {observer.is_alive()}")
    print()

    # Give observer time to start
    time.sleep(2)

    print("=" * 80)
    print("PERFORMING FILE OPERATIONS")
    print("=" * 80)
    print()

    # Test 1: Create file
    print("[TEST 1] Creating file...")
    test_file.write_text(f"# Test Observer Backend\n\nBackend: {backend_name}\n")
    time.sleep(2)
    print()

    # Test 2: Modify file
    print("[TEST 2] Modifying file...")
    test_file.write_text(f"# Test Observer Backend\n\nBackend: {backend_name}\n\nModified: {time.ctime()}\n")
    time.sleep(2)
    print()

    # Test 3: Move file (rename)
    print("[TEST 3] Moving file (rename)...")
    import shutil
    shutil.move(str(test_file), str(test_file2))
    time.sleep(3)
    print()

    # Test 4: Delete file
    print("[TEST 4] Deleting file...")
    test_file2.unlink()
    time.sleep(2)
    print()

    # Stop observer
    print("Stopping observer...")
    observer.stop()
    observer.join()
    print()

    # Print summary
    print("=" * 80)
    print("EVENT SUMMARY")
    print("=" * 80)
    print()
    print(f"Total events received: {len(handler.events_received)}")
    print()

    for i, (event_type, path, timestamp) in enumerate(handler.events_received, 1):
        print(f"{i}. [{event_type}] {path}")
    print()

    # Analyze results
    print("=" * 80)
    print("ANALYSIS")
    print("=" * 80)
    print()

    event_types = [e[0] for e in handler.events_received]

    print("Expected events:")
    print("  1. FILE_CREATED")
    print("  2. FILE_MODIFIED")
    print("  3. FILE_DELETED and FILE_CREATED (for move on Windows) OR FILE_MOVED (on other systems)")
    print("  4. FILE_DELETED")
    print()

    print("Received events:")
    for event_type in event_types:
        print(f"  - {event_type}")
    print()

    # Check if move was detected correctly
    has_file_deleted = "FILE_DELETED" in event_types
    has_file_created = "FILE_CREATED" in event_types
    has_file_moved = "FILE_MOVED" in event_types

    if has_file_moved:
        print("✓ Move detected via FILE_MOVED event (Unix/Mac behavior)")
    elif has_file_deleted and has_file_created:
        print("✓ Move detected via FILE_DELETED + FILE_CREATED pattern (Windows behavior)")
    else:
        print("✗ Move NOT detected - missing events")

    print()
    return handler.events_received

if __name__ == "__main__":
    print()
    events = test_observer_backend()
    print()
    print("=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)
