"""
Vector embedding generation using OpenAI-compatible API
"""
from config import Config

class EmbeddingGenerator:
    """Generate vector embeddings using OpenAI-compatible API (flexible provider)"""
    
    def __init__(self):
        """Initialize the embedding generator"""
        try:
            from openai import OpenAI
            self.client = OpenAI(
                api_key=Config.EMBEDDING_API_KEY,
                base_url=Config.EMBEDDING_BASE_URL,
                timeout=30,
                max_retries=3
            )
            self.model = Config.EMBEDDING_MODEL
            self.dimensions = Config.EMBEDDING_DIMENSIONS
        except ImportError:
            raise ImportError(
                "OpenAI SDK is required for embeddings. "
                "Install it with: pip install openai>=1.0"
            )
    
    async def create_embedding(self, text: str) -> list:
        """
        Create vector embedding for text
        
        Args:
            text: Text to embed
            
        Returns:
            List of float values representing the vector embedding
        """
        # Truncate text if too long (most APIs have limits)
        max_tokens = 8192
        if len(text) > max_tokens:
            text = text[:max_tokens]
        
        try:
            response = self.client.embeddings.create(
                model=self.model,
                input=text,
                dimensions=self.dimensions if self.dimensions > 0 else None
            )
            return response.data[0].embedding
        except Exception as e:
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
        if hasattr(self, 'client'):
            # OpenAI SDK handles connection cleanup
            pass