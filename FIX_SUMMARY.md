# Fix Summary: Obsidian Filename Generation

## Problem
Notes were being saved as `{date}-Untitled.md` instead of using the title from markdown headers.

Example: `2026-03-03-Untitled.md` instead of `10 Health Discoveries from 500 Studies.md`

## Root Cause Analysis
Multiple issues were discovered:

1. **API Timeout**: The z.ai API was timing out with a default 30-second timeout, preventing metadata extraction
2. **Title Not Preserved**: Even when a title was provided as a parameter, it wasn't being added to the metadata dictionary
3. **AI Not Returning Title**: The z.ai GLM-4.7 model wasn't consistently including a "title" field in its JSON response

## Solution
Multiple fixes were applied across four files to ensure robust filename generation.

## Changes Made

### File: `second-brain-mcp/metadata.py`

#### 1. Increased API Timeout
```python
self.client = OpenAI(
    api_key=self.api_key,
    base_url=self.base_url,
    timeout=90,  # Increased from 30 to 90 seconds for API reliability
    max_retries=3
)
```

#### 2. Added DEBUG Flag
```python
# Debug flag - set to True to enable debug output
DEBUG = False
```

#### 3. Enhanced Title Extraction
Updated the `_generate_title()` method to use regex pattern matching to extract markdown headers.

```python
def _generate_title(self, content: str) -> str:
    """Generate a title from content if none provided"""
    # First, try to find markdown headers (h1, h2, h3)
    import re
    
    # Look for h1 (# Header) or h2 (## Header) headers
    header_pattern = r'^(#{1,3})\s+(.+)$'
    lines = content.split('\n')
    
    for line in lines:
        line = line.strip()
        match = re.match(header_pattern, line)
        if match:
            title = match.group(2).strip()
            # Remove any extra # symbols or formatting
            title = re.sub(r'\s*#+$', '', title)
            if title and len(title) > 3:
                return title[:50]  # Limit to 50 chars
    
    # Fallback: first sentence or first 10 words
    first_sentence = content.split('.')[0].strip()
    if len(first_sentence) > 50:
        return first_sentence[:50] + "..."
    return first_sentence or "Untitled Note"
```

### File: `second-brain-mcp/tools.py`

#### 1. Added CRITICAL FIX for Title Preservation
```python
# CRITICAL FIX: Ensure title is in metadata
# The AI might not return title, so we add it from the parameter
if "title" not in metadata or not metadata.get("title"):
    metadata["title"] = title or "Untitled"
```

This defensive check ensures that even if:
- The AI doesn't return a title field
- The AI returns an empty or null title
- The title gets lost somewhere in the processing

The title from the parameter is always preserved.

#### 2. Added DEBUG Flag
```python
# Debug flag - set to True to enable debug output
DEBUG = False
```

#### 3. Conditional Debug Output
All debug dictionary creation and `_debug` field additions are now wrapped with `if DEBUG:` to disable by default.

### File: `second-brain-mcp/server.py`

#### 1. Updated Tool Description
```python
Tool(
    name="store_thought",
    description="Store a thought in both Supabase and Obsidian. Note: This tool may take up to 90 seconds due to AI metadata extraction. Please wait for completion before retrying.",
    ...
)
```

This informs calling LLMs that the operation may take up to 90 seconds, preventing duplicate storage attempts.

### File: `second-brain-mcp/obsidian.py`

#### 1. Added DEBUG Flag
```python
# Debug flag - set to True to enable debug output
DEBUG = False
```

#### 2. Conditional Debug Output
All debug dictionary creation and `_debug` field additions are now wrapped with `if DEBUG:` to disable by default.

## Test Results

### Basic Test (`test_filename_generation.py`)
- ✓ Generic title "Note" correctly uses date prefix: `2026-03-03-Note.md`
- ✓ Meaningful title uses title-only: `Python Async Programming Guide.md`
- ✓ Long titles truncated at 50 chars (by design)

### Full Workflow Test (`test_full_workflow.py`)
- ✓ Extracted title from h2 header: `Summary: The Glymphatic System and Alzheimer's Dis`
- ✓ Filename based on header: `Summary The Glymphatic System and Alzheimer's Dis.md`
- ✓ No "Untitled" in filename

### Live Test (After Fixes)
- ✓ Title "Timeout Test Note" → File: `-To-Sort-\Timeout Test Note.md`
- ✓ Title "10 Health Discoveries from 500 Studies" → File: `Resources\Health & Longevity\10 Health Discoveries from 500 Studies.md`
- ✓ No timeout errors with 90-second timeout
- ✓ Filename generation working correctly

## Important: Server Restart Required

**You must restart your MCP server for these changes to take effect!**

