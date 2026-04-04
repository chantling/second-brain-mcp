# Second Brain MCP Server - Architecture Documentation

## Overview

The Second Brain MCP Server is a knowledge management system that integrates **Supabase** (for vector storage and semantic search) with **Obsidian** (for local markdown storage). It implements the **Luca Decimal** organization system for intelligent note categorization.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     MCP Client (AI Assistant)                  │
└─────────────────────────┬─────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                   MCP Server (server.py)                       │
│  ┌───────────────────────────────────────────────────────┐   │
│  │              Tool Handlers (tools.py)                    │   │
│  │  - store_thought                                      │   │
│  │  - semantic_search                                    │   │
│  │  - list_recent                                        │   │
│  │  - ... (14 tools total)                                │   │
│  └───────────┬───────────────────────────┬───────────────┘   │
│              │                           │                       │
│              ▼                           ▼                       │
│  ┌──────────────────────┐    ┌──────────────────────┐        │
│  │  DatabaseManager    │    │  ObsidianManager     │        │
│  │  (database.py)     │    │  (obsidian.py)      │        │
│  └────────┬───────────┘    └────────┬───────────┘        │
│           │                         │                         │
└───────────┼─────────────────────────┼─────────────────────────┘
            │                         │
            ▼                         ▼
    ┌───────────────┐      ┌───────────────┐
    │   Supabase    │      │   Obsidian    │
    │  (PostgreSQL) │      │   (Markdown)  │
    │  + pgvector   │      │   Files       │
    └───────────────┘      └───────────────┘
            │                         │
            └────────┬────────────────┘
                     ▼
         ┌─────────────────┐
         │  External APIs │
         ├─────────────────┤
         │ Embeddings API │
         │ Metadata API  │
         └─────────────────┘

  Background Tasks:
  ┌─────────────────────────────────────────────────────────────────┐
  │ File Watcher (watcher.py) ──► PollingObserver (watchdog)       │
  │   ├─ on_created / on_modified / on_deleted / on_moved          │
  │   ├─ Debouncing, move detection, hash comparison               │
  │   ├─ LazyImport pattern for manager references                 │
  │   └─ Distributed lock (supabase_lock.py) before writes          │
  │                                                                 │
  │ Orphan Cleanup ──► Removes orphaned DB entries (4-case logic)  │
  │ Folder Sync ──► Syncs folder structure + embeddings             │
  │ Blacklist Watch ──► Reloads .blacklist on change               │
  │ Heartbeat ──► Verifies watchdog observer is alive              │
  └─────────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. MCP Server Layer (`server.py`)

**Purpose:** Entry point for MCP protocol communication

**Responsibilities:**
- Initialize and manage MCP server instance
- Handle tool call routing with 45-second timeout
- Coordinate background tasks (warmup, sync, orphan cleanup, heartbeat)
- Manage multi-instance locking (InstanceLock + SupabaseLock)
- Handle file watching for sync
- Coordinate graceful shutdown

**Key Functions:**
- `list_tools()` - Exposes 14 available MCP tools
- `call_tool()` - Routes tool calls to handlers with timeout protection
- `main()` - Server lifecycle management with signal handlers (SIGINT/SIGTERM)
- `_run_initial_sync()` - Background initial sync of all Obsidian notes
- `_run_folder_sync_startup()` - Sync folder structure on startup
- `_run_orphan_cleanup_startup()` - Cleanup orphaned DB entries after initial sync
- `_sync_takeover()` - Handle lock acquisition by secondary instance
- `_heartbeat_loop()` - Update heartbeat timestamp for lock coordination
- `_periodic_orphan_cleanup_loop()` - Run orphan cleanup every 10 minutes
- `_lock_retry_loop()` - Secondary instance retry logic with jitter

**Background Tasks:**
1. **Embedding warmup** - Non-blocking, pre-warms connection pool
2. **File watcher** - Monitors Obsidian vault for changes (if primary + SYNC_ENABLED)
3. **Initial sync** - Syncs all existing Obsidian notes to Supabase
4. **Folder sync** - Syncs folder structure with embeddings
5. **Orphan cleanup** - Removes DB entries without matching files (4-case logic)
6. **Periodic orphan cleanup** - Runs every 10 minutes
7. **Heartbeat** - Updates lock heartbeat every 20 seconds

### 2. Tool Handler Layer (`tools.py`)

**Purpose:** Business logic for all MCP tools

