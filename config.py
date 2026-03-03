import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file in second-brain-mcp directory
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

class Config:
    """Configuration class for the Second Brain MCP server"""
    
    # Supabase Configuration
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY") 
    SUPABASE_PUBLISH_KEY = os.getenv("SUPABASE_PUBLISH_KEY")
    
    # Embedding Configuration (generic - works with any OpenAI-compatible API)
    EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY")
    EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "https://openrouter.ai/api/v1")
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "qwen/qwen3-embedding-8b")
    EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "1536"))
    
    # Metadata Configuration (generic - works with any OpenAI-compatible API)
    METADATA_API_KEY = os.getenv("METADATA_API_KEY")
    METADATA_BASE_URL = os.getenv("METADATA_BASE_URL", "https://api.z.ai/api/coding/paas/v4")
    METADATA_MODEL = os.getenv("METADATA_MODEL", "glm-4.7")
    
    # Legacy support (for backward compatibility)
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
    ZAI_API_KEY = os.getenv("ZAI_API_KEY")
    
    # Obsidian Configuration
    OBSIDIAN_VAULT_PATH = os.getenv("OBSIDIAN_VAULT_PATH", "./SecondBrain")
    
    # Validation
    @classmethod
    def validate(cls):
        """Validate that all required environment variables are set"""
        required_vars = [
            "SUPABASE_URL",
            "SUPABASE_SECRET_KEY", 
            "SUPABASE_PUBLISH_KEY"
        ]
        
        missing_vars = []
        for var in required_vars:
            if not getattr(cls, var):
                missing_vars.append(var)
        
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
        
        # Check for API keys (new vars take precedence, legacy vars as fallback)
        if not cls.EMBEDDING_API_KEY and cls.OPENROUTER_API_KEY:
            print("[INFO] Using legacy OPENROUTER_API_KEY for embeddings")
            cls.EMBEDDING_API_KEY = cls.OPENROUTER_API_KEY
        
        if not cls.METADATA_API_KEY and cls.ZAI_API_KEY:
            print("[INFO] Using legacy ZAI_API_KEY for metadata")
            cls.METADATA_API_KEY = cls.ZAI_API_KEY
        
        # Validate that we have at least one API key for each service
        if not cls.EMBEDDING_API_KEY:
            raise ValueError("Missing required environment variable: EMBEDDING_API_KEY (or OPENROUTER_API_KEY)")
        
        if not cls.METADATA_API_KEY:
            raise ValueError("Missing required environment variable: METADATA_API_KEY (or ZAI_API_KEY)")
        
        print("[OK] All configuration validated successfully")

# Validate configuration on import
Config.validate()