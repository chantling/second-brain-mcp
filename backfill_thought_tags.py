"""Backfill thought_tags table for existing thoughts.

Scans all thoughts in the database and populates the thought_tags junction table
by extracting tags from two sources:
1. The topics array stored on the thought
2. Inline #tags found in the thought's content

Usage:
    python backfill_thought_tags.py [--dry-run]

Options:
    --dry-run   Show what would be done without making changes
"""

import sys
import re
import asyncio
import argparse
from typing import List, Set

# Add parent directory to path for imports
sys.path.insert(0, ".")

from config import Config
from database import DatabaseManager


def extract_tags(content: str, topics: List[str]) -> Set[str]:
    """Extract tags from content and topics list."""
    tags = set()
    if topics:
        tags.update(topics)
    inline_tags = re.findall(r"#(\w[\w-]*)", content)
    tags.update(inline_tags)
    return tags


async def backfill(dry_run: bool = False):
    """Backfill thought_tags for all existing thoughts."""
    db_manager = DatabaseManager()

    print("[BACKFILL] Fetching all thoughts...")
    response = db_manager.client.table("thoughts").select("id, content, topics").execute()

    if not response.data:
        print("[BACKFILL] No thoughts found in database.")
        return

    thoughts = response.data
    total = len(thoughts)
    print(f"[BACKFILL] Found {total} thoughts to process.")

    # Get existing thought_tags associations to avoid redundant work
    existing_response = db_manager.client.table("thought_tags").select("thought_id").execute()
    existing_ids = set()
    if existing_response.data:
        existing_ids = {row["thought_id"] for row in existing_response.data}
    print(f"[BACKFILL] {len(existing_ids)} thoughts already have tags.")

    stats = {
        "processed": 0,
        "skipped": 0,
        "tags_created": 0,
        "associations_created": 0,
        "errors": 0,
        "thoughts_with_new_tags": 0,
    }

    for i, thought in enumerate(thoughts, 1):
        thought_id = thought["id"]
        content = thought.get("content", "")
        topics = thought.get("topics") or []

        tags = extract_tags(content, topics)

        if not tags:
            stats["skipped"] += 1
            if i % 100 == 0 or i == total:
                print(f"[BACKFILL] Progress: {i}/{total} (skipped {stats['skipped']})")
            continue

        if dry_run:
            print(f"  [DRY RUN] Thought {thought_id}: would sync {len(tags)} tags: {tags}")
            stats["processed"] += 1
            stats["thoughts_with_new_tags"] += 1
            continue

        try:
            await db_manager.sync_tags(thought_id, list(tags))
            stats["processed"] += 1
            stats["thoughts_with_new_tags"] += 1
        except Exception as e:
            stats["errors"] += 1
            print(f"  [ERROR] Thought {thought_id}: {e}", file=sys.stderr)

        if i % 50 == 0 or i == total:
            print(f"[BACKFILL] Progress: {i}/{total} processed={stats['processed']} skipped={stats['skipped']} errors={stats['errors']}")

    print("\n[BACKFILL] Complete!")
    print(f"  Total thoughts:      {total}")
    print(f"  Processed (had tags): {stats['thoughts_with_new_tags']}")
    print(f"  Skipped (no tags):    {stats['skipped']}")
    print(f"  Errors:               {stats['errors']}")

    if dry_run:
        print("\n  *** DRY RUN - No changes were made ***")

    # Show final thought_tags count
    if not dry_run:
        final_response = db_manager.client.table("thought_tags").select("thought_id", count="exact").execute()
        count = final_response.count if hasattr(final_response, 'count') else len(final_response.data or [])
        print(f"  thought_tags rows:    {count}")


def main():
    parser = argparse.ArgumentParser(description="Backfill thought_tags for existing thoughts")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without changes")
    args = parser.parse_args()

    asyncio.run(backfill(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
