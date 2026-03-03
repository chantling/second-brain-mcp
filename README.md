# Second Brain MCP Server

A Model Context Protocol (MCP) server that integrates Supabase (for vector storage and semantic search) with Obsidian (for local knowledge management), using the **Luca Decimal** organization system.

## Features

- **Intelligent Folder Detection**: Automatically scans your Obsidian vault and learns your folder structure
- **Confidence-Based Matching**: Uses semantic analysis to determine the best folder for each note
- **Luca Decimal Support**: Respects numbered folder conventions (1xx=Projects, 2xx=Areas, 3xx=Resources)
- **Subfolder Matching**: Can place notes in nested folders (e.g., "Resources/Electronics/Arduino")
- **ToSort Fallback**: Low-confidence matches go to ToSort for manual organization
- **Manual Override**: Specify exact folder via metadata when needed
- **Special Cases**: Recipes, Todos, and Contacts handled automatically

## Luca Decimal System

This server implements the [Luca Decimal](https://github.com/lucafrance/luca-decimal) organization system:

### Folder Structure

The server works with any folder structure you have, including:

```
vault/
├── Meta/           # Obsidian-specific content
├── To-Do/          # Todo items
├── Contacts/        # Contact information
├── Projects/        # Time-limited actions (1xx)
├── Areas/           # Regular activities (2xx)
├── Resources/       # Reference information (3xx)
├── Archive/         # Completed projects (4xx)
└── ToSort/         # Unsorted items
```

**No folders are hardcoded** - the server adapts to whatever structure you use.

### Numbered Folders

- **1xx (Projects)**: Time-limited actions (e.g., "100 Learn Python", "101 Taxes 2022")
- **2xx (Areas)**: Regular activities (e.g., "200 Health", "201 Finances")
- **3xx (Resources)**: Reference information (e.g., "300 Electronics", "301 Software")
- **4xx (Archive)**: Completed projects

The system distinguishes between numbered folders (300 Electronics vs 301 Software).

## How It Works

### Folder Selection Algorithm

1. **Special Cases (100% confidence)**
   - Recipes → `Resources/Recipes`
   - Todos → `To-Do`
   - Contacts → `Contacts`

2. **Manual Override (100% confidence)**
   - If `folder` specified in metadata, use it exactly

3. **Exact Match (100% confidence)**
   - Topic matches folder name exactly
   - Example: Topic "health" → "Health & Longevity"

4. **Semantic Matching (0.6-0.9 confidence)**
   - Analyzes content and topics
   - Matches keywords to folder names
   - Checks folder numbering context

5. **Threshold Application**
   - Confidence ≥ 0.7: Use matched folder
   - Confidence < 0.7: Place in `ToSort`

### Examples

**High Confidence Match (0.85+):**
```
Content: "How to solder components"
Topics: ["electronics", "soldering"]
→ Resources/Electronics
```

**Medium Confidence Match (0.75):**
```
Content: "My blood pressure reading"
Topics: ["health"]
→ Areas/Health & Longevity
```

**Low Confidence - ToSort (0.30):**
```
Content: "Interesting article about quantum computing"
Topics: ["quantum", "computing"]
→ ToSort
```

## Installation

1. **Clone or navigate to the project directory:**
   ```bash
   cd d:/Programs/AI/!MCPServers!/!Second_Brain!
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv venv
   ```

3. **Activate the virtual environment:**
   ```bash
   venv\Scripts\activate
   ```

4. **Install dependencies:**
   ```bash
   venv\Scripts\python -m pip install -r second-brain-mcp/requirements.txt
   ```

## Configuration

1. **Create a `.env` file in `second-brain-mcp/`:**
   ```env
   SUPABASE_URL=your_supabase_project_url
   SUPABASE_SECRET_KEY=your_supabase_service_role_key
   SUPABASE_PUBLISH_KEY=your_supabase_anon_key
   OPENROUTER_API_KEY=your_openrouter_api_key
   ZAI_API_KEY=your_zai_api_key
   OBSIDIAN_VAULT_PATH=./SecondBrain
   ```

   **Get API keys:**
   - Supabase: From your project settings
   - **Flexible Configuration**: Supports multiple providers (OpenRouter, OpenAI, Z.AI, etc.)
   - **📖 See [CONFIGURATION_GUIDE.md](CONFIGURATION_GUIDE.md) for detailed setup and provider switching options.**

2. **Update your Obsidian vault path** to point to your actual vault.

## Available Tools

### store_thought
Store a thought in both Supabase and Obsidian.

**Parameters:**
- `content` (required): The thought content
- `title` (optional): Title for the thought
- `metadata` (optional): Metadata dictionary
  - `type`: "knowledge", "recipe", "todo", "contact", "guide"
  - `topics`: List of topic tags
  - `people`: List of people mentioned
  - `folder`: Override automatic folder selection
- `source` (optional): Source of the thought (default: "manual")

**Returns:**
```json
{
  "success": true,
  "supabase_id": 123,
  "obsidian_path": "Resources/Electronics/2026-03-02-Circuit-Design.md",
  "message": "Thought stored successfully in both systems"
}
```

### semantic_search
Search thoughts by semantic similarity.

**Parameters:**
- `query` (required): Search query
- `limit` (optional): Maximum results (default: 10)
- `topics` (optional): Filter by topics

**Returns:** List of matching thoughts with similarity scores

### list_recent
List recent thoughts from both systems.

**Parameters:**
- `days` (optional): Number of days to look back (default: 7)
- `thought_type` (optional): Filter by thought type

**Returns:** List of recent thoughts

### get_thought
Get a specific thought by ID.

**Parameters:**
- `thought_id` (required): Thought ID

**Returns:** Complete thought details

### search_by_topic
Search thoughts by specific topic.

**Parameters:**
- `topic` (required): Topic to search for
- `limit` (optional): Maximum results (default: 20)

**Returns:** List of matching thoughts

### get_todos
Get todo items.

**Parameters:**
- `completed` (optional): Include completed todos (default: false)

**Returns:** List of todo items

### find_recipes
Find recipes based on criteria.

**Parameters:**
- `ingredients` (optional): List of required ingredients
- `category` (optional): Recipe category
- `max_time` (optional): Maximum total time in minutes

**Returns:** List of matching recipes

### list_guides
List guides by category and difficulty.

**Parameters:**
- `category` (optional): Guide category
- `difficulty` (optional): Difficulty level (easy, medium, hard)

**Returns:** List of guides

### get_contacts
Get contact information.

**Parameters:**
- `name` (optional): Name to search for
- `category` (optional): Contact category

**Returns:** List of contacts

## Usage Examples

### Store a Health Note
```python
store_thought(
    content="Blood pressure reading: 120/80, normal range",
    title="BP Check",
    metadata={
        "type": "knowledge",
        "topics": ["health", "blood_pressure"]
    }
)
# Automatically places in: Areas/Health & Longevity
```

### Store a Recipe
```python
store_thought(
    content="Ingredients: 2 eggs, flour, milk...",
    title="Pancakes",
    metadata={
        "type": "recipe",
        "topics": ["breakfast", "dessert"]
    }
)
# Automatically places in: Resources/Recipes
```

### Store with Manual Folder Override
```python
store_thought(
    content="Project notes for roof repair",
    title="Roof Repair",
    metadata={
        "type": "knowledge",
        "topics": ["construction"],
        "folder": "Projects/102-Roof-Repair"
    }
)
# Forces placement in: Projects/102-Roof-Repair
```

### Semantic Search
```python
semantic_search(
    query="how to solder components",
    limit=5
)
# Returns notes about electronics, soldering, circuits
```

## Testing

Test your configuration:
```bash
cd second-brain-mcp
..\venv\Scripts\python test_import.py
```

Test the Obsidian integration:
```bash
cd second-brain-mcp
..\venv\Scripts\python test_obsidian.py
```

## Architecture

- **Supabase**: Stores thoughts with vector embeddings for semantic search
- **Obsidian**: Stores local markdown files for manual editing
- **z.ai**: Extracts metadata using GLM-4.7 model
- **OpenRouter**: Generates embeddings for semantic similarity
- **MCP Protocol**: Provides tools for AI assistants to interact with your knowledge

## Troubleshooting

### Import Errors
If you get `ModuleNotFoundError`, make sure:
1. Virtual environment is activated
2. Dependencies are installed: `venv\Scripts\python -m pip install -r second-brain-mcp/requirements.txt`

### Folder Not Found
The server automatically creates:
- `To-Do`
- `Contacts`
- `Resources/Recipes`
- `ToSort`

If other folders are missing, create them manually in Obsidian.

### Low Confidence Matches
Notes with low confidence (< 0.7) go to `ToSort`. Review these periodically and move them manually.

## License

This project is part of the Second Brain MCP Server implementation.

## References

- [Luca Decimal](https://github.com/lucafrance/luca-decimal) - Digital organization system
- [Building a Second Brain](https://www.buildingasecondbrain.com/) - Note-taking methodology
- [MCP Protocol](https://modelcontextprotocol.io/) - Model Context Protocol