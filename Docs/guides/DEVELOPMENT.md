# Developer Guide

This guide helps developers understand, extend, and contribute to the Second Brain MCP Server.

## Table of Contents

1. [Getting Started](#getting-started)
2. [Development Environment](#development-environment)
3. [Code Architecture](#code-architecture)
4. [Adding New Tools](#adding-new-tools)
5. [Modifying Behavior](#modifying-behavior)
6. [Testing](#testing)
7. [Debugging](#debugging)
8. [Performance Optimization](#performance-optimization)
9. [Deployment](#deployment)

## Getting Started

### Prerequisites

- Python 3.10+
- Git
- Supabase account and project
- Obsidian vault (optional)

### Initial Setup

```bash
# Clone repository
git clone <repository-url>
cd <repository>/second-brain-mcp

# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env

# Edit .env with your configuration
```

### Configuration

Create `.env` file in `second-brain-mcp/`:

```env
# Supabase Configuration
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SECRET_KEY=your-service-role-key
SUPABASE_PUBLISH_KEY=your-anon-key

# Embedding Configuration
EMBEDDING_API_KEY=your-embedding-api-key
EMBEDDING_BASE_URL=https://openrouter.ai/api/v1
EMBEDDING_MODEL=qwen/qwen3-embedding-8b
EMBEDDING_DIMENSIONS=1536

# Metadata Configuration
METADATA_API_KEY=your-metadata-api-key
METADATA_BASE_URL=https://api.z.ai/api/coding/paas/v4
METADATA_MODEL=glm-4.7

# Obsidian Configuration
OBSIDIAN_VAULT_PATH=./SecondBrain

# Sync Configuration
SYNC_ENABLED=true
SYNC_INITIAL_SYNC=true
SYNC_DEBOUNCE_SECONDS=2.0

# Lock Configuration
LOCK_RETRY_ENABLED=true
LOCK_HEARTBEAT_INTERVAL_SECONDS=20
```

## Development Environment

### Directory Structure

```
second-brain-mcp/
├── config.py              # Configuration management + blacklist
├── database.py            # Database operations + duplicate detection
├── embeddings.py          # Vector embedding generation
├── instance_lock.py       # OS-level file locking (portalocker)
├── supabase_lock.py       # Distributed DB lock for cross-instance coordination
├── links.py              # Wiki-link management
├── metadata.py           # AI metadata extraction
├── obsidian.py           # Obsidian vault management
├── search.py             # Hybrid search algorithms
├── server.py             # MCP server entry point
├── tags.py              # Tag operations and suggestions
├── tag_utils.py         # Shared tag extraction and sync utilities
├── tools.py             # Tool handlers (14 MCP tools)
├── watcher.py           # File system monitoring + debouncing + move detection
├── verify.py            # Verification utilities
├── manual_sync.py       # Standalone manual sync script
├── backfill_thought_tags.py  # Tag backfill utility
├── requirements.txt      # Python dependencies
├── .env               # Environment configuration (not in git)
├── .blacklist         # Blacklist patterns for path exclusion
└── Tests/              # Test suite (59+ test files)
```

### Key Patterns

1. **Async/Await Pattern** - All I/O is async
2. **Singleton Instances** - Global instances for DB, embedding, etc.
3. **Error Handling** - Try/except with logging to stderr
4. **Configuration** - Centralized in `config.py`

### Code Style

- **Docstrings**: Use Google-style docstrings
- **Type Hints**: Use `typing` module
- **Logging**: Use `print(..., file=sys.stderr)` for MCP logs
- **Error Messages**: Human-readable, include context

## Code Architecture

### Module Responsibilities

| Module | Responsibility | Key Classes/Functions |
|---------|----------------|----------------------|
| `server.py` | MCP protocol, lifecycle, background tasks | `main()`, `list_tools()`, `call_tool()` |
| `tools.py` | Tool implementations (14 tools) | `ToolHandlers` class |
| `database.py` | Supabase operations, duplicate detection | `DatabaseManager` class |
| `obsidian.py` | Obsidian file management, folder placement | `ObsidianManager` class |
| `embeddings.py` | Vector generation | `EmbeddingGenerator` class |
| `search.py` | Hybrid search algorithms | `SearchManager` class |
| `tags.py` | Tag operations and suggestions | `TagManager` class |
| `tag_utils.py` | Shared tag extraction and sync | `sync_tags_for_thought()` |
| `links.py` | Link management, graph exploration | `LinkManager` class |
| `metadata.py` | AI extraction | `MetadataExtractor` class |
| `watcher.py` | File monitoring, debouncing, move detection | `ObsidianEventHandler`, `LazyImport` |
| `instance_lock.py` | OS-level lock coordination | `InstanceLock` class |
| `supabase_lock.py` | Distributed DB lock | `SupabaseLock` class |
| `config.py` | Configuration + blacklist management | `Config` class |

### Data Flow

```
MCP Tool Call
    ↓
tools.py: handle_tool_call()
    ↓
→ Database (Supabase)
→ Obsidian (Markdown files)
→ External APIs (Embeddings, Metadata)
    ↓
Return result to MCP client
```

### Initialization Order

```python
# 1. Load configuration
from config import Config
Config.validate()

# 2. Initialize global instances
db_manager = DatabaseManager()
embedding_generator = EmbeddingGenerator()
obsidian_manager = ObsidianManager(Config.OBSIDIAN_VAULT_PATH, db_manager)

# 3. Start background tasks
# - File watcher
# - Initial sync
# - Heartbeat loop

# 4. Start MCP server
await server.run(read_stream, write_stream, options)
```

## Adding New Tools

### Step 1: Define Tool in server.py

Add tool to `list_tools()` function:

```python
@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        # ... existing tools ...
        Tool(
            name="my_new_tool",
            description="Description of what this tool does",
            inputSchema={
                "type": "object",
                "properties": {
                    "param1": {
                        "type": "string",
                        "description": "Parameter description"
                    },
                    "param2": {
                        "type": "integer",
                        "description": "Optional parameter",
                        "default": 10
                    }
                },
                "required": ["param1"]
            }
        )
    ]
```

### Step 2: Implement Handler in tools.py

```python
class ToolHandlers:
    async def handle_tool_call(self, name: str, arguments: Dict[str, Any]) -> Any:
        handlers = {
            # ... existing handlers ...
            "my_new_tool": self.my_new_tool,
        }
        
        handler = handlers.get(name)
        if not handler:
            return {"error": f"Unknown tool: {name}"}
        
        return await handler(**arguments)
    
    async def my_new_tool(
        self,
        param1: str,
        param2: int = 10
    ) -> Dict:
        """Implement your tool logic here"""
        try:
            # Your implementation
            result = {"success": True, "data": "..."}
            return result
        except Exception as e:
            return {"error": str(e), "message": "Operation failed"}
```

### Step 3: Add Documentation

Update:
1. `Docs/api/TOOLS_REFERENCE.md` - Add tool documentation
2. `README.md` - Brief description of new tool

### Step 4: Write Tests

Create test file `Tests/test_my_new_tool.py`:

```python
import asyncio
import sys
sys.path.insert(0, '..')

from tools import ToolHandlers

async def test_my_new_tool():
    """Test the new tool"""
    handlers = ToolHandlers()
    
    # Test basic functionality
    result = await handlers.my_new_tool(
        param1="test value",
        param2=5
    )
    
    assert "success" in result or "error" in result
    print(f"✓ Tool test passed: {result}")

if __name__ == "__main__":
    asyncio.run(test_my_new_tool())
```

### Step 5: Run Tests

```bash
cd Tests
python test_my_new_tool.py
```

## Modifying Behavior

### Changing Folder Selection Logic

Edit `obsidian.py:ObsidianManager._determine_folder()`:

```python
def _determine_folder(self, content: str, metadata: Dict) -> Tuple[str, float]:
    """Determine best folder for a note using confidence scoring"""
    
    # Add your custom logic here
    if custom_condition:
        return ("Custom/Folder/Path", 1.0)
    
    # ... existing logic ...
```

### Changing Metadata Extraction

Edit `metadata.py:MetadataExtractor.extract_metadata()`:

```python
async def extract_metadata(self, content: str, title: str = "") -> Dict:
    """Extract metadata from content"""
    
    # Add custom extraction logic
    custom_field = extract_custom_field(content)
    
    metadata = {
        "type": "knowledge",
        "topics": [],
        "people": [],
        "action_items": [],
        "custom_field": custom_field
    }
    
    return metadata
```

### Changing Search Algorithm

Edit `search.py:SearchManager.hybrid_search()`:

```python
async def hybrid_search(
    self,
    query: str,
    limit: int = 10,
    filters: Optional[Dict] = None,
    weights: Optional[Dict] = None
) -> List[Dict]:
    """Hybrid search combining vector and keyword"""
    
    # Add custom search logic
    custom_results = self.custom_search_algorithm(query)
    
    # Combine with existing results
    combined = self._combine_scores(
        vector_results,
        keyword_results,
        custom_results,
        weights
    )
    
    return combined[:limit]
```

## Testing

### Running Tests

```bash
# Run all tests
cd Tests
for test_file in test_*.py; do
    python "$test_file"
done

# Run specific test
python test_obsidian.py

# Run with coverage (if coverage.py installed)
coverage run -m pytest Tests/
```

### Test Categories

1. **Unit Tests** - Test individual functions
2. **Integration Tests** - Test module interactions
3. **MCP Tests** - Test tool calls through MCP protocol
4. **Performance Tests** - Measure response times

### Writing Tests

```python
"""
Test module description
"""
import asyncio
import sys
sys.path.insert(0, '..')

from module import FunctionOrClass

async def test_functionality():
    """Test the main functionality"""
    instance = FunctionOrClass()
    
    # Arrange
    test_data = {...}
    
    # Act
    result = await instance.method(test_data)
    
    # Assert
    assert result is not None
    assert "expected_field" in result
    print("✓ Test passed")

async def test_error_handling():
    """Test error cases"""
    instance = FunctionOrClass()
    
    try:
        result = await instance.method(invalid_data)
        assert False, "Should have raised exception"
    except Exception as e:
        assert "expected error" in str(e)
        print("✓ Error handling test passed")

if __name__ == "__main__":
    asyncio.run(test_functionality())
    asyncio.run(test_error_handling())
```

## Debugging

### Enable Debug Mode

Set `DEBUG = True` in modules:

```python
# tools.py
DEBUG = True

# obsidian.py
DEBUG = True
```

### Logging

```python
# Info logging
print("[INFO] Operation completed", file=sys.stderr)

# Warning logging
print(f"[WARNING] Non-critical issue: {e}", file=sys.stderr)

# Error logging
print(f"[ERROR] Operation failed: {e}", file=sys.stderr)

# Debug logging
print(f"[DEBUG] Variable value: {variable}", file=sys.stderr)
```

### Common Issues

1. **Import Error**: Check virtual environment activation
2. **Configuration Error**: Verify `.env` file exists
3. **Database Error**: Check Supabase credentials
4. **File Not Found**: Check `OBSIDIAN_VAULT_PATH`

## Performance Optimization

### Profiling

```python
import cProfile
import pstats

def profile_function():
    pr = cProfile.Profile()
    pr.enable()
    
    # Run function to profile
    asyncio.run(your_async_function())
    
    pr.disable()
    
    stats = pstats.Stats(pr)
    stats.sort_stats('cumtime')
    stats.print_stats(10)

if __name__ == "__main__":
    profile_function()
```

### Optimization Tips

1. **Use Async** - Never block the event loop
2. **Batch Operations** - Group database writes
3. **Cache Results** - Cache expensive computations
4. **Limit Results** - Use LIMIT in queries
5. **Use Indexes** - Ensure database indexes exist

## Deployment

### Local Deployment

```bash
# Start server
cd second-brain-mcp
python -m server
```

### MCP Client Configuration

```json
{
  "mcpServers": {
    "second-brain": {
      "command": "python",
      "args": ["-m", "server"],
      "cwd": "path/to/second-brain-mcp"
    }
  }
}
```

### Production Considerations

1. **Environment Variables** - Use `.env`, never hardcode credentials
2. **Error Handling** - Catch and log all exceptions
3. **Graceful Shutdown** - Handle SIGINT/SIGTERM
4. **Resource Limits** - Monitor memory and CPU usage
5. **Logging** - Use stderr for MCP protocol logs

## Contributing

### Code Review Checklist

- [ ] Code follows existing patterns
- [ ] Docstrings are complete and accurate
- [ ] Error handling is robust
- [ ] Tests pass successfully
- [ ] Documentation is updated
- [ ] No hardcoded credentials
- [ ] Type hints are correct

### Pull Request Process

1. Fork repository
2. Create feature branch
3. Implement changes with tests
4. Update documentation
5. Submit pull request
6. Address review feedback
7. Merge to main

## Resources

- [Architecture Documentation](../architecture/ARCHITECTURE.md)
- [API Reference](../api/TOOLS_REFERENCE.md)
- [Database Schema](../database/SCHEMA.md)
- [Testing Guide](../guides/TESTING.md)
- [Troubleshooting Guide](../guides/TROUBLESHOOTING.md)

## Getting Help

- **Issues**: Report bugs via GitHub Issues
- **Discussions**: Ask questions via GitHub Discussions
- **Documentation**: Contribute to Docs/ folder
- **Examples**: Add usage examples to README.md
