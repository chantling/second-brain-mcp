# Flexible Configuration Guide

## Overview

The Second Brain MCP server now supports **flexible provider configuration** for both embeddings and metadata extraction. You can easily switch between different AI providers without changing code - just update environment variables.

## Configuration Variables

### Embedding Configuration

These variables control the vector embedding generation:

```bash
EMBEDDING_API_KEY=your-api-key-here
EMBEDDING_BASE_URL=https://openrouter.ai/api/v1
EMBEDDING_MODEL=qwen/qwen3-embedding-8b
EMBEDDING_DIMENSIONS=1536
```

#### Provider Examples

**OpenRouter** (default):
```bash
EMBEDDING_API_KEY=sk-or-v1-your-key
EMBEDDING_BASE_URL=https://openrouter.ai/api/v1
EMBEDDING_MODEL=qwen/qwen3-embedding-8b
EMBEDDING_DIMENSIONS=1536
```

**OpenAI**:
```bash
EMBEDDING_API_KEY=sk-your-key
EMBEDDING_BASE_URL=https://api.openai.com/v1
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536
```

**Z.AI**:
```bash
EMBEDDING_API_KEY=your-zai-key
EMBEDDING_BASE_URL=https://api.z.ai/api/coding/paas/v4
EMBEDDING_MODEL=embedding-model-name
EMBEDDING_DIMENSIONS=1536
```

### Metadata Configuration

These variables control the AI-powered metadata extraction:

```bash
METADATA_API_KEY=your-api-key-here
METADATA_BASE_URL=https://api.z.ai/api/coding/paas/v4
METADATA_MODEL=glm-4.7
```

#### Provider Examples

**Z.AI GLM-4.7** (default - recommended):
```bash
METADATA_API_KEY=your-zai-key
METADATA_BASE_URL=https://api.z.ai/api/coding/paas/v4
METADATA_MODEL=glm-4.7
```

**OpenRouter Claude**:
```bash
METADATA_API_KEY=sk-or-v1-your-key
METADATA_BASE_URL=https://openrouter.ai/api/v1
METADATA_MODEL=anthropic/claude-3.5-sonnet
```

**OpenAI GPT-4**:
```bash
METADATA_API_KEY=sk-your-key
METADATA_BASE_URL=https://api.openai.com/v1
METADATA_MODEL=gpt-4-turbo
```

## How It Works

The system uses the **OpenAI Python SDK** for both embeddings and metadata, which is compatible with any OpenAI-style API. This means:

1. **Any OpenAI-compatible API works** - just change the BASE_URL and MODEL
2. **Same interface, different providers** - code doesn't need to change
3. **Easy switching** - update .env and restart the server

## Changing Providers

### Step 1: Get API Key

Get an API key from your chosen provider:
- **OpenRouter**: https://openrouter.ai/
- **OpenAI**: https://platform.openai.com/api-keys
- **Z.AI**: https://z.ai/model-api

### Step 2: Update .env File

Edit `second-brain-mcp/.env`:

```bash
# Example: Switch embeddings to OpenAI
EMBEDDING_API_KEY=sk-your-openai-key
EMBEDDING_BASE_URL=https://api.openai.com/v1
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536
```

### Step 3: Restart Server

Restart the MCP server to load the new configuration.

## Important Notes

### GLM-4.7 Thinking Mode

If using Z.AI's GLM-4.7 model for metadata, the system automatically disables "thinking mode" to prevent token waste:

```python
extra_body={"thinking": {"type": "disabled"}}
```

This ensures fast, direct responses suitable for metadata extraction.

### Embedding Dimensions

- **Supabase pgvector**: Works best with 1536 dimensions (OpenAI-compatible)
- **Other providers**: Check documentation for supported dimensions
- **OpenRouter qwen3-embedding-8b**: Returns 1536 dimensions by default

### Model Selection

