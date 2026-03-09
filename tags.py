"""
Tag management and AI-powered tag suggestions.
"""

import sys
from typing import List, Dict

from database import DatabaseManager
from embeddings import EmbeddingGenerator


class TagManager:
    """Manage tags with AI-powered suggestions"""

    def __init__(
        self, db_manager: DatabaseManager, embedding_generator: EmbeddingGenerator
    ):
        """Initialize tag manager with database and embedding generator dependencies.
        
        Stores references to database manager for tag queries and embedding
        generator for semantic similarity matching. Provides methods for managing
        tags, suggesting relevant tags based on content, and consolidating
        similar tags.
        """
        self.db_manager = db_manager
        self.embedding_generator = embedding_generator

    async def get_all_tags(self) -> List[Dict]:
        """Get all tags with usage counts"""
        try:
            response = (
                self.db_manager.client.table("thought_tags")
                .select("tag_id,count")
                .execute()
            )

            if not response.data:
                return []

            # Group by tag_id and count
            tag_counts = {}
            for row in response.data:
                tag_id = row.get("tag_id")
                if tag_id:
                    tag_counts[tag_id] = tag_counts.get(tag_id, 0) + 1

            # Fetch tag names
            tag_ids = list(tag_counts.keys())
            tags_response = (
                self.db_manager.client.table("tags")
                .select("*")
                .in_("id", tag_ids)
                .execute()
            )

            # Add counts
            tags = []
            for tag in tags_response.data if tags_response.data else []:
                tag["usage_count"] = tag_counts.get(tag.get("id"), 0)
                tags.append(tag)

            # Sort by usage count
            tags.sort(key=lambda x: x.get("usage_count", 0), reverse=True)

            return tags

        except Exception as e:
            print(f"[WARNING] Failed to get tags: {e}", file=sys.stderr)
            return []

    async def suggest_tags(self, content: str, limit: int = 10) -> List[Dict]:
        """Suggest tags based on content using semantic similarity"""
        try:
            # Generate embedding for content
            content_embedding = await self.embedding_generator.create_embedding(content)

            # Get all tags with embeddings
            response = (
                self.db_manager.client.table("tags")
                .select("id, name, embedding")
                .execute()
            )

            if not response.data:
                return []

            # Calculate similarity
            import numpy as np

            query_array = np.array(content_embedding)
            scored_tags = []

            for tag in response.data:
                if tag.get("embedding"):
                    try:
                        tag_array = np.array(tag["embedding"])
                        similarity = np.dot(query_array, tag_array) / (
                            np.linalg.norm(query_array) * np.linalg.norm(tag_array)
                        )
                        tag["similarity"] = float(similarity)
                        scored_tags.append(tag)
                    except (ValueError, TypeError):
                        pass

            # Sort by similarity
            scored_tags.sort(key=lambda x: x.get("similarity", 0.0), reverse=True)

            return scored_tags[:limit]

        except Exception as e:
            print(f"[WARNING] Failed to suggest tags: {e}", file=sys.stderr)
            return []

    async def consolidate_tags(self, old_tags: List[str], new_tag: str) -> Dict:
        """Consolidate multiple tags into a single tag"""
        stats = {"updated_thoughts": 0, "deleted_tags": 0}

        try:
            # Create new tag if it doesn't exist
            self.db_manager.client.table("tags").insert({"name": new_tag}).execute()
        except Exception:
            pass  # Tag already exists

        # Find all thoughts with old tags
        for old_tag in old_tags:
            try:
                # Get tag ID
                tag_response = (
                    self.db_manager.client.table("tags")
                    .select("id")
                    .eq("name", old_tag)
                    .execute()
                )

                if not tag_response.data:
                    continue

                tag_id = tag_response.data[0]["id"]

                # Get thought IDs
                thoughts_response = (
                    self.db_manager.client.table("thought_tags")
                    .select("thought_id")
                    .eq("tag_id", tag_id)
                    .execute()
                )

                if not thoughts_response.data:
                    continue

                thought_ids = [t["thought_id"] for t in thoughts_response.data]

                # Remove old tag assignments
                self.db_manager.client.table("thought_tags").delete().eq(
                    "tag_id", tag_id
                ).execute()

                # Add new tag assignments
                for thought_id in thought_ids:
                    self.db_manager.client.table("thought_tags").insert(
                        {
                            "thought_id": thought_id,
                            "tag_id": self.db_manager.client.table("tags")
                            .select("id")
                            .eq("name", new_tag)
                            .execute()
                            .data[0]["id"],
                        }
                    ).execute()

                stats["updated_thoughts"] += len(thought_ids)
                stats["deleted_tags"] += 1

            except Exception as e:
                print(
                    f"[ERROR] Failed to consolidate tag {old_tag}: {e}", file=sys.stderr
                )

        # Delete old tags
        for old_tag in old_tags:
            try:
                self.db_manager.client.table("tags").delete().eq(
                    "name", old_tag
                ).execute()
            except Exception as e:
                print(f"[ERROR] Failed to delete tag {old_tag}: {e}", file=sys.stderr)

        return stats