1. Stop the Second Brain MCP server
2. Start it again
3. Try saving a new note

The server will not pick up code changes until restarted.

## Filename Generation Rules

The system now uses smart filename generation:

### Meaningful Titles
- Length ≥ 3 characters
- Not a generic term ("untitled", "untitled note", "note")
- Not just numbers
- **Format**: `{title}.md`
- **Example**: `Summary The Glymphatic System and Alzheimers Disease Prevention.md`

### Generic Titles
- Short (< 3 chars), generic terms, or numbers only
- **Format**: `{YYYY-MM-DD}-{title}.md`
- **Example**: `2026-03-03-Note.md`

### Notes
- Titles are sanitized (invalid characters removed, spaces preserved)
- Maximum length: 50 characters
- Colon (:) and other special characters are removed during sanitization

## Debug Mode

Debug output is disabled by default to keep responses clean. To enable debug mode for troubleshooting:

### Enabling Debug Output

Change `DEBUG = False` to `DEBUG = True` in any of these files:

1. `second-brain-mcp/metadata.py` - Debug AI metadata extraction
2. `second-brain-mcp/tools.py` - Debug store_thought workflow
3. `second-brain-mcp/obsidian.py` - Debug filename generation

### What Debug Mode Shows

When enabled, the `store_thought` tool response includes a `_debug` field with:

- **Input parameters**: `input_title`, `content_length`
- **Metadata flow**: `metadata_keys`, `metadata_title` after extraction
- **Filename generation**: `folder`, `folder_confidence`, `sanitized_title`, `filename_format`
- **Title preservation**: Shows title before and after processing

### Example Debug Output

```json
{
  "success": true,
  "supabase_id": 17,
  "obsidian_path": "Resources\\Health & Longevity\\10 Health Discoveries from 500 Studies.md",
  "message": "Thought stored successfully in both systems",
  "_debug": {
    "input_title": "10 Health Discoveries from 500 Studies",
    "content_length": 2919,
    "metadata_keys": ["topics", "video_date", "content_type", "study_count", "title"],
    "metadata_title": "10 Health Discoveries from 500 Studies",
    "metadata_before_create": "10 Health Discoveries from 500 Studies",
    "obsidian_create": {
      "metadata_title": "10 Health Discoveries from 500 Studies",
      "folder": "Resources\\Health & Longevity",
      "folder_confidence": 1.0,
      "sanitized_title": "10 Health Discoveries from 500 Studies",
      "filename_format": "title_only",
      "filename": "10 Health Discoveries from 500 Studies.md"
    }
  }
}
```

### Disabling Debug Mode

Set `DEBUG = False` (default) in all files to disable debug output. This reduces response size and keeps the interface clean.

## Troubleshooting

### Issue: Still getting "Untitled" in filenames

**Cause**: Title parameter not being passed or title is empty/None

**Solution**: 
1. Ensure you're passing the `title` parameter when calling `store_thought`
2. Check that the title string is not empty
3. Enable debug mode to see the title flow

### Issue: Timeout errors

**Cause**: API call to z.ai is timing out

**Solution**:
1. Timeout has been increased to 90 seconds (from 30s)
2. If still timing out, check your internet connection
3. Verify z.ai API key is valid
4. Check if z.ai service is operational

### Issue: Files going to wrong folder

**Cause**: Semantic search or folder matching not working correctly

**Solution**:
1. Enable debug mode to see `folder` and `folder_confidence` values
2. Check if folders are synced to database (first call syncs folders)
3. Consider using `metadata.folder` to manually specify the folder

### Issue: Need to see what's happening internally

**Solution**: Enable debug mode by changing `DEBUG = True` in the relevant files, then restart the MCP server.

## Test Files Created

1. `second-brain-mcp/test_filename_generation.py` - Basic filename generation tests
2. `second-brain-mcp/test_full_workflow.py` - Full MCP workflow simulation

Run these to verify the changes work:
```bash
python second-brain-mcp\test_filename_generation.py
python second-brain-mcp\test_full_workflow.py
```

## Summary of All Fixes

✅ **API Timeout**: Increased from 30s → 90s in `metadata.py`  
✅ **Title Preservation**: Added defensive check in `tools.py` to ensure title is always in metadata  
✅ **Tool Documentation**: Added timeout note to `store_thought` description in `server.py`  
✅ **Debug Infrastructure**: Added `DEBUG` flags to `metadata.py`, `tools.py`, `obsidian.py`  
✅ **Debug Output**: All debug logging disabled by default, preserved for troubleshooting  
✅ **Filename Generation**: Enhanced to extract titles from markdown headers  

All changes are production-ready and tested. Debug mode is available if needed for future troubleshooting.