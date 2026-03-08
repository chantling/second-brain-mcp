# Second Brain MCP Server

A Model Context Protocol (MCP) server that integrates Supabase (for vector storage and semantic search) with Obsidian (for local knowledge management), using the **Luca Decimal** organization system.

## 📚 Documentation

For comprehensive documentation, see the **[Docs/](Docs/)** folder:

- **[📖 Docs/README.md](Docs/README.md)** - Documentation index and quick links
- **[🏗️ Docs/architecture/ARCHITECTURE.md](Docs/architecture/ARCHITECTURE.md)** - System architecture and design
- **[🔧 Docs/api/TOOLS_REFERENCE.md](Docs/api/TOOLS_REFERENCE.md)** - Complete API reference
- **[💾 Docs/database/SCHEMA.md](Docs/database/SCHEMA.md)** - Database schema documentation
- **[🎯 Docs/guides/DEVELOPMENT.md](Docs/guides/DEVELOPMENT.md)** - Development and contribution guide
- **[🧪 Docs/guides/TESTING.md](Docs/guides/TESTING.md)** - Testing procedures
- **[🔍 Docs/guides/TROUBLESHOOTING.md](Docs/guides/TROUBLESHOOTING.md)** - Troubleshooting common issues

## Features

- **Intelligent Folder Detection**: Automatically scans your Obsidian vault and learns your folder structure
- **Confidence-Based Matching**: Uses semantic analysis to determine the best folder for each note
- **Luca Decimal Support**: Respects numbered folder conventions (1xx=Projects, 2xx=Areas, 3xx=Resources)
- **Subfolder Matching**: Can place notes in nested folders (e.g., "Resources/Electronics/Arduino")
- **ToSort Fallback**: Low-confidence matches go to ToSort for manual organization
- **Manual Override**: Specify exact folder via metadata when needed
- **Special Cases**: Recipes, Todos, and Contacts handled automatically
- **Full-Text Search**: Fast exact word matching using PostgreSQL tsvector with GIN index
- **Hybrid Search**: Combines semantic similarity (vector embeddings) with full-text search
- **Timeout Protection**: All database operations protected with configurable timeouts
- **Multi-Instance Coordination**: Multiple server instances can run safely with automatic failover
- **Hash-Based Sync**: Efficient change detection using file hashes for background sync

## Luca Decimal System

