# Supabase RPC Functions Reference

## Overview

This document describes the Remote Procedure Call (RPC) functions implemented in Supabase for the Second Brain MCP Server. RPC functions allow efficient database operations with custom logic.

## Functions

### `vector_search`

Performs semantic similarity search using vector embeddings.

**Signature:**
```sql
vector_search(
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
```

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|--------|-----------|----------|-------------|
| `query_embedding` | vector(1536) | Yes | - | Vector embedding to search for (must be 1536 dimensions) |
| `match_count` | INTEGER | No | 10 | Maximum number of results to return |

**Returns:**

Table of matching thoughts ordered by similarity (most similar first):

| Column | Type | Description |
|--------|-------|-------------|
| `id` | INTEGER | Thought identifier |
| `content` | TEXT | Note content (markdown) |
| `thought_type` | VARCHAR(50) | Type of thought (knowledge, recipe, todo, etc.) |
| `topics` | TEXT[] | Array of topic tags |
| `people` | TEXT[] | Array of people mentioned |
| `action_items` | TEXT[] | Array of action items |
| `obsidian_path` | VARCHAR(500) | Path to Obsidian markdown file |
| `metadata` | JSONB | Additional metadata (JSON object) |
| `source` | VARCHAR(100) | Source of the thought (manual, sync, etc.) |
| `created_at` | TIMESTAMP | Creation timestamp |
| `similarity` | FLOAT | Cosine similarity score (0-1, higher = more similar) |

**Usage Example (Python):**

```python
from embeddings import EmbeddingGenerator

# Generate query embedding
gen = EmbeddingGenerator()
query = "how to solder electronics"
query_embedding = await gen.create_embedding(query)

# Call RPC function
response = db_manager.client.rpc(
    "vector_search",
    {
        "query_embedding": query_embedding,
        "match_count": 10
    }
).execute()

# Process results
for result in response.data:
    print(f"ID: {result['id']}")
    print(f"Similarity: {result['similarity']:.3f}")
    print(f"Content: {result['content'][:100]}...")
```

**Performance Notes:**

- Uses IVFFlat vector index for O(log n) search
- Best performance when vector index is properly configured
- Cosine distance used: `embedding <=> query_embedding`
- Converted to similarity: `1 - distance`

**Error Handling:**

The function returns all rows (no exceptions raised). Check:
- `len(response.data)` - Number of results
- Empty array if no matches found

### `execute_sql`

Executes raw SQL statements for complex queries.

**⚠️ Security Warning:** This function executes arbitrary SQL. Use with caution and validate all inputs.

**Signature:**
```sql
execute_sql(
    query TEXT
)
RETURNS JSONB
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|--------|-----------|-------------|
| `query` | TEXT | Yes | SQL query to execute (must return JSON) |

**Returns:**

JSONB result from query execution.

**Usage Example (Python):**

```python
# Complex query example
query = """
    SELECT
        id,
        content,
        thought_type,
        (embedding <=> '[0.1, 0.2, ...]'::vector(1536)) as similarity
    FROM thoughts
    WHERE thought_type = 'recipe'
    ORDER BY similarity
    LIMIT 5
"""

response = db_manager.client.rpc(
    "execute_sql",
    {"query": query}
).execute()

results = response.data
```

**When to Use:**

- Complex joins not supported by Supabase client
- Custom aggregation functions
- Window functions
- Recursive queries (CTEs)
- Performance-critical queries

**When NOT to Use:**

- Simple CRUD operations (use Supabase client methods)
- Security-sensitive queries (use parameterized queries)
- User-provided input without validation

**Security Considerations:**

1. **Never** pass user input directly into the query
2. Use parameterized queries when possible
3. Validate and sanitize all inputs
4. Consider using specific, purpose-built RPC functions instead

**Better Alternative:**

Create a specific RPC function for your use case:

```sql
CREATE OR REPLACE FUNCTION search_by_type_and_similarity(
    thought_type_param VARCHAR(50),
    query_embedding vector(1536),
    match_count INTEGER DEFAULT 10
)
RETURNS TABLE (...)
LANGUAGE sql
AS $$
BEGIN
    RETURN QUERY
    SELECT * FROM thoughts
    WHERE thought_type = thought_type_param
    ORDER BY embedding <=> query_embedding
    LIMIT match_count;
END;
$$;
```

## Creating Custom RPC Functions

### Template

```sql
CREATE OR REPLACE FUNCTION function_name(
    param1 TYPE,
    param2 TYPE DEFAULT default_value
)
RETURNS return_type
LANGUAGE language
AS $$
BEGIN
    -- Your logic here
    RETURN result;
END;
$$;