**Global Singletons:**
```python
db_manager = DatabaseManager()
obsidian_manager = ObsidianManager(Config.OBSIDIAN_VAULT_PATH, db_manager=db_manager)
embedding_generator = EmbeddingGenerator()
metadata_extractor = MetadataExtractor()
```

**Tools Provided (14 total):**
1. `store_thought` - Store notes in both systems with duplicate detection
2. `semantic_search` - Vector similarity search with topic filtering
3. `list_recent` - List recent thoughts by date/type
4. `get_thought` - Get specific thought by ID
5. `search_by_topic` - Topic-based search
6. `get_todos` - Retrieve todo items with completion filtering
7. `find_recipes` - Recipe search with ingredient/category/time filters
8. `list_guides` - Guide listing with category/difficulty filters
9. `get_contacts` - Contact lookup by name/category
10. `get_backlinks` - Get notes linking to a thought
11. `find_related_notes` - Find related via shared links and tags
12. `suggest_tags` - Tag suggestions based on content similarity
13. `hybrid_search` - Advanced vector + full-text + recency search
14. `search_by_keyword` - Full-text search using PostgreSQL tsvector

**Internal Methods:**
- `_sync_folders()` - Syncs Obsidian folder structure to DB
- `_store_new_thought()` - Core storage: folder determination, hash, Supabase + Obsidian
- `_handle_high_confidence_duplicate()` - Tier 1-2 duplicates (block/prompt/overwrite)
- `_handle_medium_confidence_duplicate()` - Tier 3 duplicates (store with warning)
- `cleanup()` - Closes async resources

**Duplicate Detection (3-tier):**
- **Tier 1 (High)**: Exact `video_id` match in metadata
- **Tier 2 (High)**: Exact URL match (basic normalization - trailing slash, lowercase domain, remove fragment)
- **Tier 3 (Medium)**: Heuristic URL match (tracking params removed: utm_*, fbclid, gclid, etc.)

**Notable Patterns:**
- All results enriched with `obsidian_url` (deep link to Obsidian)
- Semantic folder placement when `Config.SEMANTIC_FOLDER_PLACEMENT` is enabled
- File hash (SHA-256) computed for change detection
- Tags synced via `sync_tags_for_thought()` after every store operation
- 45-second overall timeout on tool calls

### 3. Database Layer (`database.py`)

**Purpose:** Supabase/PostgreSQL operations

**Class: `DatabaseManager`**

**Core Operations:**
| Method | Description |
|--------|-------------|
| `store_thought()` | Insert with content, embedding, metadata |
| `get_thought()` | Get thought by ID |
| `list_recent()` | Get recent thoughts with date/type filtering |
| `search_by_topic()` | Search by topic (JSONB array containment) |
| `get_todos()` | Get todo items with completion filtering |
| `update_thought()` | Update thought content, embedding, hash, metadata |
| `update_thought_content()` | Update thought in-place (for duplicate overwrites) |
| `update_obsidian_path()` | Update file path (for renames/moves) |
| `delete_thought_by_id()` | Cascading delete (thoughts + links + thought_tags) |
| `delete_thought_by_obsidian_path()` | Delete by file path |
| `get_thought_by_obsidian_path()` | Lookup by file path |
| `get_all_thoughts()` | Get all thoughts (for orphan cleanup) |

**Search Operations:**
| Method | Description |
|--------|-------------|
| `semantic_search()` | 3-level fallback: RPC `vector_search` -> direct SQL -> recent thoughts |
| `keyword_search()` | ILIKE pattern matching |
| `fulltext_search()` | PostgreSQL `text_search()` on `content_tsv` column, falls back to keyword |

**Folder Operations:**
| Method | Description |
|--------|-------------|
| `sync_folders()` | Upsert folders with embeddings |
| `search_folders_by_embedding()` | Cosine similarity search (numpy-based, client-side) |
| `get_all_folders()` | Get all folders |
| `delete_folder_by_path()` | Delete folder entry |

**Link Operations:**
| Method | Description |
|--------|-------------|
| `store_links()` | Store wiki-link relationships (delete old + insert new) |
| `get_backlinks()` | Get notes linking TO this thought |
| `get_outlinks()` | Get notes this thought links TO |

**Tag Operations:**
| Method | Description |
|--------|-------------|
| `sync_tags()` | Create tags if needed, update thought_tags junction table |