This server implements the [Luca Decimal](https://github.com/lucafrance/luca-decimal) organization system:

### Folder Structure

The server works with any folder structure you have, including:

```
vault/
├── Meta/           # Obsidian-specific content
├── To-Do/          # Todo items
├── Contacts/        # Contact information
├── Projects/        # Time-limited actions (1xx)
├── Areas/           # Regular activities (2xx)
├── Resources/       # Reference information (3xx)
├── Archive/         # Completed projects (4xx)
└── ToSort/         # Unsorted items
```

**No folders are hardcoded** - the server adapts to whatever structure you use.

### Numbered Folders

- **1xx (Projects)**: Time-limited actions (e.g., "100 Learn Python", "101 Taxes 2022")
- **2xx (Areas)**: Regular activities (e.g., "200 Health", "201 Finances")
- **3xx (Resources)**: Reference information (e.g., "300 Electronics", "301 Software")
- **4xx (Archive)**: Completed projects

The system distinguishes between numbered folders (300 Electronics vs 301 Software).

## How It Works

### Folder Selection Algorithm

1. **Special Cases (100% confidence)**
   - Recipes → `Resources/Recipes`
   - Todos → `To-Do`
   - Contacts → `Contacts`

2. **Manual Override (100% confidence)**
   - If `folder` specified in metadata, use it exactly

3. **Exact Match (100% confidence)**
   - Topic matches folder name exactly
   - Example: Topic "health" → "Health & Longevity"

4. **Semantic Matching (0.6-0.9 confidence)**
   - Analyzes content and topics
   - Matches keywords to folder names
   - Checks folder numbering context

5. **Threshold Application**
   - Confidence ≥ 0.7: Use matched folder
   - Confidence < 0.7: Place in `ToSort`

### Examples

**High Confidence Match (0.85+):**
```
Content: "How to solder components"
Topics: ["electronics", "soldering"]
→ Resources/Electronics
```

**Medium Confidence Match (0.75):**
```
Content: "My blood pressure reading"
Topics: ["health"]
→ Areas/Health & Longevity
```

**Low Confidence - ToSort (0.30):**
```
Content: "Interesting article about quantum computing"
Topics: ["quantum", "computing"]
→ ToSort
```

## Installation

1. **Clone or navigate to the project directory:**
   ```bash
   cd d:/Programs/AI/!MCPServers!/!Second_Brain!
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv venv
   ```

3. **Activate the virtual environment:**
   ```bash
   venv\Scripts\activate
   ```

4. **Install dependencies:**
   ```bash
   venv\Scripts\python -m pip install -r second-brain-mcp/requirements.txt
   ```

## Configuration

1. **Create a `.env` file in `second-brain-mcp/`:**
    ```env
    # Supabase Configuration
    SUPABASE_URL=your_supabase_project_url
    SUPABASE_SECRET_KEY=your_supabase_service_role_key
    SUPABASE_PUBLISH_KEY=your_supabase_anon_key

    # Embedding & Metadata Configuration
    EMBEDDING_API_KEY=your_embedding_api_key
    EMBEDDING_BASE_URL=https://openrouter.ai/api/v1
    EMBEDDING_MODEL=qwen/qwen3-embedding-8b
    EMBEDDING_DIMENSIONS=1536
    METADATA_API_KEY=your_metadata_api_key

    # Obsidian Configuration
    OBSIDIAN_VAULT_PATH=./SecondBrain

    # Sync Configuration
    SYNC_ENABLED=true
    SYNC_INITIAL_SYNC=true
    SYNC_DEBOUNCE_SECONDS=2.0
    SYNC_FULL_SYNC_INTERVAL=3600

    # Instance Lock Configuration
    LOCK_RETRY_ENABLED=true
    LOCK_RETRY_INTERVAL_SECONDS=30
    LOCK_RETRY_JITTER_SECONDS=10
    LOCK_HEARTBEAT_INTERVAL_SECONDS=20
    LOCK_STALE_THRESHOLD_SECONDS=60

    # Search Configuration
    SEARCH_VECTOR_WEIGHT=0.7
    SEARCH_KEYWORD_WEIGHT=0.3
    SEARCH_RECENCY_WEIGHT=0.0

    # Full-Text Search Configuration
    DB_TIMEOUT=10
    FTS_LANGUAGE=english
    FTS_MIN_WORD_LENGTH=3

    # Debug Configuration
    DEBUG=false
    ```

   **Get API keys:**
   - Supabase: From your project settings
   - **Flexible Configuration**: Supports multiple providers (OpenRouter, OpenAI, Z.AI, etc.)
   - **📖 See [CONFIGURATION_GUIDE.md](CONFIGURATION_GUIDE.md) for detailed setup and provider switching options.**

2. **Update your Obsidian vault path** to point to your actual vault.

## MCP Configuration

### Cline (VSCode Extension)

Add to your Cline MCP settings file (`~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`):

```json
{
  "mcpServers": {
    "second-brain": {
      "autoApprove": [],
      "disabled": false,
      "timeout": 300,
      "type": "stdio",
      "command": "PATH_TO_VENV_PYTHON",
      "args": [
        "PATH_TO_SERVER_PY"
      ]
    }
  }
}
```

**Replace:**
- `PATH_TO_VENV_PYTHON` - Full path to your virtual environment's Python executable (e.g., `d:\\Programs\\AI\\!MCPServers!\\!Second_Brain!\\venv\\Scripts\\python.exe`)
- `PATH_TO_SERVER_PY` - Full path to the server script (e.g., `d:\\Programs\\AI\\!MCPServers!\\!Second_Brain!\\second-brain-mcp\\server.py`)

**Note:** Cline uses **seconds** for timeout (300 = 5 minutes)

### Opencode (CLI/TUI)

Add to your Opencode config file (`~/.config/opencode/opencode.json`):

```json
{
  "mcp": {
    "second-brain": {
      "type": "local",
      "command": ["PATH_TO_VENV_PYTHON", "PATH_TO_SERVER_PY"],
      "timeout": 300000,
      "enabled": true
    }
  }
}
```

**Replace:**
- `PATH_TO_VENV_PYTHON` - Full path to your virtual environment's Python executable (e.g., `d:\\Programs\\AI\\!MCPServers!\\!Second_Brain!\\venv\\Scripts\\python.exe`)
- `PATH_TO_SERVER_PY` - Full path to the server script (e.g., `d:\\Programs\\AI\\!MCPServers!\\!Second_Brain!\\second-brain-mcp\\server.py`)

**Note:** Opencode uses **milliseconds** for timeout (300000 = 5 minutes)

### MCP Inspector Testing

To test your server configuration using MCP Inspector:

```bash
# From the parent directory
npx @modelcontextprotocol/inspector --cli PATH_TO_VENV_PYTHON PATH_TO_SERVER_PY --method tools/list

# Example:
npx @modelcontextprotocol/inspector --cli venv/Scripts/python.exe second-brain-mcp/server.py --method tools/list
```

## Available MCP Tools

### Core Tools

- **store_thought**: Store a thought in both Supabase and Obsidian
- **semantic_search**: Search thoughts by semantic similarity (vector embeddings)
- **search_by_keyword**: Search for exact words/phrases in note content using full-text search
- **hybrid_search**: Advanced search combining vector similarity + full-text search + filters
- **list_recent**: List recent thoughts from both systems
- **get_thought**: Get a specific thought by ID

### Search & Retrieval

- **search_by_topic**: Search thoughts by specific topic tag
- **get_backlinks**: Get all notes that link to this thought
- **find_related_notes**: Find related notes via shared links and tags
- **suggest_tags**: Suggest tags based on content using semantic similarity

### Specialized Content

### store_thought
Store a thought in both Supabase and Obsidian.

**Parameters:**
- `content` (required): The thought content
- `title` (optional): Title for the thought
- `metadata` (optional): Metadata dictionary
  - `type`: "knowledge", "recipe", "todo", "contact", "guide"
  - `topics`: List of topic tags
  - `people`: List of people mentioned
  - `folder`: Override automatic folder selection
- `source` (optional): Source of the thought (default: "manual")

**Returns:**
```json
{
  "success": true,
  "supabase_id": 123,
  "obsidian_path": "Resources/Electronics/2026-03-02-Circuit-Design.md",
  "message": "Thought stored successfully in both systems"
}
```

### semantic_search
Search thoughts by semantic similarity.

**Parameters:**
- `query` (required): Search query
- `limit` (optional): Maximum results (default: 10)
- `topics` (optional): Filter by topics

**Returns:** List of matching thoughts with similarity scores

### list_recent
List recent thoughts from both systems.

**Parameters:**
- `days` (optional): Number of days to look back (default: 7)
- `thought_type` (optional): Filter by thought type

**Returns:** List of recent thoughts

### get_thought
Get a specific thought by ID.

**Parameters:**
- `thought_id` (required): Thought ID

**Returns:** Complete thought details

### search_by_topic
Search thoughts by specific topic.

**Parameters:**
- `topic` (required): Topic to search for
- `limit` (optional): Maximum results (default: 20)

**Returns:** List of matching thoughts

### get_todos
Get todo items.

**Parameters:**
- `completed` (optional): Include completed todos (default: false)

**Returns:** List of todo items

### find_recipes
Find recipes based on criteria.

**Parameters:**
- `ingredients` (optional): List of required ingredients
- `category` (optional): Recipe category
- `max_time` (optional): Maximum total time in minutes

**Returns:** List of matching recipes

### list_guides
List guides by category and difficulty.

**Parameters:**
- `category` (optional): Guide category
- `difficulty` (optional): Difficulty level (easy, medium, hard)

**Returns:** List of guides

### get_contacts
Get contact information.

**Parameters:**
- `name` (optional): Name to search for
- `category` (optional): Contact category

**Returns:** List of contacts

## Usage Examples

### Store a Health Note
```python
store_thought(
    content="Blood pressure reading: 120/80, normal range",
    title="BP Check",
    metadata={
        "type": "knowledge",
        "topics": ["health", "blood_pressure"]
    }
)
# Automatically places in: Areas/Health & Longevity
```

### Store a Recipe
```python
store_thought(
    content="Ingredients: 2 eggs, flour, milk...",
    title="Pancakes",
    metadata={
        "type": "recipe",
        "topics": ["breakfast", "dessert"]
    }
)
# Automatically places in: Resources/Recipes
```

### Store with Manual Folder Override
```python
store_thought(
    content="Project notes for roof repair",
    title="Roof Repair",
    metadata={
        "type": "knowledge",
        "topics": ["construction"],
        "folder": "Projects/102-Roof-Repair"
    }
)
# Forces placement in: Projects/102-Roof-Repair
```

### Semantic Search
```python
semantic_search(
    query="how to solder components",
    limit=5
)
# Returns notes about electronics, soldering, circuits
```

## Testing

Test your configuration:
```bash
cd second-brain-mcp
..\venv\Scripts\python test_import.py
```

Test the Obsidian integration:
```bash
cd second-brain-mcp
..\venv\Scripts\python test_obsidian.py
```

## Architecture

- **Supabase**: Stores thoughts, tags, folders, and links with vector embeddings for semantic search
- **Obsidian**: Stores local markdown files for manual editing
- **z.ai / OpenRouter**: Extracts metadata and generates embeddings for semantic similarity
- **MCP Protocol**: Provides tools for AI assistants to interact with your knowledge
- **PostgreSQL pgvector**: Vector similarity search for semantic matching
- **PostgreSQL Full-Text Search**: Exact word matching with GIN indexes (tsvector)
- **Multi-Instance Locking**: OS-level file locking for safe concurrent operation
- **Hash-Based Sync**: Efficient change detection using SHA-256 file hashes

### Database Schema

The system uses five main tables:

1. **thoughts** - Main storage for notes, recipes, todos, contacts, guides
2. **tags** - Tag definitions with optional vector embeddings
3. **thought_tags** - Many-to-many relationship between thoughts and tags
4. **folders** - Folder structure with embeddings for semantic placement
5. **links** - Wiki-link relationships (backlinks) between thoughts

### Search Capabilities

Three search strategies are available:

1. **Semantic Search** - Vector-based similarity using embeddings (good for concepts)
2. **Full-Text Search** - Exact word matching using PostgreSQL tsvector (good for specific terms)
3. **Hybrid Search** - Combines semantic + full-text with configurable weights

### Timeout & Performance

- All database operations protected with 10-second timeout (configurable)
- Blocking operations moved to thread pool to prevent event loop blocking
- Connection warmup on server startup prevents first-call latency
- GIN indexes provide O(1) lookups for full-text search

## Recent Improvements

### Full-Text Search Implementation (2026-03-07)

- **Added PostgreSQL full-text search** using tsvector column
- **Created GIN index** on content_tsv for O(1) word lookups
- **New search_by_keyword tool** for exact word/phrase matching
- **Enhanced hybrid_search** now combines vector + full-text search
- **Fixed timeout issues** - All database operations now complete in < 3 seconds
- **Added timeout protection** - Configurable 10-second timeout with fallback to ILIKE
- **Added database warmup** - Connection pooling prevents first-call latency
- **Improved error logging** - Detailed error messages for better debugging

**Performance Improvements:**
- Before: hybrid_search timed out after 60s
- After: hybrid_search completes in 1.4s (42x faster)
- Full-text search: 0.26s for exact word matches
- Storage overhead: Only 7.8% increase (~2.4 KB per 10 KB thought)

See **[FULLTEXT_SEARCH_TEST_REPORT.md](FULLTEXT_SEARCH_TEST_REPORT.md)** for detailed testing results.

### Multi-Instance Coordination

- **OS-level file locking** using portalocker
- **Automatic failover** - Secondary instances take over if primary crashes
- **Hash-based sync** - Efficient change detection during takeover
- **Heartbeat mechanism** - 20-second intervals with stale detection
- **Configurable retry** - 30s interval with random jitter

See **[IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md)** for complete implementation details.

## Known Issues

### Multiple Client Startup Delays

**Symptom:**
When running multiple MCP clients (e.g., Opencode and Cline) simultaneously, each new client connection may trigger folder synchronization, causing 60+ second delays on first tool calls.

**Root Cause:**
Previously, folder sync was triggered on the first tool call from each client. The `_folders_synced` flag was a module-level global variable in `tools.py`. Multiple clients shared the same server process and module instance, but timing differences could cause multiple clients to attempt sync before the first completed.

**Current Behavior (after fixes):**
- Folder sync now runs at server startup (non-blocking background task)
- The server instance lock (via `instance_lock.py`) ensures only the primary instance runs folder sync
- Secondary instances operate in read-only mode and don't sync folders
- All clients benefit from the single folder sync that completes on startup

**Potential Inefficiency:**
- If folder sync takes longer than expected, clients starting during sync might still attempt sync
- In practice, this is mostly a performance concern rather than correctness
- The folder sync operation is idempotent (safe to run multiple times)

**Future Mitigation Options (if this becomes problematic):**
1. Add `asyncio.Lock()` to protect synchronization state for thread-safe access
2. Add state checks at sync function start: `if sync_already_running: return`
3. Track sync status in shared location (database or lock file) instead of module variable

**Current Status:**
- Not actively addressed since folder sync has moved to startup (non-blocking background task)
- Documented here for reference if performance issues resurface
- Monitoring recommended after startup to verify behavior

## Troubleshooting


### Database Setup

For new installations, run the complete database initialization script:

```bash
# Run each SQL block from README_SQL.md in Supabase SQL Editor
# Or use: second-brain-mcp/README_SQL.md
```

The script includes:
- All table schemas (thoughts, tags, folders, links, thought_tags)
- All indexes (vector similarity, full-text search, GIN indexes)
- All RPC functions (vector_search, execute_sql, search_thoughts_by_text)
- All triggers (automatic timestamps, content_tsv updates)
- Verification queries to confirm setup

See **[README_SQL.md](README_SQL.md)** for complete database initialization script.

### Import Errors
If you get `ModuleNotFoundError`, make sure:
1. Virtual environment is activated
2. Dependencies are installed: `venv\Scripts\python -m pip install -r second-brain-mcp/requirements.txt`

### Folder Not Found
The server automatically creates:
- `To-Do`
- `Contacts`
- `Resources/Recipes`
- `ToSort`

If other folders are missing, create them manually in Obsidian.

### Low Confidence Matches
Notes with low confidence (< 0.7) go to `ToSort`. Review these periodically and move them manually.

## License

This project is part of the Second Brain MCP Server implementation.

## References

### Documentation

- **[README_SQL.md](README_SQL.md)** - Complete database initialization script for fresh installations
- **[FULLTEXT_MIGRATION.md](FULLTEXT_MIGRATION.md)** - Full-text search migration guide
- **[FULLTEXT_SEARCH_TEST_REPORT.md](FULLTEXT_SEARCH_TEST_REPORT.md)** - Full-text search testing results
- **[IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md)** - Multi-instance coordination implementation
- **[MIGRATION_SUMMARY.md](MIGRATION_SUMMARY.md)** - Supabase Python API migration summary
- **[Docs/README.md](Docs/README.md)** - Complete documentation index

### Architecture & Guides

- **[Luca Decimal](https://github.com/lucafrance/luca-decimal)** - Digital organization system
- **[Building a Second Brain](https://www.buildingasecondbrain.com/)** - Note-taking methodology
- **[MCP Protocol](https://modelcontextprotocol.io/)** - Model Context Protocol