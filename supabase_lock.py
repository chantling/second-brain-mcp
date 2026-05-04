"""
Distributed lock for cross-instance coordination via Supabase.

Uses TTL-based per-operation locking on a singleton row in the server_lock
table. PostgreSQL row-level locking ensures only one instance can acquire
the lock at a time. TTL auto-expires to prevent deadlocks from crashed instances.
"""

import os
import sys
import uuid
import asyncio
import socket
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import Config


class SupabaseLock:
    """Supabase-based distributed lock with TTL and automatic renewal.

    All instances share the same server_lock table (singleton row, id=1).
    Lock acquisition is atomic via PostgreSQL row-level locking on UPDATE.
    TTL prevents permanent lockout from crashed instances.
    """

    def __init__(self, supabase_client):
        """Initialize lock manager.

        Args:
            supabase_client: Initialized Supabase client instance
        """
        self.client = supabase_client
        self.instance_id = f"{uuid.uuid4()}"
        self.hostname = socket.gethostname()
        self.pid = os.getpid()
        self._renew_task: Optional[asyncio.Task] = None

    async def acquire(self, operation: str, ttl_seconds: int = None) -> bool:
        """Attempt to acquire the lock.

        Atomically updates the server_lock row only if:
        - The lock has expired (expires_at < now), OR
        - We already hold it (instance_id matches)

        PostgreSQL's row-level locking ensures only one UPDATE succeeds
        when multiple instances race for an expired lock.

        Args:
            operation: Description of what operation is being performed
            ttl_seconds: How long the lock is valid (default: LOCK_TTL_SECONDS)

        Returns:
            True if lock acquired, False if held by another active instance
        """
        if ttl_seconds is None:
            ttl_seconds = Config.LOCK_TTL_SECONDS

        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    self._acquire_sync, operation, ttl_seconds
                ),
                timeout=Config.DB_TIMEOUT,
            )
            return result
        except asyncio.TimeoutError:
            print(
                f"[LOCK] Lock acquire timed out after {Config.DB_TIMEOUT}s",
                file=sys.stderr,
            )
            return False
        except Exception as e:
            print(f"[LOCK] Lock acquire failed: {e}", file=sys.stderr)
            return False

    def _acquire_sync(self, operation: str, ttl_seconds: int) -> bool:
        """Synchronous lock acquisition via Supabase RPC or direct SQL.

        Uses the Supabase client to attempt an atomic UPDATE on the
        server_lock singleton row.
        """
        try:
            # Use the Supabase client's rpc to execute atomic lock acquire
            # The SQL ensures only one instance wins the race
            resp = self.client.rpc(
                "acquire_lock",
                {
                    "p_instance_id": self.instance_id,
                    "p_hostname": self.hostname,
                    "p_pid": self.pid,
                    "p_operation": operation,
                    "p_ttl_seconds": ttl_seconds,
                },
            ).execute()

            # RPC returns the updated row if successful, empty if lock held by another
            return bool(resp.data)

        except Exception:
            # Fallback: try direct table update if RPC doesn't exist yet
            # Only acquire if the lock is expired (prevents stealing from active holder)
            try:
                resp = (
                    self.client.table("server_lock")
                    .update(
                        {
                            "instance_id": self.instance_id,
                            "hostname": self.hostname,
                            "pid": self.pid,
                            "acquired_at": datetime.utcnow().isoformat(),
                            "expires_at": (
                                datetime.utcnow() + timedelta(seconds=ttl_seconds)
                            ).isoformat(),
                            "operation": operation,
                        }
                    )
                    .eq("id", 1)
                    .lt("expires_at", datetime.utcnow().isoformat())
                    .execute()
                )
                return bool(resp.data)
            except Exception as e:
                print(f"[LOCK] Lock acquire fallback failed: {e}", file=sys.stderr)
                return False

    async def release(self) -> bool:
        """Release the lock if we hold it.

        Updates the server_lock row to expired state only if instance_id
        matches ours. Safe against races: after TTL expires and another
        instance acquires, our WHERE clause no longer matches.

        Returns:
            True if lock released, False if we don't hold it or error
        """
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(self._release_sync),
                timeout=Config.DB_TIMEOUT,
            )
            return result
        except asyncio.TimeoutError:
            print(
                f"[LOCK] Lock release timed out after {Config.DB_TIMEOUT}s",
                file=sys.stderr,
            )
            return False
        except Exception as e:
            print(f"[LOCK] Lock release failed: {e}", file=sys.stderr)
            return False

    def _release_sync(self) -> bool:
        """Synchronous lock release."""
        try:
            resp = (
                self.client.table("server_lock")
                .update(
                    {
                        "instance_id": None,
                        "expires_at": "1970-01-01T00:00:00Z",
                        "operation": None,
                    }
                )
                .eq("id", 1)
                .eq("instance_id", self.instance_id)
                .execute()
            )
            return bool(resp.data)
        except Exception as e:
            print(f"[LOCK] Lock release failed: {e}", file=sys.stderr)
            return False

    def _renew_sync(self, ttl_seconds: int) -> bool:
        """Synchronous lock renewal."""
        try:
            resp = (
                self.client.table("server_lock")
                .update(
                    {
                        "expires_at": (
                            datetime.utcnow() + timedelta(seconds=ttl_seconds)
                        ).isoformat(),
                    }
                )
                .eq("id", 1)
                .eq("instance_id", self.instance_id)
                .execute()
            )
            return bool(resp.data)
        except Exception as e:
            print(f"[LOCK] Lock renew failed: {e}", file=sys.stderr)
            return False

    async def renew(self, ttl_seconds: int = None) -> bool:
        """Extend the lock's TTL while we still hold it.

        Called periodically (every LOCK_HEARTBEAT_INTERVAL seconds) while
        holding the lock to prevent it from expiring during long operations.

        Args:
            ttl_seconds: New TTL to set (default: LOCK_TTL_SECONDS)

        Returns:
            True if renewed, False if we no longer hold it
        """
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

    async def start_auto_renew(self, ttl_seconds: int = None, interval: int = None):
        """Start a background task that periodically renews the lock.

        Args:
            ttl_seconds: TTL for each renewal (default: LOCK_TTL_SECONDS)
            interval: How often to renew in seconds (default: LOCK_HEARTBEAT_INTERVAL)
        """
        if ttl_seconds is None:
            ttl_seconds = Config.LOCK_TTL_SECONDS
        if interval is None:
            interval = Config.LOCK_HEARTBEAT_INTERVAL

        async def _renew_loop():
            while True:
                try:
                    await asyncio.sleep(interval)
                    renewed = await self.renew(ttl_seconds)
                    if not renewed:
                        print(
                            "[LOCK] Auto-renew failed — lock no longer held",
                            file=sys.stderr,
                        )
                        break
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    print(f"[LOCK] Auto-renew error: {e}", file=sys.stderr)

        self._renew_task = asyncio.create_task(_renew_loop())

    async def stop_auto_renew(self):
        """Stop the auto-renew background task."""
        if self._renew_task and not self._renew_task.done():
            self._renew_task.cancel()
            try:
                await self._renew_task
            except asyncio.CancelledError:
                pass
            self._renew_task = None

    async def force_acquire(self, operation: str, ttl_seconds: int = None) -> bool:
        """Unconditionally acquire the lock, regardless of current holder.

        Used on startup to override stale locks from crashed instances.
        Bypasses the instance_id check.

        Args:
            operation: Description of operation
            ttl_seconds: TTL for the lock (default: LOCK_TTL_SECONDS)

        Returns:
            True if acquired (should always succeed unless DB error)
        """
        if ttl_seconds is None:
            ttl_seconds = Config.LOCK_TTL_SECONDS

        try:
            resp = (
                self.client.table("server_lock")
                .update(
                    {
                        "instance_id": self.instance_id,
                        "hostname": self.hostname,
                        "pid": self.pid,
                        "acquired_at": datetime.utcnow().isoformat(),
                        "expires_at": (
                            datetime.utcnow() + timedelta(seconds=ttl_seconds)
                        ).isoformat(),
                        "operation": operation,
                    }
                )
                .eq("id", 1)
                .execute()
            )
            return bool(resp.data)
        except Exception as e:
            print(f"[LOCK] Force acquire failed: {e}", file=sys.stderr)
            return False

    async def is_held(self) -> bool:
        """Check if the lock is currently held by any instance (non-blocking).

        Returns:
            True if lock is held and not expired
        """
        try:
            resp = (
                self.client.table("server_lock")
                .select("instance_id, expires_at")
                .eq("id", 1)
                .execute()
            )
            if not resp.data:
                return False

            row = resp.data[0]
            if not row.get("instance_id"):
                return False

            expires_at = datetime.fromisoformat(
                row["expires_at"].replace("Z", "+00:00")
            )
            return expires_at > datetime.now(timezone.utc)

        except Exception:
            return False

    async def get_lock_info(self) -> Optional[dict]:
        """Get current lock information for diagnostics.

        Returns:
            Dict with lock info or None if error
        """
        try:
            resp = (
                self.client.table("server_lock")
                .select("*")
                .eq("id", 1)
                .execute()
            )
            if resp.data:
                return resp.data[0]
            return None
        except Exception:
            return None
