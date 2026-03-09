"""
Standalone Watchdog Test Script
Tests if watchdog events are being received in this environment
"""
import sys
import time
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


class TestHandler(FileSystemEventHandler):
    """Test handler that logs ALL events"""
    
    def __init__(self):
        super().__init__()
        self.event_count = 0
        self.events_by_type = {}
    
    def on_any_event(self, event):
        """Log all events"""
        print(f"[RAW EVENT] {event.event_type}: {event.src_path} (dir={event.is_directory})", file=sys.stderr)
        self.event_count += 1
        
        event_type = event.event_type
        if event_type not in self.events_by_type:
            self.events_by_type[event_type] = 0
        self.events_by_type[event_type] += 1
    
    def on_moved(self, event):
        """Log move events"""
        dest_path = event.dest_path if hasattr(event, 'dest_path') else "N/A"
        print(f"[MOVED] {event.src_path} -> {dest_path}", file=sys.stderr)
        self.event_count += 1
    
    def on_modified(self, event):
        """Log modify events"""
        print(f"[MODIFIED] {event.src_path}", file=sys.stderr)
        self.event_count += 1
    
    def on_deleted(self, event):
        """Log delete events"""
        print(f"[DELETED] {event.src_path}", file=sys.stderr)
        self.event_count += 1


def main():
    # Get vault path from command line or use default
    if len(sys.argv) > 1:
        vault_path = sys.argv[1]
    else:
        vault_path = r"C:\Users\John\Documents\#Obisidian#\John"
    
    vault_path = Path(vault_path)
    
    print("=" * 80, file=sys.stderr)
    print("Watchdog Standalone Test", file=sys.stderr)
    print("=" * 80, file=sys.stderr)
    print(f"[TEST] Vault path: {vault_path}", file=sys.stderr)
    print(f"[TEST] Vault exists: {vault_path.exists()}", file=sys.stderr)
    print(f"[TEST] Observer type will be: Observer", file=sys.stderr)
    print("=" * 80, file=sys.stderr)
    
    event_handler = TestHandler()
    observer = Observer()
    
    print(f"[TEST] Observer type: {type(observer).__name__}", file=sys.stderr)
    
    try:
        observer.schedule(event_handler, str(vault_path), recursive=True)
        observer.start()
        
        print(f"[TEST] Observer started: {observer.is_alive()}", file=sys.stderr)
        print("[TEST] Waiting 2 seconds before test operations...", file=sys.stderr)
        time.sleep(2)
        
        # Perform test operations
        print("\n" + "=" * 80, file=sys.stderr)
        print("Starting Test Operations", file=sys.stderr)
        print("=" * 80 + "\n", file=sys.stderr)
        
        # Test 1: Create
        test_file = vault_path / "WATCHDOG_TEST.md"
        print(f"[TEST 1] Creating: {test_file}", file=sys.stderr)
        test_file.write_text("Initial content\n")
        time.sleep(2)
        
        # Test 2: Modify
        print(f"[TEST 2] Modifying: {test_file}", file=sys.stderr)
        test_file.write_text("Modified content\n")
        time.sleep(2)
        
        # Test 3: Move
        todo_folder = vault_path / "-To-Do-"
        if not todo_folder.exists():
            todo_folder.mkdir(exist_ok=True)
        moved_file = todo_folder / "WATCHDOG_TEST.md"
        print(f"[TEST 3] Moving: {test_file} -> {moved_file}", file=sys.stderr)
        test_file.rename(moved_file)
        time.sleep(2)
        
        # Test 4: Delete
        print(f"[TEST 4] Deleting: {moved_file}", file=sys.stderr)
        moved_file.unlink()
        time.sleep(2)
        
        print("\n" + "=" * 80, file=sys.stderr)
        print("Test Operations Complete", file=sys.stderr)
        print("=" * 80, file=sys.stderr)
        
        # Wait for any delayed events
        print("[TEST] Waiting 2 more seconds for delayed events...", file=sys.stderr)
        time.sleep(2)
        
        # Print summary
        print("\n" + "=" * 80, file=sys.stderr)
        print("Test Summary", file=sys.stderr)
        print("=" * 80, file=sys.stderr)
        print(f"[SUMMARY] Total events received: {event_handler.event_count}", file=sys.stderr)
        print("[SUMMARY] Events by type:", file=sys.stderr)
        for event_type, count in event_handler.events_by_type.items():
            print(f"  - {event_type}: {count}", file=sys.stderr)
        print("=" * 80, file=sys.stderr)
        
        # Expected events:
        # 1. Created event for WATCHDOG_TEST.md
        # 2. Modified event (multiple)
        # 3. Moved event (may also get create/delete)
        # 4. Deleted event
        
        expected_min = 4  # At minimum: create, modify, move, delete
        if event_handler.event_count >= expected_min:
            print(f"[SUCCESS] Watchdog is working! Received {event_handler.event_count} events", file=sys.stderr)
            return 0
        else:
            print(f"[FAILURE] Watchdog not working properly! Expected at least {expected_min} events, got {event_handler.event_count}", file=sys.stderr)
            return 1
            
    except KeyboardInterrupt:
        print("\n[TEST] Interrupted by user", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"[ERROR] Test failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 3
    finally:
        observer.stop()
        observer.join()
        print("[TEST] Observer stopped", file=sys.stderr)


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