-- Grant permissions
GRANT EXECUTE ON FUNCTION function_name TO service_role;
GRANT EXECUTE ON FUNCTION function_name TO anon;
```

### Example: Search with Type Filter

```sql
CREATE OR REPLACE FUNCTION vector_search_by_type(
    query_embedding vector(1536),
    thought_type_param VARCHAR(50),
    match_count INTEGER DEFAULT 10
)
RETURNS TABLE (same_as_vector_search)
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
    WHERE
        t.embedding IS NOT NULL
        AND t.thought_type = thought_type_param
    ORDER BY t.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- Grant permissions
GRANT EXECUTE ON FUNCTION vector_search_by_type TO service_role;
```

**Usage:**

```python
response = db_manager.client.rpc(
    "vector_search_by_type",
    {
        "query_embedding": query_embedding,
        "thought_type_param": "recipe",
        "match_count": 5
    }
).execute()
```

### Example: Search by Tags

```sql
CREATE OR REPLACE FUNCTION search_by_tags(
    tag_names TEXT[],
    match_count INTEGER DEFAULT 10
)
RETURNS TABLE (
    id INTEGER,
    content TEXT,
    thought_type VARCHAR(50),
    topics TEXT[],
    created_at TIMESTAMP WITH TIME ZONE,
    tag_count INTEGER
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
        t.created_at,
        COUNT(tt.tag_id) as tag_count
    FROM thoughts t
    INNER JOIN thought_tags tt ON t.id = tt.thought_id
    INNER JOIN tags tg ON tt.tag_id = tg.id
    WHERE tg.name = ANY(tag_names)
    GROUP BY t.id, t.content, t.thought_type, t.topics, t.created_at
    ORDER BY COUNT(*) DESC, t.created_at DESC
    LIMIT match_count;
END;
$$;
```

## Testing RPC Functions

### Unit Testing (via Supabase CLI)

```bash
# Test vector_search
supabase db execute --sql \
  "SELECT * FROM vector_search('[0.1,0.2,...]'::vector(1536), 5)"

# Check function exists
supabase db execute --sql \
  "SELECT routine_name, routine_type FROM information_schema.routines WHERE routine_name = 'vector_search'"
```

### Integration Testing (Python)

```python
async def test_vector_search():
    """Test vector_search RPC function"""
    from embeddings import EmbeddingGenerator

    gen = EmbeddingGenerator()

    # Create test embedding
    test_embedding = await gen.create_embedding("test query")

    # Call RPC
    response = db_manager.client.rpc(
        "vector_search",
        {
            "query_embedding": test_embedding,
            "match_count": 5
        }
    ).execute()

    # Validate
    assert response.data is not None
    assert len(response.data) <= 5
    assert all("similarity" in r for r in response.data)
    assert all(0 <= r["similarity"] <= 1 for r in response.data)

    print("✓ vector_search RPC working correctly")
```

## Performance Optimization

### Index Requirements

RPC functions that use vector search require proper indexing:

```sql
-- Check index exists
SELECT indexname FROM pg_indexes WHERE indexname = 'thoughts_embedding_idx';

-- Create if missing
CREATE INDEX IF NOT EXISTS thoughts_embedding_idx ON thoughts
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
```

### Query Plan Analysis

```sql
EXPLAIN ANALYZE
SELECT * FROM vector_search('[...]'::vector(1536), 10);
```

**Look for:**
- Index Scan on `thoughts_embedding_idx`
- No Seq Scan on thoughts table
- Reasonable cost estimation

### Common Performance Issues

1. **Missing vector index** → Falls back to Seq Scan (slow)
2. **Wrong vector dimension** → Function fails
3. **Large result sets** → Increase `match_count` slowly
4. **Outdated statistics** → Run `ANALYZE thoughts`

## Troubleshooting

### RPC Function Not Found

```python
# Error: "function vector_search(...) does not exist"
```

**Solutions:**
1. Check function exists: `SELECT routine_name FROM information_schema.routines`
2. Grant permissions: `GRANT EXECUTE ON FUNCTION ... TO service_role`
3. Verify schema: Use `public.vector_search` if needed

### Permission Denied

```python
# Error: "permission denied for function vector_search"
```

**Solutions:**
1. Check user role: `SELECT current_user, current_role;`
2. Grant execute permission: `GRANT EXECUTE ON FUNCTION vector_search TO service_role`
3. Check RLS policies: Ensure they allow RPC execution

### Vector Dimension Mismatch

```python
# Error: "vector must have 1536 dimensions"
```

**Solutions:**
1. Check embedding dimension: `array_length(query_embedding, 1)`
2. Regenerate embeddings with correct dimension
3. Update function to accept variable dimensions (advanced)

### Slow Performance

**Symptoms:** RPC calls take >1 second

**Solutions:**
1. Rebuild vector index: `REINDEX INDEX thoughts_embedding_idx`
2. Analyze table: `ANALYZE thoughts`
3. Check vector index configuration (lists parameter)
4. Reduce result count (match_count)
5. Add additional filters (thought_type, date range)

## Best Practices

1. **Use specific RPC functions** over `execute_sql`
2. **Parameterize queries** when possible
3. **Use LIMIT** to control result size
4. **Index frequently queried columns**
5. **Monitor performance** with `EXPLAIN ANALYZE`
6. **Document functions** in code comments
7. **Version functions** for easy rollback
8. **Test functions** before deploying to production
9. **Grant minimal permissions** required
10. **Use transactions** for multi-step operations

## Migration

When modifying RPC functions:

1. Create new version: `vector_search_v2`
2. Test thoroughly
3. Update code to use new version
4. Drop old version: `DROP FUNCTION IF EXISTS vector_search_v1`

```sql
-- Safe drop
DROP FUNCTION IF EXISTS vector_search_v1(vector(1536), INTEGER);
```

## Additional Resources

- [Supabase RPC Documentation](https://supabase.com/docs/guides/database/functions)
- [PostgreSQL Functions](https://www.postgresql.org/docs/current/sql-createfunction.html)
- [pgvector Documentation](https://github.com/pgvector/pgvector)
- [Advanced PostgreSQL Performance](https://wiki.postgresql.org/wiki/Performance_Optimization)

### `acquire_lock`

Atomically acquires a distributed lock for cross-instance coordination. Used by `SupabaseLock` class.

**Signature:**
```sql
acquire_lock(
    p_instance_id UUID,
    p_hostname TEXT,
    p_pid INTEGER,
    p_operation TEXT,
    p_ttl_seconds INTEGER
)
RETURNS BOOLEAN
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `p_instance_id` | UUID | Yes | Unique identifier for the requesting instance |
| `p_hostname` | TEXT | Yes | Host machine name |
| `p_pid` | INTEGER | Yes | Process ID |
| `p_operation` | TEXT | Yes | Operation name (e.g., "orphan_cleanup", "file_write") |
| `p_ttl_seconds` | INTEGER | Yes | Time-to-live for the lock in seconds |

**Returns:**
- `TRUE` if lock was acquired successfully
- `FALSE` if lock is already held by another non-expired instance

**Behavior:**
1. If no lock exists or existing lock has expired, acquires the lock
2. Updates `server_lock` table (singleton row, id=1)
3. Sets `expires_at` to `NOW() + p_ttl_seconds`
4. Returns `FALSE` if another instance holds a valid (non-expired) lock

**Usage Example (Python):**

```python
from supabase_lock import SupabaseLock

lock = SupabaseLock()
acquired = await lock.acquire(
    operation="orphan_cleanup",
    ttl_seconds=300
)

if acquired:
    try:
        # Perform locked operation
        await perform_cleanup()
    finally:
        await lock.release()
else:
    print("Lock held by another instance, skipping")
```

**SQL Implementation:**

```sql
CREATE OR REPLACE FUNCTION acquire_lock(
    p_instance_id UUID,
    p_hostname TEXT,
    p_pid INTEGER,
    p_operation TEXT,
    p_ttl_seconds INTEGER
)
RETURNS BOOLEAN
LANGUAGE plpgsql
AS $$
BEGIN
    -- Try to acquire: update if expired, or insert if no row exists
    UPDATE server_lock
    SET
        instance_id = p_instance_id,
        hostname = p_hostname,
        pid = p_pid,
        acquired_at = NOW(),
        expires_at = NOW() + (p_ttl_seconds || ' seconds')::INTERVAL,
        operation = p_operation
    WHERE id = 1
      AND (expires_at IS NULL OR expires_at < NOW());

    -- Check if we got a row
    IF FOUND THEN
        RETURN TRUE;
    END IF;

    -- If no row was updated, check if we need to insert
    IF NOT EXISTS (SELECT 1 FROM server_lock WHERE id = 1) THEN
        INSERT INTO server_lock (id, instance_id, hostname, pid, acquired_at, expires_at, operation)
        VALUES (1, p_instance_id, p_hostname, p_pid, NOW(), NOW() + (p_ttl_seconds || ' seconds')::INTERVAL, p_operation);
        RETURN TRUE;
    END IF;

    -- Lock is held by another instance
    RETURN FALSE;
END;
$$;
```

**Performance Notes:**
- Uses PostgreSQL row-level locking for atomicity
- TTL-based auto-expiration prevents deadlocks
- Singleton row pattern (id=1) ensures only one lock exists
