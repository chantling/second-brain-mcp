"""
Enhanced search with hybrid vector + keyword filtering, faceted search, and ranking.
"""

import sys
from typing import List, Dict, Optional
from datetime import datetime, timedelta

from database import DatabaseManager
from embeddings import EmbeddingGenerator


class SearchManager:
    """Enhanced search with multiple search strategies"""

    def __init__(
        self,
        db_manager: DatabaseManager,
        embedding_generator: EmbeddingGenerator,
        reranker=None,
    ):
        self.db_manager = db_manager
        self.embedding_generator = embedding_generator
        self.reranker = reranker

    async def hybrid_search(
        self,
        query: str,
        limit: int = 10,
        filters: Optional[Dict] = None,
        weights: Optional[Dict] = None,
        use_rerank: bool = True,
    ) -> List[Dict]:
        """
        Hybrid search combining vector similarity and keyword matching.

        Args:
            query: Search query
            limit: Max results
            filters: Dict of filters (type, folder, tags, date_range)
            weights: Dict of weights for scoring (vector: 0.7, keywords: 0.3)
            use_rerank: Whether to apply reranking (default True)

        Returns:
            Ranked list of results with scores
        """
        if weights is None:
            weights = {"vector": 0.7, "keywords": 0.3, "recency": 0.0}

        # Vector search
        query_embedding = await self.embedding_generator.create_embedding(query)
        vector_results = await self.db_manager.semantic_search(
            query_embedding, limit * 2
        )

        # Full-text search (faster and more accurate than keyword_search)
        keyword_results = await self.db_manager.fulltext_search(query, limit * 2)

        # Combine and score
        scored_results = self._combine_scores(vector_results, keyword_results, weights)

        # Apply filters
        if filters:
            scored_results = self._apply_filters(scored_results, filters)

        # Sort by combined score
        scored_results.sort(key=lambda x: x.get("combined_score", 0.0), reverse=True)

        # Rerank if enabled
        if use_rerank and self.reranker is not None:
            candidates = scored_results[:limit * 2]
            scored_results = await self.reranker.rerank(
                query, candidates, top_n=limit
            )

        return scored_results[:limit]

    def _combine_scores(
        self, vector_results: List[Dict], keyword_results: List[Dict], weights: Dict
    ) -> List[Dict]:
        """Combine vector and keyword search scores"""
        combined = {}

        # Add vector scores
        for result in vector_results:
            try:
                thought_id = result.get("id")
                if thought_id:
                    combined[thought_id] = {
                        **result,
                        "vector_score": result.get("similarity", 0.0),
                        "keyword_score": 0.0,
                        "combined_score": 0.0,
                    }
            except (TypeError, AttributeError):
                pass

        # Add keyword scores
        for result in keyword_results:
            try:
                thought_id = result.get("id")
                if thought_id:
                    if thought_id in combined:
                        combined[thought_id]["keyword_score"] = result.get("score", 0.0)
                    else:
                        combined[thought_id] = {
                            **result,
                            "vector_score": 0.0,
                            "keyword_score": result.get("score", 0.0),
                            "combined_score": 0.0,
                        }
            except (TypeError, AttributeError):
                pass

        # Calculate combined score
        for thought_id, result in combined.items():
            result["combined_score"] = weights.get("vector", 0.7) * result.get(
                "vector_score", 0.0
            ) + weights.get("keywords", 0.3) * result.get("keyword_score", 0.0)

            # Add recency boost if configured
            if weights.get("recency", 0.0) > 0:
                result["combined_score"] += self._recency_boost(result)

        return list(combined.values())

    def _apply_filters(self, results: List[Dict], filters: Dict) -> List[Dict]:
        """Apply filters to search results"""
        filtered = results

        if filters.get("thought_type"):
            filtered = [
                r for r in filtered if r.get("thought_type") == filters["thought_type"]
            ]

        if filters.get("folder"):
            filtered = [
                r
                for r in filtered
                if filters.get("folder") in r.get("obsidian_path", "")
            ]

        if filters.get("tags"):
            tags = filters["tags"]
            filtered = [
                r
                for r in filtered
                if any(tag in (r.get("topics") or []) for tag in tags)
            ]

        if filters.get("date_range"):
            date_range = filters["date_range"]
            try:
                if date_range.get("start"):
                    start_date = datetime.fromisoformat(date_range["start"])
                    filtered = [
                        r
                        for r in filtered
                        if r.get("created_at") >= start_date.isoformat()
                    ]

                if date_range.get("end"):
                    end_date = datetime.fromisoformat(date_range["end"])
                    filtered = [
                        r
                        for r in filtered
                        if r.get("created_at") <= end_date.isoformat()
                    ]
            except (ValueError, TypeError, AttributeError):
                pass

        return filtered

    def _recency_boost(self, result: Dict) -> float:
        """Calculate recency boost for scoring"""
        created = result.get("created_at")
        if not created:
            return 0.0

        # Convert to datetime
        if isinstance(created, str):
            try:
                created = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                return 0.0

        # Calculate age in days
        try:
            age = (datetime.now() - created).days

            # Exponential decay boost
            boost = 1.0 / (1.0 + age / 30.0)  # 30-day half-life

            return boost * 0.1  # Max 0.1 boost
        except (TypeError, AttributeError):
            return 0.0

    async def search_by_tags(self, tags: List[str], limit: int = 20) -> List[Dict]:
        """Search thoughts by tags"""
        try:
            # Get tag IDs
            tag_ids = []
            for tag_name in tags:
                response = (
                    self.db_manager.client.table("tags")
                    .select("id")
                    .eq("name", tag_name)
                    .execute()
                )
                if response.data:
                    tag_ids.append(response.data[0]["id"])

            if not tag_ids:
                return []

            # Get thoughts with these tags
            response = (
                self.db_manager.client.table("thought_tags")
                .select("*,thought:thoughts!thought_tags_thought_id_fkey(*)")
                .in_("tag_id", tag_ids)
                .limit(limit)
                .execute()
            )

            # Extract unique thoughts
            thoughts = {}
            for row in response.data if response.data else []:
                thought = row.get("thought")
                if thought and thought.get("id") not in thoughts:
                    thoughts[thought["id"]] = thought

            return list(thoughts.values())

        except Exception as e:
            print(f"[WARNING] Failed to search by tags: {e}", file=sys.stderr)
            return []