**Duplicate Detection:**
| Method | Description |
|--------|-------------|
| `check_for_duplicates()` | 3-tier: video_id -> exact URL -> heuristic URL |

**Standalone Functions:**
- `basic_normalize_url()` - Tier 2 normalization (trailing slash, lowercase domain, remove fragment)
- `heuristic_normalize_url()` - Tier 3 normalization (remove tracking params like utm_*, fbclid, gclid)
- `get_tracking_params()` - Returns set of known tracking parameters
- `transform_metadata_for_database()` - Maps `type` -> `thought_type`, separates standard fields from extra JSONB

**Notable Patterns:**
- All blocking Supabase calls wrapped in `asyncio.to_thread()` for async compatibility
- Timeout protection via `Config.DB_TIMEOUT`
- Extensive debug logging to `database_debug.log`

### 4. Obsidian Layer (`obsidian.py`)

**Purpose:** Local markdown file management

**Class: `ObsidianManager`**

**Note Creation:**
| Method | Description |
|--------|-------------|
| `create_note()` | Creates markdown file with YAML frontmatter |
| `_determine_folder()` | 5-priority folder selection |
| `_find_exact_folder()` | Exact folder name matching |
| `_find_semantic_match()` | Keyword-based folder matching with confidence scoring |
| `_find_semantic_folder_match()` | Hierarchical semantic search using embeddings (top-down traversal) |
| `_create_frontmatter()` | YAML frontmatter generation |
| `_sanitize_filename()` | Removes invalid filename characters |

**Folder Management:**
| Method | Description |
|--------|-------------|
| `sync_folders_to_database()` | Two-tier caching: local cache (7 days) -> DB -> generate new -> save cache |
| `_generate_folder_description()` | Creates description from folder hierarchy + sample note content |
| `_organize_folders_by_level()` | Groups folders by depth for hierarchical search |
| `_find_best_match_at_level()` | Cosine similarity search at a specific hierarchy level |
| `get_folder_stats()` | Statistics categorized by Luca Decimal system |

**Sync Operations:**
| Method | Description |
|--------|-------------|
| `sync_existing_notes_to_supabase()` | One-time import of all vault notes to Supabase |
| `sync_changed_notes_to_supabase()` | Hash-based incremental sync (for lock takeover) |
| `remove_orphaned_supabase_entries()` | 4-case cleanup: empty path, moved file, deleted file, mismatched supabase_id |

**Folder Embedding Cache:**
- Stored as markdown file `!Folder_Embeddings.md` in vault root
- Format: `|folder_path|embedding_vector|`
- Validity: 7 days (`CACHE_VALIDITY_DAYS`)

**Notable Patterns:**
- Luca Decimal folder organization system (1xx/2xx/3xx/4xx)
- Confidence scoring for folder placement (0.0-1.0)
- Special folders: `!To-Do!`, `Contacts`, `Resources/Recipes`, `!To-Sort!`
- Orphan cleanup uses distributed lock with extended TTL
- `_last_sync_result` class-level shared state for coordination with server.py

### 5. Embedding Layer (`embeddings.py`)

**Purpose:** Vector embedding generation

**Class: `EmbeddingGenerator`**
| Method | Description |
|--------|-------------|
| `create_embedding(text)` | Async wrapper around `_sync_create_embedding()` via `asyncio.get_running_loop().run_in_executor()` |
| `_sync_create_embedding(text)` | POST to `{base_url}/embeddings` with `requests` library |
| `warmup()` | Makes a test embedding to warm connection pool |
| `batch_create_embeddings(texts)` | Sequential embedding generation |
| `close()` | No-op (requests library manages connections) |

**Notable Patterns:**
- Text truncated to 8192 chars before embedding
- Uses `requests` (not async HTTP) for reliability, wrapped in executor
- Configurable model, dimensions, base URL
- Default: `qwen/qwen3-embedding-8b` via OpenRouter

### 6. Metadata Layer (`metadata.py`)

**Purpose:** AI-powered metadata extraction

**Class: `MetadataExtractor`**
| Method | Description |
|--------|-------------|
| `extract_metadata(content, title)` | Calls AI to extract: type, topics, people, action_items, summary, difficulty, estimated_time |
| `_generate_title(content)` | Extracts from markdown headers or first sentence |
| `_extract_video_id(content)` | Extracts from frontmatter or YouTube URL patterns |
| `_extract_url(content)` | Extracts from frontmatter or content URLs |
| `close()` | No-op (sync OpenAI client) |

