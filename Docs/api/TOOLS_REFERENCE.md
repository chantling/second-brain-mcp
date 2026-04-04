# MCP Tools API Reference

Complete reference for all MCP tools provided by the Second Brain Server.

## Overview

The Second Brain MCP Server provides 14 tools for interacting with your knowledge base. All tools return data in consistent formats and include error handling.

## Common Response Format

### Success Response

```json
{
  "field1": "value",
  "field2": 123,
  "_debug": {} // Optional debug information
}
```

### Error Response

```json
{
  "error": "Error message",
  "message": "Human-readable error description"
}
```

## Tools

### 1. store_thought

Store a thought in both Supabase (with vector embedding) and Obsidian (as markdown file).

**Endpoint:** `store_thought`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|-------|-----------|-------------|
| `content` | string | Yes | The thought content (markdown supported) |
| `title` | string | No | Optional title for the thought (used in filename) |
| `metadata` | object | No | Metadata dictionary (see below) |
| `source` | string | No | Source of the thought (default: "manual") |

**Metadata Object Structure:**

```json
{
  "type": "knowledge",           // Required: "knowledge", "recipe", "todo", "contact", "guide"
  "topics": ["tag1", "tag2"],   // Optional: Array of topic tags
  "people": ["Alice", "Bob"],       // Optional: Array of people mentioned
  "action_items": ["Task 1"],       // Optional: Array of action items
  "folder": "Resources/Electronics", // Optional: Override automatic folder selection
  "custom_field": "any value"        // Optional: Any custom metadata
}
```

**Returns:**

```json
{
  "success": true,
  "supabase_id": 123,
  "obsidian_path": "Resources/Electronics/2026-03-04-Soldering-Guide.md",
  "message": "Thought stored successfully in both systems"
}
```

**Behavior:**

1. Extracts metadata if not provided (uses AI via configured provider)
2. Generates vector embedding for content
3. Checks for duplicates (3-tier: video_id, exact URL, heuristic URL)
4. Handles duplicates based on `DUPLICATE_HANDLING_MODE` (prompt/skip/overwrite)
5. Stores in Supabase with embedding
6. Syncs tags (from frontmatter + inline `#tags`)
7. Determines optimal folder (semantic matching if enabled)
8. Creates markdown file in Obsidian vault with frontmatter
9. Updates database with obsidian_path
10. Returns both IDs and file path

**Duplicate Detection Tiers:**
- **Tier 1 (High confidence)**: Exact `video_id` match → block/prompt/overwrite
- **Tier 2 (High confidence)**: Exact URL match (normalized) → block/prompt/overwrite
- **Tier 3 (Medium confidence)**: Heuristic URL match (tracking params removed) → store with warning

**Duplicate Handling Modes:**
- `prompt` (default): Returns duplicate info for LLM to decide
- `skip`: Silently skips storage, returns existing thought info
- `overwrite`: Updates existing thought in place

**Example:**

```python
result = await store_thought(
    content="Blood pressure reading: 120/80, normal range",
    title="BP Check",
    metadata={
        "type": "knowledge",
        "topics": ["health", "blood_pressure"],
        "folder": "Areas/Health & Longevity"
    }
)
# → Places in: Areas/Health & Longevity/BP-Check.md
```

**Timeout:** Up to 240 seconds (AI metadata extraction + embedding generation)

---

### 2. semantic_search

Search thoughts by semantic similarity using vector embeddings.

**Endpoint:** `semantic_search`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|-------|-----------|-------------|
| `query` | string | Yes | Search query (natural language) |
| `limit` | integer | No | Maximum results to return (default: 10) |
| `topics` | array | No | Filter by topic tags |

**Returns:**

```json
[
  {
    "id": 123,
    "content": "Note content...",
    "thought_type": "knowledge",
    "topics": ["electronics", "soldering"],
    "people": [],
    "action_items": [],
    "obsidian_path": "Resources/Electronics/2026-03-04-Soldering-Guide.md",
    "obsidian_url": "obsidian://open?file=Resources/Electronics/2026-03-04-Soldering-Guide.md",
    "created_at": "2026-03-04T12:00:00Z",
    "similarity": 0.85
  },
  // ... more results
]
```

**Behavior:**

