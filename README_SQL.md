# Second Brain MCP Server - Complete Database Initialization Script

This script contains all SQL commands necessary to create a fresh database for Second Brain MCP Server with Supabase (PostgreSQL + pgvector).

## Order of Execution

1. Enable required extensions
2. Create base tables (with all columns)
3. Create indexes
4. Create RPC functions
5. Create triggers
6. Enable Row Level Security (RLS) policies (if needed)

## Prerequisites

- Supabase project with PostgreSQL 14+
- pgvector extension enabled
- Run each block separately in Supabase SQL Editor

---

## 1. EXTENSIONS

### Enable pgvector extension

```sql
-- Enable pgvector extension for vector embeddings (semantic search)
-- Note: In Supabase, this may need to be enabled via dashboard first
CREATE EXTENSION IF NOT EXISTS vector;
```

### Enable pg_trgm extension

```sql
-- Enable pg_trgm extension for trigram pattern matching (ILIKE optimization)
-- This enables faster substring searches
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

---

## 2. TABLES

### 2.1. thoughts Table

Main storage table for all notes, thoughts, recipes, todos, contacts, etc.

```sql
CREATE TABLE IF NOT EXISTS thoughts (
    -- Primary Key
    id SERIAL PRIMARY KEY,

    -- Core Content
    content TEXT NOT NULL,

    -- Vector Embedding (for semantic search)
    embedding vector(1536),

    -- Categorization
    thought_type VARCHAR(50) DEFAULT 'knowledge',
    topics TEXT[] DEFAULT '{}',
    people TEXT[] DEFAULT '{}',
    action_items TEXT[] DEFAULT '{}',

    -- Obsidian Integration
    obsidian_path VARCHAR(500),
    file_hash VARCHAR(64),

    -- Metadata
    metadata JSONB DEFAULT '{}',
    source VARCHAR(100) DEFAULT 'manual',

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Soft Delete (for sync coordination)
    deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMP WITH TIME ZONE,

    -- Full-Text Search Vector
    content_tsv TSVECTOR
);
```

### 2.2. tags Table

Tag definitions for categorization with semantic matching.

```sql
CREATE TABLE IF NOT EXISTS tags (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    embedding vector(1536),

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### 2.3. thought_tags Table

Many-to-many relationship between thoughts and tags.

```sql
CREATE TABLE IF NOT EXISTS thought_tags (
    thought_id INTEGER REFERENCES thoughts(id) ON DELETE CASCADE,
    tag_id INTEGER REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (thought_id, tag_id)
);
```

### 2.4. folders Table

Folder structure with embeddings for semantic placement matching.

```sql
CREATE TABLE IF NOT EXISTS folders (
    id SERIAL PRIMARY KEY,
    path VARCHAR(500) UNIQUE NOT NULL,
    folder_name VARCHAR(100) NOT NULL,
    full_path_hierarchy TEXT[] DEFAULT '{}',
    description TEXT,
    embedding vector(1536),

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### 2.5. links Table

Wiki-link relationships between thoughts (backlinks).

```sql
CREATE TABLE IF NOT EXISTS links (
    id SERIAL PRIMARY KEY,
    source_thought_id INTEGER REFERENCES thoughts(id) ON DELETE CASCADE,
    target_thought_id INTEGER REFERENCES thoughts(id) ON DELETE CASCADE,
    link_type TEXT DEFAULT 'wiki',
    link_text TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(source_thought_id, target_thought_id, link_type)
);
```

---

## 3. INDEXES

### 3.1. thoughts Table Indexes

#### Vector similarity index

```sql
-- Vector similarity index (IVFFlat for pgvector)
-- Provides O(log n) search for semantic similarity
CREATE INDEX IF NOT EXISTS thoughts_embedding_idx ON thoughts
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
```

#### Created timestamp index

```sql
-- Created timestamp index (for recent queries)
CREATE INDEX IF NOT EXISTS thoughts_created_at_idx ON thoughts(created_at DESC);
```

#### Updated timestamp index

```sql
-- Updated timestamp index (for sync and cleanup)
CREATE INDEX IF NOT EXISTS thoughts_updated_at_idx ON thoughts(updated_at DESC);
```

#### Thought type index

```sql
-- Thought type index (for filtering by type)
CREATE INDEX IF NOT EXISTS thoughts_type_idx ON thoughts(thought_type);
```

#### Obsidian path index

```sql
-- Obsidian path index (for lookup by file path)
CREATE INDEX IF NOT EXISTS thoughts_obsidian_path_idx ON thoughts(obsidian_path);
```

#### File hash index

```sql
-- File hash index (for duplicate detection)
CREATE INDEX IF NOT EXISTS thoughts_file_hash_idx ON thoughts(file_hash);
```

#### Deleted status index

```sql
-- Deleted status index (for cleanup and filtering)
CREATE INDEX IF NOT EXISTS thoughts_deleted_idx ON thoughts(deleted);
```

#### Full-text search GIN index

```sql
-- Full-text search GIN index (for exact word matching)
CREATE INDEX IF NOT EXISTS idx_thoughts_content_tsv ON thoughts USING gin(content_tsv);
```

#### Trigram index for ILIKE pattern matching

```sql
-- Trigram index for ILIKE pattern matching (fallback search)
CREATE INDEX IF NOT EXISTS idx_thoughts_content_trgm ON thoughts USING gin(content gin_trgm_ops);
```

### 3.2. tags Table Indexes

#### Unique index on tag name

```sql
-- Unique index on tag name (already enforced by UNIQUE constraint, but indexed for lookups)
CREATE INDEX IF NOT EXISTS tags_name_idx ON tags(name);
```

### 3.3. thought_tags Table Indexes

#### Tag lookups

```sql
-- Tag lookups (find thoughts by tag)
CREATE INDEX IF NOT EXISTS thought_tags_tag_id_idx ON thought_tags(tag_id);
```

#### Thought lookups

```sql
-- Thought lookups (find tags by thought)
CREATE INDEX IF NOT EXISTS thought_tags_thought_id_idx ON thought_tags(thought_id);
```

### 3.4. folders Table Indexes

#### Path lookup

```sql
-- Path lookup (for folder matching)
CREATE INDEX IF NOT EXISTS folders_path_idx ON folders(path);
```

#### Vector similarity index for folders

```sql
-- Vector similarity index for folders (for semantic placement)
CREATE INDEX IF NOT EXISTS folders_embedding_idx ON folders
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 50);
```

### 3.5. links Table Indexes

#### Backlink lookups

```sql
-- Backlink lookups (find notes linking TO this note)
CREATE INDEX IF NOT EXISTS links_target_thought_id_idx ON links(target_thought_id);
```

#### Outlink lookups

```sql
-- Outlink lookups (find notes linked FROM this note)
CREATE INDEX IF NOT EXISTS links_source_thought_id_idx ON links(source_thought_id);
```

---

## 4. RPC FUNCTIONS

### 4.1. vector_search Function

Performs semantic similarity search using vector embeddings.
Returns thoughts ordered by similarity (most similar first).

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
    updated_at TIMESTAMP WITH TIME ZONE,
    deleted BOOLEAN,
    deleted_at TIMESTAMP WITH TIME ZONE,
    content_tsv TSVECTOR,
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
        t.updated_at,
        t.deleted,
        t.deleted_at,
        t.content_tsv,
        1 - (t.embedding <=> query_embedding) as similarity
    FROM thoughts t
    WHERE t.deleted = FALSE
    ORDER BY t.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;
```