**For Metadata Extraction**:
- Best: GLM-4.7 (cost-effective, strong reasoning)
- Alternative: Claude 3.5 Sonnet (excellent quality, higher cost)
- Alternative: GPT-4 Turbo (good quality, moderate cost)

**For Embeddings**:
- Best: qwen3-embedding-8b (1536 dims, cost-effective)
- Alternative: text-embedding-3-small (OpenAI, 1536 dims)
- Alternative: text-embedding-3-large (OpenAI, 3072 dims)

## Legacy Support

For backward compatibility, the system still supports old variable names:

```bash
# These still work if new vars not set
OPENROUTER_API_KEY=sk-or-v1-key
ZAI_API_KEY=your-zai-key
```

Priority order:
1. New variables (`EMBEDDING_API_KEY`, `METADATA_API_KEY`)
2. Legacy variables (`OPENROUTER_API_KEY`, `ZAI_API_KEY`)

## Validation

The system validates configuration on startup:

```python
Config.validate()
```

Required variables:
- `SUPABASE_URL`
- `SUPABASE_SECRET_KEY`
- `SUPABASE_PUBLISH_KEY`
- `EMBEDDING_API_KEY` (or `OPENROUTER_API_KEY`)
- `METADATA_API_KEY` (or `ZAI_API_KEY`)

## Troubleshooting

### "Missing required environment variable"

**Cause**: Required API key not set in .env

**Solution**: Add the missing variable to `second-brain-mcp/.env`

### "Model not found"

**Cause**: Invalid model name for the provider

**Solution**: Check provider documentation for valid model names

### "Connection timeout"

**Cause**: Invalid BASE_URL or network issues

**Solution**: Verify BASE_URL format (include `/v1` if needed)

### "Invalid dimensions"

**Cause**: Provider doesn't support requested dimensions

**Solution**: Adjust `EMBEDDING_DIMENSIONS` to match provider's capabilities

## Testing Configuration

Test your configuration:

```bash
# Test metadata extraction
python second-brain-mcp/test_metadata_integration.py

# Test embeddings
python second-brain-mcp/test_embedding_config.py
```

Both scripts validate:
- Configuration loading
- API connectivity
- Model response
- Output quality

## Cost Optimization

### Recommended Setup (Current Default)

**Embeddings**: OpenRouter qwen3-embedding-8b
- Cost: Very low per 1M tokens
- Dimensions: 1536 (Supabase compatible)
- Quality: Excellent for semantic search

**Metadata**: Z.AI GLM-4.7
- Cost: Very low per 1M tokens
- Quality: Superior reasoning
- Speed: Fast with thinking disabled

### Alternative: All OpenAI

```bash
EMBEDDING_API_KEY=sk-openai-key
EMBEDDING_BASE_URL=https://api.openai.com/v1
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536

METADATA_API_KEY=sk-openai-key
METADATA_BASE_URL=https://api.openai.com/v1
METADATA_MODEL=gpt-4-turbo
```

**Pros**: Single provider, unified billing
**Cons**: Higher cost than optimized setup

## Security Notes

1. **Never commit .env files** - they contain sensitive API keys
2. **Use environment-specific keys** - different keys for dev/prod
3. **Rotate keys regularly** - follow provider security best practices
4. **Monitor usage** - check dashboards for unusual activity

## API Provider Comparison

| Provider | Embedding | Metadata | Cost | Quality |
|-----------|-----------|-----------|-------|---------|
| Z.AI | ✓ | ✓ | Low | High |
| OpenRouter | ✓ | ✓ | Low | High |
| OpenAI | ✓ | ✓ | High | Very High |

## Summary

The flexible configuration system gives you:

✅ **Easy provider switching** - change .env, not code
✅ **Cost optimization** - use best provider for each task
✅ **OpenAI compatibility** - any OpenAI-style API works
✅ **Legacy support** - existing setups continue to work
✅ **Production ready** - fully tested and validated

For questions or issues, check:
1. Configuration validation output
2. Test scripts for detailed error messages
3. Provider documentation for API details