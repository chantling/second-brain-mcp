# Troubleshooting Guide

Comprehensive troubleshooting for common issues with the Second Brain MCP Server.

## Table of Contents

1. [Installation Issues](#installation-issues)
2. [Configuration Issues](#configuration-issues)
3. [Connection Issues](#connection-issues)
4. [Performance Issues](#performance-issues)
5. [Sync Issues](#sync-issues)
6. [Search Issues](#search-issues)
7. [Obsidian Issues](#obsidian-issues)
8. [Multi-Instance Issues](#multi-instance-issues)

## Installation Issues

### Python Version Mismatch

**Symptom:**
```
SyntaxError: invalid syntax
ModuleNotFoundError: No module named 'asyncio'
```

**Solution:**
```bash
# Check Python version
python --version  # Should be 3.10+

# If too old, install newer Python
# Windows: https://www.python.org/downloads/
# Mac: brew install python
# Linux: sudo apt install python3.10
```

### Missing Dependencies

**Symptom:**
```
ModuleNotFoundError: No module named 'supabase'
```

**Solution:**
```bash
# Activate virtual environment
cd second-brain-mcp
venv\Scripts\activate  # Windows
source venv/bin/activate  # Mac/Linux

# Install dependencies
pip install -r requirements.txt

# Verify installation
pip list | grep -E "supabase|openai|watchdog"
```

### Import Path Issues

**Symptom:**
```
ModuleNotFoundError: No module named 'config'
```

**Solution:**
```bash
# Run from correct directory
cd second-brain-mcp
python -m server

# Or add to PYTHONPATH
export PYTHONPATH="$PYTHONPATH:$(pwd)"
```

## Configuration Issues

### Missing Environment Variables

**Symptom:**
```
ValueError: Missing required environment variables: SUPABASE_URL
```

**Solution:**
```bash
# Check .env file exists
ls -la .env

# Create from example if missing
cp .env.example .env

# Edit with proper values
# Use VS Code, nano, or your preferred editor
notepad .env  # Windows
nano .env       # Mac/Linux
```

### Invalid API Keys

**Symptom:**
```
Error: Failed to create embedding: Invalid API key
```

**Solution:**
1. Verify key in `.env`
2. Check key format (no extra spaces/quotes)
3. Test API key with curl
4. Regenerate key if necessary

```env
# Correct format (no quotes)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SECRET_KEY=your_key_here

# Incorrect format
SUPABASE_URL="https://your-project.supabase.co"
SUPABASE_SECRET_KEY='your_key_here'
```

### Supabase Connection Failed

**Symptom:**
```
Error: Failed to connect to database
```

**Solution:**
```bash
# 1. Verify Supabase project URL
# Should be: https://project-name.supabase.co

# 2. Test connection
curl https://your-project.supabase.co

# 3. Check network/firewall
# Ensure outbound HTTPS is allowed

# 4. Verify secret key
# Use "service_role" key, not "anon" key
```

### Obsidian Path Not Found

**Symptom:**
```
[WARNING] Obsidian vault not found at path
```

**Solution:**
```bash
# Update .env with correct path
OBSIDIAN_VAULT_PATH=C:/Users/YourName/Obsidian/Vault

# Or use relative path
OBSIDIAN_VAULT_PATH=../../ObsidianVault

# Verify path exists
ls "C:/Users/YourName/Obsidian/Vault"
```

## Connection Issues

### Embedding API Timeout

**Symptom:**
```
Error: API timeout after 240 seconds
```

**Solution:**
```python
# Check embeddings.py:16 - verify timeout is 240
self.client = OpenAI(
    timeout=240,  # Should be 240
    max_retries=3
)

# Test API directly
curl https://your-embedding-api.com/embeddings -H "Authorization: Bearer YOUR_KEY"
```

### Metadata API Slow

**Symptom:**
```
store_thought takes > 60 seconds
```

**Solution:**
```python
# Check metadata.py:25 - verify timeout
client = AsyncClient(
    timeout=240,  # Should be 240
    base_url=Config.METADATA_BASE_URL
)
```

### First Search Timeout (Fixed in Recent Version)

**Symptom:**
```
First semantic search times out after 6+ minutes
Subsequent searches work immediately
```

**Solution:**

**This issue has been FIXED in recent updates.**

If you experience this:
1. Update to latest version: `git pull`
2. Restart server to trigger connection warmup
3. Check server logs for warmup message:
   ```
   [INIT] Warming up connections...
   [EMBEDDINGS] Connection pool warmed up successfully
   [INIT] Connection warmup complete, server ready to accept requests
   ```

## Performance Issues

### Slow Search Performance

**Symptom:**
```
semantic_search takes > 2 seconds consistently
```

**Diagnosis:**
```python
# Check if vector index exists
# In Supabase SQL editor:
SELECT indexname FROM pg_indexes 
WHERE indexname = 'thoughts_embedding_idx';

# Expected result: thoughts_embedding_idx
# If missing: Create index
CREATE INDEX thoughts_embedding_idx ON thoughts
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
```

### High Memory Usage

**Symptom:**
```
Server uses > 1GB memory
```

**Solution:**
```python
# 1. Reduce sync batch size
# In watcher.py or obsidian.py
BATCH_SIZE = 10  # Instead of 100

# 2. Monitor connection pool
# In embeddings.py, connection pooling is automatic
# Consider closing idle connections periodically

# 3. Profile memory usage
# Add to server.py:
import psutil
print(f"[MEMORY] {psutil.Process().memory_info().rss / 1024 / 1024} MB", file=sys.stderr)
```

### CPU High During Sync

**Symptom:**
```
CPU usage spikes to 100% during sync
```

**Solution:**
```python
# 1. Increase debounce time
# In config.py
SYNC_DEBOUNCE_SECONDS = 5.0  # Instead of 2.0

# 2. Reduce sync frequency
# In config.py
SYNC_FULL_SYNC_INTERVAL = 7200  # 2 hours instead of 1 hour

# 3. Disable initial sync if not needed
# In config.py
SYNC_INITIAL_SYNC = false
```

## Sync Issues

### Files Not Syncing to Supabase

**Symptom:**
```
Files changed in Obsidian but not in database
```

**Diagnosis:**
```bash
# Check if file watcher is running
# Server logs should show:
[SYNC] File watcher enabled

# Check if lock is held
# Should see:
[LOCK] Acquired primary lock
```

**Solution:**
```bash
# 1. Verify file watcher dependencies
pip install watchdog

# 2. Check exclude patterns
# In config.py, verify:
SYNC_EXCLUDE_PATTERNS = ".obsidian,.trash,.ClineData"

# 3. Manually trigger sync
# Stop server, delete lock file:
rm .server_lock

# Restart server
```

### Duplicate Thoughts in Database

**Symptom:**
```
Same note appears multiple times in search results
```

**Solution:**
```python
# Check file_hash is being used
# In database.py:44
# Should have:
file_hash VARCHAR(64)

# Verify hash is computed correctly
# In watcher.py:
import hashlib
file_hash = hashlib.sha256(content.encode()).hexdigest()

# Clean duplicates manually
# In Supabase SQL editor:
DELETE FROM thoughts t1
WHERE id < (
    SELECT MIN(id)
    FROM thoughts t2
    WHERE t1.file_hash = t2.file_hash
);
```

### Folder Sync Incomplete

**Symptom:**
```
Some folders missing from database
```

**Solution:**
```python
# Manually trigger folder sync
# Add to server.py or run separately:
from obsidian import ObsidianManager
obsidian_manager = ObsidianManager(vault_path, db_manager)
await obsidian_manager.sync_folders_to_database()
```

## Search Issues

### No Search Results

**Symptom:**
```
semantic_search returns empty array
```

**Diagnosis:**
```python
# 1. Check if data exists
# In Supabase SQL editor:
SELECT COUNT(*) FROM thoughts WHERE embedding IS NOT NULL;

# 2. Check embeddings are correct dimension
SELECT id, array_length(embedding, 1) FROM thoughts LIMIT 5;

# 3. Test RPC function
SELECT * FROM vector_search('[0.1,0.2,...]'::vector(1536), 10);
```

**Solution:**
```python
# If no data: Run initial sync
from obsidian import ObsidianManager
obsidian_manager.sync_existing_notes_to_supabase()

# If dimension mismatch: Regenerate embeddings
# In Supabase SQL editor:
UPDATE thoughts
SET embedding = (SELECT array_to_json(embedding)::vector(1536))
WHERE embedding IS NULL OR array_length(embedding, 1) != 1536;
```

### Poor Search Relevance

**Symptom:**
```
Search results don't match query intent
```

**Diagnosis:**
```python
# Test with various queries
queries = [
    "electronics",
    "soldering",
    "circuit design"
]

for q in queries:
    results = await semantic_search(q)
    print(f"Query: {q}")
    print(f"Results: {[r['content'][:50] for r in results]}")
```

**Solution:**
```python
# 1. Adjust search weights
# In config.py:
SEARCH_VECTOR_WEIGHT = 0.8  # Increase vector weight
SEARCH_KEYWORD_WEIGHT = 0.2

# 2. Use hybrid search
results = await hybrid_search(
    query="your query",
    weights={"vector": 0.8, "keywords": 0.2}
)

# 3. Add more specific topics to metadata
metadata = {
    "topics": ["electronics", "circuits", "soldering"]
}
```

## Obsidian Issues

### Files Not Created

**Symptom:**
```
store_thought returns success but file not in vault
```

**Diagnosis:**
```python
# Check obsidian_path in result
result = await store_thought(...)
print(result["obsidian_path"])

# Manually check if file exists
from pathlib import Path
path = Path(vault_path) / result["obsidian_path"]
print(f"File exists: {path.exists()}")
```

**Solution:**
```python
# 1. Verify vault path is correct
# In .env:
OBSIDIAN_VAULT_PATH=C:/absolute/path/to/vault

# 2. Check permissions
# Ensure user can write to vault
# Windows: Right-click folder → Properties → Security
# Mac/Linux: chmod u+w vault/

# 3. Check for special characters in path
# Avoid: spaces, unicode characters in path
# Use underscores or hyphens: My_Vault not My Vault
```

### Folder Structure Not Detected

**Symptom:**
```
Notes go to ToSort instead of proper folders
```

**Diagnosis:**
```python
# Check folder sync
from obsidian import ObsidianManager
obsidian_manager = ObsidianManager(vault_path, db_manager)
stats = await obsidian_manager.sync_folders_to_database()
print(f"Synced {stats['total']} folders")

# Check embeddings
# In Supabase:
SELECT path, embedding IS NOT NULL FROM folders;
```

**Solution:**
```python
# 1. Manually sync folders
await obsidian_manager.sync_folders_to_database()

# 2. Clear folder cache
rm !Folder_Embeddings.md

# 3. Restart server to reload folders
```

## Multi-Instance Issues

### Multiple Servers Running

**Symptom:**
```
[LOCK] Another instance running - file watcher disabled
```

**Solution:**
```bash
# 1. Find running instances
# Windows:
tasklist | findstr python
# Mac/Linux:
ps aux | grep python

# 2. Stop old instances
# Kill the process (save work first!)

# 3. Clean up lock file
rm .server_lock

# 4. Start fresh instance
python -m server
```

### Lock File Stuck

**Symptom:**
```
Cannot start server, lock file exists but no process running
```

**Solution:**
```bash
# Check lock file info
cat .server_lock

# Remove stale lock
rm .server_lock

# Or use server's built-in cleanup
# In server.py, lock_manager.cleanup_stale_lock() handles this automatically
```

### Secondary Instance Not Taking Over

**Symptom:**
```
Primary died but secondary didn't take over
```

**Solution:**
```python
# Check retry settings in config.py
LOCK_RETRY_ENABLED = true  # Should be true
LOCK_RETRY_INTERVAL_SECONDS = 30  # Check interval
LOCK_RETRY_JITTER_SECONDS = 10  # Random delay

# Verify heartbeat interval
LOCK_HEARTBEAT_INTERVAL_SECONDS = 20  # Primary heartbeat frequency

# Manually remove lock to force takeover
rm .server_lock
```

## Debug Mode

### Enable Debug Logging

```python
# Add to modules
DEBUG = True

# In obsidian.py:
DEBUG = True

# In tools.py:
DEBUG = True

# Or set via environment variable
export DEBUG=true
```

### Server Logs

```bash
# Check stderr output
python -m server 2>&1 | tee server.log

# Or redirect to file
python -m server > server.log 2>&1

# Monitor in real-time
tail -f server.log
```

### Database Query Logging

```python
# Add to database.py:
import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('supabase')

# Queries will be logged automatically
```

## Getting Help

### Report Issues

When reporting issues, include:

1. **System Information**
   - OS version
   - Python version
   - Git commit hash

2. **Configuration**
   - Relevant .env settings (hide secrets)
   - File paths

3. **Error Messages**
   - Full error traceback
   - Server logs around error

4. **Steps to Reproduce**
   - What you were doing
   - Expected vs actual behavior

5. **Attempted Solutions**
   - What you've tried
   - Results of those attempts

### Community Resources

- **GitHub Issues**: https://github.com/your-repo/issues
- **GitHub Discussions**: https://github.com/your-repo/discussions
- **MCP Documentation**: https://modelcontextprotocol.io/

## Resources

- [Architecture Documentation](../architecture/ARCHITECTURE.md)
- [Developer Guide](../guides/DEVELOPMENT.md)
- [Testing Guide](../guides/TESTING.md)
- [API Reference](../api/TOOLS_REFERENCE.md)
