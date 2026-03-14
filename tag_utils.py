"""Shared tag extraction and syncing utilities."""

import re
import sys
from typing import List, Optional


async def sync_tags_for_thought(
    db_manager,
    thought_id: int,
    content: str,
    topics: Optional[List[str]] = None,
):
    """Extract tags from content and topics, then sync to thought_tags table.

    Extracts tags from two sources:
    1. The topics list (from frontmatter metadata)
    2. Inline #tags found in the content body

    Args:
        db_manager: DatabaseManager instance
        thought_id: ID of the thought to sync tags for
        content: The thought's text content
        topics: Optional list of topic strings from metadata
    """
    tags = set()

    if topics:
        tags.update(topics)

    inline_tags = re.findall(r"#(\w[\w-]*)", content)
    tags.update(inline_tags)

    if tags:
        await db_manager.sync_tags(thought_id, list(tags))
