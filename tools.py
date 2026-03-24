import os
import sys
import asyncio
import hashlib
from datetime import datetime
from typing import Dict, List, Optional, Any
from config import Config
from database import DatabaseManager, transform_metadata_for_database
from obsidian import ObsidianManager
from embeddings import EmbeddingGenerator
from metadata import MetadataExtractor
from tag_utils import sync_tags_for_thought

# Debug flag - set to True to enable debug output
DEBUG = False

# Global instances
db_manager = DatabaseManager()
obsidian_manager = ObsidianManager(Config.OBSIDIAN_VAULT_PATH, db_manager=db_manager)
embedding_generator = EmbeddingGenerator()
metadata_extractor = MetadataExtractor()


class ToolHandlers:
    """Handler class for all MCP tool operations"""

    async def handle_tool_call(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Route MCP tool calls to the appropriate handler method.
        
        Maps tool names to their corresponding handler methods in this class.
        Validates that the requested tool exists and invokes it with the provided
        arguments. Returns the handler's result or an error message if the tool
        is unknown.
        """
        # Folder sync now runs at server startup, not on first tool call
        # This eliminates blocking delays on initial tool calls

        handlers = {
            "store_thought": self.store_thought,
            "semantic_search": self.semantic_search,
            "list_recent": self.list_recent,
            "get_thought": self.get_thought,
            "search_by_topic": self.search_by_topic,
            "get_todos": self.get_todos,
            "find_recipes": self.find_recipes,
            "list_guides": self.list_guides,
            "get_contacts": self.get_contacts,
            "get_backlinks": self.get_backlinks,
            "find_related_notes": self.find_related_notes,
            "suggest_tags": self.suggest_tags,
            "hybrid_search": self.hybrid_search,
            "search_by_keyword": self.search_by_keyword,
        }

        handler = handlers.get(name)
        if not handler:
            return {"error": f"Unknown tool: {name}"}

        return await handler(**arguments)

    async def _sync_folders(self):
        """Sync Obsidian vault folders to database.
        
        Ensures all folders in the vault are represented in the database
        with embeddings for semantic folder placement. This is called once on
        server startup rather than on each tool call to avoid delays.
        """
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
        source: str = "manual",
        force_create: bool = False,
        force_overwrite: bool = False,
    ) -> Dict:
        """Store thought with duplicate detection"""
        debug_info = {} if DEBUG else None

        try:
            # Debug: Capture initial parameters
            if DEBUG:
                debug_info["input_title"] = title
                debug_info["content_length"] = len(content)
                debug_info["metadata_provided"] = metadata is not None
                if metadata:
                    debug_info["metadata_keys"] = list(metadata.keys())
                    debug_info["video_id_in_metadata"] = "video_id" in metadata
                    debug_info["url_in_metadata"] = "url" in metadata
                    debug_info["video_id_value"] = metadata.get("video_id", "NOT_SET")
                    debug_info["url_value"] = metadata.get("url", "NOT_SET")
                print(f"[DEBUG] store_thought - Initial metadata: {debug_info}", file=sys.stderr)

            # Extract metadata if not provided
            if not metadata:
                print(f"[DEBUG] store_thought - No metadata provided, extracting from content", file=sys.stderr)
                metadata = await metadata_extractor.extract_metadata(content, title)
            else:
                print(f"[DEBUG] store_thought - Using provided metadata with keys: {list(metadata.keys())}", file=sys.stderr)

            # CRITICAL FIX: Ensure title is in metadata
            # The AI might not return title, so we add it from the parameter
            if "title" not in metadata or not metadata.get("title"):
                metadata["title"] = title or "Untitled"

            # Debug: Capture metadata after extraction
            if DEBUG:
                debug_info["metadata_after_title"] = {k: metadata[k] for k in ["video_id", "url", "title", "type"] if k in metadata}
                print(f"[DEBUG] store_thought - Metadata after title set: {debug_info['metadata_after_title']}", file=sys.stderr)

            # Generate vector embedding
            embedding = await embedding_generator.create_embedding(content)

            # Check for duplicates (unless forced create)
            duplicate = None
            if not force_create:
                duplicate = await db_manager.check_for_duplicates(metadata)

            if duplicate and duplicate["found"] and not force_create:
                # Handle based on confidence level
                if duplicate["confidence"] == "high":
                    # High confidence - block and prompt user
                    return await self._handle_high_confidence_duplicate(
                        duplicate, content, embedding, metadata, source, force_overwrite
                    )
                elif duplicate["confidence"] == "medium":
                    # Medium confidence - flag warning, but store
                    return await self._handle_medium_confidence_duplicate(
                        duplicate, content, embedding, metadata, source
                    )
                # If we get here with found=True but no confidence level, treat as error
                duplicate = None

            # No duplicate or forced create - proceed with storage
            # Only pass duplicate info if a duplicate was actually FOUND
            return await self._store_new_thought(
                content, embedding, metadata, source, None
            )

        except Exception as e:
            if debug_info is None:
                debug_info = {}
            debug_info["error"] = str(e)
            debug_info["error_type"] = type(e).__name__
            result = {
                "success": False,
                "error": str(e),
                "message": "Failed to store thought",
            }
            if DEBUG:
                result["_debug"] = debug_info
            return result

    async def semantic_search(
        self, query: str, limit: int = 10, topics: Optional[List[str]] = None
    ) -> List[Dict]:
        """Search thoughts by semantic similarity"""
        try:
            # Generate query embedding
            query_embedding = await embedding_generator.create_embedding(query)

            # Perform semantic search
            results = await db_manager.semantic_search(query_embedding, limit)

            # Filter by topics if provided
            if topics:
                results = [
                    r
                    for r in results
                    if any(topic in (r.get("topics") or []) for topic in topics)
                ]

            # Enrich with Obsidian paths
            for result in results:
                if result.get("obsidian_path"):
                    result["obsidian_url"] = (
                        f"obsidian://open?file={result['obsidian_path']}"
                    )

            return results

        except Exception as e:
            return [{"error": str(e), "message": "Search failed"}]

    async def list_recent(
        self, days: int = 7, thought_type: Optional[str] = None
    ) -> List[Dict]:
        """List recent thoughts from both systems"""
        try:
            results = await db_manager.list_recent(days, thought_type)

            # Enrich with Obsidian URLs
            for result in results:
                if result.get("obsidian_path"):
                    result["obsidian_url"] = (
                        f"obsidian://open?file={result['obsidian_path']}"
                    )

            return results

        except Exception as e:
            return [{"error": str(e), "message": "Failed to get recent thoughts"}]

    async def get_thought(self, thought_id: int) -> Optional[Dict]:
        """Get a specific thought by ID"""
        try:
            result = await db_manager.get_thought(thought_id)
            if result and result.get("obsidian_path"):
                result["obsidian_url"] = (
                    f"obsidian://open?file={result['obsidian_path']}"
                )
            return result
        except Exception as e:
            return {"error": str(e), "message": "Failed to get thought"}

    async def search_by_topic(self, topic: str, limit: int = 20) -> List[Dict]:
        """Search thoughts by specific topic"""
        try:
            results = await db_manager.search_by_topic(topic, limit)

            # Enrich with Obsidian URLs
            for result in results:
                if result.get("obsidian_path"):
                    result["obsidian_url"] = (
                        f"obsidian://open?file={result['obsidian_path']}"
                    )

            return results

        except Exception as e:
            return [{"error": str(e), "message": "Failed to search by topic"}]

    async def search_by_keyword(self, query: str, limit: int = 10) -> List[Dict]:
        """Search thoughts using full-text search for exact word matching"""
        try:
            results = await db_manager.fulltext_search(query, limit)

            # Enrich with Obsidian URLs
            for result in results:
                if result.get("obsidian_path"):
                    result["obsidian_url"] = (
                        f"obsidian://open?file={result['obsidian_path']}"
                    )

            return results

        except Exception as e:
            return [{"error": str(e), "message": "Failed to search by keyword"}]

    async def get_todos(self, completed: bool = False) -> List[Dict]:
        """Get todo items"""
        try:
            results = await db_manager.get_todos(completed)

            # Enrich with Obsidian URLs
            for result in results:
                if result.get("obsidian_path"):
                    result["obsidian_url"] = (
                        f"obsidian://open?file={result['obsidian_path']}"
                    )

            return results

        except Exception as e:
            return [{"error": str(e), "message": "Failed to get todos"}]

    async def find_recipes(
        self,
        ingredients: Optional[List[str]] = None,
        category: Optional[str] = None,
        max_time: Optional[int] = None,
    ) -> List[Dict]:
        """Find recipes based on criteria"""
        try:
            query = (
                db_manager.client.table("thoughts")
                .select("id, content, metadata, created_at, obsidian_path")
                .eq("thought_type", "recipe")
            )

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
                if result.get("obsidian_path"):
                    result["obsidian_url"] = (
                        f"obsidian://open?file={result['obsidian_path']}"
                    )

            return results

        except Exception as e:
            return [{"error": str(e), "message": "Failed to find recipes"}]

    async def list_guides(
        self, category: Optional[str] = None, difficulty: Optional[str] = None
    ) -> List[Dict]:
        """List guides by category and difficulty"""
        try:
            query = (
                db_manager.client.table("thoughts")
                .select("id, content, metadata, created_at, obsidian_path")
                .eq("thought_type", "guide")
            )

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
                if result.get("obsidian_path"):
                    result["obsidian_url"] = (
                        f"obsidian://open?file={result['obsidian_path']}"
                    )

            return results

        except Exception as e:
            return [{"error": str(e), "message": "Failed to list guides"}]

    async def get_contacts(
        self, name: Optional[str] = None, category: Optional[str] = None
    ) -> List[Dict]:
        """Get contact information"""
        try:
            query = (
                db_manager.client.table("thoughts")
                .select("id, content, metadata, created_at, obsidian_path")
                .eq("thought_type", "contact")
            )

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
                if result.get("obsidian_path"):
                    result["obsidian_url"] = (
                        f"obsidian://open?file={result['obsidian_path']}"
                    )

            return results

        except Exception as e:
            return [{"error": str(e), "message": "Failed to get contacts"}]

    async def get_backlinks(self, thought_id: int, limit: int = 10) -> List[Dict]:
        """Get backlinks for a thought"""
        try:
            from links import LinkManager

            link_manager = LinkManager(db_manager)
            results = await link_manager.get_backlinks(thought_id)

            # Enrich with Obsidian URLs
            for result in results:
                if result.get("obsidian_path"):
                    result["obsidian_url"] = (
                        f"obsidian://open?file={result['obsidian_path']}"
                    )

            return results[:limit]
        except Exception as e:
            return [{"error": str(e), "message": "Failed to get backlinks"}]

    async def find_related_notes(self, thought_id: int, limit: int = 10) -> List[Dict]:
        """Find related notes"""
        try:
            from links import LinkManager

            link_manager = LinkManager(db_manager)
            results = await link_manager.find_related_notes(thought_id, limit)

            # Enrich with Obsidian URLs
            for result in results:
                if result.get("obsidian_path"):
                    result["obsidian_url"] = (
                        f"obsidian://open?file={result['obsidian_path']}"
                    )

            return results
        except Exception as e:
            return [{"error": str(e), "message": "Failed to find related notes"}]

    async def suggest_tags(self, content: str, limit: int = 10) -> List[Dict]:
        """Suggest tags based on content"""
        try:
            from tags import TagManager

            tag_manager = TagManager(db_manager, embedding_generator)
            results = await tag_manager.suggest_tags(content, limit)
            return results
        except Exception as e:
            return [{"error": str(e), "message": "Failed to suggest tags"}]

    async def hybrid_search(
        self,
        query: str,
        limit: int = 10,
        filters: Optional[Dict] = None,
        weights: Optional[Dict] = None,
    ) -> List[Dict]:
        """Hybrid search with vector + keywords"""
        try:
            from search import SearchManager

            search_manager = SearchManager(db_manager, embedding_generator)

            # Default weights from config
            if weights is None:
                weights = {
                    "vector": Config.SEARCH_VECTOR_WEIGHT,
                    "keywords": Config.SEARCH_KEYWORD_WEIGHT,
                    "recency": Config.SEARCH_RECENCY_WEIGHT,
                }

            results = await search_manager.hybrid_search(query, limit, filters, weights)

            # Enrich with Obsidian URLs
            for result in results:
                if result.get("obsidian_path"):
                    result["obsidian_url"] = (
                        f"obsidian://open?file={result['obsidian_path']}"
                    )

            return results
        except Exception as e:
            return [{"error": str(e), "message": "Failed to perform hybrid search"}]

    async def _store_new_thought(
        self,
        content: str,
        embedding: List[float],
        metadata: Dict,
        source: str,
        duplicate: Optional[Dict] = None,
    ) -> Dict:
        """Store a new thought in both Supabase and Obsidian.
        
        Determines the appropriate folder for storage using semantic search if enabled.
        Computes file hash for change detection. Stores the thought in Supabase
        database, creates the Obsidian markdown file with frontmatter, and
        updates the database with the file path. Optionally adds duplicate warnings
        to the Obsidian note if duplicate information is provided.
        """
        # Determine folder using semantic search if enabled and folders are synced
        global _folders_synced
        if Config.SEMANTIC_FOLDER_PLACEMENT and _folders_synced:
            folder, confidence = await obsidian_manager._find_semantic_folder_match(
                content, metadata
            )
            # Override folder in metadata if semantic search found a good match
            if confidence >= 0.6:
                metadata["folder"] = folder
                print(
                    f"[INFO] Semantic folder search selected: {folder} (confidence: {confidence:.2f})",
                    file=sys.stderr,
                )
        else:
            # Default to !To-Sort! folder if semantic placement is disabled
            metadata["folder"] = "!To-Sort!"
            print(
                "[INFO] Semantic folder placement disabled, using !To-Sort! folder",
                file=sys.stderr,
            )

        # CRITICAL FIX: Compute file_hash before storing
        # This ensures that future modifications can be detected
        file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        metadata["file_hash"] = file_hash

        if DEBUG:
            print(f"[DEBUG] _store_new_thought - Metadata before database store: video_id={metadata.get('video_id')}, url={metadata.get('url')}", file=sys.stderr)
            print(f"[DEBUG] _store_new_thought - All metadata keys: {list(metadata.keys())}", file=sys.stderr)
        
        # Transform metadata to database format
        # This handles: 'type' → 'thought_type', extra fields → metadata JSONB
        transformed_metadata = transform_metadata_for_database(metadata)
        
        # Store in Supabase
        supabase_id = await db_manager.store_thought(content, embedding, transformed_metadata)

        # Sync tags to thought_tags table
        await sync_tags_for_thought(
            db_manager, supabase_id, content, metadata.get("topics")
        )

        if DEBUG:
            print(f"[DEBUG] _store_new_thought - Stored in Supabase with ID: {supabase_id}", file=sys.stderr)

        # Store in Obsidian
        obsidian_result = obsidian_manager.create_note(
            content, {**metadata, "supabase_id": supabase_id, "source": source}
        )

        obsidian_path = obsidian_result["path"]
        
        if DEBUG:
            print(f"[DEBUG] _store_new_thought - Created Obsidian note at: {obsidian_path}", file=sys.stderr)
        
        # CRITICAL FIX: Update database with obsidian_path so downstream logic can find it
        await db_manager.update_obsidian_path(supabase_id, obsidian_path)

        result = {
            "success": True,
            "action_taken": "stored",
            "supabase_id": supabase_id,
            "obsidian_path": obsidian_path,
            "message": "Thought stored successfully",
        }

        # Add duplicate warning to Obsidian if duplicate info provided
        if duplicate:
            self._add_duplicate_warning_to_obsidian(obsidian_path, duplicate)
            
            # Safely extract duplicate info
            existing_thought = duplicate.get("existing_thought", {})
            metadata_info = existing_thought.get("metadata", {}) if isinstance(existing_thought, dict) else {}
            
            result["possible_duplicate"] = {
                "found": True,
                "tier": duplicate.get("tier"),
                "type": duplicate.get("type"),
                "confidence": duplicate.get("confidence"),
                "existing_id": existing_thought.get("id") if isinstance(existing_thought, dict) else None,
                "existing_title": metadata_info.get("title", "") if isinstance(metadata_info, dict) else "",
                "existing_created": existing_thought.get("created_at") if isinstance(existing_thought, dict) else None,
                "existing_obsidian_path": existing_thought.get("obsidian_path") if isinstance(existing_thought, dict) else None,
                "message": f"Note stored with duplicate warning (Tier {duplicate.get('tier')})",
            }

        return result

    async def _handle_high_confidence_duplicate(
        self,
        duplicate: Dict,
        content: str,
        embedding: List[float],
        metadata: Dict,
        source: str,
        force_overwrite: bool,
    ) -> Dict:
        """Handle high confidence duplicates (Tiers 1-2)"""
        existing = duplicate["existing_thought"]

        if force_overwrite:
            # Update existing thought in place
            supabase_id = await db_manager.update_thought_content(
                existing["id"], content, embedding, metadata
            )

            # Sync tags to thought_tags table
            await sync_tags_for_thought(
                db_manager, existing["id"], content, metadata.get("topics")
            )

            # Update Obsidian file
            obsidian_path = self._update_obsidian_note(
                existing["obsidian_path"], content, metadata
            )

            return {
                "success": True,
                "action_taken": "overwritten",
                "supabase_id": supabase_id,
                "obsidian_path": obsidian_path,
                "message": f"Existing thought updated (Tier {duplicate['tier']} duplicate)",
            }

        # Check DUPLICATE_HANDLING_MODE
        mode = Config.DUPLICATE_HANDLING_MODE

        if mode == "skip":
            return {
                "success": True,
                "action_taken": "skipped",
                "duplicate_detected": {
                    "found": True,
                    "tier": duplicate["tier"],
                    "type": duplicate["type"],
                    "confidence": "high",
                    "existing_id": existing["id"],
                    "existing_title": existing["metadata"].get("title", ""),
                    "existing_created": existing["created_at"],
                    "existing_obsidian_path": existing["obsidian_path"],
                },
                "message": f"Duplicate found (Tier {duplicate['tier']}), skipping storage",
            }

        elif mode == "overwrite":
            return await self._handle_high_confidence_duplicate(
                duplicate, content, embedding, metadata, source, force_overwrite=True
            )

        elif mode == "prompt":
            # Simple mode - return duplicate info for LLM to decide
            # Note: MCP Tasks support not implemented yet, using simple response
            return {
                "success": False,
                "requires_action": True,
                "duplicate_detected": {
                    "found": True,
                    "tier": duplicate["tier"],
                    "type": duplicate["type"],
                    "confidence": "high",
                    "existing_id": existing["id"],
                    "existing_title": existing["metadata"].get("title", ""),
                    "existing_created": existing["created_at"],
                    "existing_obsidian_path": existing["obsidian_path"],
                },
                "message": self._format_duplicate_message(duplicate, existing),
                "suggested_actions": ["skip", "force_create", "force_overwrite"],
            }

        return {"success": False, "error": "Unknown duplicate handling mode"}

    async def _handle_medium_confidence_duplicate(
        self,
        duplicate: Dict,
        content: str,
        embedding: List[float],
        metadata: Dict,
        source: str,
    ) -> Dict:
        """Handle medium confidence duplicates (Tier 3) - store with warning"""
        # Store new note (don't block)
        return await self._store_new_thought(
            content, embedding, metadata, source, duplicate
        )

    def _format_duplicate_message(self, duplicate: Dict, existing: Dict) -> str:
        """Format user-friendly duplicate message"""
        type_names = {
            "video_id": "YouTube video ID",
            "url_exact": "URL (exact match)",
            "url_heuristic": "URL (heuristic match)",
        }

        return (
            f"Duplicate found: {type_names.get(duplicate['type'], 'Unknown')} "
            f"(Tier {duplicate['tier']}, {duplicate['confidence']} confidence)\n"
            f"Existing: '{existing['metadata'].get('title', 'Untitled')}' "
            f"stored on {existing['created_at'][:10]}\n"
            f"Path: {existing['obsidian_path']}\n\n"
            f"Options: skip, force_create (create anyway), or force_overwrite (update existing)"
        )

    def _add_duplicate_warning_to_obsidian(
        self, obsidian_path: str, existing_thought: Dict
    ):
        """Add duplicate warning to top of Obsidian note"""
        try:
            # Safely extract duplicate info with fallbacks
            metadata = existing_thought.get("metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}
            
            title = metadata.get("title", "Untitled")
            created_at = existing_thought.get("created_at", "Unknown")
            existing_path = existing_thought.get("obsidian_path", "Unknown")
            tier = existing_thought.get("tier", 3)
            
            # Read existing note content
            full_path = f"{Config.OBSIDIAN_VAULT_PATH}/{obsidian_path}"
            with open(full_path, "r", encoding="utf-8") as f:
                existing_content = f.read()

            # Extract frontmatter and body
            frontmatter_end = existing_content.find("\n---\n", 1)
            if frontmatter_end == -1:
                # No frontmatter found
                frontmatter = ""
                body = existing_content
            else:
                frontmatter = existing_content[: frontmatter_end + 5]
                body = existing_content[frontmatter_end + 5 :]

            # Build warning
            type_names = {
                1: "exact video ID match",
                2: "exact URL match",
                3: "heuristic URL match (tracking parameters removed)",
            }

            match_type = type_names.get(tier, "unknown match")

            warning = f"""> [!WARNING] Possible Duplicate Detected
>
> This note may be a duplicate of an existing thought.
>
> **Existing Note:** {title}
> **Created:** {created_at}
> **Path:** {existing_path}
> **Match Type:** Tier {tier} - {match_type}
>
> Search your vault for this warning to find related notes.
>
> ---
"""

            # Write back with warning at top of body
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(frontmatter + warning + body)

            print(f"[INFO] Added duplicate warning to {obsidian_path}", file=sys.stderr)
        except Exception as e:
            print(
                f"[WARNING] Failed to add duplicate warning to {obsidian_path}: {e}",
                file=sys.stderr,
            )

    def _update_obsidian_note(
        self, obsidian_path: str, content: str, metadata: Dict
    ) -> str:
        """Update existing Obsidian note file"""
        try:
            full_path = f"{Config.OBSIDIAN_VAULT_PATH}/{obsidian_path}"
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"[INFO] Updated Obsidian note: {obsidian_path}", file=sys.stderr)
            return obsidian_path
        except Exception as e:
            print(
                f"[ERROR] Failed to update Obsidian note {obsidian_path}: {e}",
                file=sys.stderr,
            )
            raise

    async def cleanup(self):
        """Clean up async resources"""
        await db_manager.close()
        await embedding_generator.close()
        await metadata_extractor.close()
