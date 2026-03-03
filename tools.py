import os
import sys
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Any
from config import Config
from database import DatabaseManager
from obsidian import ObsidianManager
from embeddings import EmbeddingGenerator
from metadata import MetadataExtractor

# Debug flag - set to True to enable debug output
DEBUG = False

# Global instances
db_manager = DatabaseManager()
obsidian_manager = ObsidianManager(Config.OBSIDIAN_VAULT_PATH, db_manager=db_manager)
embedding_generator = EmbeddingGenerator()
metadata_extractor = MetadataExtractor()

# Global sync flag
_folders_synced = False

class ToolHandlers:
    """Handler class for all MCP tool operations"""
    
    async def handle_tool_call(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Route tool calls to appropriate handler"""
        # Sync folders on first call if not already synced
        global _folders_synced
        if not _folders_synced:
            await self._sync_folders()
            _folders_synced = True
        
        handlers = {
            "store_thought": self.store_thought,
            "semantic_search": self.semantic_search,
            "list_recent": self.list_recent,
            "get_thought": self.get_thought,
            "search_by_topic": self.search_by_topic,
            "get_todos": self.get_todos,
            "find_recipes": self.find_recipes,
            "list_guides": self.list_guides,
            "get_contacts": self.get_contacts
        }
        
        handler = handlers.get(name)
        if not handler:
            return {"error": f"Unknown tool: {name}"}
        
        return await handler(**arguments)
    
    async def _sync_folders(self):
        """Sync folders to database on first tool call"""
        try:
            print("[INFO] Syncing Obsidian folders to database...", file=sys.stderr)
            stats = await obsidian_manager.sync_folders_to_database()
            print(f"[INFO] Folder sync complete: {stats}", file=sys.stderr)
        except Exception as e:
            print(f"[WARNING] Failed to sync folders: {e}", file=sys.stderr)
    
    async def store_thought(
        self,
        content: str,
        title: str = "",
        metadata: Optional[Dict] = None,
        source: str = "manual"
    ) -> Dict:
        """Store a thought in both Supabase and Obsidian"""
        debug_info = {} if DEBUG else None
        
        try:
            # Debug: Capture initial parameters
            if DEBUG:
                debug_info["input_title"] = title
                debug_info["content_length"] = len(content)
            
            # Extract metadata if not provided
            if not metadata:
                metadata = await metadata_extractor.extract_metadata(content, title)
            
            # CRITICAL FIX: Ensure title is in metadata
            # The AI might not return title, so we add it from the parameter
            if "title" not in metadata or not metadata.get("title"):
                metadata["title"] = title or "Untitled"
            
            # Debug: Capture metadata after extraction
            if DEBUG:
                debug_info["metadata_keys"] = list(metadata.keys())
                debug_info["metadata_title"] = metadata.get("title", "NOT_SET")
            
            # Generate vector embedding
            embedding = await embedding_generator.create_embedding(content)
            
            # Store in Supabase
            supabase_id = await db_manager.store_thought(content, embedding, metadata)
            
            # Determine folder using semantic search if folders are synced
            if _folders_synced:
                folder, confidence = await obsidian_manager._find_semantic_folder_match(content, metadata)
                # Override folder in metadata if semantic search found a good match
                if confidence >= 0.6:
                    metadata["folder"] = folder
                    print(f"[INFO] Semantic folder search selected: {folder} (confidence: {confidence:.2f})", file=sys.stderr)
            
            # Debug: Capture metadata before creating note
            if DEBUG:
                debug_info["metadata_before_create"] = metadata.get("title", "NOT_SET")
                debug_info["all_metadata_before_create"] = {k: v for k, v in metadata.items()}
            
            # Store in Obsidian
            obsidian_result = obsidian_manager.create_note(content, {
                **metadata,
                "supabase_id": supabase_id,
                "source": source
            })
            
            # Extract path from the returned dict
            obsidian_path = obsidian_result["path"]
            
            # Include obsidian debug info
            if DEBUG:
                debug_info["obsidian_create"] = obsidian_result.get("_debug", {})
            
            result = {
                "success": True,
                "supabase_id": supabase_id,
                "obsidian_path": obsidian_path,
                "message": "Thought stored successfully in both systems"
            }
            
            # Include debug info in result
            if DEBUG:
                result["_debug"] = debug_info
            
            return result
            
        except Exception as e:
            if debug_info is None:
                debug_info = {}
            debug_info["error"] = str(e)
            debug_info["error_type"] = type(e).__name__
            result = {
                "success": False,
                "error": str(e),
                "message": "Failed to store thought"
            }
            if DEBUG:
                result["_debug"] = debug_info
            return result
    
    async def semantic_search(
        self,
        query: str,
        limit: int = 10,
        topics: Optional[List[str]] = None
    ) -> List[Dict]:
        """Search thoughts by semantic similarity"""
        try:
            # Generate query embedding
            query_embedding = await embedding_generator.create_embedding(query)
            
            # Perform semantic search
            results = await db_manager.semantic_search(query_embedding, limit)
            
            # Filter by topics if provided
            if topics:
                results = [r for r in results if any(topic in (r.get('topics') or []) for topic in topics)]
            
            # Enrich with Obsidian paths
            for result in results:
                if result.get('obsidian_path'):
                    result['obsidian_url'] = f"obsidian://open?file={result['obsidian_path']}"
            
            return results
            
        except Exception as e:
            return [{"error": str(e), "message": "Search failed"}]
    
    async def list_recent(
        self,
        days: int = 7,
        thought_type: Optional[str] = None
    ) -> List[Dict]:
        """List recent thoughts from both systems"""
        try:
            results = await db_manager.list_recent(days, thought_type)
            
            # Enrich with Obsidian URLs
            for result in results:
                if result.get('obsidian_path'):
                    result['obsidian_url'] = f"obsidian://open?file={result['obsidian_path']}"
            
            return results
            
        except Exception as e:
            return [{"error": str(e), "message": "Failed to get recent thoughts"}]
    
    async def get_thought(
        self,
        thought_id: int
    ) -> Optional[Dict]:
        """Get a specific thought by ID"""
        try:
            result = await db_manager.get_thought(thought_id)
            if result and result.get('obsidian_path'):
                result['obsidian_url'] = f"obsidian://open?file={result['obsidian_path']}"
            return result
        except Exception as e:
            return {"error": str(e), "message": "Failed to get thought"}
    
    async def search_by_topic(
        self,
        topic: str,
        limit: int = 20
    ) -> List[Dict]:
        """Search thoughts by specific topic"""
        try:
            results = await db_manager.search_by_topic(topic, limit)
            
            # Enrich with Obsidian URLs
            for result in results:
                if result.get('obsidian_path'):
                    result['obsidian_url'] = f"obsidian://open?file={result['obsidian_path']}"
            
            return results
            
        except Exception as e:
            return [{"error": str(e), "message": "Failed to search by topic"}]
    
    async def get_todos(
        self,
        completed: bool = False
    ) -> List[Dict]:
        """Get todo items"""
        try:
            results = await db_manager.get_todos(completed)
            
            # Enrich with Obsidian URLs
            for result in results:
                if result.get('obsidian_path'):
                    result['obsidian_url'] = f"obsidian://open?file={result['obsidian_path']}"
            
            return results
            
        except Exception as e:
            return [{"error": str(e), "message": "Failed to get todos"}]
    
    async def find_recipes(
        self,
        ingredients: Optional[List[str]] = None,
        category: Optional[str] = None,
        max_time: Optional[int] = None
    ) -> List[Dict]:
        """Find recipes based on criteria"""
        try:
            query = db_manager.client.table("thoughts").select(
                "id, content, metadata, created_at, obsidian_path"
            ).eq("thought_type", "recipe")
            
            if ingredients:
                for ingredient in ingredients:
                    query = query.ilike("content", f"%{ingredient.lower()}%")
            
            if category:
                query = query.eq("metadata->>category", category.lower())
            
            if max_time:
                query = query.lte("metadata->>total_time", str(max_time))
            
            response = query.order("created_at", desc=True).execute()
            
            if not response.data:
                raise Exception(f"Failed to find recipes: {response}")
            
            results = response.data
            
            # Enrich with Obsidian URLs
            for result in results:
                if result.get('obsidian_path'):
                    result['obsidian_url'] = f"obsidian://open?file={result['obsidian_path']}"
            
            return results
            
        except Exception as e:
            return [{"error": str(e), "message": "Failed to find recipes"}]
    
    async def list_guides(
        self,
        category: Optional[str] = None,
        difficulty: Optional[str] = None
    ) -> List[Dict]:
        """List guides by category and difficulty"""
        try:
            query = db_manager.client.table("thoughts").select(
                "id, content, metadata, created_at, obsidian_path"
            ).eq("thought_type", "guide")
            
            if category:
                query = query.eq("metadata->>category", category.lower())
            
            if difficulty:
                query = query.eq("metadata->>difficulty", difficulty.lower())
            
            response = query.order("created_at", desc=True).execute()
            
            if not response.data:
                raise Exception(f"Failed to list guides: {response}")
            
            results = response.data
            
            # Enrich with Obsidian URLs
            for result in results:
                if result.get('obsidian_path'):
                    result['obsidian_url'] = f"obsidian://open?file={result['obsidian_path']}"
            
            return results
            
        except Exception as e:
            return [{"error": str(e), "message": "Failed to list guides"}]
    
    async def get_contacts(
        self,
        name: Optional[str] = None,
        category: Optional[str] = None
    ) -> List[Dict]:
        """Get contact information"""
        try:
            query = db_manager.client.table("thoughts").select(
                "id, content, metadata, created_at, obsidian_path"
            ).eq("thought_type", "contact")
            
            if name:
                query = query.ilike("content", f"%{name.lower()}%")
            
            if category:
                query = query.eq("metadata->>category", category.lower())
            
            response = query.order("created_at", desc=True).execute()
            
            if not response.data:
                raise Exception(f"Failed to get contacts: {response}")
            
            results = response.data
            
            # Enrich with Obsidian URLs
            for result in results:
                if result.get('obsidian_path'):
                    result['obsidian_url'] = f"obsidian://open?file={result['obsidian_path']}"
            
            return results
            
        except Exception as e:
            return [{"error": str(e), "message": "Failed to get contacts"}]
    
    async def cleanup(self):
        """Clean up async resources"""
        await db_manager.close()
        await embedding_generator.close()
        await metadata_extractor.close()
