#!/usr/bin/env python
"""
Quick verification script to check sync implementation.
"""

import sys
import asyncio
from pathlib import Path

# Add second-brain-mcp to path
sys.path.insert(0, str(Path(__file__).parent))

from config import Config


async def verify():
    """Verify configuration and modules"""
    print("=" * 50, file=sys.stderr)
    print("VERIFICATION SCRIPT", file=sys.stderr)
    print("=" * 50, file=sys.stderr)

    # Check configuration
    print("\n[1] Checking configuration...", file=sys.stderr)
    try:
        Config.validate()
        print("  ✓ Configuration is valid", file=sys.stderr)
    except Exception as e:
        print(f"  ✗ Configuration error: {e}", file=sys.stderr)
        return False

    # Check vault path
    vault_path = Path(Config.OBSIDIAN_VAULT_PATH)
    print(f"\n[2] Checking vault path...", file=sys.stderr)
    if vault_path.exists():
        print(f"  ✓ Vault exists: {vault_path}", file=sys.stderr)
        markdown_files = list(vault_path.rglob("*.md"))
        print(f"  ✓ Found {len(markdown_files)} markdown files", file=sys.stderr)
    else:
        print(f"  ✗ Vault not found: {vault_path}", file=sys.stderr)
        return False

    # Check sync settings
    print(f"\n[3] Checking sync settings...", file=sys.stderr)
    print(f"  SYNC_ENABLED: {Config.SYNC_ENABLED}")
    print(f"  SYNC_DEBOUNCE_SECONDS: {Config.SYNC_DEBOUNCE_SECONDS}")
    print(f"  SYNC_INITIAL_SYNC: {Config.SYNC_INITIAL_SYNC}")
    print(f"  SYNC_FULL_SYNC_INTERVAL: {Config.SYNC_FULL_SYNC_INTERVAL}")

    # Check modules can be imported
    print(f"\n[4] Checking module imports...", file=sys.stderr)
    try:
        from database import DatabaseManager

        print("  ✓ database module", file=sys.stderr)
    except Exception as e:
        print(f"  ✗ database module: {e}", file=sys.stderr)
        return False

    try:
        from obsidian import ObsidianManager

        print("  ✓ obsidian module", file=sys.stderr)
    except Exception as e:
        print(f"  ✗ obsidian module: {e}", file=sys.stderr)
        return False

    try:
        from embeddings import EmbeddingGenerator

        print("  ✓ embeddings module", file=sys.stderr)
    except Exception as e:
        print(f"  ✗ embeddings module: {e}", file=sys.stderr)
        return False

    try:
        from metadata import MetadataExtractor

        print("  ✓ metadata module", file=sys.stderr)
    except Exception as e:
        print(f"  ✗ metadata module: {e}", file=sys.stderr)
        return False

    try:
        from watcher import start_file_watcher

        print("  ✓ watcher module", file=sys.stderr)
    except Exception as e:
        print(f"  ✗ watcher module: {e}", file=sys.stderr)
        return False

    try:
        from links import LinkManager

        print("  ✓ links module", file=sys.stderr)
    except Exception as e:
        print(f"  ✗ links module: {e}", file=sys.stderr)
        return False

    try:
        from tags import TagManager

        print("  ✓ tags module", file=sys.stderr)
    except Exception as e:
        print(f"  ✗ tags module: {e}", file=sys.stderr)
        return False

    try:
        from search import SearchManager

        print("  ✓ search module", file=sys.stderr)
    except Exception as e:
        print(f"  ✗ search module: {e}", file=sys.stderr)
        return False

    print("\n" + "=" * 50, file=sys.stderr)
    print("VERIFICATION COMPLETE", file=sys.stderr)
    print("=" * 50, file=sys.stderr)
    print("\nAll modules loaded successfully!", file=sys.stderr)
    print("Ready to run: python server.py", file=sys.stderr)
    print("\nNext steps:", file=sys.stderr)
    print(
        "1. Run database migration in Supabase SQL Editor (migration_sql.txt)",
        file=sys.stderr,
    )
    print("2. Install dependencies: pip install -r requirements.txt", file=sys.stderr)
    print("3. Start server: python server.py", file=sys.stderr)

    return True


if __name__ == "__main__":
    success = asyncio.run(verify())
    sys.exit(0 if success else 1)
