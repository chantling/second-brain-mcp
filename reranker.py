"""
Cohere reranking via OpenRouter API for improved search result relevance.
"""

import asyncio
import logging
import sys
from typing import Dict, List, Optional

from config import Config

logger = logging.getLogger("second_brain.reranker")


class Reranker:
    """Rerank search results using Cohere rerank model via OpenRouter."""

    def __init__(self):
        self.api_key = Config.RERANK_API_KEY
        self.base_url = Config.RERANK_BASE_URL.rstrip("/")
        self.model = Config.RERANK_MODEL
        self.timeout = Config.RERANK_TIMEOUT
        self.min_relevance_score = Config.RERANK_MIN_RELEVANCE_SCORE
        self.max_doc_length = Config.RERANK_MAX_DOC_LENGTH

    async def rerank(
        self,
        query: str,
        results: List[Dict],
        top_n: Optional[int] = None,
        content_key: str = "content",
    ) -> List[Dict]:
        """Rerank search results by relevance to query.

        Args:
            query: The search query.
            results: List of result dicts from search.
            top_n: Number of top results to return. Defaults to len(results).
            content_key: Key in each result dict containing the document text.

        Returns:
            Results reordered by rerank relevance_score, with original
            ordering preserved as fallback on failure.
        """
        if not results:
            return results

        if top_n is None:
            top_n = len(results)

        documents = self._extract_documents(results, content_key)

        if not documents:
            return results

        try:
            loop = asyncio.get_running_loop()
            rerank_response = await loop.run_in_executor(
                None, self._sync_rerank, query, documents, top_n
            )
            return self._apply_rerank_results(results, rerank_response)
        except Exception as e:
            logger.warning(f"Rerank failed, returning original ordering: {e}")
            print(
                f"[WARNING] Rerank failed, returning original ordering: {e}",
                file=sys.stderr,
            )
            return results

    def _extract_documents(
        self, results: List[Dict], content_key: str
    ) -> List[str]:
        documents = []
        for result in results:
            text = result.get(content_key, "")
            if not text:
                text = result.get("title", "")
            if not text:
                text = ""
            if len(text) > self.max_doc_length:
                text = text[: self.max_doc_length]
            documents.append(text)
        return documents

    def _sync_rerank(
        self, query: str, documents: List[str], top_n: int
    ) -> List[Dict]:
        import requests

        url = f"{self.base_url}/rerank"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "query": query,
            "documents": documents,
            "top_n": min(top_n, len(documents)),
        }

        logger.debug(
            f"[RERANK] Calling API with model={self.model}, "
            f"docs={len(documents)}, top_n={top_n}"
        )

        response = requests.post(
            url, headers=headers, json=payload, timeout=self.timeout
        )
        response.raise_for_status()

        data = response.json()
        results = data.get("results", [])

        logger.info(
            f"[RERANK] Reranked {len(documents)} documents, "
            f"returned {len(results)} results"
        )

        return results

    def _apply_rerank_results(
        self, original_results: List[Dict], rerank_results: List[Dict]
    ) -> List[Dict]:
        reordered = []
        for rerank_item in rerank_results:
            idx = rerank_item.get("index")
            score = rerank_item.get("relevance_score", 0.0)

            if idx is not None and 0 <= idx < len(original_results):
                result = dict(original_results[idx])
                result["relevance_score"] = score
                result["reranked"] = True
                reordered.append(result)

        if not reordered:
            logger.warning(
                "[RERANK] No rerank results, returning original ordering"
            )
            return original_results

        filtered = [r for r in reordered if r.get("relevance_score", 0.0) >= self.min_relevance_score]

        if not filtered:
            logger.warning(
                "[RERANK] No results passed min_relevance_score threshold, "
                "returning original ordering"
            )
            return original_results

        return filtered

    async def close(self):
        pass