1. Generates vector embedding for query
2. Performs cosine similarity search in Supabase
3. Returns results ranked by similarity (0-1, higher = more similar)
4. Includes `obsidian_url` for easy Obsidian navigation
5. Filters by topics if provided

**Example:**

```python
results = await semantic_search(
    query="how to solder components",
    limit=5
)
# Returns notes about electronics, soldering, circuits
```

**Performance:** < 1 second after connection warmup

---

### 3. list_recent

List recent thoughts from both systems.

**Endpoint:** `list_recent`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|-------|-----------|-------------|
| `days` | integer | No | Number of days to look back (default: 7) |
| `thought_type` | string | No | Filter by thought type (knowledge, recipe, todo, etc.) |

**Returns:**

```json
[
  {
    "id": 123,
    "content": "Recent note content...",
    "thought_type": "knowledge",
    "topics": ["tag1", "tag2"],
    "obsidian_path": "Resources/Notes/2026-03-04-Recent-Note.md",
    "obsidian_url": "obsidian://open?file=Resources/Notes/2026-03-04-Recent-Note.md",
    "created_at": "2026-03-04T10:30:00Z"
  },
  // ... more results
]
```

**Example:**

```python
# Recent thoughts from last 3 days
results = await list_recent(days=3)

# Recent recipes only
results = await list_recent(days=7, thought_type="recipe")
```

---

### 4. get_thought

Get a specific thought by ID.

**Endpoint:** `get_thought`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|-------|-----------|-------------|
| `thought_id` | integer | Yes | Thought ID to retrieve |

**Returns:**

```json
{
  "id": 123,
  "content": "Full note content...",
  "thought_type": "knowledge",
  "topics": ["tag1", "tag2"],
  "people": ["Alice"],
  "action_items": ["Task 1"],
  "obsidian_path": "Resources/Notes/2026-03-04-Specific-Note.md",
  "obsidian_url": "obsidian://open?file=Resources/Notes/2026-03-04-Specific-Note.md",
  "metadata": {
    "title": "Note Title",
    "custom_field": "value"
  },
  "source": "manual",
  "created_at": "2026-03-04T12:00:00Z",
  "updated_at": "2026-03-04T12:30:00Z"
}
```

**Example:**

```python
thought = await get_thought(thought_id=123)
print(thought["content"])
```

---

### 5. search_by_topic

Search thoughts by specific topic tag.

**Endpoint:** `search_by_topic`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|-------|-----------|-------------|
| `topic` | string | Yes | Topic to search for |
| `limit` | integer | No | Maximum results (default: 20) |

**Returns:**

```json
[
  {
    "id": 123,
    "content": "Topic-related content...",
    "thought_type": "knowledge",
    "topics": ["health", "blood_pressure"],
    "obsidian_path": "Areas/Health/2026-03-04-BP-Reading.md",
    "obsidian_url": "obsidian://open?file=Areas/Health/2026-03-04-BP-Reading.md",
    "created_at": "2026-03-04T10:00:00Z"
  },
  // ... more results
]
```

**Example:**

```python
results = await search_by_topic(topic="health", limit=10)
```

---

### 6. get_todos

Get todo items.

**Endpoint:** `get_todos`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|-------|-----------|-------------|
| `completed` | boolean | No | Include completed todos (default: false) |

**Returns:**

```json
[
  {
    "id": 123,
    "content": "- [ ] Task to do",
    "thought_type": "todo",
    "topics": [],
    "metadata": {
      "completed": false
    },
    "obsidian_path": "-To-Do-/2026-03-04-Task.md",
    "obsidian_url": "obsidian://open?file=-To-Do-/2026-03-04-Task.md",
    "created_at": "2026-03-04T09:00:00Z"
  },
  // ... more results
]
```

**Example:**

```python
# Get active todos
active = await get_todos(completed=False)

# Get all todos (including completed)
all = await get_todos(completed=True)
```

---

### 7. find_recipes

Find recipes based on criteria.

**Endpoint:** `find_recipes`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|-------|-----------|-------------|
| `ingredients` | array | No | List of required ingredients (subset match) |
| `category` | string | No | Recipe category (breakfast, dessert, etc.) |
| `max_time` | integer | No | Maximum total time in minutes |

**Returns:**