**Extracted Metadata Schema:**
```json
{
  "type": "knowledge|todo|recipe|guide|contact|note|other",
  "topics": ["topic1", "topic2", ...],
  "people": ["person1", ...],
  "action_items": ["item1", ...],
  "summary": "...",
  "difficulty": "beginner|intermediate|advanced|not_applicable",
  "estimated_time": "minutes or not_applicable",
  "title": "...",
  "video_id": "...",
  "url": "..."
}
```

**Notable Patterns:**
- Content truncated to 4000 chars for cost efficiency
- 240-second timeout, 3 retries on API calls
- `video_id` and `url` extracted BEFORE AI call to preserve for duplicate detection
- Fallback metadata on API failure
- Default model: `glm-4.7` via z.ai API

### 7. Search Layer (`search.py`)

**Purpose:** Advanced search capabilities

**Class: `SearchManager`**
| Method | Description |
|--------|-------------|
| `hybrid_search(query, limit, filters, weights)` | Combines vector + full-text search with weighted scoring |
| `_combine_scores()` | Merges results, calculates `combined_score = vector*0.7 + keyword*0.3 + recency_boost` |
| `_apply_filters()` | Filters by thought_type, folder, tags, date_range |
| `_recency_boost()` | Exponential decay boost (30-day half-life, max 0.1) |
| `search_by_tags(tags, limit)` | Search thoughts by tag membership |

**Features:**
- Configurable weights (vector, keywords, recency)
- Multiple filter types (type, folder, tags, date)
- Combined scoring algorithm

### 8. Link Management Layer (`links.py`)

**Purpose:** Wiki-link relationship tracking

**Class: `LinkManager`**
| Method | Description |
|--------|-------------|
| `get_backlinks(thought_id)` | Notes linking TO this thought (delegates to DB) |
| `get_outlinks(thought_id)` | Notes this thought links TO (delegates to DB) |
| `find_related_notes(thought_id, limit)` | Notes connected via shared links, sorted by link count |
| `get_link_graph(thought_id, depth)` | Recursive graph exploration for visualization (nodes + edges) |

### 9. Tag Management Layer (`tags.py`)

**Purpose:** Tag operations and suggestions

**Class: `TagManager`**
| Method | Description |
|--------|-------------|
| `get_all_tags()` | Get all tags with usage counts (sorted by popularity) |
| `suggest_tags(content, limit)` | Generate embedding for content, compare with tag embeddings via cosine similarity |
| `consolidate_tags(old_tags, new_tag)` | Merge multiple tags into one |

### 10. Tag Utilities (`tag_utils.py`)

**Purpose:** Lightweight shared utility for tag extraction and syncing

**Function: `sync_tags_for_thought(db_manager, thought_id, content, topics)`**
- Extracts tags from `topics` list (frontmatter metadata)
- Extracts inline `#tags` from content body via regex `#(\w[\w-]*)`
- Calls `db_manager.sync_tags()` to update junction table

### 11. File Watcher Layer (`watcher.py`)

**Purpose:** Real-time file system monitoring with debouncing and move detection

**Class: `LazyImport`**
- Avoids circular dependencies by lazily loading managers
- Stores `db_manager`, `obsidian_manager`, `embedding_generator`, `metadata_extractor`, `supabase_lock`
- Uses weak references for event loop to prevent memory leaks
- `LazyImport.cleanup()` releases all references on shutdown

**Class: `ObsidianEventHandler(FileSystemEventHandler)`**

**Key State:**
- `_processing_files` - Set of files currently being processed (prevents duplicates)
- `_processing_lock` - Async lock for processing state
- `_debounce_queue` - Pending events with cancelable tasks
- `_skip_next_modify` - Files to skip (when watcher writes frontmatter)
- `_files_being_moved` - Tracks files in transit
- `_recent_deletes` - Tracks recent deletes for move detection (Windows workaround)
- `_move_event_queue` - Thread-safe async queue for move events
- `_deferred_move_queue` - Queue for moves that occur during processing

**Event Handlers:**
| Method | Description |
|--------|-------------|
| `on_created()` | New file or move destination. Detects moves via correlation with `_recent_deletes` |
| `on_modified()` | File content change. Debounced, skips self-inflicted writes |
| `on_deleted()` | File deletion. Tracks in `_recent_deletes` for move detection |
| `on_moved()` | File rename. Queues to async move queue for thread-safe processing |

