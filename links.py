"""
Link management for wiki-links and embeds.
Provides backlink queries and relationship discovery.
"""

import sys
from typing import List, Dict

from database import DatabaseManager


class LinkManager:
    """Manage wiki-links, embeds, and backlinks"""

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    async def get_backlinks(self, thought_id: int) -> List[Dict]:
        """Get all notes that link to this thought"""
        return await self.db_manager.get_backlinks(thought_id)

    async def get_outlinks(self, thought_id: int) -> List[Dict]:
        """Get all notes this thought links to"""
        return await self.db_manager.get_outlinks(thought_id)

    async def find_related_notes(self, thought_id: int, limit: int = 10) -> List[Dict]:
        """Find related notes via shared links and tag overlap"""
        # Get backlinks and outlinks
        backlinks = await self.get_backlinks(thought_id)
        outlinks = await self.get_outlinks(thought_id)

        # Collect all related thought IDs
        related_ids = set()
        for link in backlinks:
            try:
                related_ids.add(link["source_thought_id"])
            except (TypeError, KeyError):
                pass

        for link in outlinks:
            try:
                related_ids.add(link["target_thought_id"])
            except (TypeError, KeyError):
                pass

        # Remove self
        related_ids.discard(thought_id)

        if not related_ids:
            return []

        # Fetch related thoughts
        response = (
            self.db_manager.client.table("thoughts")
            .select("*")
            .in_("id", list(related_ids))
            .limit(limit)
            .execute()
        )

        if not response.data:
            return []

        # Add link metadata
        results = []
        for thought in response.data:
            try:
                link_count = len(
                    [
                        l
                        for l in backlinks + outlinks
                        if l.get("source_thought_id") == thought["id"]
                        or l.get("target_thought_id") == thought["id"]
                    ]
                )
                thought["link_count"] = link_count
                results.append(thought)
            except (TypeError, KeyError):
                thought["link_count"] = 0
                results.append(thought)

        # Sort by link count
        results.sort(key=lambda x: x.get("link_count", 0), reverse=True)

        return results[:limit]

    async def get_link_graph(self, thought_id: int, depth: int = 2) -> Dict:
        """Get link graph for visualization"""
        graph = {"nodes": {}, "edges": []}

        async def explore(current_id: int, current_depth: int):
            if current_depth > depth:
                return

            if current_id not in graph["nodes"]:
                try:
                    thought = await self.db_manager.get_thought(current_id)
                    if thought:
                        graph["nodes"][current_id] = thought
                except Exception as e:
                    print(
                        f"[WARNING] Failed to get thought {current_id}: {e}",
                        file=sys.stderr,
                    )
                    return

            # Get outlinks
            outlinks = await self.get_outlinks(current_id)
            for link in outlinks:
                try:
                    target_id = link.get("target_thought_id")
                    link_type = link.get("link_type", "wiki")

                    if target_id:
                        edge = {
                            "source": current_id,
                            "target": target_id,
                            "type": link_type,
                        }
                        # Check if edge already exists
                        if edge not in graph["edges"]:
                            graph["edges"].append(edge)
                            await explore(target_id, current_depth + 1)
                except (TypeError, KeyError):
                    pass

        await explore(thought_id, 0)

        return graph