```json
[
  {
    "id": 123,
    "content": "# Pancakes\n\nIngredients: 2 eggs, flour, milk...",
    "thought_type": "recipe",
    "topics": ["breakfast", "dessert"],
    "metadata": {
      "title": "Pancakes",
      "category": "breakfast",
      "total_time": 15,
      "ingredients": ["eggs", "flour", "milk"]
    },
    "obsidian_path": "Resources/Recipes/Pancakes.md",
    "obsidian_url": "obsidian://open?file=Resources/Recipes/Pancakes.md",
    "created_at": "2026-03-04T08:00:00Z"
  },
  // ... more results
]
```

**Example:**

```python
# Recipes with eggs
results = await find_recipes(ingredients=["eggs"])

# Breakfast recipes under 30 minutes
results = await find_recipes(category="breakfast", max_time=30)
```

---

### 8. list_guides

List guides by category and difficulty.

**Endpoint:** `list_guides`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|-------|-----------|-------------|
| `category` | string | No | Guide category (programming, cooking, etc.) |
| `difficulty` | string | No | Difficulty level: "easy", "medium", "hard" |

**Returns:**

```json
[
  {
    "id": 123,
    "content": "# How to Solder Components\n\n...",
    "thought_type": "guide",
    "topics": ["electronics", "soldering"],
    "metadata": {
      "title": "Soldering Guide",
      "category": "electronics",
      "difficulty": "medium"
    },
    "obsidian_path": "Resources/Electronics/Soldering-Guide.md",
    "obsidian_url": "obsidian://open?file=Resources/Electronics/Soldering-Guide.md",
    "created_at": "2026-03-04T10:00:00Z"
  },
  // ... more results
]
```

**Example:**

```python
# Medium difficulty electronics guides
results = await list_guides(category="electronics", difficulty="medium")
```

---

### 9. get_contacts

Get contact information.

**Endpoint:** `get_contacts`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|-------|-----------|-------------|
| `name` | string | No | Name to search for (partial match) |
| `category` | string | No | Contact category (work, personal, etc.) |

**Returns:**

```json
[
  {
    "id": 123,
    "content": "# Alice Smith\n\nEmail: alice@example.com",
    "thought_type": "contact",
    "topics": [],
    "metadata": {
      "name": "Alice Smith",
      "category": "work",
      "email": "alice@example.com"
    },
    "obsidian_path": "Contacts/Alice-Smith.md",
    "obsidian_url": "obsidian://open?file=Contacts/Alice-Smith.md",
    "created_at": "2026-03-04T09:00:00Z"
  },
  // ... more results
]
```

**Example:**

```python
# Search for Alice
results = await get_contacts(name="Alice")

# Get all work contacts
results = await get_contacts(category="work")
```

---

### 10. get_backlinks

Get all notes that link to a given note.

**Endpoint:** `get_backlinks`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|-------|-----------|-------------|
| `thought_id` | integer | Yes | Target thought ID |
| `limit` | integer | No | Maximum results (default: 10) |

**Returns:**

```json
[
  {
    "id": 456,
    "content": "Note that links to the target...",
    "thought_type": "knowledge",
    "obsidian_path": "Resources/Notes/2026-03-04-Referencing-Note.md",
    "obsidian_url": "obsidian://open?file=Resources/Notes/2026-03-04-Referencing-Note.md",
    "link_type": "wiki",
    "link_text": "Target Note Name",
    "created_at": "2026-03-04T11:00:00Z"
  },
  // ... more notes linking to this thought
]
```

**Behavior:**
- Finds all notes with wiki-links pointing to this thought
- Useful for understanding context and connections

**Example:**

```python
# Find notes that link to thought ID 123
backlinks = await get_backlinks(thought_id=123)
```

---

### 11. find_related_notes

Find related notes via shared links and tag overlap.

**Endpoint:** `find_related_notes`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|-------|-----------|-------------|
| `thought_id` | integer | Yes | Starting thought ID |
| `limit` | integer | No | Maximum results (default: 10) |

**Returns:**

```json
[
  {
    "id": 456,
    "content": "Related note content...",
    "thought_type": "knowledge",
    "topics": ["electronics", "circuits"],
    "obsidian_path": "Resources/Electronics/Circuit-Design.md",
    "obsidian_url": "obsidian://open?file=Resources/Electronics/Circuit-Design.md",
    "link_count": 3,
    "created_at": "2026-03-04T10:00:00Z"
  },
  // ... more related notes
]
```