**Processing Pipeline:**
1. `_debounce_event()` - Cancels previous task, schedules new one with delay
2. `_process_event_after_delay()` - Waits debounce delay, checks file-level lock, executes handler
3. `_handle_create()` - New note: reads content, extracts metadata, generates embedding, stores to Supabase
4. `_handle_modify()` - Modified note: checks hash, updates if changed, creates if missing
5. `_handle_delete()` - Hard delete from Supabase
6. `_handle_move()` - Updates `obsidian_path` in DB, updates frontmatter with supabase_id

**Move Detection (Windows workaround):**
- On Windows, `watchdog` fires `delete + create` instead of `on_moved()`
- Correlates by filename matching within 2-second window
- Uses `_recent_deletes` dict to track pending deletes

**Background Tasks:**
| Task | Interval | Purpose |
|------|----------|---------|
| `_cleanup_timer_loop()` | 30s | Cleans stale delete/move tracking entries |
| `_blacklist_watch_loop()` | 30s | Reloads blacklist if `.blacklist` file changed |
| `_observer_heartbeat_loop()` | 30s | Verifies watchdog observer is still alive |
| `_process_deferred_moves()` | Continuous | Processes moves deferred during active file processing |
| `_process_move_queue()` | Continuous | Thread-safe move event processing |

**Function: `start_file_watcher()`**
- Creates `ObsidianEventHandler`, initializes `LazyImport` with managers
- Starts `PollingObserver` (60s timeout) with recursive monitoring
- Returns tuple: `(observer, cleanup_task, move_processor_task, heartbeat_task, deferred_move_task, blacklist_watch_task)`

### 12. Instance Lock Layer (`instance_lock.py`)

**Purpose:** OS-level file locking for multi-instance coordination

**Class: `InstanceLock`**
- Lock file: `.server_lock` in the same directory as the script
- Uses `portalocker.LOCK_EX | portalocker.LOCK_NB` for exclusive non-blocking locks
- Lock file contains JSON: `{pid, start_time, last_heartbeat, instance_id, status}`

**Key Methods:**
| Method | Description |
|--------|-------------|
| `acquire_lock()` | Blocking exclusive lock |
| `acquire_lock_nonblocking()` | Non-blocking attempt |
| `release_lock()` | Unlock and delete lock file |
| `is_locked()` | Check if lock is held |
| `update_heartbeat()` | Update heartbeat timestamp |
| `is_lock_stale()` | Check if heartbeat exceeds threshold |
| `cleanup_stale_lock()` | Clean up and acquire stale lock |

### 13. Supabase Lock Layer (`supabase_lock.py`)

**Purpose:** Cross-instance coordination via Supabase `server_lock` table (singleton row, id=1)

**Class: `SupabaseLock`**

**Key Methods:**
| Method | Description |
|--------|-------------|
| `acquire(operation, ttl_seconds)` | Atomic lock via RPC `acquire_lock` or direct table UPDATE |
| `release()` | Release lock if we hold it (WHERE instance_id matches) |
| `renew(ttl_seconds)` | Extend TTL while holding lock |
| `start_auto_renew()` | Background task to periodically renew |
| `stop_auto_renew()` | Cancel auto-renew task |
| `force_acquire()` | Unconditionally take lock (for stale lock recovery) |
| `is_held()` | Check if any instance holds a non-expired lock |
| `get_lock_info()` | Get current lock state for diagnostics |

**Lock Table Schema:**
- `id` (primary key, singleton = 1)
- `instance_id`, `hostname`, `pid`, `acquired_at`, `expires_at`, `operation`

**Notable Patterns:**
- TTL-based auto-expiration prevents deadlocks from crashed instances
- PostgreSQL row-level locking ensures atomicity
- Auto-renew background task runs at `LOCK_HEARTBEAT_INTERVAL`

### 14. Configuration Layer (`config.py`)

**Purpose:** Centralized configuration loaded from `.env` file with validation and blacklist management

**Blacklist System:**
- Loads from `.blacklist` file (one pattern per line, supports comments)
- Classifies patterns into 5 types: `folder`, `file`, `glob`, `abs_folder`, `abs_file`
- Compiles each to a regex for efficient matching
- Supports runtime reload via `Config.reload_blacklist_if_changed()`
- `Config.is_blacklisted(rel_path, abs_path)` checks if a path should be excluded

