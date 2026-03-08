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
```

## Core Components

### 1. MCP Server Layer (`server.py`)

**Purpose:** Entry point for MCP protocol communication

**Responsibilities:**
- Initialize and manage MCP server instance
- Handle tool call routing
- Coordinate background tasks
- Manage multi-instance locking
- Handle file watching for sync
- Coordinate graceful shutdown

**Key Functions:**
- `list_tools()` - Exposes available MCP tools
- `call_tool()` - Routes tool calls to handlers
- `main()` - Server lifecycle management
- `_run_initial_sync()` - Background initial sync
- `_sync_takeover()` - Handle lock acquisition by secondary instance

### 2. Tool Handler Layer (`tools.py`)

**Purpose:** Business logic for all MCP tools

**Responsibilities:**
- Route tool calls to appropriate handlers
- Sync folders on first call
- Coordinate between database and Obsidian
- Enrich results with Obsidian URLs

**Tools Provided:**
1. `store_thought` - Store notes in both systems
2. `semantic_search` - Vector similarity search
3. `list_recent` - List recent thoughts
4. `get_thought` - Get specific thought by ID
5. `search_by_topic` - Topic-based search
6. `get_todos` - Retrieve todo items
7. `find_recipes` - Recipe search with filters
8. `list_guides` - Guide listing with filters
9. `get_contacts` - Contact lookup
10. `get_backlinks` - Get notes linking to a thought
11. `find_related_notes` - Find related via links/tags
12. `suggest_tags` - Tag suggestions based on content
13. `hybrid_search` - Advanced vector + keyword search

### 3. Database Layer (`database.py`)

**Purpose:** Supabase/PostgreSQL operations

**Responsibilities:**
- CRUD operations for thoughts
- Vector similarity search
- Tag management
- Link management (wiki-links)
- Folder metadata storage
- Backlink/outlink queries

**Key Tables:**
- `thoughts` - Main notes storage with embeddings
- `tags` - Tag definitions
- `thought_tags` - Many-to-many tag associations
- `folders` - Folder structure with embeddings
- `links` - Wiki-link relationships

**Important Methods:**
- `store_thought()` - Insert with embedding
- `semantic_search()` - Vector similarity via RPC
- `search_folders_by_embedding()` - Folder matching
- `sync_folders()` - Update folder metadata
- `get_backlinks()` - Reverse link lookup

### 4. Obsidian Layer (`obsidian.py`)

**Purpose:** Local markdown file management

**Responsibilities:**
- Create and organize markdown notes
- Intelligent folder selection using semantic analysis
- Folder structure scanning
- Wiki-link extraction from content
- Tag extraction from frontmatter

**Folder Selection Algorithm:**
1. Special cases (Recipes → Resources/Recipes, etc.)
2. Manual override via metadata
3. Exact topic match
4. Hierarchical semantic matching
5. Low confidence → ToSort

**Key Methods:**
- `create_note()` - Create markdown file
- `_determine_folder()` - Folder selection logic
- `sync_existing_notes_to_supabase()` - Initial sync
- `sync_changed_notes_to_supabase()` - Incremental sync
- `_find_semantic_folder_match()` - Hierarchical matching

### 5. Embedding Layer (`embeddings.py`)

**Purpose:** Vector embedding generation

**Responsibilities:**
- Generate embeddings for search queries
- Generate embeddings for notes
- Connection pool management
- Non-blocking async implementation

**Features:**
- OpenAI-compatible API (flexible providers)
- Thread pool execution (non-blocking)
- Connection warmup on startup
- Timeout: 240 seconds
- Retries: 3 attempts

### 6. Metadata Layer (`metadata.py`)

**Purpose:** AI-powered metadata extraction

**Responsibilities:**
- Extract thought type from content
- Identify topics/keywords
- Extract people mentions
- Extract action items
- Generate summaries

**Models:**
- Default: GLM-4.7 (via Z.AI)
- Configurable via METADATA_BASE_URL/METADATA_MODEL

### 7. Search Layer (`search.py`)

**Purpose:** Advanced search capabilities

**Responsibilities:**
- Hybrid vector + keyword search
- Faceted search (filters)
- Scoring and ranking
- Recency boosting

**Features:**
- Configurable weights (vector, keywords, recency)
- Multiple filter types (type, folder, tags, date)
- Combined scoring algorithm

### 8. Link Management Layer (`links.py`)

**Purpose:** Wiki-link relationship tracking

**Responsibilities:**
- Extract links from content
- Find backlinks (incoming)
- Find outlinks (outgoing)
- Find related notes
- Generate link graphs for visualization

### 9. Tag Management Layer (`tags.py`)

**Purpose:** Tag operations and suggestions

**Responsibilities:**
- Tag consolidation
- Tag suggestions based on content
- Semantic tag matching
- Tag hierarchy support

### 10. File Watcher Layer (`watcher.py`)

**Purpose:** Real-time file system monitoring

**Responsibilities:**
- Monitor Obsidian vault changes
- Debounce rapid changes
- Trigger incremental syncs
- Handle file moves/renames
- Detect deletions

**Technology:**
- watchdog library for file system events

### 11. Instance Lock Layer (`instance_lock.py`)

**Purpose:** Multi-instance coordination

**Responsibilities:**
- OS-level file locking (portalocker)
- Heartbeat mechanism
- Stale lock detection
- Automatic lock cleanup

**Configuration:**
- Lock file: `.server_lock`
- Heartbeat interval: 20 seconds
- Stale threshold: 60 seconds
- Retry interval: 30 seconds (with jitter)

### 12. Migration Layer (`migrate_sync.py`)

**Purpose:** Data migration and sync

**Responsibilities:**
- Vault migration from old sync system
- Hash-based change detection
- Bulk sync operations
- Conflict resolution

## Data Flow

### Storing a Thought

```
User Request
    ↓
