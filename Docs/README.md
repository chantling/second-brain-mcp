# Second Brain MCP Server - Documentation Index

Complete index for all Second Brain MCP Server documentation.

## Quick Links

- **[README](../README.md)** - Getting started guide
- **[Architecture](./architecture/ARCHITECTURE.md)** - System design and components
- **[Configuration Guide](./guides/CONFIGURATION.md)** - Setup and configuration
- **[Developer Guide](./guides/DEVELOPMENT.md)** - Development and contribution
- **[Testing Guide](./guides/TESTING.md)** - Testing procedures
- **[Troubleshooting Guide](./guides/TROUBLESHOOTING.md)** - Common issues and solutions

## Documentation Structure

```
Docs/
├── README.md                      # This file (index)
├── architecture/
│   └── ARCHITECTURE.md          # System architecture and components
├── database/
│   ├── SCHEMA.md                 # Database schema and tables
│   └── RPC_FUNCTIONS.md          # Supabase RPC functions
├── api/
│   └── TOOLS_REFERENCE.md        # Complete API reference
└── guides/
    ├── CONFIGURATION.md            # Configuration options
    ├── DEVELOPMENT.md             # Development guide
    ├── TESTING.md                # Testing procedures
    └── TROUBLESHOOTING.md       # Troubleshooting guide
```

## Documentation by Topic

### Getting Started

| Document | Description | Audience |
|----------|-------------|-----------|
| [README](../README.md) | Installation, quick start, basic usage | New users |
| [Configuration Guide](./guides/CONFIGURATION.md) | Detailed configuration options | System administrators |

### Architecture

| Document | Description | Audience |
|----------|-------------|-----------|
| [Architecture](./architecture/ARCHITECTURE.md) | System design, components, data flow | Developers, architects |
| [Database Schema](./database/SCHEMA.md) | Tables, indexes, relationships | Database administrators |
| [RPC Functions](./database/RPC_FUNCTIONS.md) | Supabase RPC functions | Backend developers |

### API Reference

| Document | Description | Audience |
|----------|-------------|-----------|
| [Tools Reference](./api/TOOLS_REFERENCE.md) | Complete API reference for all 13 tools | API users, AI assistants |

### Development

| Document | Description | Audience |
|----------|-------------|-----------|
| [Development Guide](./guides/DEVELOPMENT.md) | Development environment, adding features | Contributors |
| [Testing Guide](./guides/TESTING.md) | Testing procedures, test coverage | QA engineers |
| [Troubleshooting](./guides/TROUBLESHOOTING.md) | Common issues and solutions | All users |

## Quick Reference

### Core Components

| Component | File | Purpose |
|-----------|-------|---------|
| MCP Server | `server.py` | Entry point, tool routing |
| Tool Handlers | `tools.py` | Business logic for 13 tools |
| Database | `database.py` | Supabase operations |
| Obsidian | `obsidian.py` | Markdown file management |
| Embeddings | `embeddings.py` | Vector generation |
| Search | `search.py` | Search algorithms |
| Links | `links.py` | Wiki-link management |
| Tags | `tags.py` | Tag operations |
| Metadata | `metadata.py` | AI extraction |
| Watcher | `watcher.py` | File monitoring |
| Lock | `instance_lock.py` | Multi-instance coordination |
| Config | `config.py` | Configuration management |

### MCP Tools (13 Total)

1. `store_thought` - Store notes in both systems
2. `semantic_search` - Vector similarity search
3. `list_recent` - List recent thoughts
4. `get_thought` - Get thought by ID
5. `search_by_topic` - Topic-based search
6. `get_todos` - Retrieve todos
7. `find_recipes` - Recipe search
8. `list_guides` - Guide listing
9. `get_contacts` - Contact lookup
10. `get_backlinks` - Find notes linking to thought
11. `find_related_notes` - Find related via links/tags
12. `suggest_tags` - Tag suggestions
13. `hybrid_search` - Advanced vector + keyword search

### Database Tables

| Table | Purpose |
|-------|---------|
| `thoughts` | Main notes with embeddings |
| `tags` | Tag definitions |
| `thought_tags` | Many-to-many tag associations |
| `folders` | Folder structure with embeddings |
| `links` | Wiki-link relationships |

### Configuration Variables

