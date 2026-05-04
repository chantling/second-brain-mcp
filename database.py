import os
import sys
import asyncio
import logging
from typing import Dict, List, Optional, Set
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from config import Config
from supabase import create_client, Client
from supabase.lib.client_options import ClientOptions

# Get logger for this module
logger = logging.getLogger('second_brain.database')


# Helper function for debug logging
def debug_log_to_file(message: str):
    """Write message to database_debug.log if DEBUG is enabled"""
    if not Config.DEBUG:
        return
    try:
        db_log_file = Path(__file__).parent / "database_debug.log"
        with open(db_log_file, "a", encoding="utf-8") as f:
            f.write(message + "\n")
            f.flush()
    except Exception:
        pass


# ✅ FIX #4: Define _log function for database operations
def _log(message: str, level: str = "INFO"):
    """Database operation logging with consistent format

    Args:
        message: Log message
        level: Log level (INFO, WARNING, ERROR, DELETE, INSERT, LOOKUP, etc.)
    """
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    log_msg = f"[{timestamp}] [DB:{level}] {message}"

    print(log_msg, file=sys.stderr)

    # Also write to database_debug.log if DEBUG enabled
    if Config.DEBUG:
        try:
            db_log_file = Path(__file__).parent / "database_debug.log"
            with open(db_log_file, "a", encoding="utf-8") as f:
                f.write(log_msg + "\n")
                f.flush()
        except Exception:
            pass  # Don't fail logging if can't write to file


