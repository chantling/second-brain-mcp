# Database Schema Documentation

## Overview

This document describes the database schema used by the Second Brain MCP Server. The system uses **Supabase** (PostgreSQL with pgvector extension) for storing thoughts, embeddings, tags, and relationships.

## Tables

### 1. `thoughts`

Main storage table for all notes and thoughts.

```sql
CREATE TABLE thoughts (
    id SERIAL PRIMARY KEY,
    content TEXT NOT NULL,
    embedding vector(1536),
    thought_type VARCHAR(50) DEFAULT 'knowledge',
    topics TEXT[],
    people TEXT[],
    action_items TEXT[],
    obsidian_path VARCHAR(500),
    metadata JSONB,
    source VARCHAR(100) DEFAULT 'manual',
    file_hash VARCHAR(64),
    content_tsv tsvector,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

**Columns:**

| Column | Type | Description | Default |
|--------|-------|-------------|----------|
| `id` | SERIAL | Unique identifier | Auto-increment |
| `content` | TEXT | Note content (markdown) | Required |
| `embedding` | vector(1536) | Vector embedding for semantic search | NULL |
| `thought_type` | VARCHAR(50) | Type of thought (knowledge, recipe, todo, contact, guide, note, other) | 'knowledge' |
| `topics` | TEXT[] | Array of topic tags | [] |
| `people` | TEXT[] | Array of people mentioned | [] |
| `action_items` | TEXT[] | Array of action items | [] |
| `obsidian_path` | VARCHAR(500) | Path to Obsidian markdown file | NULL |
| `metadata` | JSONB | Additional metadata as JSON | {} |
| `source` | VARCHAR(100) | Source of the thought (manual, sync, etc.) | 'manual' |
| `file_hash` | VARCHAR(64) | SHA-256 hash of file content | NULL |
| `content_tsv` | tsvector | Full-text search vector (auto-updated via trigger) | NULL |
| `created_at` | TIMESTAMP | Creation timestamp | NOW() |
| `updated_at` | TIMESTAMP | Last update timestamp | NOW() |

**Indexes:**

```sql
-- Vector similarity index (pgvector)
CREATE INDEX thoughts_embedding_idx ON thoughts
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- Created timestamp index
CREATE INDEX thoughts_created_at_idx ON thoughts(created_at DESC);

-- Type index
CREATE INDEX thoughts_type_idx ON thoughts(thought_type);

-- Path index for lookups
CREATE INDEX thoughts_obsidian_path_idx ON thoughts(obsidian_path);

-- Hash index for sync change detection
CREATE INDEX thoughts_file_hash_idx ON thoughts(file_hash);

-- Full-text search index (GIN)
CREATE INDEX thoughts_content_tsv_idx ON thoughts USING gin(content_tsv);
```

**Metadata JSONB Structure:**

```json
{
  "title": "Note Title",
  "folder": "Resources/Electronics",
  "category": "dessert",
  "difficulty": "medium",
  "total_time": 45,
  "ingredients": ["eggs", "flour", "milk"],
  "completed": false,
  "custom_field": "any value"
}
```

**Thought Types:**
- `knowledge` - General knowledge notes
- `recipe` - Cooking recipes
- `todo` - Todo items
- `contact` - Contact information
- `guide` - How-to guides

### 2. `tags`

Tag definitions for categorization.

```sql
CREATE TABLE tags (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

**Columns:**

| Column | Type | Description |
|--------|-------|-------------|
| `id` | SERIAL | Unique identifier |
| `name` | VARCHAR(100) | Tag name (unique) |
| `created_at` | TIMESTAMP | Creation timestamp |

**Indexes:**

```sql
-- Unique constraint on name
CREATE UNIQUE INDEX tags_name_idx ON tags(name);
```

### 3. `thought_tags`

Many-to-many relationship between thoughts and tags.

```sql
CREATE TABLE thought_tags (
    thought_id INTEGER REFERENCES thoughts(id) ON DELETE CASCADE,
    tag_id INTEGER REFERENCES tags(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (thought_id, tag_id)
);
```

**Columns:**

| Column | Type | Description |
|--------|-------|-------------|
| `thought_id` | INTEGER | Foreign key to thoughts |
| `tag_id` | INTEGER | Foreign key to tags |
| `created_at` | TIMESTAMP | Association timestamp |

**Indexes:**

```sql
-- Tag lookups
CREATE INDEX thought_tags_tag_id_idx ON thought_tags(tag_id);
-- Thought lookups
CREATE INDEX thought_tags_thought_id_idx ON thought_tags(thought_id);
```

### 4. `folders`

Folder structure with embeddings for semantic matching.

```sql
CREATE TABLE folders (
    id SERIAL PRIMARY KEY,
    path VARCHAR(500) UNIQUE NOT NULL,
    folder_name VARCHAR(100) NOT NULL,
    full_path_hierarchy TEXT[],
    description TEXT,
    embedding vector(1536),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

**Columns:**

| Column | Type | Description |
|--------|-------|-------------|
| `id` | SERIAL | Unique identifier |
| `path` | VARCHAR(500) | Full folder path (e.g., "Resources/Electronics") |
| `folder_name` | VARCHAR(100) | Leaf folder name (e.g., "Electronics") |
| `full_path_hierarchy` | TEXT[] | Array of path components (e.g., ["Resources", "Electronics"]) |
| `description` | TEXT | Descriptive text for embedding generation |
| `embedding` | vector(1536) | Vector embedding for semantic folder matching |
| `created_at` | TIMESTAMP | Creation timestamp |
| `updated_at` | TIMESTAMP | Last update timestamp |

**Indexes:**

```sql
-- Path lookup
CREATE UNIQUE INDEX folders_path_idx ON folders(path);

-- Vector similarity index
CREATE INDEX folders_embedding_idx ON folders
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 50);
```

### 5. `links`

Wiki-link relationships between thoughts.

```sql
CREATE TABLE links (
    id SERIAL PRIMARY KEY,
    source_thought_id INTEGER REFERENCES thoughts(id) ON DELETE CASCADE,
    target_thought_id INTEGER REFERENCES thoughts(id) ON DELETE CASCADE,
    link_type VARCHAR(20) DEFAULT 'wiki',
    link_text VARCHAR(200),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(source_thought_id, target_thought_id, link_type)
);
```

**Columns:**

| Column | Type | Description | Default |
|--------|-------|-------------|----------|
| `id` | SERIAL | Unique identifier |
| `source_thought_id` | INTEGER | ID of thought containing the link |
| `target_thought_id` | INTEGER | ID of thought being linked to |
| `link_type` | VARCHAR(20) | Type of link (wiki, embed, transclusion) | 'wiki' |
| `link_text` | VARCHAR(200) | Display text of the link | NULL |
| `created_at` | TIMESTAMP | Creation timestamp | NOW() |

**Link Types:**
- `wiki` - Standard wiki-link `[[Note Name]]`
- `embed` - Embedded content `![[Note Name]]`
- `transclusion` - Transcluded content

**Indexes:**

```sql
-- Backlink lookups (find notes linking TO this note)
CREATE INDEX links_target_thought_id_idx ON links(target_thought_id);