Tool Handler (store_thought)
    ↓
Metadata Extractor → Get type, topics, people, etc.
    ↓
Embedding Generator → Create vector embedding
    ↓
Database Manager → Store in Supabase
    ↓
Obsidian Manager → Create markdown file
    ↓
Folder Selection → Intelligent placement
    ↓
File Write → Obsidian vault
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
Supabase RPC (vector_search)
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
Debounce (2 seconds)
    ↓
Hash Check → File changed?
    ↓
Embedding Generator → New embedding
    ↓
Database Manager → Update Supabase
    ↓
Extract Links/Tags → Update relationships
```

## Multi-Instance Coordination

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
- `EMBEDDING_MODEL` - Default: qwen3-embedding-8b
- `EMBEDDING_DIMENSIONS` - Default: 1536
- `METADATA_BASE_URL` - Default: Z.AI API
- `METADATA_MODEL` - Default: glm-4.7
- `OBSIDIAN_VAULT_PATH` - Default: ./SecondBrain

**Sync Configuration:**
- `SYNC_ENABLED` - Enable background sync (default: true)
- `SYNC_INITIAL_SYNC` - Run initial sync on startup (default: true)
- `SYNC_DEBOUNCE_SECONDS` - Debounce delay (default: 2.0s)
- `SYNC_FULL_SYNC_INTERVAL` - Periodic full sync interval (default: 3600s)

**Lock Configuration:**
- `LOCK_FILE_PATH` - Lock file location (default: .server_lock)
- `LOCK_RETRY_ENABLED` - Enable retry logic (default: true)
- `LOCK_RETRY_INTERVAL_SECONDS` - Retry interval (default: 30s)
- `LOCK_RETRY_JITTER_SECONDS` - Random jitter (default: 10s)
- `LOCK_HEARTBEAT_INTERVAL_SECONDS` - Heartbeat interval (default: 20s)
- `LOCK_STALE_THRESHOLD_SECONDS` - Stale detection (default: 60s)

**Search Configuration:**
- `SEARCH_VECTOR_WEIGHT` - Vector search weight (default: 0.7)
- `SEARCH_KEYWORD_WEIGHT` - Keyword search weight (default: 0.3)
- `SEARCH_RECENCY_WEIGHT` - Recency boost weight (default: 0.0)

## Error Handling Strategy

### API Errors
- Embeddings: 3 retries with 240s timeout
- Metadata: 240s timeout, errors logged
- Supabase: Automatic retries via client

### File System Errors
- Lock acquisition: Raises LockException
- File write: Logged, operation skipped
- File read: Logged, returns empty/default

### Database Errors
- Connection: Logged, operation fails gracefully
- Query: Logged, returns error message to user
- RPC not available: Falls back to direct SQL or recent items

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
- Blocking calls wrapped in thread pools
- Prevents event loop blocking

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
- Efficient similarity search with index
- Scales to millions of vectors

### File Watching
- Single process monitors vault
- Debounce reduces sync overhead
- Incremental sync only on changes

### Multi-Instance
- Single primary instance for writes
- Multiple secondary instances can read
- Automatic failover mechanism

## Future Enhancements

Potential areas for expansion:
1. Real-time streaming of search results
2. Webhook notifications for new thoughts
3. Plugin system for custom processors
4. Distributed note sharing
5. Advanced graph visualization
6. Mobile app sync via Supabase
7. Offline-first mode with sync queue
