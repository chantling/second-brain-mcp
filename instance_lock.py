"""
Instance lock management using OS-level file locking (portalocker).
Handles multi-instance coordination with heartbeat and stale lock detection.
"""

import os
import sys
import json
import uuid
import portalocker
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from config import Config


# Helper function for debug logging
def debug_log(msg: str):
    """Print debug message if DEBUG is enabled"""
    if Config.DEBUG:
        print(msg, file=sys.stderr)


class InstanceLock:
    """
    Manages cross-platform file locking for multi-instance coordination.
    
    Lock file location is determined using os.path.abspath(__file__) to ensure
    the lock file is always in the same directory as the running script,
    regardless of where server.py is called from.
    """
    def __init__(self, config):
        """Initialize instance lock manager with configuration.
        
        Determines lock file location based on script directory to ensure consistent
        path resolution. Generates unique instance ID, stores start time,
        and sets stale threshold from config. Prepares for lock acquisition
        and heartbeat monitoring.
        
        Args:
            config: Config object with lock configuration including threshold and file settings
        """

        # Use directory of this file (instance_lock.py) for lock file location
        # This ensures lock file is always next to instance_lock.py, regardless of
        # where server.py is called from.
        # os.path.abspath(__file__) gives the actual running script's absolute path
        # Path(...).parent places it in the same directory as this file
        # Example: if instance_lock.py is at /path/to/second-brain-mcp/instance_lock.py
        #          then lock file is at /path/to/second-brain-mcp/.server_lock
        #          even if server.py is called from /different/path/
        #
        # Config.LOCK_FILE_NAME provides the lock file name (default: .server_lock)
        # Users can override via LOCK_FILE_PATH env var if needed
        self.lock_file_path = Path(os.path.dirname(os.path.abspath(__file__))) / Config.LOCK_FILE_NAME
        self.lock_file = None
        self.stale_threshold = timedelta(seconds=config.LOCK_STALE_THRESHOLD_SECONDS)
        self.instance_id = str(uuid.uuid4())
        self.start_time = datetime.now()

    def acquire_lock(self) -> bool:
        """Acquire the instance lock (blocking attempt)

        Raises:
            portalocker.LockException: If lock is already held by another instance

        Returns:
            True if lock acquired successfully
        """
        # Ensure parent directory exists
        self.lock_file_path.parent.mkdir(parents=True, exist_ok=True)

        # Open lock file - use "a+" (append) to avoid truncating if file exists
        # This is crucial for Windows where "w+" could interfere with existing locks
        try:
            self.lock_file = open(self.lock_file_path, "a+b")
        except IOError:
            # If append mode fails, try creating fresh
            self.lock_file = open(self.lock_file_path, "w+b")

        try:
            # Try to acquire exclusive, non-blocking lock
            portalocker.lock(self.lock_file, portalocker.LOCK_EX | portalocker.LOCK_NB)

            # Clear file and write lock metadata
            self.lock_file.seek(0)
            self.lock_file.truncate()

            lock_data = {
                "pid": os.getpid(),
                "start_time": self.start_time.isoformat(),
                "last_heartbeat": self.start_time.isoformat(),
                "instance_id": self.instance_id,
                "status": "active",
            }

            lock_json = json.dumps(lock_data).encode('utf-8')
            self.lock_file.write(lock_json)
            self.lock_file.flush()

            return True

        except portalocker.LockException:
            self.lock_file.close()
            self.lock_file = None
            raise

    def acquire_lock_nonblocking(self) -> bool:
        """Try to acquire lock without blocking

        Returns:
            True if lock acquired, False if already held
        """
        try:
            self.acquire_lock()
            return True
        except portalocker.LockException:
            return False

    def release_lock(self):
        """Release the instance lock"""
        if self.lock_file:
            try:
                portalocker.unlock(self.lock_file)
                self.lock_file.close()

                # Remove lock file
                if self.lock_file_path.exists():
                    self.lock_file_path.unlink()

            except Exception as e:
                print(f"[LOCK] Error releasing lock: {e}", file=sys.stderr)
            finally:
                self.lock_file = None

    def is_locked(self) -> bool:
        """Check if lock is currently held (non-blocking)

        Returns:
            True if lock is held, False otherwise
        """
        try:
            if not self.lock_file_path.exists():
                return False

            # Try to open and lock (use binary mode for consistency)
            with open(self.lock_file_path, "rb") as f:
                portalocker.lock(f, portalocker.LOCK_EX | portalocker.LOCK_NB)
                portalocker.unlock(f)

            return False

        except portalocker.LockException:
            # Lock is held by another process
            return True
        except (IOError, OSError):
            # File might not be readable yet
            return False

    def get_lock_info(self) -> Optional[Dict]:
        """Read lock file metadata

        Returns:
            Lock data dict if file exists and is valid, None otherwise
        """
        try:
            if not self.lock_file_path.exists():
                return None

            with open(self.lock_file_path, "rb") as f:
                return json.loads(f.read().decode('utf-8'))

        except (json.JSONDecodeError, IOError, UnicodeDecodeError) as e:
            #print(f"[LOCK] Error reading lock file: {e}", file=sys.stderr)
            return None

    def update_heartbeat(self):
        """Update heartbeat timestamp in lock file"""
        if not self.lock_file:
            return

        try:
            # Move to beginning of file
            self.lock_file.seek(0)

            # Read existing data (binary mode)
            lock_data = json.loads(self.lock_file.read().decode('utf-8'))

            # Update heartbeat
            lock_data["last_heartbeat"] = datetime.now().isoformat()

            # Write back
            self.lock_file.seek(0)
            self.lock_file.truncate()
            lock_json = json.dumps(lock_data).encode('utf-8')
            self.lock_file.write(lock_json)
            self.lock_file.flush()

        except Exception as e:
            print(f"[LOCK] Error updating heartbeat: {e}", file=sys.stderr)

    def is_lock_stale(self) -> Tuple[bool, Optional[datetime]]:
        """Check if lock is stale (heartbeat too old)

        Returns:
            Tuple of (is_stale, last_heartbeat_time)
        """
        lock_info = self.get_lock_info()

        if not lock_info:
            return False, None

        try:
            last_heartbeat = datetime.fromisoformat(lock_info["last_heartbeat"])
            age = datetime.now() - last_heartbeat

            return age > self.stale_threshold, last_heartbeat

        except (KeyError, ValueError) as e:
            print(f"[LOCK] Error checking lock staleness: {e}", file=sys.stderr)
            return False, None

    def cleanup_stale_lock(self) -> bool:
        """Attempt to clean up a stale lock file

        Returns:
            True if successfully cleaned up, False otherwise
        """
        try:
            is_stale, last_heartbeat = self.is_lock_stale()

            if is_stale:
                debug_log(
                    f"[LOCK] Found stale lock (last heartbeat: {last_heartbeat}), attempting cleanup..."
                )

                # Try to acquire lock (will succeed if stale holder is gone)
                if self.acquire_lock_nonblocking():
                    debug_log("[LOCK] Successfully cleaned up stale lock")
                    return True
                else:
                    debug_log(
                        "[LOCK] Could not acquire lock (may still be held)"
                    )
                    return False
            else:
                return False

        except Exception as e:
            print(f"[LOCK] Error cleaning up stale lock: {e}", file=sys.stderr)
            return False
