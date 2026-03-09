import os
import sys
from pathlib import Path
from typing import List, Dict, Optional, Any
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
    METADATA_BASE_URL = os.getenv(
        "METADATA_BASE_URL", "https://api.z.ai/api/coding/paas/v4"
    )
    METADATA_MODEL = os.getenv("METADATA_MODEL", "glm-4.7")

    # Legacy support (for backward compatibility)
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
    ZAI_API_KEY = os.getenv("ZAI_API_KEY")
    
    # Blacklist Configuration
    BLACKLIST_FILE = os.getenv("BLACKLIST_FILE")
    if BLACKLIST_FILE:
        BLACKLIST_FILE_PATH = Path(BLACKLIST_FILE)
    else:
        # Default to .blacklist in same directory as .env
        BLACKLIST_FILE_PATH = Path(__file__).parent / ".blacklist"
    IGNORED_PATHS: List[str] = []
    IGNORED_FILES: List[str] = []
    
    # Obsidian Configuration
    OBSIDIAN_VAULT_PATH = os.getenv("OBSIDIAN_VAULT_PATH", "./SecondBrain")

    # Sync Configuration
    SYNC_ENABLED = os.getenv("SYNC_ENABLED", "true").lower() == "true"
    SYNC_DEBOUNCE_SECONDS = float(os.getenv("SYNC_DEBOUNCE_SECONDS", "2.0"))
    SYNC_INITIAL_SYNC = os.getenv("SYNC_INITIAL_SYNC", "true").lower() == "true"
    SYNC_FULL_SYNC_INTERVAL = int(
        os.getenv("SYNC_FULL_SYNC_INTERVAL", "3600")
    )  # 1 hour in seconds
    SYNC_EXCLUDE_PATTERNS = os.getenv(
        "SYNC_EXCLUDE_PATTERNS", ".obsidian,.trash,.ClineData,!Folder_Embeddings.md"
    ).split(",")

    # Obsidian Configuration
    SEMANTIC_FOLDER_PLACEMENT = (
        os.getenv("SEMANTIC_FOLDER_PLACEMENT", "false").lower() == "true"
    )

    # Search Configuration
    SEARCH_VECTOR_WEIGHT = float(os.getenv("SEARCH_VECTOR_WEIGHT", "0.7"))
    SEARCH_KEYWORD_WEIGHT = float(os.getenv("SEARCH_KEYWORD_WEIGHT", "0.3"))
    SEARCH_RECENCY_WEIGHT = float(os.getenv("SEARCH_RECENCY_WEIGHT", "0.0"))

    # Database Configuration
    DB_TIMEOUT = int(os.getenv("DB_TIMEOUT", "10"))

    # Full-text Search Configuration
    FTS_LANGUAGE = os.getenv("FTS_LANGUAGE", "english")
    FTS_MIN_WORD_LENGTH = int(os.getenv("FTS_MIN_WORD_LENGTH", "3"))

    # Instance Lock Configuration
    # Lock file name (used by instance_lock.py to determine lock file location)
    LOCK_FILE_NAME = ".server_lock"
    
    # Use absolute path based on script location to ensure both instances use of same lock file
    # Note: The actual path is determined by instance_lock.py using os.path.abspath(__file__)
    # This ensures lock file is always in the same directory as the running script
    LOCK_FILE_PATH = os.getenv("LOCK_FILE_PATH")  # Optional override
    LOCK_RETRY_ENABLED = os.getenv("LOCK_RETRY_ENABLED", "true").lower() == "true"
    LOCK_RETRY_INTERVAL_SECONDS = int(os.getenv("LOCK_RETRY_INTERVAL_SECONDS", "30"))
    LOCK_RETRY_JITTER_SECONDS = int(os.getenv("LOCK_RETRY_JITTER_SECONDS", "10"))
    LOCK_HEARTBEAT_INTERVAL_SECONDS = int(
        os.getenv("LOCK_HEARTBEAT_INTERVAL_SECONDS", "20")
    )
    LOCK_STALE_THRESHOLD_SECONDS = int(os.getenv("LOCK_STALE_THRESHOLD_SECONDS", "60"))

    # Duplicate Handling Configuration
    DUPLICATE_HANDLING_MODE = os.getenv("DUPLICATE_HANDLING_MODE", "prompt").lower()
    DUPLICATE_USE_TASKS = os.getenv("DUPLICATE_USE_TASKS", "false").lower() == "true"
    DUPLICATE_TRACKING_PARAMS = os.getenv("DUPLICATE_TRACKING_PARAMS", "")

    # Debug Configuration
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"
    DEBUG_VERBOSE = os.getenv("DEBUG_VERBOSE", "false").lower() == "true"

    # Validation
    @classmethod
    def validate(cls):
        """Validate that all required environment variables are set"""
        required_vars = ["SUPABASE_URL", "SUPABASE_SECRET_KEY", "SUPABASE_PUBLISH_KEY"]

        missing_vars = []
        for var in required_vars:
            if not getattr(cls, var):
                missing_vars.append(var)

        if missing_vars:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing_vars)}"
            )

        # Check for API keys (new vars take precedence, legacy vars as fallback)
        if not cls.EMBEDDING_API_KEY and cls.OPENROUTER_API_KEY:
            print(
                "[INFO] Using legacy OPENROUTER_API_KEY for embeddings", file=sys.stderr
            )
            cls.EMBEDDING_API_KEY = cls.OPENROUTER_API_KEY

        if not cls.METADATA_API_KEY and cls.ZAI_API_KEY:
            print("[INFO] Using legacy ZAI_API_KEY for metadata", file=sys.stderr)
            cls.METADATA_API_KEY = cls.ZAI_API_KEY

        # Validate that we have at least one API key for each service
        if not cls.EMBEDDING_API_KEY:
            raise ValueError(
                "Missing required environment variable: EMBEDDING_API_KEY (or OPENROUTER_API_KEY)"
            )

        if not cls.METADATA_API_KEY:
            raise ValueError(
                "Missing required environment variable: METADATA_API_KEY (or ZAI_API_KEY)"
            )

        print("[OK] All configuration validated successfully", file=sys.stderr)
    
    @classmethod
    def _parse_list_var(cls, value: str) -> List[str]:
        """Parse comma-separated list from .env"""
        if not value:
            return []
        return [item.strip() for item in value.split(",") if item.strip()]
    
    @classmethod
    def _load_blacklist(cls) -> List[str]:
        """Load blacklist from .blacklist file
        
        Returns: List of blacklisted paths and filenames (one per line, supports comments)
        """
        if not Config.BLACKLIST_FILE_PATH or not Config.BLACKLIST_FILE_PATH.exists():
            print(f"[CONFIG] No blacklist file found at: {Config.BLACKLIST_FILE_PATH}", file=sys.stderr)
            return []
        
        blacklisted_items = []
        
        try:
            with open(Config.BLACKLIST_FILE_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line_stripped = line.strip()
                    
                    if not line_stripped or line_stripped.startswith('#'):
                        continue
                    
                    blacklisted_items.append(line_stripped)
            
            print(f"[CONFIG] Loaded {len(blacklisted_items)} items from blacklist", file=sys.stderr)
            return blacklisted_items
        except Exception as e:
            print(f"[CONFIG] Failed to load blacklist: {e}", file=sys.stderr)
            return []

    @classmethod
    def _initialize_blacklists(cls):
        """Initialize IGNORED_PATHS and IGNORED_FILES from multiple sources"""
        from pathlib import Path

        # Load from .blacklist file
        blacklist_items = cls._load_blacklist()

        # Separate into paths and files based on content
        # Paths: Don't contain . or end with /
        # Files: Contain . and don't contain /
        ignored_paths = []
        ignored_files = []

        for item in blacklist_items:
            # Skip comments and empty lines (already handled in _load_blacklist)
            if not item or item.startswith('#'):
                continue

            # Check if it's a path or file
            # Heuristic: If it ends with / or doesn't contain ., it's a path
            # If it contains . and doesn't have /, it's a file
            item_stripped = item.strip()

            if item_stripped.endswith('/') or '.' not in item_stripped:
                ignored_paths.append(item_stripped.rstrip('/'))
            else:
                # Extract just filename if path provided
                if '/' in item_stripped:
                    filename = Path(item_stripped).name
                    ignored_files.append(filename)
                else:
                    ignored_files.append(item_stripped)

        # Also parse environment variables for backward compatibility
        env_paths_str = os.getenv("IGNORED_PATHS", "")
        env_files_str = os.getenv("IGNORED_FILES", "")

        if env_paths_str:
            env_paths = cls._parse_list_var(env_paths_str)
            ignored_paths.extend(env_paths)

        if env_files_str:
            env_files = cls._parse_list_var(env_files_str)
            ignored_files.extend(env_files)

        # Remove duplicates and sort, then assign to class variables
        cls.IGNORED_PATHS = sorted(list(set(ignored_paths)))
        cls.IGNORED_FILES = sorted(list(set(ignored_files)))

        if Config.DEBUG:
            print(f"[CONFIG] Initialized blacklists: {len(cls.IGNORED_PATHS)} paths, {len(cls.IGNORED_FILES)} files", file=sys.stderr)
            if hasattr(Config, 'DEBUG_VERBOSE') and Config.DEBUG_VERBOSE:
                print(f"[CONFIG] IGNORED_PATHS: {cls.IGNORED_PATHS}", file=sys.stderr)
                print(f"[CONFIG] IGNORED_FILES: {cls.IGNORED_FILES}", file=sys.stderr)

    print("[OK] All configuration validated successfully", file=sys.stderr)

    # Validate configuration on import
    @staticmethod
    def validate():
        """Validate configuration and initialize blacklists"""
        # Call _initialize_blacklists to populate IGNORED_PATHS and IGNORED_FILES
        Config._initialize_blacklists()
