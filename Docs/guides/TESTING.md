# Testing Guide

Comprehensive guide for testing the Second Brain MCP Server.

## Table of Contents

1. [Test Structure](#test-structure)
2. [Running Tests](#running-tests)
3. [Test Categories](#test-categories)
4. [Writing Tests](#writing-tests)
5. [Continuous Integration](#continuous-integration)
6. [Test Coverage](#test-coverage)

## Test Structure

### Directory Organization

```
Tests/
├── test_import.py              # Module imports
├── test_obsidian.py            # Obsidian integration
├── test_mcp_tools.py          # MCP tool functionality
├── test_full_workflow.py       # End-to-end workflows
├── test_metadata_integration.py  # AI metadata extraction
├── test_folder_sync.py         # Folder synchronization
├── test_supabase_rpc.py      # Database RPC functions
├── debug_database.py           # Database debugging
└── debug_zai.py              # Metadata API debugging
```

### Test File Template

```python
"""
Test module description
"""
import asyncio
import sys

# Add parent directory to path for imports
sys.path.insert(0, '..')

from module import FunctionOrClass

async def test_basic_functionality():
    """Test basic functionality"""
    print(f"[TEST] Testing basic functionality...", file=sys.stderr)
    
    try:
        # Arrange
        instance = FunctionOrClass()
        input_data = {...}
        
        # Act
        result = await instance.method(input_data)
        
        # Assert
        assert result is not None
        assert "expected_field" in result
        
        print(f"[PASS] Basic functionality test", file=sys.stderr)
        return True
        
    except Exception as e:
        print(f"[FAIL] Basic functionality test: {e}", file=sys.stderr)
        return False

async def test_error_handling():
    """Test error cases"""
    print(f"[TEST] Testing error handling...", file=sys.stderr)
    
    try:
        instance = FunctionOrClass()
        
        # Test with invalid input
        result = await instance.method(invalid_data)
        
        assert "error" in result
        print(f"[PASS] Error handling test", file=sys.stderr)
        return True
        
    except Exception as e:
        print(f"[FAIL] Error handling test: {e}", file=sys.stderr)
        return False

async def main():
    """Run all tests"""
    print("=" * 60, file=sys.stderr)
    print("TEST SUITE: Module Name", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    
    results = []
    
    # Run tests
    results.append(await test_basic_functionality())
    results.append(await test_error_handling())
    
    # Summary
    passed = sum(results)
    total = len(results)
    
    print("\n" + "=" * 60, file=sys.stderr)
    print(f"RESULTS: {passed}/{total} tests passed", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    
    # Exit with appropriate code
    sys.exit(0 if passed == total else 1)

if __name__ == "__main__":
    asyncio.run(main())
```

## Running Tests

### Run All Tests

```bash
cd second-brain-mcp/Tests

# Run each test file
for test in test_*.py; do
    echo "Running $test..."
    python "$test"
done

# Or run specific test
python test_import.py
```

### Run with Coverage (Optional)

```bash
# Install coverage
pip install coverage

# Run tests with coverage
cd Tests
coverage run -m pytest test_*.py -v

# Generate report
coverage report -m

# Generate HTML report
coverage html -d coverage_report
```

## Test Categories

### 1. Import Tests (`test_import.py`)

**Purpose:** Verify all modules import correctly

```python
from config import Config
from database import DatabaseManager
from embeddings import EmbeddingGenerator
from obsidian import ObsidianManager
from tools import ToolHandlers

assert Config.validate() is not None
assert DatabaseManager() is not None
```

**What to test:**
- All core modules import without errors
- Configuration validation
- Database client initialization
- Embedding generator initialization

### 2. Obsidian Tests (`test_obsidian.py`)

**Purpose:** Test Obsidian file operations

```python
obsidian_manager = ObsidianManager(vault_path, db_manager)

# Test note creation
result = obsidian_manager.create_note(content, metadata)
assert "path" in result
assert Path(result["path"]).exists()

# Test folder detection
folders = obsidian_manager._scan_vault_structure()
assert len(folders) > 0
```

**What to test:**
- Note creation with frontmatter
- Folder structure scanning
- File path sanitization
- Special folder handling

### 3. MCP Tool Tests (`test_mcp_tools.py`)

**Purpose:** Test all MCP tools end-to-end

```python
handlers = ToolHandlers()

# Test store_thought
result = await handlers.store_thought(
    content="Test content",
    title="Test Title",
    metadata={"type": "knowledge"}
)
assert result["success"] is True
assert "supabase_id" in result
assert "obsidian_path" in result

# Test semantic_search
result = await handlers.semantic_search("test query", limit=5)
assert len(result) <= 5
assert all("content" in r for r in result)
```

**What to test:**
- All 13 tools execute correctly
- Parameters are validated
- Errors are returned properly
- Response format is correct

### 4. Full Workflow Tests (`test_full_workflow.py`)

**Purpose:** Test complete user workflows

```python
# Workflow: Store → Search → Retrieve

# 1. Store thought
store_result = await handlers.store_thought(
    content="Unique test content",
    title="Test Note"
)
thought_id = store_result["supabase_id"]

# 2. Search for it
search_result = await handlers.semantic_search("unique test content")
assert len(search_result) > 0

# 3. Retrieve by ID
get_result = await handlers.get_thought(thought_id)
assert get_result["id"] == thought_id
assert get_result["content"] == "Unique test content"
```

**What to test:**
- Store → Search workflow
- Search → Retrieve workflow
- Multi-step operations
- Data consistency across systems

### 5. Metadata Integration Tests (`test_metadata_integration.py`)

**Purpose:** Test AI metadata extraction

```python
extractor = MetadataExtractor()

# Test metadata extraction
metadata = await extractor.extract_metadata(
    content="Blood pressure: 120/80",
    title="BP Check"
)

assert "type" in metadata
assert "topics" in metadata
assert metadata["type"] in ["knowledge", "recipe", "todo", "contact", "guide"]
```

**What to test:**
- Metadata extraction from content
- Topic identification
- People detection
- Action item extraction

### 6. Folder Sync Tests (`test_folder_sync.py`)

**Purpose:** Test folder synchronization

```python
# Test folder sync to database
obsidian_manager = ObsidianManager(vault_path, db_manager)
stats = await obsidian_manager.sync_folders_to_database()

assert stats["total"] > 0
assert stats["created"] + stats["updated"] > 0
```

**What to test:**
- Folder structure detection
- Embedding generation for folders
- Database synchronization
- Cache management

### 7. Supabase RPC Tests (`test_supabase_rpc.py`)

**Purpose:** Test database RPC functions

```python
# Test vector_search RPC
from embeddings import EmbeddingGenerator
gen = EmbeddingGenerator()
query_embedding = await gen.create_embedding("test")

response = db_manager.client.rpc(
    "vector_search",
    {"query_embedding": query_embedding, "match_count": 5}
).execute()

assert response.data is not None
assert len(response.data) <= 5
```

**What to test:**
- RPC function execution
- Vector search functionality
- Parameter handling
- Error conditions

## Writing Tests

### Test Naming Convention

- `test_<module>_<feature>.py` - Specific feature test
- `test_<module>_integration.py` - Integration test
- `test_full_<workflow>.py` - Workflow test

### Test Structure

```python
import asyncio
import sys

sys.path.insert(0, '..')

def test_setup():
    """Setup before tests"""
    # Create test data, initialize resources
    pass

def test_teardown():
    """Cleanup after tests"""
    # Remove test data, close resources
    pass

async def test_scenario_1():
    """Test scenario 1"""
    print(f"[TEST] Scenario 1...", file=sys.stderr)
    try:
        # Test logic
        assert True  # Replace with actual assertion
        print(f"[PASS] Scenario 1", file=sys.stderr)
        return True
    except AssertionError as e:
        print(f"[FAIL] Scenario 1: {e}", file=sys.stderr)
        return False

async def main():
    """Run all tests"""
    test_setup()
    try:
        results = []
        results.append(await test_scenario_1())
        # ... more tests ...
        
        passed = sum(results)
        total = len(results)
        print(f"\n[RESULTS] {passed}/{total} tests passed", file=sys.stderr)
    finally:
        test_teardown()

if __name__ == "__main__":
    asyncio.run(main())
```

### Assertions

```python
# Basic assertions
assert condition, "Error message"

# String assertions
assert result["field"] == expected, "Field should equal expected"

# Numeric assertions
assert len(results) > 0, "Should have results"
assert value >= minimum, "Value should be >= minimum"

# Collection assertions
assert "key" in dict_obj, "Dictionary should contain key"
assert item in list_obj, "List should contain item"

# None assertions
assert result is not None, "Result should not be None"

# Exception assertions
try:
    risky_operation()
    assert False, "Should have raised exception"
except ExpectedException:
    pass  # Expected
```

## Continuous Integration

### GitHub Actions Example

`.github/workflows/tests.yml`:

```yaml
name: Tests

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.10'
    
    - name: Install dependencies
      run: |
        cd second-brain-mcp
        pip install -r requirements.txt
    
    - name: Run tests
      env:
        SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
        SUPABASE_SECRET_KEY: ${{ secrets.SUPABASE_SECRET_KEY }}
        EMBEDDING_API_KEY: ${{ secrets.EMBEDDING_API_KEY }}
        METADATA_API_KEY: ${{ secrets.METADATA_API_KEY }}
      run: |
        cd Tests
        for test in test_*.py; do
          python "$test"
        done
```

## Test Coverage

### Coverage Goals

- **Core modules**: 90%+ coverage
- **Tool handlers**: 95%+ coverage
- **Error paths**: 100% coverage

### Measuring Coverage

```bash
# Install coverage
pip install coverage pytest

# Run tests with coverage
cd second-brain-mcp
coverage run -m pytest Tests/ -v

# View report
coverage report --include='*.py' --omit='Tests/*'

# Generate HTML
coverage html --include='*.py' --omit='Tests/*'
open htmlcov/index.html
```

### Coverage Report

```
Name                       Stmts   Miss  Cover   Missing
--------------------------------------------------------
config.py                      20      0   100%
database.py                   150     15    90%   23-27, 45-50
embeddings.py                  45      5    89%   12-13, 25
obsidian.py                   200     30    85%   15-20, 45-50, 100-110
tools.py                      180     10    94%   50-55
--------------------------------------------------------
TOTAL                         595     60    90%
```

## Best Practices

1. **Isolation** - Tests should not depend on each other
2. **Cleanup** - Always clean up resources after tests
3. **Fast** - Tests should complete quickly (<5s each)
4. **Clear** - Test names should describe what is tested
5. **Deterministic** - Tests should produce consistent results
6. **Comprehensive** - Test both success and failure cases
7. **Maintainable** - Tests should be easy to update

## Debugging Failed Tests

### Enable Verbose Output

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Or set DEBUG flag
DEBUG = True
```

### Interactive Testing

```python
# Run single test interactively
cd Tests
python test_obsidian.py

# Or use Python REPL
python
>>> import asyncio
>>> from obsidian import ObsidianManager
>>> # Test interactively
```

### Common Issues

1. **Import Error** - Check PYTHONPATH
2. **Configuration Error** - Check .env file
3. **Database Error** - Check Supabase connection
4. **Timeout** - Increase timeout in tests
5. **Race Condition** - Add delay between operations

## Resources

- [Architecture Documentation](../architecture/ARCHITECTURE.md)
- [Developer Guide](../guides/DEVELOPMENT.md)
- [Troubleshooting Guide](../guides/TROUBLESHOOTING.md)