-- Outlink lookups (find notes linked FROM this note)
CREATE INDEX links_source_thought_id_idx ON links(source_thought_id);

-- Unique constraint prevents duplicate links
CREATE UNIQUE INDEX links_unique_idx ON links(source_thought_id, target_thought_id, link_type);
```

### 6. `server_lock`

Distributed lock table for cross-instance coordination (singleton row, id=1).

```sql
CREATE TABLE server_lock (
    id INTEGER PRIMARY KEY DEFAULT 1,
    instance_id UUID NOT NULL,
    hostname VARCHAR(255),
    pid INTEGER,
    acquired_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE,
    operation VARCHAR(100)
);
```

**Columns:**

| Column | Type | Description |
|--------|-------|-------------|
| `id` | INTEGER | Singleton row (always 1) |
| `instance_id` | UUID | Unique instance identifier |
| `hostname` | VARCHAR | Host machine name |
| `pid` | INTEGER | Process ID |
| `acquired_at` | TIMESTAMP | When lock was acquired |
| `expires_at` | TIMESTAMP | When lock expires (TTL-based) |
| `operation` | VARCHAR | Current operation holding the lock |

**Purpose:**
- Prevents race conditions between multiple server instances
- TTL-based auto-expiration prevents deadlocks from crashed instances
- Used by `SupabaseLock` class in `supabase_lock.py`
- Atomic acquisition via `acquire_lock` RPC function

## PostgreSQL Functions (RPC)

### `vector_search`

Performs semantic similarity search using pgvector.

```sql
CREATE OR REPLACE FUNCTION vector_search(
    query_embedding vector(1536),
    match_count INTEGER DEFAULT 10
)
RETURNS TABLE (
    id INTEGER,
    content TEXT,
    thought_type VARCHAR(50),
    topics TEXT[],
    people TEXT[],
    action_items TEXT[],
    obsidian_path VARCHAR(500),
    metadata JSONB,
    source VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE,
    similarity FLOAT
)
LANGUAGE sql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        t.id,
        t.content,
        t.thought_type,
        t.topics,
        t.people,
        t.action_items,
        t.obsidian_path,
        t.metadata,
        t.source,
        t.created_at,
        1 - (t.embedding <=> query_embedding) as similarity
    FROM thoughts t
    WHERE t.embedding IS NOT NULL
    ORDER BY t.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;