class DatabaseManager:
    """Database manager for Supabase operations using Supabase Python API"""

    def __init__(self):
        """Initialize database manager with Supabase client configuration.

        Loads Supabase URL and secret/publish keys from Config.
        Creates a Supabase client instance for all database operations.
        The client uses connection pooling for efficient query execution.
        """
        self.supabase_url = Config.SUPABASE_URL
        self.supabase_secret_key = Config.SUPABASE_SECRET_KEY
        self.supabase_publish_key = Config.SUPABASE_PUBLISH_KEY

        # Initialize Supabase client
        self.client: Client = create_client(self.supabase_url, self.supabase_secret_key)

    async def _async_execute(self, query):
        """Run a synchronous Supabase query in a thread to avoid blocking the event loop.

        The Supabase Python client uses synchronous httpx internally.
        Without this wrapper, every .execute() call blocks the event loop,
        preventing the MCP server from responding to initialize requests
        during background sync operations.
        """
        return await asyncio.to_thread(query.execute)

    async def store_thought(
        self, content: str, embedding: List[float], metadata: Dict
    ) -> int:
        """Store a thought in Supabase"""
        obsidian_path = metadata.get("obsidian_path", "")
        file_hash = metadata.get("file_hash", "")
        source = metadata.get("source", "manual")

        # Log the insertion attempt
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        log_msg = f"[{ts}] [DB:INSERT] ↓↓↓ STORE_THOUGHT called ↓↓↓ path={obsidian_path}, hash={file_hash[:8] if file_hash else 'NONE'}..., source={source}"
        debug_log_to_file(log_msg)
        logger.info(f"[DB] store_thought started - path={obsidian_path}, hash={file_hash[:8] if file_hash else 'NONE'}..., source={source}")

        log_msg = f"[{ts}] [DB:INSERT] Inserting new entry: path={obsidian_path}, hash={file_hash[:8] if file_hash else 'NONE'}..., source={source}"
        debug_log_to_file(log_msg)

        thought_data = {
            "content": content,
            "embedding": embedding,
            "thought_type": metadata.get("type", "knowledge"),
            "topics": metadata.get("topics", []),
            "people": metadata.get("people", []),
            "action_items": metadata.get("action_items", []),
            "obsidian_path": obsidian_path,
            "metadata": metadata,
            "source": source,
            "file_hash": file_hash,
        }

        # Insert into thoughts table
        try:
            logger.info("[DB] Executing Supabase insert...")
            db_start = datetime.now()
            response = await self._async_execute(self.client.table("thoughts").insert(thought_data))
            db_elapsed = (datetime.now() - db_start).total_seconds()
            logger.info(f"[DB] Supabase insert completed in {db_elapsed:.2f}s")
        except Exception as insert_err:
            log_msg = f"[{ts}] [DB:INSERT] ✗ INSERT FAILED: {str(insert_err)}"
            debug_log_to_file(log_msg)
            logger.error(f"[DB] Insert failed: {insert_err}")
            raise

        if not response.data:
            log_msg = f"[{ts}] [DB:INSERT] ✗ INSERT returned no data: {response}"
            debug_log_to_file(log_msg)
            logger.error(f"[DB] Insert returned no data: {response}")
            raise Exception(f"Failed to store thought: {response}")

        created_id = response.data[0]["id"]

        # Log successful insertion with returned ID
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        log_msg = f"[{ts}] [DB:INSERT] ✓✓✓ SUCCESS ✓✓✓: New entry created with ID={created_id} for path={obsidian_path}"
        debug_log_to_file(log_msg)
        logger.info(f"[DB] Successfully stored thought with ID={created_id}")

        return created_id

    async def semantic_search(
        self, query_embedding: List[float], limit: int = 10
    ) -> List[Dict]:
        """Search thoughts by semantic similarity using Supabase Python API"""
        try:
            # Try to use RPC function for vector search
            # This requires a PostgreSQL function to be created in Supabase
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self.client.rpc(
                        "vector_search",
                        {"query_embedding": query_embedding, "match_count": limit},
                    ).execute
                ),
                timeout=Config.DB_TIMEOUT,
            )

            if response.data:
                return response.data
        except asyncio.TimeoutError:
            print(
                f"[ERROR] semantic_search timeout after {Config.DB_TIMEOUT}s (RPC)",
                file=sys.stderr,
            )
        except Exception as e:
            print(f"[WARNING] semantic_search RPC failed: {e}", file=sys.stderr)

        # Fallback: Use direct SQL with vector comparison
        try:
            # Validate limit to prevent SQL injection
            if not isinstance(limit, int) or limit < 1 or limit > 1000:
                limit = 10

            # Format embedding for PostgreSQL
            embedding_str = "[" + ",".join([str(x) for x in query_embedding]) + "]"

            # Use direct SQL with vector comparison
            query = f"""
            SELECT
                id, content, thought_type, topics, people,
                action_items, obsidian_path, created_at,
                (embedding <=> '{embedding_str}'::vector(Config.EMBEDDING_DIMENSIONS)) as similarity
            FROM thoughts
            ORDER BY embedding <=> '{embedding_str}'::vector(Config.EMBEDDING_DIMENSIONS)
            LIMIT {limit}
            """

            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self.client.rpc("execute_sql", {"query": query}).execute
                ),
                timeout=Config.DB_TIMEOUT,
            )

            if response.data:
                return response.data
        except asyncio.TimeoutError:
            print(
                f"[ERROR] semantic_search timeout after {Config.DB_TIMEOUT}s (SQL fallback)",
                file=sys.stderr,
            )
        except Exception as e:
            print(
                f"[WARNING] semantic_search SQL fallback failed: {e}", file=sys.stderr
            )

        # Final fallback: return recent thoughts if vector search not available
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self.client.table("thoughts")
                    .select(
                        "id,content,thought_type,topics,people,action_items,obsidian_path,created_at"
                    )
                    .order("created_at", desc=True)
                    .limit(limit)
                    .execute
                ),
                timeout=Config.DB_TIMEOUT,
            )

            if not response.data:
                raise Exception(f"Failed to search thoughts: {response}")

            results = response.data
            # Add similarity score of 0 for fallback results
            for result in results:
                result["similarity"] = 0.0

            return results
        except asyncio.TimeoutError:
            print(
                f"[ERROR] semantic_search timeout after {Config.DB_TIMEOUT}s (recent fallback)",
                file=sys.stderr,
            )
            return []
        except Exception as e:
            print(
                f"[ERROR] semantic_search recent fallback failed: {e}", file=sys.stderr
            )
            return []

    async def get_thought(self, thought_id: int) -> Optional[Dict]:
        """Get a specific thought by ID"""
        try:
            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            log_msg = f"[{ts}] [DB:LOOKUP] Querying for supabase_id={thought_id}"
            debug_log_to_file(log_msg)

            response = await self._async_execute(
                self.client.table("thoughts").select("*").eq("id", thought_id)
            )

            if response.data:
                result = response.data[0]
                path = result.get("obsidian_path", "")
                log_msg = f"[{ts}] [DB:LOOKUP] ✓ FOUND: ID={thought_id}, path={path}"
                debug_log_to_file(log_msg)
                return result
            else:
                log_msg = f"[{ts}] [DB:LOOKUP] ✗ NOT FOUND: supabase_id={thought_id}"
                debug_log_to_file(log_msg)
                return None
        except Exception as e:
            print(f"[WARNING] Failed to get thought by ID: {e}", file=sys.stderr)
            return None

    async def list_recent(
        self, days: int = 7, thought_type: Optional[str] = None
    ) -> List[Dict]:
        """List recent thoughts"""
        from datetime import datetime, timedelta

        since_date = datetime.now() - timedelta(days=days)

        query = (
            self.client.table("thoughts")
            .select(
                "id, content, thought_type, topics, people, action_items, created_at, obsidian_path"
            )
            .gte("created_at", since_date.isoformat())
        )

        if thought_type:
            query = query.eq("thought_type", thought_type)

        response = await asyncio.wait_for(
            asyncio.to_thread(query.order("created_at", desc=True).execute),
            timeout=Config.DB_TIMEOUT,
        )

        if not response.data:
            raise Exception(f"Failed to list recent thoughts: {response}")

        return response.data

    async def search_by_topic(self, topic: str, limit: int = 20) -> List[Dict]:
        """Search thoughts by specific topic"""
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self.client.table("thoughts")
                    .select(
                        "id, content, thought_type, topics, people, action_items, created_at, obsidian_path"
                    )
                    .contains("topics", [topic])
                    .order("created_at", desc=True)
                    .limit(limit)
                    .execute
                ),
                timeout=Config.DB_TIMEOUT,
            )

            if not response.data:
                raise Exception(f"Failed to search by topic: {response}")

            return response.data
        except asyncio.TimeoutError:
            print(
                f"[ERROR] search_by_topic timeout after {Config.DB_TIMEOUT}s",
                file=sys.stderr,
            )
            return []
        except Exception as e:
            print(f"[ERROR] search_by_topic failed: {e}", file=sys.stderr)
            return []

    async def get_todos(self, completed: bool = False) -> List[Dict]:
        """Get todo items with timeout protection"""
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self.client.table("thoughts")
                    .select(
                        "id, content, thought_type, topics, people, action_items, created_at, obsidian_path, metadata"
                    )
                    .eq("thought_type", "todo")
                    .order("created_at", desc=True)
                    .execute
                ),
                timeout=Config.DB_TIMEOUT,
            )

            if not response.data:
                _log(f"[DB:GET_TODOS] No todos found", "GET_TODOS")
                return []

            results = response.data

            # Filter by completion status if needed
            if completed:
                results = [r for r in results if r.get("metadata", {}).get("completed")]
            else:
                results = [
                    r for r in results if not r.get("metadata", {}).get("completed")
                ]

            _log(
                f"[DB:GET_TODOS] Retrieved {len(results)} todos (completed={completed})",
                "GET_TODOS",
            )
            return results

        except asyncio.TimeoutError:
            _log(
                f"[DB:GET_TODOS] ERROR: Timeout after {Config.DB_TIMEOUT}s", "GET_TODOS"
            )
            print(
                f"[ERROR] get_todos timeout after {Config.DB_TIMEOUT}s", file=sys.stderr
            )
            return []
        except Exception as e:
            _log(f"[DB:GET_TODOS] ERROR: {str(e)}", "GET_TODOS")
            print(f"[ERROR] Failed to get todos: {e}", file=sys.stderr)
            return []

    async def close(self):
        """Close and cleanup database resources.

        The Supabase Python client manages connections automatically through
        connection pooling, so no explicit cleanup is required. This method
        is provided for compatibility with resource cleanup patterns.
        """
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
                - embedding: List[float] (optional, pre-computed by caller)

        Returns:
            Dict with sync statistics (total, created, updated, skipped, errors)
        """
        stats = {
            "total": len(folders_data),
            "created": 0,
            "updated": 0,
            "cached": 0,
            "errors": [],
        }

        from embeddings import EmbeddingGenerator

        embedding_manager = EmbeddingGenerator()

        for folder_info in folders_data:
            try:
                path = folder_info["path"]

                # Check if folder exists
                existing = await self._async_execute(
                    self.client.table("folders").select("*").eq("path", path)
                )

                # Use pre-computed embedding if provided (from cache or DB)
                # Only generate embedding if None (defensive fallback)
                embedding = folder_info.get("embedding")
                if embedding is None:
                    print(
                        f"[WARNING] No embedding provided for {path}, generating...",
                        file=sys.stderr,
                    )
                    embedding = await embedding_manager.create_embedding(
                        folder_info["description"]
                    )
                else:
                    stats["cached"] += 1

                folder_data = {
                    "path": path,
                    "folder_name": folder_info["folder_name"],
                    "full_path_hierarchy": folder_info["hierarchy"],
                    "description": folder_info["description"],
                    "embedding": embedding,
                }

                if not existing.data:
                    # Create new folder
                    await self._async_execute(self.client.table("folders").insert(folder_data))
                    stats["created"] += 1
                else:
                    # Update existing folder
                    await self._async_execute(self.client.table("folders").update(folder_data).eq(
                        "path", path
                    ))
                    stats["updated"] += 1

            except Exception as e:
                stats["errors"].append(
                    f"Failed to sync folder {folder_info.get('path', 'unknown')}: {str(e)}"
                )

        await embedding_manager.close()
        return stats

    async def search_folders_by_embedding(
        self, query_embedding: List[float], limit: int = 5
    ) -> List[Dict]:
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
            response = await self._async_execute(
                self.client.table("folders")
                .select(
                    "path, folder_name, full_path_hierarchy, description, embedding"
                )
            )

            if not response.data:
                print("[DEBUG] No folders found in database", file=sys.stderr)
                return []

            print(
                f"[DEBUG] Retrieved {len(response.data)} folders from database",
                file=sys.stderr,
            )

            # Calculate cosine similarity in Python
            import numpy as np

            query_array = np.array(query_embedding)
            results = []

            for folder in response.data:
                if folder.get("embedding"):
                    # Convert embedding to list of floats if it's a string
                    embedding = folder["embedding"]
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

                    folder["similarity"] = float(similarity)
                    results.append(folder)
                else:
                    print(
                        f"[DEBUG] Folder {folder.get('path')} has no embedding",
                        file=sys.stderr,
                    )

            if not results:
                print("[DEBUG] No folders with embeddings found", file=sys.stderr)
                return []

            # Sort by similarity (highest first)
            results.sort(key=lambda x: x["similarity"], reverse=True)

            print(
                f"[DEBUG] Top folder similarity: {results[0]['similarity']:.4f}",
                file=sys.stderr,
            )

            # Return top results
            return results[:limit]

        except Exception as e:
            # Fallback: get folders without similarity scoring
            print(
                f"[WARNING] Vector search failed: {e}, using fallback", file=sys.stderr
            )
            import traceback

            traceback.print_exc()
            try:
                response = await self._async_execute(
                    self.client.table("folders")
                    .select("path, folder_name, full_path_hierarchy, description")
                    .limit(limit)
                )

                results = response.data if response.data else []
                # Add default similarity score
                for result in results:
                    result["similarity"] = 0.5  # Neutral score
                return results

            except Exception as fallback_e:
                print(
                    f"[WARNING] Failed to search folders: {fallback_e}", file=sys.stderr
                )
                return []

    async def get_all_folders(self) -> List[Dict]:
        """Get all folders from database"""
        try:
            response = await self._async_execute(
                self.client.table("folders")
                .select(
                    "path, folder_name, full_path_hierarchy, description, created_at, updated_at"
                )
                .order("path")
            )

            return response.data if response.data else []

        except Exception as e:
            print(f"[WARNING] Failed to get folders: {e}", file=sys.stderr)
            return []

    async def get_thought_by_obsidian_path(self, obsidian_path: str) -> Optional[Dict]:
        """Find thought by Obsidian file path"""
        try:
            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]

            # Log the lookup attempt
            log_msg = f"[{ts}] [DB:LOOKUP] Querying for obsidian_path={obsidian_path}"
            debug_log_to_file(log_msg)

            response = await self._async_execute(
                self.client.table("thoughts")
                .select("*")
                .eq("obsidian_path", obsidian_path)
            )

            if response.data:
                found_id = response.data[0]["id"]
                found_hash = (
                    response.data[0].get("file_hash", "")[:8]
                    if response.data[0].get("file_hash")
                    else "NONE"
                )
                log_msg = f"[{ts}] [DB:LOOKUP] ✓ FOUND: ID={found_id}, hash={found_hash}... for obsidian_path={obsidian_path}"
                debug_log_to_file(log_msg)
                return response.data[0]
            else:
                log_msg = (
                    f"[{ts}] [DB:LOOKUP] ✗ NOT FOUND: obsidian_path={obsidian_path}"
                )
                debug_log_to_file(log_msg)
                return None
        except Exception as e:
            print(f"[WARNING] Failed to get thought by path: {e}", file=sys.stderr)
            return None

    async def delete_thought_by_obsidian_path(self, obsidian_path: str) -> bool:
        """Delete thought by Obsidian file path"""
        _log(
            f"[DB:DELETE] Deleting thought by obsidian_path: {obsidian_path}", "DELETE"
        )
        try:
            thought = await self.get_thought_by_obsidian_path(obsidian_path)
            if thought:
                return await self.delete_thought_by_id(thought["id"])
            else:
                _log(
                    f"[DB:DELETE] No entry found for obsidian_path: {obsidian_path}",
                    "DELETE",
                )
                return False
        except Exception as e:
            _log(
                f"[DB:DELETE] ERROR deleting thought by obsidian_path {obsidian_path}: {e}",
                "DELETE",
            )
            return False

    async def get_all_thoughts(self) -> List[Dict]:
        """Get all thoughts from database (for orphan verification)"""
        try:
            response = await self._async_execute(
                self.client.table("thoughts").select("id, obsidian_path")
            )

            return response.data if response.data else []
        except Exception as e:
            print(f"[WARNING] Failed to get all thoughts: {e}", file=sys.stderr)
            return []

    async def delete_thought_by_id(self, thought_id: int):
        """Delete thought by ID"""
        _log(f"[DB:DELETE] Deleting thought by ID: {thought_id}", "DELETE")
        try:
            # _log(f"[DB:DELETE] Deleting thought by ID: {thought_id}", "DELETE")
            # Delete related links
            await self._async_execute(self.client.table("links").delete().eq(
                "source_thought_id", thought_id
            ))

            await self._async_execute(self.client.table("links").delete().eq(
                "target_thought_id", thought_id
            ))

            # Delete tag associations
            await self._async_execute(self.client.table("thought_tags").delete().eq(
                "thought_id", thought_id
            ))

            # Delete thought
            await self._async_execute(self.client.table("thoughts").delete().eq("id", thought_id))

            _log(f"[DB:DELETE] Successfully deleted thought ID: {thought_id}", "DELETE")
            return True
        except Exception as e:
            _log(f"[DB:DELETE] ERROR deleting thought {thought_id}: {e}", "DELETE")
            return False

    async def update_thought(
        self,
        thought_id: int,
        content: str,
        embedding: List[float],
        file_hash: str,
        metadata: Optional[Dict] = None,
    ):
        """Update existing thought in Supabase"""
        update_data = {
            "content": content,
            "embedding": embedding,
            "file_hash": file_hash,
            "updated_at": datetime.now().isoformat(),
        }

        if metadata:
            update_data["topics"] = metadata.get("topics", [])
            update_data["people"] = metadata.get("people", [])
            update_data["action_items"] = metadata.get("action_items", [])
            update_data["metadata"] = metadata
            update_data["thought_type"] = metadata.get("type", "knowledge")

        response = await self._async_execute(
            self.client.table("thoughts")
            .update(update_data)
            .eq("id", thought_id)
        )

        if not response.data:
            raise Exception(f"Failed to update thought {thought_id}")

    async def update_thought_content(
        self,
        thought_id: int,
        content: str,
        embedding: List[float],
        metadata: Dict,
    ) -> int:
        """Update existing thought content in place (for duplicate overwrites)"""
        thought_data = {
            "content": content,
            "embedding": embedding,
            "thought_type": metadata.get("type", "knowledge"),
            "topics": metadata.get("topics", []),
            "people": metadata.get("people", []),
            "action_items": metadata.get("action_items", []),
            "metadata": metadata,
            "updated_at": datetime.now().isoformat(),
        }

        response = await self._async_execute(
            self.client.table("thoughts")
            .update(thought_data)
            .eq("id", thought_id)
        )

        if not response.data:
            raise Exception(f"Failed to update thought {thought_id}")

        return thought_id

    async def check_for_duplicates(self, metadata: Dict) -> Dict:
        """
        Three-tier duplicate detection:
        - Tier 1 (High): Exact video_id match
        - Tier 2 (High): Exact URL match (basic normalization)
        - Tier 3 (Medium): Heuristic URL match (remove tracking params)
        """
        result = {
            "found": False,
            "tier": None,
            "type": None,
            "confidence": None,  # "high" | "medium"
            "existing_thought": None,
        }

        # Safely get metadata fields
        video_id = metadata.get("video_id") if metadata else None
        url = metadata.get("url") if metadata else None

        # Tier 1: Exact video_id match (highest priority)
        if video_id:
            try:
                response = await self._async_execute(
                    self.client.table("thoughts")
                    .select("id, content, metadata, created_at, obsidian_path")
                    .eq("metadata->>video_id", video_id)
                )

                if response.data:
                    result["found"] = True
                    result["tier"] = 1
                    result["type"] = "video_id"
                    result["confidence"] = "high"
                    result["existing_thought"] = response.data[0]
                    return result
            except Exception as e:
                print(f"[WARNING] Tier 1 duplicate check failed: {e}", file=sys.stderr)

        # Tier 2: Exact URL match (basic normalization)
        if url:
            try:
                normalized_url = basic_normalize_url(url)

                response = await self._async_execute(
                    self.client.table("thoughts")
                    .select("id, content, metadata, created_at, obsidian_path")
                    .not_.is_("metadata->>url", "null")
                )

                for thought in response.data:
                    existing_url = thought.get("metadata", {}).get("url", "")
                    if existing_url:
                        existing_normalized = basic_normalize_url(existing_url)
                        if existing_normalized == normalized_url:
                            result["found"] = True
                            result["tier"] = 2
                            result["type"] = "url_exact"
                            result["confidence"] = "high"
                            result["existing_thought"] = thought
                            return result
            except Exception as e:
                print(f"[WARNING] Tier 2 duplicate check failed: {e}", file=sys.stderr)

        # Tier 3: Heuristic URL match (remove tracking params)
        if url:
            try:
                normalized_url = heuristic_normalize_url(url)

                response = await self._async_execute(
                    self.client.table("thoughts")
                    .select("id, content, metadata, created_at, obsidian_path")
                    .not_.is_("metadata->>url", "null")
                )

                for thought in response.data:
                    existing_url = thought.get("metadata", {}).get("url", "")
                    if existing_url:
                        existing_normalized = heuristic_normalize_url(existing_url)
                        if existing_normalized == normalized_url:
                            result["found"] = True
                            result["tier"] = 3
                            result["type"] = "url_heuristic"
                            result["confidence"] = "medium"
                            result["existing_thought"] = thought
                            return result
            except Exception as e:
                print(f"[WARNING] Tier 3 duplicate check failed: {e}", file=sys.stderr)

        # No duplicate found
        return result

    async def update_obsidian_path(self, thought_id: int, new_path: str):
        """Update the obsidian_path for a thought (used for file renames)"""
        try:
            response = await self._async_execute(
                self.client.table("thoughts")
                .update({"obsidian_path": new_path})
                .eq("id", thought_id)
            )

            if not response.data:
                raise Exception(
                    f"Failed to update obsidian_path for thought {thought_id}"
                )
        except Exception as e:
            print(f"[WARNING] Failed to update obsidian_path: {e}", file=sys.stderr)

    async def delete_folder_by_path(self, folder_path: str):
        """Delete folder entry from database folders table"""
        _log(f"[DB:DELETE] Deleting folder: {folder_path}", "DELETE")
        try:
            # Delete folder entry from database
            response = await self._async_execute(
                self.client.table("folders")
                .delete()
                .eq("path", folder_path)
            )

            if not response.data:
                _log(f"[DB:DELETE] No folder found at path: {folder_path}", "DELETE")
                return False

            _log(f"[DB:DELETE] Successfully deleted folder: {folder_path}", "DELETE")
            return True
        except Exception as e:
            _log(f"[DB:DELETE] ERROR deleting folder {folder_path}: {e}", "DELETE")
            return False

    async def store_links(self, thought_id: int, links: List[Dict]):
        """Store wiki-link relationships"""
        if not links:
            return

        try:
            # Delete existing links for this thought
            await self._async_execute(self.client.table("links").delete().eq(
                "source_thought_id", thought_id
            ))

            # Insert new links
            for link_data in links:
                await self._async_execute(self.client.table("links").insert(link_data))
        except Exception as e:
            print(f"[WARNING] Failed to store links: {e}", file=sys.stderr)

    async def sync_tags(self, thought_id: int, tag_names: List[str]):
        """Sync tags for a thought"""
        if not tag_names:
            return

        try:
            # Create tags if they don't exist
            for tag_name in tag_names:
                try:
                    await self._async_execute(self.client.table("tags").insert({"name": tag_name}))
                except Exception:
                    pass

            # Delete existing tag associations
            await self._async_execute(self.client.table("thought_tags").delete().eq(
                "thought_id", thought_id
            ))

            # Get tag IDs
            tag_ids = []
            for tag_name in tag_names:
                response = await self._async_execute(
                    self.client.table("tags")
                    .select("id")
                    .eq("name", tag_name)
                )
                if response.data:
                    tag_ids.append(response.data[0]["id"])

            # Insert new associations
            for tag_id in tag_ids:
                await self._async_execute(self.client.table("thought_tags").insert(
                    {"thought_id": thought_id, "tag_id": tag_id}
                ))
        except Exception as e:
            print(f"[WARNING] Failed to sync tags: {e}", file=sys.stderr)

    async def keyword_search(self, query: str, limit: int = 10) -> List[Dict]:
        """Search thoughts by keyword matching"""
        try:
            # Use ILIKE for case-insensitive search
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self.client.table("thoughts")
                    .select(
                        "id, content, thought_type, topics, obsidian_path, created_at"
                    )
                    .ilike("content", f"%{query}%")
                    .limit(limit)
                    .execute
                ),
                timeout=Config.DB_TIMEOUT,
            )

            # Add score based on position
            results = response.data if response.data else []
            for idx, result in enumerate(results):
                result["score"] = 1.0 - (idx / limit)
                result["similarity"] = result["score"]

            return results
        except asyncio.TimeoutError:
            print(
                f"[ERROR] keyword_search timeout after {Config.DB_TIMEOUT}s",
                file=sys.stderr,
            )
            return []
        except Exception as e:
            print(f"[WARNING] Failed keyword search: {e}", file=sys.stderr)
            return []

    async def fulltext_search(self, query: str, limit: int = 10) -> List[Dict]:
        """Search thoughts using PostgreSQL full-text search with tsvector"""
        try:
            # Use text_search() which correctly maps to @@ operator
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self.client.table("thoughts")
                    .select(
                        "id, content, thought_type, topics, obsidian_path, created_at"
                    )
                    .text_search("content_tsv", query)
                    .limit(limit)
                    .execute
                ),
                timeout=Config.DB_TIMEOUT,
            )

            # Add score based on position (simplified ranking)
            results = response.data if response.data else []
            for idx, result in enumerate(results):
                result["score"] = 1.0 - (idx / limit)
                result["similarity"] = result["score"]

            return results
        except asyncio.TimeoutError:
            print(
                f"[ERROR] fulltext_search timeout after {Config.DB_TIMEOUT}s",
                file=sys.stderr,
            )
            return []
        except Exception as e:
            print(f"[WARNING] Full-text search failed: {e}", file=sys.stderr)
            # Fallback to keyword_search if full-text search fails
            return await self.keyword_search(query, limit)

    async def get_backlinks(self, thought_id: int) -> List[Dict]:
        """Get all notes that link to this thought"""
        try:
            response = await self._async_execute(
                self.client.table("links")
                .select("*,source_thought:thoughts!links_source_thought_id_fkey(*)")
                .eq("target_thought_id", thought_id)
            )

            return response.data if response.data else []
        except Exception as e:
            print(f"[WARNING] Failed to get backlinks: {e}", file=sys.stderr)
            return []

    async def get_outlinks(self, thought_id: int) -> List[Dict]:
        """Get all notes this thought links to"""
        try:
            response = await self._async_execute(
                self.client.table("links")
                .select("*,target_thought:thoughts!links_target_thought_id_fkey(*)")
                .eq("source_thought_id", thought_id)
            )

            return response.data if response.data else []
        except Exception as e:
            print(f"[WARNING] Failed to get outlinks: {e}", file=sys.stderr)
            return []


def basic_normalize_url(url: str) -> str:
    """Tier 2: Basic URL normalization for exact matching

    Removes trailing slash, lowercases domain, removes fragment (#section)
    Keeps scheme and query string intact
    """
    if not url:
        return url

    parsed = urlparse(url)

    # Remove trailing slash from path (even if path is just "/")
    path = parsed.path.rstrip("/") or "/"

    # Lowercase domain
    netloc = parsed.netloc.lower()

    # Build normalized URL (keep scheme, remove fragment only)
    # Scheme:netloc/path?query
    parts = []
    if parsed.scheme:
        parts.append(f"{parsed.scheme}://")
    parts.append(netloc)
    if path:
        parts.append(path)
    if parsed.query:
        parts.append(f"?{parsed.query}")

    return "".join(parts)


def heuristic_normalize_url(url: str) -> str:
    """Tier 3: Heuristic normalization - remove tracking parameters

    Removes known tracking parameters and scheme for comparison
    """
    if not url:
        return url

    # Start with basic normalization (remove trailing slash, lowercase domain, remove fragment)
    basic = basic_normalize_url(url)
    parsed = urlparse(basic)

    # Define tracking parameters to remove
    tracking_params = get_tracking_params()

    # Process query string
    if parsed.query:
        # Parse and filter query string
        filtered_params = []
        for param_pair in parsed.query.split("&"):
            if "=" in param_pair:
                key, _ = param_pair.split("=", 1)
                if key not in tracking_params:
                    filtered_params.append(param_pair)

        # Rebuild query string
        query = "&".join(filtered_params) if filtered_params else ""
    else:
        query = ""

    # Build normalized URL (no scheme, no fragment, filtered query)
    # netloc/path?query
    parts = []
    parts.append(parsed.netloc)
    if parsed.path:
        parts.append(parsed.path)
    if query:
        parts.append(f"?{query}")

    return "".join(parts)


def get_tracking_params() -> Set[str]:
    """Get list of tracking parameters to remove from URLs

    Uses hardcoded default + environment override
    """
    from config import Config

    # Default tracking parameters
    default_params = {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_content",
        "utm_term",
        "utm_id",
        "fbclid",
        "gclid",
        "msclkid",
        "_ga",
        "_gl",
        "ref",
        "source",
        "campaign",
        "medium",
    }

    # Allow override via environment variable
    custom_params = Config.DUPLICATE_TRACKING_PARAMS
    if custom_params:
        default_params.update(p.strip() for p in custom_params.split(","))

    return default_params


def transform_metadata_for_database(metadata: Dict) -> Dict:
    """Transform metadata for database storage

    Handles:
    - 'type' → 'thought_type' (defaults to 'knowledge')
    - Standard fields: topics, people, action_items, obsidian_path, source, file_hash
    - Extra fields → metadata JSONB

    Args:
        metadata: Raw metadata dict from user input

    Returns:
        Transformed metadata dict ready for database
    """
    result = {}

    # Transform 'type' to 'thought_type'
    if "type" in metadata:
        result["thought_type"] = metadata["type"]
    else:
        result["thought_type"] = "knowledge"

    # Extract standard fields
    standard_fields = [
        "topics",
        "people",
        "action_items",
        "obsidian_path",
        "source",
        "file_hash",
    ]
    for field in standard_fields:
        if field in metadata:
            result[field] = metadata[field]
        elif field in ["topics", "people", "action_items"]:
            # Default empty lists for array fields
            result[field] = []

    # Put everything else in metadata JSONB
    extra_fields = {}
    for key, value in metadata.items():
        if key not in standard_fields and key != "type" and key != "thought_type":
            extra_fields[key] = value

    result["metadata"] = extra_fields

    return result

    return default_params