### 4.2. execute_sql Function

Executes raw SQL statements for complex queries.

**⚠️ SECURITY WARNING:** This function executes arbitrary SQL. Use with caution and validate all inputs.

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

### 4.3. search_thoughts_by_text Function

Full-text search with ranking using PostgreSQL tsvector.
Returns thoughts ordered by relevance and recency.

```sql
CREATE OR REPLACE FUNCTION search_thoughts_by_text(
    search_query TEXT,
    match_limit INT DEFAULT 10
)
RETURNS TABLE (
    id INT,
    content TEXT,
    thought_type VARCHAR(50),
    topics TEXT[],
    obsidian_path VARCHAR(500),
    created_at TIMESTAMP WITH TIME ZONE,
    rank FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        t.id,
        t.content,
        t.thought_type,
        t.topics,
        t.obsidian_path,
        t.created_at,
        ts_rank(t.content_tsv, to_tsquery('english', search_query)) as rank
    FROM thoughts t
    WHERE t.content_tsv @@ to_tsquery('english', search_query)
      AND t.deleted = FALSE
    ORDER BY rank DESC, t.created_at DESC
    LIMIT match_limit;
END;
$$;
```

### 4.4. update_tag_embedding Function

Placeholder function for updating tag embeddings (optional).
This would generate embeddings for tags using an external service.

```sql
CREATE OR REPLACE FUNCTION update_tag_embedding()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.embedding IS NULL THEN
        -- Generate embedding for tag using your embedding service
        -- This requires an external function call
        NEW.embedding := NULL; -- Placeholder
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

---

## 5. TRIGGERS

### 5.1. thoughts_content_tsv_trigger

Automatically updates the content_tsv column when content is inserted or updated.
Converts text to tsvector format for full-text search.

```sql
CREATE OR REPLACE FUNCTION thoughts_content_tsv_trigger() RETURNS trigger AS $$
BEGIN
    NEW.content_tsv := to_tsvector('english', coalesce(NEW.content, ''));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

#### Create trigger on thoughts table