| Category | Variables |
|----------|------------|
| **Supabase** | SUPABASE_URL, SUPABASE_SECRET_KEY, SUPABASE_PUBLISH_KEY |
| **Embeddings** | EMBEDDING_API_KEY, EMBEDDING_BASE_URL, EMBEDDING_MODEL, EMBEDDING_DIMENSIONS |
| **Metadata** | METADATA_API_KEY, METADATA_BASE_URL, METADATA_MODEL |
| **Obsidian** | OBSIDIAN_VAULT_PATH |
| **Sync** | SYNC_ENABLED, SYNC_INITIAL_SYNC, SYNC_DEBOUNCE_SECONDS, SYNC_FULL_SYNC_INTERVAL |
| **Lock** | LOCK_FILE_PATH, LOCK_RETRY_ENABLED, LOCK_RETRY_INTERVAL_SECONDS, LOCK_HEARTBEAT_INTERVAL_SECONDS, LOCK_STALE_THRESHOLD_SECONDS |
| **Search** | SEARCH_VECTOR_WEIGHT, SEARCH_KEYWORD_WEIGHT, SEARCH_RECENCY_WEIGHT |

## Key Concepts

### Luca Decimal System

Folder organization using numbered prefixes:
- **1xx**: Projects (time-limited actions)
- **2xx**: Areas (regular activities)
- **3xx**: Resources (reference information)
- **4xx**: Archive (completed projects)

### Vector Embeddings

1536-dimensional vectors for semantic similarity:
- Generated by OpenAI-compatible API
- Stored in Supabase with pgvector
- Used for semantic search and folder matching

### Multi-Instance Coordination

Single-writer, multiple-reader pattern:
- **Primary**: Runs file watcher, syncs to Supabase
- **Secondary**: Read-only, retries lock acquisition
- **Heartbeat**: Primary sends heartbeat every 20s
- **Stale Detection**: Secondary takes over if primary stops

### Folder Selection Algorithm

1. Special cases (Recipes, Todos, Contacts)
2. Manual override via metadata
3. Exact topic match
4. Hierarchical semantic matching
5. Low confidence → ToSort

## Common Workflows

### Store and Search

```python
# 1. Store a thought
result = await store_thought(
    content="How to solder components",
    metadata={"type": "knowledge", "topics": ["electronics"]}
)

# 2. Search for similar content
results = await semantic_search("soldering")
```

### Find Related Notes

```python
# 1. Get a note
note = await get_thought(note_id=123)

# 2. Find backlinks
backlinks = await get_backlinks(thought_id=123)

# 3. Find related notes
related = await find_related_notes(thought_id=123)
```

### Advanced Search

```python
results = await hybrid_search(
    query="circuit design",
    limit=10,
    filters={
        "thought_type": "knowledge",
        "tags": ["electronics"]
    },
    weights={
        "vector": 0.8,
        "keywords": 0.2
    }
)
```

## Getting Help

### Documentation Search

1. **New to the project?** Start with [README](../README.md)
2. **Setting up?** Read [Configuration Guide](./guides/CONFIGURATION.md)
3. **Developing?** See [Developer Guide](./guides/DEVELOPMENT.md)
4. **Having issues?** Check [Troubleshooting Guide](./guides/TROUBLESHOOTING.md)
5. **API questions?** Review [Tools Reference](./api/TOOLS_REFERENCE.md)

### Community Resources

- **GitHub Issues**: Report bugs and feature requests
- **GitHub Discussions**: Ask questions and share ideas
- **MCP Protocol**: https://modelcontextprotocol.io/
- **Supabase Docs**: https://supabase.com/docs
- **Obsidian Docs**: https://help.obsidian.md/

## Contributing to Documentation

### Adding Documentation

1. Create new `.md` file in appropriate `Docs/` subdirectory
2. Follow existing documentation style
3. Use clear headings and code blocks
4. Include examples where helpful
5. Add link to this index

### Improving Documentation

1. Edit existing `.md` files
2. Fix typos and clarity issues
3. Add missing information
4. Update outdated sections
5. Submit pull request

### Documentation Style Guide

- **Headings**: Use `#`, `##`, `###` for hierarchy
- **Code Blocks**: Use triple backticks with language identifier
- **Links**: Use `[text](path)` format
- **Lists**: Use `-` for unordered, `1.` for ordered
- **Tables**: Use Markdown tables
- **Emphasis**: Use `**bold**` and `*italic*` sparingly

## Version Information

Current documentation version: 1.0.0
Last updated: March 4, 2026
Compatible with server version: Latest main branch

## Changelog

### v1.0.0 (2026-03-04)
- Initial comprehensive documentation structure
- Added architecture documentation
- Added database schema reference
- Added complete API reference
- Added developer guide
- Added testing guide
- Added troubleshooting guide
- Added documentation index

---

**For the most up-to-date information, check the individual documentation files in this directory.**
