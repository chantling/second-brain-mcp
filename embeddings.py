"""
Vector embedding generation using OpenAI-compatible API
"""

import asyncio
import sys
from config import Config


class EmbeddingGenerator:
    """Generate vector embeddings using OpenAI-compatible API (flexible provider)"""

    def __init__(self):
        """Initialize the embedding generator with OpenAI-compatible API client.
        
        Loads API key, base URL, model name, and embedding dimensions from
        Config. Creates an OpenAI client instance for generating vector
        embeddings from text content using the configured embedding model.
        """
        try:
            from openai import OpenAI

            self.client = OpenAI(
                api_key=Config.EMBEDDING_API_KEY,
                base_url=Config.EMBEDDING_BASE_URL,
                timeout=240,
                max_retries=3,
            )
            self.model = Config.EMBEDDING_MODEL
            self.dimensions = Config.EMBEDDING_DIMENSIONS
        except ImportError:
            raise ImportError(
                "OpenAI SDK is required for embeddings. "
                "Install it with: pip install openai>=1.0"
            )

    async def warmup(self):
        """Warm up connection pool by making a test embedding"""
        try:
            print("[EMBEDDINGS] Warming up connection pool...", file=sys.stderr)
            await self.create_embedding("warmup")
            print(
                "[EMBEDDINGS] Connection pool warmed up successfully", file=sys.stderr
            )
        except Exception as e:
            print(f"[WARNING] Failed to warmup embeddings: {e}", file=sys.stderr)

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
            text = text[:max_tokens]

        try:
            # Run blocking call in thread pool to avoid blocking async event loop
            def _create_sync_embedding():
                kwargs = {"model": self.model, "input": text}
                if self.dimensions > 0:
                    kwargs["dimensions"] = self.dimensions
                response = self.client.embeddings.create(**kwargs)
                return response.data[0].embedding

            embedding = await asyncio.to_thread(_create_sync_embedding)

            elapsed = time.time() - start_time
            print(
                f"[EMBEDDINGS] Created embedding for {len(text)} chars in {elapsed:.2f}s",
                file=sys.stderr,
            )

            return embedding
        except Exception as e:
            elapsed = time.time() - start_time
            print(
                f"[ERROR] Failed to create embedding after {elapsed:.2f}s: {e}",
                file=sys.stderr,
            )
            raise Exception(f"Failed to create embedding: {e}")

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
        Note: OpenAI SDK handles connection pooling automatically
        """
        if hasattr(self, "client"):
            # OpenAI SDK handles connection cleanup
            pass


class EmbeddingManager(EmbeddingGenerator):
    """Alias for EmbeddingGenerator for backward compatibility"""

    pass
