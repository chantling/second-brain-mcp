import os
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple
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
    _blacklist_mtime: Optional[float] = None
    # Unified pattern storage: list of (raw_pattern, pattern_type, compiled_regex)
    # Types: "folder", "file", "glob", "abs_folder", "abs_file"
    _blacklist_patterns: List[Tuple[str, str, "re.Pattern"]] = []

    # Obsidian Configuration
    OBSIDIAN_VAULT_PATH = os.getenv("OBSIDIAN_VAULT_PATH", "./SecondBrain")

    # Sync Configuration
    SYNC_ENABLED = os.getenv("SYNC_ENABLED", "true").lower() == "true"
    SYNC_DEBOUNCE_SECONDS = float(os.getenv("SYNC_DEBOUNCE_SECONDS", "2.0"))
    SYNC_INITIAL_SYNC = os.getenv("SYNC_INITIAL_SYNC", "true").lower() == "true"
    SYNC_FULL_SYNC_INTERVAL = int(
        os.getenv("SYNC_FULL_SYNC_INTERVAL", "3600")
    )  # 1 hour in seconds
    SYNC_EXCLUDE_PATTERNS = [
        p.strip() for p in os.getenv(
            "SYNC_EXCLUDE_PATTERNS", ".obsidian,.trash,.ClineData,!Folder_Embeddings.md"
        ).split(",") if p.strip()
    ]

    # Watcher Configuration
    WATCHER_POLL_INTERVAL = int(os.getenv("WATCHER_POLL_INTERVAL", "10"))

    # Obsidian Configuration
    SEMANTIC_FOLDER_PLACEMENT = (
        os.getenv("SEMANTIC_FOLDER_PLACEMENT", "false").lower() == "true"
    )

    # Search Configuration
    SEARCH_VECTOR_WEIGHT = float(os.getenv("SEARCH_VECTOR_WEIGHT", "0.7"))
    SEARCH_KEYWORD_WEIGHT = float(os.getenv("SEARCH_KEYWORD_WEIGHT", "0.3"))
    SEARCH_RECENCY_WEIGHT = float(os.getenv("SEARCH_RECENCY_WEIGHT", "0.0"))

    # Reranking Configuration (Cohere via OpenRouter)
    RERANK_ENABLED = os.getenv("RERANK_ENABLED", "true").lower() == "true"
    RERANK_API_KEY = os.getenv("RERANK_API_KEY")
    RERANK_BASE_URL = os.getenv("RERANK_BASE_URL", "https://openrouter.ai/api/v1")
    RERANK_MODEL = os.getenv("RERANK_MODEL", "cohere/rerank-4-pro")
    RERANK_TIMEOUT = int(os.getenv("RERANK_TIMEOUT", "10"))
    RERANK_MIN_RELEVANCE_SCORE = float(os.getenv("RERANK_MIN_RELEVANCE_SCORE", "0.0"))
    RERANK_MAX_DOC_LENGTH = int(os.getenv("RERANK_MAX_DOC_LENGTH", "4000"))

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

    # Supabase Distributed Lock Configuration (cross-instance coordination)
    LOCK_TTL_SECONDS = int(os.getenv("LOCK_TTL_SECONDS", "30"))
    LOCK_HEARTBEAT_INTERVAL = int(os.getenv("LOCK_HEARTBEAT_INTERVAL", "10"))
    LOCK_ORPHAN_CLEANUP_TTL = int(os.getenv("LOCK_ORPHAN_CLEANUP_TTL", "120"))

    # Duplicate Handling Configuration
    DUPLICATE_HANDLING_MODE = os.getenv("DUPLICATE_HANDLING_MODE", "prompt").lower()
    DUPLICATE_USE_TASKS = os.getenv("DUPLICATE_USE_TASKS", "false").lower() == "true"
    DUPLICATE_TRACKING_PARAMS = os.getenv("DUPLICATE_TRACKING_PARAMS", "")

    # Debug Configuration
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"
    DEBUG_VERBOSE = os.getenv("DEBUG_VERBOSE", "false").lower() == "true"
    
    # File Logging Configuration
    FILE_LOGGING = os.getenv("FILE_LOGGING", "false").lower() == "true"

    _validated = False

    # Validation
    @classmethod
    def validate(cls):
        """Validate that all required environment variables are set"""
        if cls._validated:
            return
        cls._validated = True
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

        if not cls.RERANK_API_KEY and cls.EMBEDDING_API_KEY:
            print(
                "[INFO] Using EMBEDDING_API_KEY for reranking (RERANK_API_KEY not set)",
                file=sys.stderr,
            )
            cls.RERANK_API_KEY = cls.EMBEDDING_API_KEY

        if cls.RERANK_ENABLED and not cls.RERANK_API_KEY:
            print(
                "[WARNING] Reranking enabled but no API key available. Disabling reranking.",
                file=sys.stderr,
            )
            cls.RERANK_ENABLED = False

        print("[OK] All configuration validated successfully", file=sys.stderr)
        cls._initialize_blacklists()

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
            print(
                f"[CONFIG] No blacklist file found at: {Config.BLACKLIST_FILE_PATH}",
                file=sys.stderr,
            )
            return []

        blacklisted_items = []

        try:
            with open(Config.BLACKLIST_FILE_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line_stripped = line.strip()

                    if not line_stripped or line_stripped.startswith("#"):
                        continue

                    blacklisted_items.append(line_stripped)

            print(
                f"[CONFIG] Loaded {len(blacklisted_items)} items from blacklist",
                file=sys.stderr,
            )
            return blacklisted_items
        except Exception as e:
            print(f"[CONFIG] Failed to load blacklist: {e}", file=sys.stderr)
            return []

    @classmethod
    def _initialize_blacklists(cls):
        """Initialize blacklist patterns from .blacklist file and environment variables.

        Classification rules:
        - Ends with \\ or /                        → folder (explicit directory marker)
        - Contains *                               → glob pattern
        - Starts with X:\\ or \\\\                 → absolute path
        - Starts with .\\ or ..\\ (relative path)  → folder after stripping prefix
        - Contains / or \\ (has path separator)    → folder if no file extension, else file
        - Ends with .extension (e.g., .md)         → file
        - Bare name (no dots, slashes, wildcards)  → folder in vault root

        File extension: a dot followed by 2-10 word chars at end of string,
        but NOT a leading dot (which indicates a dot-folder like .obsidian).
        """
        # Load from .blacklist file
        blacklist_items = cls._load_blacklist()

        # Also parse environment variables
        env_paths_str = os.getenv("IGNORED_PATHS", "")
        env_files_str = os.getenv("IGNORED_FILES", "")
        if env_paths_str:
            blacklist_items.extend(cls._parse_list_var(env_paths_str))
        if env_files_str:
            blacklist_items.extend(cls._parse_list_var(env_files_str))

        # Classify each item
        ignored_paths = []
        ignored_files = []
        patterns = []

        for item in blacklist_items:
            if not item or item.startswith("#"):
                continue

            raw = item.strip()
            normalized = raw.replace("\\", "/")

            ptype = cls._classify_pattern(normalized)

            # Normalize relative path prefixes for clean matching
            # (paths in the vault are relative without ./ prefix)
            match_path = normalized
            if match_path.startswith("./"):
                match_path = match_path[2:]
            elif match_path.startswith("../"):
                match_path = match_path[3:]

            compiled = cls._compile_pattern(match_path, ptype)

            if compiled is None:
                print(
                    f"[CONFIG] Skipping invalid blacklist pattern: {raw}",
                    file=sys.stderr,
                )
                continue

            patterns.append((raw, ptype, compiled))

            # Maintain legacy lists for backward compatibility
            if ptype in ("folder", "abs_folder"):
                ignored_paths.append(match_path.rstrip("/"))
            elif ptype == "file":
                ignored_files.append(raw)
            elif ptype == "glob":
                # Glob patterns affect both paths and files
                ignored_paths.append(match_path)
                ignored_files.append(raw)
            elif ptype == "abs_file":
                ignored_files.append(raw)

        cls.IGNORED_PATHS = sorted(list(set(ignored_paths)))
        cls.IGNORED_FILES = sorted(list(set(ignored_files)))
        cls._blacklist_patterns = patterns

        # Store current mtime for change detection
        if cls.BLACKLIST_FILE_PATH.exists():
            cls._blacklist_mtime = cls.BLACKLIST_FILE_PATH.stat().st_mtime
        else:
            cls._blacklist_mtime = None

        if Config.DEBUG:
            print(
                f"[CONFIG] Initialized blacklists: {len(patterns)} patterns "
                f"({len(cls.IGNORED_PATHS)} paths, {len(cls.IGNORED_FILES)} files)",
                file=sys.stderr,
            )
            if hasattr(Config, "DEBUG_VERBOSE") and Config.DEBUG_VERBOSE:
                for raw, ptype, _ in patterns:
                    print(f"[CONFIG]   [{ptype}] {raw}", file=sys.stderr)

    @classmethod
    def _classify_pattern(cls, normalized: str) -> str:
        """Classify a normalized (forward-slash) blacklist pattern.

        Returns one of: folder, file, glob, abs_folder, abs_file
        """
        # Ends with / → folder
        if normalized.endswith("/"):
            return "folder"

        # Contains * → glob
        if "*" in normalized:
            return "glob"

        # Starts with X:/ or // → absolute path (Windows drive or UNC)
        is_absolute = (
            len(normalized) >= 3
            and normalized[1] == ":"
            and normalized[2] == "/"
        ) or normalized.startswith("//")

        if is_absolute:
            # Check if it looks like a file (has extension at end)
            if cls._has_file_extension(normalized):
                return "abs_file"
            return "abs_folder"

        # Relative path with ./ or ../ prefix → strip prefix, classify remainder
        if normalized.startswith("./"):
            normalized = normalized[2:]
        elif normalized.startswith("../"):
            normalized = normalized[3:]

        # Contains / → has directory component
        has_separator = "/" in normalized

        # Check for file extension
        has_extension = cls._has_file_extension(normalized)

        if has_extension:
            return "file"
        elif has_separator:
            return "folder"
        else:
            # Bare name like "copilot" or ".obsidian" → folder in vault root
            return "folder"

    @classmethod
    def _has_file_extension(cls, path: str) -> bool:
        """Check if path ends with a file extension (. followed by 2-10 word chars).

        Returns False for dot-folders like .obsidian (leading dot, no second dot).
        A file extension requires a dot that is NOT at position 0.
        """
        # Match .extension at end: dot followed by 2-10 alphanumeric/underscore chars
        # The dot must NOT be at position 0 (that's a dot-folder)
        match = re.search(r"\.(\w{2,10})$", path)
        if match:
            # Check if this dot is at position 0 (dot-folder like .obsidian)
            dot_pos = match.start()
            return dot_pos > 0
        return False

    @classmethod
    def _compile_pattern(cls, normalized: str, ptype: str) -> Optional["re.Pattern"]:
        """Compile a pattern into a regex for matching.

        For glob patterns: * matches any characters including /
        For folder patterns: matches path prefix, nested component, or exact
        For file patterns: matches filename
        """
        try:
            if ptype == "glob":
                # Convert glob to regex: * → .* (matches anything including /)
                # Escape all regex special chars except *
                escaped = re.escape(normalized)
                # re.escape turns * into \*, so we need to unescape those
                escaped = escaped.replace(r"\*", ".*")
                # Glob patterns match anywhere in the path
                # Add leading .* unless pattern already starts with .*
                if not escaped.startswith(".*"):
                    escaped = ".*" + escaped
                # If glob contains path separators, it describes a directory path
                # and should also match any contents beneath it
                if "/" in normalized:
                    escaped += "(/.*)?"
                return re.compile("^" + escaped + "$", re.IGNORECASE)

            elif ptype in ("folder", "abs_folder"):
                # Folder patterns match as:
                # 1. Path starts with folder/
                # 2. Path equals folder exactly
                # 3. Path contains /folder/ as a complete directory segment
                clean = normalized.rstrip("/")
                escaped = re.escape(clean)
                # Match: ^folder/ or /folder/ or ^folder$ or ^folder$ (at root)
                pattern_str = (
                    f"^({escaped}/|{escaped}$|.*/{escaped}/|/{escaped}$)"
                )
                return re.compile(pattern_str, re.IGNORECASE)

            elif ptype in ("file", "abs_file"):
                # File patterns match the filename component
                filename = Path(normalized).name
                escaped = re.escape(filename)
                # Match filename exactly or as prefix (for partial name matching)
                return re.compile(f"^({escaped}|{re.escape(Path(normalized).stem)})", re.IGNORECASE)

            return None
        except re.error as e:
            print(
                f"[CONFIG] Invalid regex in pattern '{normalized}': {e}",
                file=sys.stderr,
            )
            return None

    @classmethod
    def reload_blacklist_if_changed(cls) -> bool:
        """Check if .blacklist file has been modified and reload if so.

        Returns True if blacklist was reloaded, False otherwise.
        """
        if not cls.BLACKLIST_FILE_PATH.exists():
            return False

        current_mtime = cls.BLACKLIST_FILE_PATH.stat().st_mtime

        if cls._blacklist_mtime is None or current_mtime > cls._blacklist_mtime:
            print(
                f"[CONFIG] Blacklist file changed, reloading...",
                file=sys.stderr,
            )
            cls._initialize_blacklists()
            print(
                f"[CONFIG] Blacklist reloaded: {len(cls.IGNORED_PATHS)} paths, {len(cls.IGNORED_FILES)} files",
                file=sys.stderr,
            )
            if Config.DEBUG:
                print(f"[CONFIG] IGNORED_PATHS: {cls.IGNORED_PATHS}", file=sys.stderr)
                print(f"[CONFIG] IGNORED_FILES: {cls.IGNORED_FILES}", file=sys.stderr)
            return True

        return False

    @classmethod
    def is_blacklisted(cls, rel_path: str, abs_path: str = "") -> str:
        """Check if a path should be excluded based on blacklist patterns.

        Args:
            rel_path: Relative path from vault root (e.g., "copilot/note.md")
            abs_path: Absolute path (optional, used for absolute pattern matching)

        Returns: The matching blacklist pattern string if excluded, empty string otherwise.
        """
        rel_normalized = rel_path.replace("\\", "/")

        for raw, ptype, compiled in cls._blacklist_patterns:
            if ptype in ("folder", "file", "glob"):
                # Match against relative path
                if compiled.search(rel_normalized):
                    return raw
                # For file patterns, also check just the filename
                if ptype == "file":
                    filename = Path(rel_normalized).name
                    if compiled.search(filename):
                        return raw
            elif ptype in ("abs_folder", "abs_file"):
                # Match against absolute path
                if abs_path:
                    abs_normalized = abs_path.replace("\\", "/")
                    if compiled.search(abs_normalized):
                        return raw
                    if ptype == "abs_file":
                        filename = Path(abs_normalized).name
                        if compiled.search(filename):
                            return raw

        return ""

