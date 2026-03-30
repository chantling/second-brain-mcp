"""
Vector embedding generation using OpenAI-compatible API (uses requests for reliability)
"""

import asyncio
import sys
import logging
from config import Config

# Get logger for this module
logger = logging.getLogger('second_brain.embeddings')


class EmbeddingGenerator:
    """Generate vector embeddings using OpenAI-compatible API (flexible provider)"""

    def __init__(self):
        """Initialize the embedding generator with API configuration."""
        self.api_key = Config.EMBEDDING_API_KEY
        self.base_url = Config.EMBEDDING_BASE_URL.rstrip("/")
        self.model = Config.EMBEDDING_MODEL
        self.dimensions = Config.EMBEDDING_DIMENSIONS

    async def warmup(self):
        """Warm up connection pool by making a test embedding"""
        try:
            logger.info("[EMBEDDINGS] Warming up connection pool...")
            await self.create_embedding("warmup")
            logger.info("[EMBEDDINGS] Connection pool warmed up successfully")
        except Exception as e:
            logger.warning(f"Failed to warmup embeddings: {e}")

    async def create_embedding(self, text: str) -> list:
        """
        Create vector embedding for text

        Args:
            text: Text to embed

        Returns:
            List of float values representing the vector embedding
        """
        import time

        start_time = time.time()

        # Truncate text if too long (most APIs have limits)
        max_tokens = 8192
        if len(text) > max_tokens:
            logger.warning(f"[EMBEDDINGS] Text too long ({len(text)} chars), truncating to {max_tokens} chars")
            text = text[:max_tokens]

        logger.info(f"[EMBEDDINGS] Creating embedding for {len(text)} chars...")

        try:
            loop = asyncio.get_running_loop()
            embedding = await loop.run_in_executor(None, self._sync_create_embedding, text)

            elapsed = time.time() - start_time
            logger.info(f"[EMBEDDINGS] Created embedding for {len(text)} chars in {elapsed:.2f}s")
            print(
                f"[EMBEDDINGS] Created embedding for {len(text)} chars in {elapsed:.2f}s",
                file=sys.stderr,
            )

            return embedding
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"[EMBEDDINGS] Failed to create embedding after {elapsed:.2f}s: {e}")
            print(
                f"[ERROR] Failed to create embedding after {elapsed:.2f}s: {e}",
                file=sys.stderr,
            )
            raise Exception(f"Failed to create embedding: {e}")

    def _sync_create_embedding(self, text: str) -> list:
        """Synchronous embedding creation using requests library"""
        import requests
        import json

        url = f"{self.base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "input": text,
        }
        if self.dimensions > 0:
            payload["dimensions"] = self.dimensions

        logger.debug(f"[EMBEDDINGS] Calling API with model={self.model}, dimensions={self.dimensions}")

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=30,
        )
        response.raise_for_status()

        data = response.json()
        return data["data"][0]["embedding"]

    async def batch_create_embeddings(self, texts: list) -> list:
        """
        Create embeddings for multiple texts

        Args:
            texts: List of texts to embed

        Returns:
            List of vector embeddings
        """
        embeddings = []
        for text in texts:
            embedding = await self.create_embedding(text)
            embeddings.append(embedding)
        return embeddings

    async def close(self):
        """
        Close the client connection
        """
        pass


class EmbeddingManager(EmbeddingGenerator):
    """Alias for EmbeddingGenerator for backward compatibility"""

    pass