**Key Methods:**
- `Config.validate()` - Validates required env vars, initializes blacklists
- `Config._classify_pattern()` - Classifies blacklist patterns by type
- `Config._compile_pattern()` - Compiles patterns to regex
- `Config.is_blacklisted()` - Checks if a path matches any blacklist pattern

### 15. Utility Scripts

| Script | Purpose |
|--------|---------|
| `manual_sync.py` | Standalone script to manually trigger initial sync of all existing Obsidian notes |
| `backfill_thought_tags.py` | Scans all existing thoughts and populates `thought_tags` junction table |
| `verify.py` | Validates configuration, vault path, sync settings, and module imports |

## Data Flow

### Storing a Thought

```
User Request
    ↓
Tool Handler (store_thought)
    ↓
Metadata Extractor → Get type, topics, people, etc. (AI-powered)
    ↓
Embedding Generator → Create vector embedding
    ↓
Duplicate Detection → 3-tier check (video_id, URL exact, URL heuristic)
    ↓
Database Manager → Store in Supabase
    ↓
Tag Sync → Extract tags from content + frontmatter, update thought_tags
    ↓
Obsidian Manager → Create markdown file with frontmatter
    ↓
Folder Selection → Intelligent placement (5-priority algorithm)
    ↓
File Write → Obsidian vault
    ↓
Update DB with obsidian_path
    ↓
Return success with IDs and path
```

### Semantic Search

```
User Query
    ↓
Tool Handler (semantic_search)
    ↓
Embedding Generator → Create query embedding
    ↓
Database Manager → Vector similarity search
    ↓
Supabase RPC (vector_search) → Fallback: direct SQL → Fallback: recent thoughts
    ↓
Results with similarity scores
    ↓
Enrich with Obsidian URLs
    ↓
Return ranked results
```

### File Sync (Background)

```
File System Event (watchdog)
    ↓
Obsidian Event Handler
    ↓
Debounce (configurable delay, default 2s)
    ↓
Hash Check → File changed?
    ↓
Embedding Generator → New embedding
    ↓
Database Manager → Update Supabase
    ↓
Extract Links/Tags → Update relationships
    ↓
Update frontmatter with supabase_id
```

## Multi-Instance Coordination

**Two-Tier Locking:**

1. **InstanceLock** (`instance_lock.py`):
   - OS-level file locking via `portalocker`
   - Lock file: `.server_lock`
   - Heartbeat every 20s, stale after 60s

2. **SupabaseLock** (`supabase_lock.py`):
   - Distributed DB lock via `server_lock` table
   - TTL-based auto-expiration
   - Auto-renew background task

**Primary Instance:**
- Acquires file lock
- Runs file watcher
- Performs syncs
- Sends heartbeats every 20s
- Handles tool calls

**Secondary Instance:**
- Fails to acquire lock
- Runs in read-only mode
- Retries lock every 30s (+ jitter)
- Takes over if primary dies
- Starts file watcher and sync on takeover

## Configuration

All configuration via environment variables (see `config.py`):

**Required:**
- `SUPABASE_URL` - Database endpoint
- `SUPABASE_SECRET_KEY` - Service role key
- `SUPABASE_PUBLISH_KEY` - Anon/public key
- `EMBEDDING_API_KEY` - For embeddings
- `METADATA_API_KEY` - For metadata extraction

**Optional (with defaults):**
- `EMBEDDING_BASE_URL` - Default: OpenRouter
- `EMBEDDING_MODEL` - Default: `qwen/qwen3-embedding-8b`
- `EMBEDDING_DIMENSIONS` - Default: 1536
- `METADATA_BASE_URL` - Default: z.ai API
- `METADATA_MODEL` - Default: `glm-4.7`
- `OBSIDIAN_VAULT_PATH` - Default: `./SecondBrain`
- `SEMANTIC_FOLDER_PLACEMENT` - Enable semantic folder placement (default: false)

**Sync Configuration:**
- `SYNC_ENABLED` - Enable background sync (default: true)
- `SYNC_INITIAL_SYNC` - Run initial sync on startup (default: true)
- `SYNC_DEBOUNCE_SECONDS` - Debounce delay (default: 2.0s)
- `SYNC_FULL_SYNC_INTERVAL` - Periodic full sync interval (default: 3600s)
- `SYNC_EXCLUDE_PATTERNS` - Comma-separated exclude patterns

