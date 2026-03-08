"""
Manually trigger initial sync of all existing notes in vault.
Run this script when watcher doesn't sync existing files.
"""
import asyncio
import sys
from pathlib import Path
from config import Config
from obsidian import ObsidianManager
from database import DatabaseManager

async def sync_existing_notes():
    """Sync all existing markdown files to database"""
    print("Starting manual sync of existing notes...", file=sys.stderr)
    
    # Initialize managers
    db_manager = DatabaseManager()
    obsidian_manager = ObsidianManager(
        Config.OBSIDIAN_VAULT_PATH,
        db_manager=db_manager
    )
    
    # Run sync
    try:
        await obsidian_manager.sync_existing_notes_to_supabase()
        print("✓ Sync completed!", file=sys.stderr)
    except Exception as e:
        print(f"✗ Sync failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(sync_existing_notes())