**Behavior:**
- Finds notes with bidirectional links
- Considers tag overlap
- Ranks by connection count

**Example:**

```python
# Find notes related to thought ID 123
related = await find_related_notes(thought_id=123, limit=10)
```

---

### 12. suggest_tags

Suggest tags for a note based on content.

**Endpoint:** `suggest_tags`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|-------|-----------|-------------|
| `content` | string | Yes | Note content to analyze |
| `limit` | integer | No | Maximum suggestions (default: 10) |

**Returns:**

```json
[
  {
    "name": "electronics",
    "confidence": 0.92
  },
  {
    "name": "soldering",
    "confidence": 0.85
  },
  {
    "name": "circuits",
    "confidence": 0.78
  },
  // ... more suggestions
]
```

**Behavior:**
- Uses semantic similarity to existing tags
- Returns confidence score (0-1)
- Helps maintain consistent tagging

**Example:**

```python
suggestions = await suggest_tags(
    content="How to solder electronic components on PCB boards",
    limit=5
)
```

---

### 13. hybrid_search

Advanced search combining vector similarity, keyword matching, and recency.

**Endpoint:** `hybrid_search`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|-------|-----------|-------------|
| `query` | string | Yes | Search query |
| `limit` | integer | No | Maximum results (default: 10) |
| `filters` | object | No | Filters object (see below) |
| `weights` | object | No | Scoring weights (see below) |

**Filters Object:**

```json
{
  "thought_type": "knowledge",        // Filter by type
  "folder": "Resources/Electronics", // Filter by folder path
  "tags": ["electronics", "circuits"], // Filter by tags
  "date_range": {
    "start": "2026-01-01T00:00:00Z",
    "end": "2026-12-31T23:59:59Z"
  }
}
```

**Weights Object:**

```json
{
  "vector": 0.7,    // Weight for vector similarity (default: 0.7)
  "keywords": 0.3,  // Weight for keyword match (default: 0.3)
  "recency": 0.0    // Weight for recency boost (default: 0.0)
}
```

**Returns:**

```json
[
  {
    "id": 123,
    "content": "Search result content...",
    "thought_type": "knowledge",
    "topics": ["electronics"],
    "obsidian_path": "Resources/Electronics/2026-03-04-Note.md",
    "obsidian_url": "obsidian://open?file=Resources/Electronics/2026-03-04-Note.md",
    "vector_score": 0.85,
    "keyword_score": 0.60,
    "recency_score": 0.10,
    "combined_score": 0.78,
    "created_at": "2026-03-04T10:00:00Z"
  },
  // ... more results
]
```

**Scoring:**

```
combined_score = (vector_weight * vector_score)
              + (keyword_weight * keyword_score)
              + (recency_weight * recency_score)
```

**Example:**

```python
results = await hybrid_search(
    query="soldering electronics",
    limit=10,
    filters={
        "thought_type": "knowledge",
        "tags": ["electronics"]
    },
    weights={
        "vector": 0.6,
        "keywords": 0.3,
        "recency": 0.1
    }
)
```

---

### 14. search_by_keyword

Search for exact words or phrases in note content using PostgreSQL full-text search (tsvector). Finds exact matches regardless of topic tags.

**Endpoint:** `search_by_keyword`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|-------|-----------|-------------|
| `query` | string | Yes | Exact word or phrase to search for |
| `limit` | integer | No | Maximum results (default: 10) |

**Returns:**

```json
[
  {
    "id": 123,
    "content": "Note content containing the exact word...",
    "thought_type": "knowledge",
    "topics": ["electronics"],
    "obsidian_path": "Resources/Electronics/2026-03-04-Note.md",
    "obsidian_url": "obsidian://open?file=Resources/Electronics/2026-03-04-Note.md",
    "score": 0.95,
    "similarity": 0.95,
    "created_at": "2026-03-04T10:00:00Z"
  },
  // ... more results
]
```

**Behavior:**

1. Uses PostgreSQL full-text search on `content_tsv` column (tsvector with GIN index)
2. Falls back to ILIKE keyword search if full-text search fails
3. Results scored by position (earlier matches score higher)
4. Includes `obsidian_url` for easy Obsidian navigation

**Example:**

