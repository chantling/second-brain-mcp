#!/usr/bin/env python3
"""
Comprehensive move detection diagnostic test

This test will:
1. Start the MCP server with DEBUG_VERBOSE enabled
2. Perform various file operations
3. Analyze logs to determine why move events are not detected
"""

import subprocess
import time
import sys
from pathlib import Path

def run_mcp_test_with_logging():
    """Run MCP server test with verbose logging"""
    
    print("=" * 80)
    print("MOVE DETECTION DIAGNOSTIC TEST")
    print("=" * 80)
    print()
    
    # Test setup
    vault_path = Path(r"C:\Users\John\Documents\#Obisidian#\John")
    test_file = vault_path / "WATCHDOG_TEST_MOVE.md"
    target_folder = vault_path / "TestMove"
    target_folder.mkdir(exist_ok=True)
    target_file = target_folder / "WATCHDOG_TEST_MOVE.md"
    
    # Start server with verbose logging
    print("Step 1: Starting MCP server with DEBUG_VERBOSE=true...")
    print("-" * 80)
    
    # Set environment variable for verbose logging
    import os
    os.environ['DEBUG_VERBOSE'] = 'true'
    
    # Start the server in background
    server_cmd = [
        "npx", "@modelcontextprotocol/inspector", "--cli",
        "python", "-m", "server", "--method", "tools/list"
    ]
    
    print(f"Running: {' '.join(server_cmd)}")
    print()
    
    try:
        # Run server initialization
        result = subprocess.run(
            server_cmd,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=r"D:\Programs\AI\!MCPServers!\!Second_Brain!\second-brain-mcp"
        )
        
        print("Server output:")
        print(result.stdout)
        if result.stderr:
            print("Server errors:")
            print(result.stderr)
        
        # Check for observer type in output
        if "Observer type:" in result.stdout or "Observer type:" in result.stderr:
            print("✓ Observer initialization found")
        else:
            print("✗ Observer initialization NOT found - server may not have started properly")
        
        print()
        print("=" * 80)
        print("Step 2: Creating test file...")
        print("-" * 80)
        
        # Create test file
        test_file.write_text(f"# Test Move Detection\n\nCreated at: {time.ctime()}\n")
        print(f"Created: {test_file}")
        
        # Wait for events to propagate
        time.sleep(3)
        print()
        
        print("=" * 80)
        print("Step 3: Moving file using Python shutil.move()...")
        print("-" * 80)
        
        import shutil
        shutil.move(str(test_file), str(target_file))
        print(f"Moved: {test_file} -> {target_file}")
        
        # Wait for events to propagate
        time.sleep(5)
        print()
        
        print("=" * 80)
        print("Step 4: Performing modify operation on moved file...")
        print("-" * 80)
        
        target_file.write_text(f"# Test Move Detection\n\nCreated at: {time.ctime()}\n\nModified at: {time.ctime()}\n")
        print(f"Modified: {target_file}")
        
        # Wait for events to propagate
        time.sleep(3)
        print()
        
        print("=" * 80)
        print("Step 5: Deleting test file...")
        print("-" * 80)
        
        target_file.unlink()
        print(f"Deleted: {target_file}")
        
        # Wait for events to propagate
        time.sleep(3)
        print()
        
        print("=" * 80)
        print("DIAGNOSTIC SUMMARY")
        print("=" * 80)
        print()
        print("Expected events:")
        print("  1. on_created for WATCHDOG_TEST_MOVE.md")
        print("  2. on_deleted for WATCHDOG_TEST_MOVE.md (as part of move)")
        print("  3. on_created for TestMove/WATCHDOG_TEST_MOVE.md (as part of move)")
        print("  4. on_modified for TestMove/WATCHDOG_TEST_MOVE.md")
        print("  5. on_deleted for TestMove/WATCHDOG_TEST_MOVE.md")
        print()
        print("Check logs above for:")
        print("  - Observer type (should be WindowsApiObserver on Windows)")
        print("  - [RAW EVENT] tags showing events received")
        print("  - [FILTER] tags showing which events were filtered")
        print("  - [CREATE], [DELETE], [MOVE] tags showing event processing")
        print()
        print("If events are NOT being received:")
        print("  - Check if observer is alive")
        print("  - Check if watch path is correct")
        print("  - Check if file is in blacklisted paths")
        print()
        print("If events ARE being received but not processed:")
        print("  - Check _should_process filter results")
        print("  - Check move detection correlation logic")
        
    except subprocess.TimeoutExpired:
        print("ERROR: Server timed out during initialization")
        return False
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print()
    print("=" * 80)
    print("Test complete. Check logs above for diagnostic information.")
    print("=" * 80)
    
    return True

if __name__ == "__main__":
    success = run_mcp_test_with_logging()
    sys.exit(0 if success else 1)