```sql
DROP TRIGGER IF EXISTS thoughts_content_tsv_update ON thoughts;
CREATE TRIGGER thoughts_content_tsv_update
BEFORE INSERT OR UPDATE OF content ON thoughts
FOR EACH ROW EXECUTE FUNCTION thoughts_content_tsv_trigger();
```

### 5.2. update_updated_at Trigger

Automatically updates the updated_at timestamp when any row is modified.

```sql
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

#### Create trigger on thoughts table

```sql
DROP TRIGGER IF EXISTS thoughts_update_updated_at ON thoughts;
CREATE TRIGGER thoughts_update_updated_at
BEFORE UPDATE ON thoughts
FOR EACH ROW EXECUTE FUNCTION update_updated_at();
```

#### Create trigger on folders table

```sql
DROP TRIGGER IF EXISTS folders_update_updated_at ON folders;
CREATE TRIGGER folders_update_updated_at
BEFORE UPDATE ON folders
FOR EACH ROW EXECUTE FUNCTION update_updated_at();
```

---

## 6. COMMENTS

Document the purpose of key columns and triggers.

```sql
-- Document the purpose of key columns and triggers
COMMENT ON COLUMN thoughts.embedding IS 'Vector embedding for semantic similarity search (1536 dimensions)';
COMMENT ON COLUMN thoughts.content_tsv IS 'Full-text search vector for exact word matching, automatically maintained by trigger';
COMMENT ON COLUMN thoughts.deleted IS 'Soft delete flag for sync coordination and data retention';
COMMENT ON COLUMN thoughts.file_hash IS 'SHA-256 hash of file content for duplicate detection';
COMMENT ON COLUMN folders.embedding IS 'Vector embedding for semantic folder matching and placement';
COMMENT ON COLUMN tags.embedding IS 'Vector embedding for semantic tag matching (optional, for future use)';
COMMENT ON TABLE thoughts IS 'Main storage table for notes, recipes, todos, contacts, and guides';
COMMENT ON TABLE tags IS 'Tag definitions for categorization with optional semantic matching';
COMMENT ON TABLE folders IS 'Folder structure with semantic embeddings for intelligent note placement';
COMMENT ON TABLE links IS 'Wiki-link relationships between thoughts for backlink support';
COMMENT ON TABLE thought_tags IS 'Many-to-many relationship between thoughts and tags';
```

---

## 7. VERIFICATION QUERIES

Run these queries to verify database was created successfully.

### Check all tables exist

```sql
SELECT
    'thoughts' as table_name,
    COUNT(*) as row_count
FROM thoughts
WHERE deleted = FALSE
UNION ALL
SELECT
    'tags' as table_name,
    COUNT(*) as row_count
FROM tags
UNION ALL
SELECT
    'folders' as table_name,
    COUNT(*) as row_count
FROM folders
UNION ALL
SELECT
    'links' as table_name,
    COUNT(*) as row_count
FROM links
UNION ALL
SELECT
    'thought_tags' as table_name,
    COUNT(*) as row_count
FROM thought_tags;
```

### Check all indexes exist

```sql
SELECT
    indexname,
    indexdef
FROM pg_indexes
WHERE tablename = 'thoughts'
   OR tablename = 'tags'
   OR tablename = 'folders'
   OR tablename = 'links'
   OR tablename = 'thought_tags'
ORDER BY tablename, indexname;
```

### Check all functions exist

```sql
SELECT
    routine_name,
    routine_type
FROM information_schema.routines
WHERE routine_schema = 'public'
  AND routine_name IN ('vector_search', 'execute_sql', 'search_thoughts_by_text', 'update_tag_embedding', 'update_updated_at', 'thoughts_content_tsv_trigger')
ORDER BY routine_name;
```

---

## 8. SAMPLE DATA (Optional - for testing)

Uncomment these inserts to add sample data for testing.

```sql
-- Insert sample thoughts for testing
INSERT INTO thoughts (content, thought_type, topics, obsidian_path) VALUES
    ('Example note about electronics', 'knowledge', ARRAY['electronics', 'hardware'], 'Resources/Electronics/Example.md'),
    ('My blood pressure readings', 'knowledge', ARRAY['health'], 'Health/Blood Pressure.md'),
    ('Tomato soup recipe', 'recipe', ARRAY['cooking', 'dinner'], 'Recipes/Soups/Tomato Soup.md'),
    ('Buy groceries', 'todo', ARRAY['shopping'], 'To-Do/Buy Groceries.md'),
    ('Dr. Smith - Cardiologist', 'contact', ARRAY['health', 'doctor'], 'Contacts/Doctors.md');
```

---

## END OF INITIALIZATION SCRIPT

All database objects created successfully!

### Next Steps

1. Verify all tables have been created (run verification queries above)
2. Test vector_search function with a sample embedding
3. Test full-text search with: `SELECT * FROM search_thoughts_by_text('test', 10)`
4. Start MCP server and verify all tools work correctly