```python
# Search for exact word
results = await search_by_keyword(query="soldering")

# Search for exact phrase
results = await search_by_keyword(query="circuit design", limit=5)
```

**Performance:** ~0.26s for exact word matches (GIN index O(1) lookups)

**Note:** This tool is different from `semantic_search` which finds conceptually similar content. `search_by_keyword` finds exact word matches regardless of semantic meaning.

---

## Error Handling

All tools handle errors gracefully:

### Common Errors

1. **Database Connection Error**
   ```json
   {
     "error": "Failed to connect to database",
     "message": "Check Supabase configuration"
   }
   ```

2. **Obsidian Path Error**
   ```json
   {
     "error": "Obsidian vault not found",
     "message": "Check OBSIDIAN_VAULT_PATH in .env"
   }
   ```

3. **API Timeout**
   ```json
   {
     "error": "API timeout after 240 seconds",
     "message": "Embedding or metadata API slow/unavailable"
   }
   ```

4. **Invalid Input**
   ```json
   {
     "error": "Invalid parameter",
     "message": "thought_id must be an integer"
   }
   ```

## Performance Characteristics

| Tool | Typical Response Time | Notes |
|-------|---------------------|--------|
| `store_thought` | 3-13s | Depends on AI metadata extraction + embedding |
| `semantic_search` | 1-3s | After connection warmup, API-bound |
| `list_recent` | < 0.5s | Simple database query |
| `get_thought` | < 0.5s | Single record lookup |
| `search_by_topic` | < 0.5s | Tag-based query |
| `get_todos` | < 0.5s | Type-based filter |
| `find_recipes` | < 1s | Multiple filter conditions |
| `list_guides` | < 1s | Multiple filter conditions |
| `get_contacts` | < 1s | Name/category filters |
| `get_backlinks` | < 1s | Join query |
| `find_related_notes` | 1-2s | Complex graph traversal |
| `suggest_tags` | < 1s | Vector tag matching |
| `hybrid_search` | 1-2s | Multiple scoring phases |
| `search_by_keyword` | < 0.3s | FTS with GIN index (O(1) lookups) |

## Usage Patterns

### Storing Thoughts

```python
# Simple note
await store_thought(
    content="Quick note about something"
)

# With metadata
await store_thought(
    content="Blood pressure: 120/80",
    title="BP Reading",
    metadata={
        "type": "knowledge",
        "topics": ["health"],
        "people": []
    }
)

# With folder override
await store_thought(
    content="Project notes",
    metadata={
        "folder": "Projects/101-Specific-Project"
    }
)
```

### Searching

```python
# Semantic search
results = await semantic_search("how to solder", limit=5)

# Topic search
results = await search_by_topic("electronics", limit=10)

# Hybrid search
results = await hybrid_search(
    query="circuit design",
    filters={"thought_type": "knowledge"},
    weights={"vector": 0.8, "keywords": 0.2}
)
```

### Navigation

```python
# Get backlinks
backlinks = await get_backlinks(thought_id=123)

# Find related notes
related = await find_related_notes(thought_id=123)

# Get specific note
thought = await get_thought(thought_id=123)
```

## Best Practices

1. **Use `semantic_search`** for natural language queries
2. **Use `hybrid_search`** for complex queries with filters
3. **Include metadata** when storing for better organization
4. **Check `obsidian_url`** for direct Obsidian navigation
5. **Handle errors gracefully** - check for `"error"` key in response
6. **Set appropriate limits** - don't fetch unnecessary data
7. **Use tags** for consistent categorization
8. **Use `store_thought`** for creating, not direct file manipulation

## Advanced Usage

### Batch Operations

```python
# Store multiple thoughts
for thought in thoughts_batch:
    await store_thought(**thought)
```

### Chained Operations

```python
# Search → Get details → Find related
results = await semantic_search("soldering")
if results:
    thought = await get_thought(results[0]["id"])
    related = await find_related_notes(thought["id"])
```

### Filtering and Pagination

```python
# Get recent, then filter
recent = await list_recent(days=30)
knowledge_only = [r for r in recent if r["thought_type"] == "knowledge"]
```

## See Also

- [Architecture Documentation](../architecture/ARCHITECTURE.md)
- [Database Schema](../database/SCHEMA.md)
- [Configuration Guide](../guides/CONFIGURATION.md)
