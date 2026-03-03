import os
import asyncio
from typing import Dict, List, Optional
from config import Config
from supabase import create_client, Client
from supabase.lib.client_options import ClientOptions

class DatabaseManager:
    """Database manager for Supabase operations using Supabase Python API"""
    
    def __init__(self):
        self.supabase_url = Config.SUPABASE_URL
        self.supabase_secret_key = Config.SUPABASE_SECRET_KEY
        self.supabase_publish_key = Config.SUPABASE_PUBLISH_KEY
        
        # Initialize Supabase client
        self.client: Client = create_client(
            self.supabase_url,
            self.supabase_secret_key
        )
    
    async def store_thought(self, content: str, embedding: List[float], 
                          metadata: Dict) -> int:
        """Store a thought in Supabase"""
        thought_data = {
            "content": content,
            "embedding": embedding,
            "thought_type": metadata.get("type", "knowledge"),
            "topics": metadata.get("topics", []),
            "people": metadata.get("people", []),
            "action_items": metadata.get("action_items", []),
            "obsidian_path": metadata.get("obsidian_path", ""),
            "metadata": metadata,
            "source": metadata.get("source", "manual")
        }
        
        # Insert into thoughts table
        response = self.client.table("thoughts").insert(thought_data).execute()
        
        if not response.data:
            raise Exception(f"Failed to store thought: {response}")
        
        return response.data[0]["id"]
    
    async def semantic_search(self, query_embedding: List[float], 
                            limit: int = 10) -> List[Dict]:
        """Search thoughts by semantic similarity using Supabase Python API"""
        try:
            # Try to use RPC function for vector search
            # This requires a PostgreSQL function to be created in Supabase
            response = self.client.rpc(
                "vector_search",
                {
                    "query_embedding": query_embedding,
                    "match_count": limit
                }
            ).execute()
            
            if response.data:
                return response.data
        except Exception:
            pass  # Fall back if RPC not available
        
        # Fallback: Use direct SQL with vector comparison
        try:
            # Format embedding for PostgreSQL
            embedding_str = "[" + ",".join([str(x) for x in query_embedding]) + "]"
            
            # Use direct SQL with vector comparison
            query = f"""
            SELECT 
                id, content, thought_type, topics, people, 
                action_items, obsidian_path, created_at,
                (embedding <=> '{embedding_str}'::vector(1536)) as similarity
            FROM thoughts
            ORDER BY embedding <=> '{embedding_str}'::vector(1536)
            LIMIT {limit}
            """
            
            response = self.client.rpc("execute_sql", {"query": query}).execute()
            
            if response.data:
                return response.data
        except Exception:
            pass  # Fall back to recent thoughts
        
        # Final fallback: return recent thoughts if vector search not available
        response = self.client.table("thoughts").select(
            "id,content,thought_type,topics,people,action_items,obsidian_path,created_at"
        ).order("created_at", desc=True).limit(limit).execute()
        
        if not response.data:
            raise Exception(f"Failed to search thoughts: {response}")
        
        results = response.data
        # Add similarity score of 0 for fallback results
        for result in results:
            result['similarity'] = 0.0
        
        return results
    
    async def get_thought(self, thought_id: int) -> Optional[Dict]:
        """Get a specific thought by ID"""
        response = self.client.table("thoughts").select(
            "*"
        ).eq("id", thought_id).execute()
        
        if not response.data:
            raise Exception(f"Failed to get thought: {response}")
        
        return response.data[0] if response.data else None
    
    async def list_recent(self, days: int = 7, thought_type: Optional[str] = None) -> List[Dict]:
        """List recent thoughts"""
        from datetime import datetime, timedelta
        since_date = datetime.now() - timedelta(days=days)
        
        query = self.client.table("thoughts").select(
            "id, content, thought_type, topics, people, action_items, created_at, obsidian_path"
        ).gte("created_at", since_date.isoformat())
        
        if thought_type:
            query = query.eq("thought_type", thought_type)
        
        response = query.order("created_at", desc=True).execute()
        
        if not response.data:
            raise Exception(f"Failed to list recent thoughts: {response}")
        
        return response.data
    
    async def search_by_topic(self, topic: str, limit: int = 20) -> List[Dict]:
        """Search thoughts by specific topic"""
        response = self.client.table("thoughts").select(
            "id, content, thought_type, topics, people, action_items, created_at, obsidian_path"
        ).contains("topics", [topic]).order("created_at", desc=True).limit(limit).execute()
        
        if not response.data:
            raise Exception(f"Failed to search by topic: {response}")
        
        return response.data
    
    async def get_todos(self, completed: bool = False) -> List[Dict]:
        """Get todo items"""
        response = self.client.table("thoughts").select(
            "id, content, thought_type, topics, people, action_items, created_at, obsidian_path, metadata"
        ).eq("thought_type", "todo").order("created_at", desc=True).execute()
        
        if not response.data:
            raise Exception(f"Failed to get todos: {response}")
        
        results = response.data
        
        # Filter by completion status if needed
        if completed:
            results = [r for r in results if r.get('metadata', {}).get('completed')]
        else:
            results = [r for r in results if not r.get('metadata', {}).get('completed')]
        
        return results
    
    async def close(self):
        """Close the Supabase client"""
        # Supabase Python client doesn't require explicit closing
        # The client manages connections automatically
        pass
    
    async def sync_folders(self, folders_data: List[Dict]) -> Dict:
        """
        Sync folder structure with database.
        Creates new folders and updates existing ones.
        
        Args:
            folders_data: List of dicts with folder info:
                - path: str (e.g., "Resources/Health & Longevity/Youtube")
                - folder_name: str (e.g., "Youtube")
                - hierarchy: List[str] (e.g., ["Resources", "Health & Longevity", "Youtube"])
                - description: str (descriptive text for embedding)
                - embedding: List[float] (optional, generated if not provided)
        
        Returns:
            Dict with sync statistics
        """
        stats = {
            "total": len(folders_data),
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "errors": []
        }
        
        from embeddings import EmbeddingManager
        embedding_manager = EmbeddingManager()
        
        for folder_info in folders_data:
            try:
                path = folder_info["path"]
                
                # Check if folder exists
                existing = self.client.table("folders").select("*").eq("path", path).execute()
                
                # Generate embedding if not provided
                embedding = folder_info.get("embedding")
                if embedding is None:
                    embedding = await embedding_manager.create_embedding(folder_info["description"])
                
                folder_data = {
                    "path": path,
                    "folder_name": folder_info["folder_name"],
                    "full_path_hierarchy": folder_info["hierarchy"],
                    "description": folder_info["description"],
                    "embedding": embedding
                }
                
                if not existing.data:
                    # Create new folder
                    self.client.table("folders").insert(folder_data).execute()
                    stats["created"] += 1
                else:
                    # Update existing folder
                    self.client.table("folders").update(folder_data).eq("path", path).execute()
                    stats["updated"] += 1
                    
            except Exception as e:
                stats["errors"].append(f"Failed to sync folder {folder_info.get('path', 'unknown')}: {str(e)}")
        
        await embedding_manager.close()
        return stats
    
    async def search_folders_by_embedding(self, query_embedding: List[float], limit: int = 5) -> List[Dict]:
        """
        Find similar folders using vector search.
        
        Args:
            query_embedding: Vector embedding to search with
            limit: Maximum number of results to return
        
        Returns:
            List of dicts with folder info and similarity scores
        """
        try:
            # Get all folders with embeddings
            response = self.client.table("folders").select(
                "path, folder_name, full_path_hierarchy, description, embedding"
            ).execute()
            
            if not response.data:
                print("[DEBUG] No folders found in database", file=sys.stderr)
                return []
            
            print(f"[DEBUG] Retrieved {len(response.data)} folders from database", file=sys.stderr)
            
            # Calculate cosine similarity in Python
            import numpy as np
            
            query_array = np.array(query_embedding)
            results = []
            
            for folder in response.data:
                if folder.get('embedding'):
                    # Convert embedding to list of floats if it's a string
                    embedding = folder['embedding']
                    if isinstance(embedding, str):
                        # Parse string representation to list
                        import ast
                        embedding = ast.literal_eval(embedding)
                    
                    folder_array = np.array(embedding, dtype=np.float64)
                    # Calculate cosine similarity (1 - cosine distance)
                    # Cosine similarity: 1 = identical, 0 = orthogonal, -1 = opposite
                    dot_product = np.dot(query_array, folder_array)
                    norm_query = np.linalg.norm(query_array)
                    norm_folder = np.linalg.norm(folder_array)
                    similarity = dot_product / (norm_query * norm_folder)
                    
                    folder['similarity'] = float(similarity)
                    results.append(folder)
                else:
                    print(f"[DEBUG] Folder {folder.get('path')} has no embedding", file=sys.stderr)
            
            if not results:
                print("[DEBUG] No folders with embeddings found", file=sys.stderr)
                return []
            
            # Sort by similarity (highest first)
            results.sort(key=lambda x: x['similarity'], reverse=True)
            
            print(f"[DEBUG] Top folder similarity: {results[0]['similarity']:.4f}", file=sys.stderr)
            
            # Return top results
            return results[:limit]
                
        except Exception as e:
            # Fallback: get folders without similarity scoring
            print(f"[WARNING] Vector search failed: {e}, using fallback", file=sys.stderr)
            import traceback
            traceback.print_exc()
            try:
                response = self.client.table("folders").select(
                    "path, folder_name, full_path_hierarchy, description"
                ).limit(limit).execute()
                
                results = response.data if response.data else []
                # Add default similarity score
                for result in results:
                    result['similarity'] = 0.5  # Neutral score
                return results
                
            except Exception as fallback_e:
                print(f"[WARNING] Failed to search folders: {fallback_e}", file=sys.stderr)
                return []
    
    async def get_all_folders(self) -> List[Dict]:
        """Get all folders from database"""
        try:
            response = self.client.table("folders").select(
                "path, folder_name, full_path_hierarchy, description, created_at, updated_at"
            ).order("path").execute()
            
            return response.data if response.data else []
            
        except Exception as e:
            print(f"[WARNING] Failed to get folders: {e}", file=sys.stderr)
            return []