```

**Parameters:**
- `query_embedding` - Vector to search for (1536 dimensions)
- `match_count` - Number of results to return (default: 10)

**Returns:**
- Table of matching thoughts with similarity score (0-1, higher = more similar)

**Usage:**
```python
results = client.rpc(
    "vector_search",
    {
        "query_embedding": query_embedding,
        "match_count": 10
    }
).execute()
```

### `execute_sql`

Execute raw SQL for complex queries.

```sql
CREATE OR REPLACE FUNCTION execute_sql(
    query TEXT
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    RETURN query::JSONB;
END;
$$;
```

**Note:** This is a fallback function. For security, prefer using Supabase client methods instead.

## Triggers

### `update_updated_at`

Automatically update `updated_at` timestamp.

```sql
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER thoughts_update_updated_at
    BEFORE UPDATE ON thoughts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER folders_update_updated_at
    BEFORE UPDATE ON folders
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
```

### `update_content_tsv`

Automatically update `content_tsv` for full-text search when content changes.

```sql
CREATE TRIGGER thoughts_update_content_tsv
    BEFORE INSERT OR UPDATE ON thoughts
    FOR EACH ROW EXECUTE FUNCTION
    tsvector_update_trigger(content_tsv, 'pg_catalog.english', content);
```

**Note:** The FTS language is configurable via `Config.FTS_LANGUAGE`.

## Data Types

### Array Types

- `TEXT[]` - Array of text values (topics, people, action_items)
- `TEXT[]` - Hierarchical path components (full_path_hierarchy)

### Vector Type

- `vector(1536)` - 1536-dimensional vector for embeddings
- Supported operations:
  - `<=>` - Cosine distance (default for semantic search)
  - `<#>` - Inner product
  - `<->` - L2 distance (Euclidean)

### JSONB Type

- `JSONB` - Binary JSON with indexing support
- Operators:
  - `->` - Get JSON field by key
  - `->>` - Get JSON field by text path
  - `@>` - Contains JSON key/value
  - `?` - Check for text key

## Vector Operations

### Cosine Similarity

```sql
-- Cosine distance (lower = more similar)
embedding <=> query_embedding

-- Convert to similarity (0-1, higher = more similar)
1 - (embedding <=> query_embedding)
```

### Inner Product

```sql
embedding <#> query_embedding
```

### L2 Distance (Euclidean)

```sql
embedding <-> query_embedding
```

**Note:** The system uses cosine distance for semantic search, as it's less affected by vector magnitude.

## Indexing Strategy

### Vector Index (IVFFlat)

```sql
CREATE INDEX ON table
USING ivfflat (vector_col vector_cosine_ops)
WITH (lists = N)
```

**Parameters:**
- `lists` - Number of lists for IVFFlat (typical: sqrt(rows))
- `vector_cosine_ops` - Cosine distance operator class

**Trade-offs:**
- More lists = faster search, slower insert
- Fewer lists = slower search, faster insert
- Recommended: `lists = 100` for thoughts, `lists = 50` for folders

### GIN Index (JSONB)

```sql
CREATE INDEX ON table USING gin (jsonb_column);
```

**Benefits:**
- Fast JSON field queries
- Supports `@>`, `?`, `?&`, `?\|` operators
- Automatically used for JSONB queries

## Row-Level Security (RLS)

The system uses Supabase's RLS policies. Examples:

```sql
-- Enable RLS
ALTER TABLE thoughts ENABLE ROW LEVEL SECURITY;

-- Allow service role full access
CREATE POLICY "Service role has full access" ON thoughts
FOR ALL TO service_role
USING (true)
WITH CHECK (true);

-- Allow anon role read access with restrictions
CREATE POLICY "Anon can read public thoughts" ON thoughts
FOR SELECT TO anon
USING (source = 'public')
WITH CHECK (false);
```

## Backup and Restore

### Backup

```bash
# Using Supabase CLI
supabase db dump -f backup.sql

# Using pg_dump
pg_dump -h db.xxx.supabase.co -U postgres -d postgres > backup.sql
```

### Restore

```bash
# Using Supabase CLI
supabase db reset

# Using psql
psql -h db.xxx.supabase.co -U postgres -d postgres -f backup.sql
```

## Performance Optimization

### Query Optimization

1. **Use indexed columns in WHERE clauses**
2. **Limit vector search results** with `LIMIT`
3. **Use JSONB operators** for metadata queries
4. **Batch inserts** when possible

### Connection Pooling

Supabase client manages connection pooling:
- Min connections: 1
- Max connections: 20
- Idle timeout: 10 minutes

### Vector Index Maintenance

```sql
-- Rebuild vector index
REINDEX INDEX thoughts_embedding_idx;

-- Vacuum table
VACUUM ANALYZE thoughts;
```

## Migration

See `migration_sql.txt` for database schema migrations.

To add new tables/columns:
1. Create migration SQL file
2. Add to migration tracking
3. Run migration via Supabase dashboard or CLI

## Troubleshooting

### Vector Search Slow

- Check vector index exists: `\d thoughts_embedding_idx`
- Rebuild index: `REINDEX INDEX thoughts_embedding_idx`
- Analyze table: `ANALYZE thoughts`

### Query Timeouts

- Check connection limits in Supabase dashboard
- Increase statement timeout: `SET statement_timeout = '60s'`
- Use `LIMIT` to reduce result set

### Out of Memory

- Reduce `lists` parameter in IVFFlat index
- Use smaller batch sizes for bulk operations
- Increase memory limit: `SET work_mem = '256MB'`
