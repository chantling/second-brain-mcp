# Hierarchical Folder Matching Implementation

## Overview

Implemented a hierarchical semantic folder matching system that navigates through folder trees level by level to find the most appropriate location for storing notes.

## How It Works

### Hierarchical Search Algorithm

1. **Level 0 (Top-level folders)**: Search all top-level folders using semantic similarity
2. **Level 1 (Subfolders)**: Once a top-level folder is selected, search only its direct subfolders
3. **Level 2+**: Continue drilling down until reaching a leaf folder (no subfolders)
4. **Stop conditions**: 
   - No subfolders found (leaf folder reached)
   - Confidence drops below 0.3 (uncertain match)
   - Maximum depth of 10 levels reached (safety limit)

### Local Caching System

**File**: `!Folder_Embeddings.md` (stored in vault root)

**Purpose**: Cache folder embeddings locally to reduce database queries

**Benefits**:
- **Faster matching**: No need to query Supabase for each folder comparison
- **Reduced network overhead**: Embeddings are read from local file
- **Offline capability**: Can work with cached embeddings even if database is temporarily unavailable
- **Lower cost**: Fewer API calls to embeddng provider during matching

**Cache Lifecycle**:
- Created/updated during folder sync on server startup
- Valid for 7 days (configurable via `CACHE_VALIDITY_DAYS`)
- Automatically refreshed when expired
- Updated whenever new folder embeddings are fetched from database

**Format**: Markdown file with pipe-delimited format:
```markdown
# Folder Embeddings Cache

# Generated: 2026-03-03T17:50:00
# Valid for: 7 days

# Format: |folder_path|embedding_vector|

|Resources/Health & Longevity|[0.1234, 0.5678, ...]|
|Resources/Technology/AI|[0.9876, 0.5432, ...]|
```

## Implementation Details

### Files Modified

1. **obsidian.py**:
   - Added `_find_semantic_folder_match()`: Main hierarchical search method
   - Added `_find_best_match_at_level()`: Finds best match at a specific hierarchy level
   - Added `_organize_folders_by_level()`: Organizes folders by depth
   - Added `_load_folder_embeddings_cache()`: Loads cache from markdown file
   - Added `_save_folder_embeddings_cache()`: Saves cache to markdown file
   - Added `_is_cache_valid()`: Checks if cache needs refresh
   - Updated `sync_folders_to_database()`: Now saves embeddings to local cache

### Key Methods

#### `_find_semantic_folder_match(content, metadata)`
Main entry point for hierarchical folder matching.

**Returns**: `(folder_path, confidence_score)`

**Process**:
1. Load folder embeddings from local cache
2. Create embedding for note content
3. Navigate through hierarchy levels
4. At each level, find best matching subfolder
5. Continue until leaf folder or low confidence
6. Return final folder with overall confidence

#### `_find_best_match_at_level(note_embedding, folder_paths, cache, embedding_manager)`
Finds the best matching folder at a specific hierarchy level.

**Strategy**:
- Check cache for folder embeddings first
- Fetch missing embeddings from database
- Calculate cosine similarity between note and each folder
- Return best match with confidence score

#### Cache Management

**Loading**: 
```python
cache = _load_folder_embeddings_cache()
```

**Saving**:
```python
_save_folder_embeddings_cache(cache)
```

**Checking Validity**:
```python
if not _is_cache_valid():
    # Refresh cache
```

## Performance Considerations

### Why Local Caching Makes Sense

1. **Minimal Database Overhead**:
   - Folder embeddings only change when folder structure changes
   - Most queries are read-only (matching notes to folders)
   - Caching eliminates repeated database queries for the same folders

2. **Speed**:
   - Local file I/O is faster than network queries
   - No need to decode JSON from Supabase responses
   - Parallel comparisons can be done with in-memory data

3. **Reliability**:
   - Works offline if cache is available
   - Fallback to database if cache is missing or expired
   - Graceful degradation if cache is corrupted

4. **Cost**:
   - No additional API calls to embedding provider during matching
   - Embeddings are generated once per folder during sync
   - Reduced compute costs for vector similarity calculations

### When Cache is Refreshed

- On server startup (during folder sync)
- When cache is older than 7 days
- When new folders are added to the vault
- Manually triggered by restarting the server

## Debug Mode

Set `DEBUG = True` at the top of `obsidian.py` to enable detailed logging:

- Folder discovery process
- Cache loading/saving
- Hierarchical search progress
- Similarity scores at each level
- Final folder selection

Example output:
```
[DEBUG] Starting hierarchical folder search for content length: 1234
[DEBUG] Level 0: Searching 15 top-level folders
[DEBUG] Level 0: Best match = Resources (confidence: 0.8234)
[DEBUG] Level 1: Found 8 subfolders under Resources
[DEBUG] Level 1: Best match = Resources/Health & Longevity (confidence: 0.7654)
[DEBUG] Level 2: Found 3 subfolders under Resources/Health & Longevity
[DEBUG] Level 2: Best match = Resources/Health & Longevity/Exercise (confidence: 0.8123)
[DEBUG] Level 3: Found 0 subfolders under Resources/Health & Longevity/Exercise
[DEBUG] Final folder: Resources/Health & Longevity/Exercise (overall confidence: 0.5092)
```

## Configuration

### Adjustable Parameters

```python
# obsidian.py

EMBEDDINGS_CACHE_FILE = "!Folder_Embeddings.md"  # Cache filename
CACHE_VALIDITY_DAYS = 7  # How long cache remains valid

# Search thresholds
CONFIDENCE_THRESHOLD = 0.3  # Stop if confidence drops below this
MAX_HIERARCHY_DEPTH = 10  # Safety limit
```

## Testing

To test the implementation:

1. Start the server (triggers folder sync and cache creation)
2. Check that `!Folder_Embeddings.md` exists in vault root
3. Store a note and observe the console output
4. Verify the note is placed in the appropriate folder
5. Check the confidence score in the note's frontmatter

## Troubleshooting

### Cache Not Created
- Check that folder sync completed successfully
- Verify database connection is working
- Ensure folders have been synced to database

### Notes Going to "-To-Sort-"
- Enable DEBUG mode to see similarity scores
- Check if folder embeddings exist in cache
- Verify confidence threshold (0.3) is appropriate
- May need to adjust folder descriptions

### Slow Performance
- Check if cache is being used (DEBUG mode shows "Using cached embedding")
- Verify embeddings are being fetched from database, not regenerated
- Consider reducing hierarchy depth if folder tree is very deep

## Future Enhancements

Potential improvements:

1. **Learning from corrections**: Track when users move notes to different folders
2. **Confidence tuning**: Adjust thresholds based on user feedback
3. **Folder suggestions**: Suggest better folder names based on note content
4. **Batch processing**: Cache multiple folders in single database query
5. **Cache compression**: Compress embeddings to reduce file size
6. **Incremental updates**: Only update changed folder embeddings