**Lock Configuration:**
- `LOCK_FILE_NAME` - Lock file name (default: `.server_lock`)
- `LOCK_RETRY_ENABLED` - Enable retry logic (default: true)
- `LOCK_RETRY_INTERVAL_SECONDS` - Retry interval (default: 30s)
- `LOCK_RETRY_JITTER_SECONDS` - Random jitter (default: 10s)
- `LOCK_HEARTBEAT_INTERVAL_SECONDS` - Heartbeat interval (default: 20s)
- `LOCK_STALE_THRESHOLD_SECONDS` - Stale detection (default: 60s)

**Search Configuration:**
- `SEARCH_VECTOR_WEIGHT` - Vector search weight (default: 0.7)
- `SEARCH_KEYWORD_WEIGHT` - Keyword search weight (default: 0.3)
- `SEARCH_RECENCY_WEIGHT` - Recency boost weight (default: 0.0)

**Full-Text Search Configuration:**
- `FTS_LANGUAGE` - PostgreSQL FTS language (default: english)
- `FTS_MIN_WORD_LENGTH` - Minimum word length for FTS (default: 3)

**Database Configuration:**
- `DB_TIMEOUT` - Database operation timeout in seconds (default: 10)

**Duplicate Handling:**
- `DUPLICATE_HANDLING_MODE` - Mode: prompt/skip/overwrite (default: prompt)
- `DUPLICATE_USE_TASKS` - Use MCP Tasks for duplicate resolution (default: false)
- `DUPLICATE_TRACKING_PARAMS` - Custom tracking params for URL normalization

**Debug Configuration:**
- `DEBUG` - Enable debug output (default: false)
- `DEBUG_VERBOSE` - Enable verbose debug output (default: true)
- `FILE_LOGGING` - Log to file in Logs/ directory (default: false)

## Error Handling Strategy

### API Errors
- Embeddings: 3 retries with 240s timeout
- Metadata: 240s timeout, 3 retries, fallback metadata on failure
- Supabase: Automatic retries via client

### File System Errors
- Lock acquisition: Raises `LockException`
- File write: Logged, operation skipped
- File read: Logged, returns empty/default

### Database Errors
- Connection: Logged, operation fails gracefully
- Query: Logged, returns error message to user
- RPC not available: Falls back to direct SQL or recent items
- Timeout: All operations protected by `Config.DB_TIMEOUT`

### Tool Call Errors
- 45-second overall timeout (to beat MCP Inspector's 60s default)
- Returns error message to client on timeout or exception
- Orphan cleanup runs after each tool call (non-blocking, best-effort)

## Performance Considerations

### Connection Pooling
- Embedding API: Pre-warmed on startup (~1-2s)
- Supabase: Managed by Supabase client
- Subsequent calls reuse connections

### Caching
- Folder embeddings: Local cache file (`!Folder_Embeddings.md`)
- Valid for 7 days before refresh
- Reduces API calls for folder matching

### Async/Await
- All I/O operations are async
- Blocking calls wrapped in `asyncio.to_thread()`
- Prevents event loop blocking

### Full-Text Search
- PostgreSQL `tsvector` column with GIN index
- O(1) lookups for exact word matching
- Falls back to ILIKE keyword search if FTS unavailable

## Security

### API Keys
- Stored in `.env` file (not in git)
- Loaded via `python-dotenv`
- Secret key for Supabase operations

### File Locking
- OS-level locking prevents concurrent writes
- Lock file contains process ID and heartbeat
- Automatic cleanup of stale locks

### SQL Injection
- Parameterized queries via Supabase client
- No raw SQL construction (except in RPC fallback)
- User input properly escaped

## Scalability

### Vector Search
- Supabase uses pgvector extension
- Efficient similarity search with IVFFlat index
- Scales to millions of vectors

### File Watching
- Single process monitors vault
- Debounce reduces sync overhead
- Incremental sync only on changes
- SHA-256 hash comparison for change detection

### Multi-Instance
- Single primary instance for writes
- Multiple secondary instances can read
- Automatic failover mechanism
- Two-tier locking (OS-level + database)

## Future Enhancements

Potential areas for expansion:
1. Real-time streaming of search results
2. Webhook notifications for new thoughts
3. Plugin system for custom processors
4. Distributed note sharing
5. Advanced graph visualization
6. Mobile app sync via Supabase
7. Offline-first mode with sync queue
8. Support for additional AI providers for embeddings/metadata
