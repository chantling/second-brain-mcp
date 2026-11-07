import os
import sys
import asyncio
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from config import Config
from database import DatabaseManager, transform_metadata_for_database
from obsidian import ObsidianManager
from embeddings import EmbeddingGenerator
from metadata import MetadataExtractor
from tag_utils import sync_tags_for_thought
from reranker import Reranker

# Get logger for this module
logger = logging.getLogger('second_brain.tools')

# Debug flag - set to True to enable debug output
DEBUG = False

# Global instances
db_manager = DatabaseManager()
obsidian_manager = ObsidianManager(Config.OBSIDIAN_VAULT_PATH, db_manager=db_manager)
embedding_generator = EmbeddingGenerator()
metadata_extractor = MetadataExtractor()
reranker = Reranker() if Config.RERANK_ENABLED else None


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
            "delete_note": self.delete_note,
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
            logger.error(f"[TOOLS] Unknown tool requested: {name}")
            return {"error": f"Unknown tool: {name}"}

        logger.info(f"[TOOLS] Routing to handler: {name}")
        start_time = datetime.now()
        
        try:
            result = await handler(**arguments)
            elapsed = (datetime.now() - start_time).total_seconds()
            logger.info(f"[TOOLS] Handler {name} completed in {elapsed:.2f}s")
            return result
        except Exception as e:
            elapsed = (datetime.now() - start_time).total_seconds()
            logger.error(f"[TOOLS] Handler {name} failed after {elapsed:.2f}s: {e}")
            raise

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
        store_start_time = datetime.now()
        
        logger.info(f"[STORE] store_thought started - content_length={len(content)}, title='{title[:50]}...' " if len(title) > 50 else f"[STORE] store_thought started - content_length={len(content)}, title='{title}'")

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
                logger.info("[STORE] No metadata provided, extracting from content...")
                metadata = await metadata_extractor.extract_metadata(content, title)
                logger.info(f"[STORE] Metadata extracted - type: {metadata.get('type', 'unknown')}, topics: {metadata.get('topics', [])}")
            else:
                logger.info(f"[STORE] Using provided metadata with keys: {list(metadata.keys())}")

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
        self, query: str, limit: int = 10, topics: Optional[List[str]] = None,
        rerank: Optional[bool] = None
    ) -> List[Dict]:
        """Search thoughts by semantic similarity"""
        try:
            # Generate query embedding with timeout
            logger.info("[TOOLS] Creating query embedding...")
            query_embedding = await asyncio.wait_for(
                embedding_generator.create_embedding(query), timeout=15.0
            )
            logger.info("[TOOLS] Query embedding created, searching database...")

            # Perform semantic search with timeout
            results = await asyncio.wait_for(
                db_manager.semantic_search(query_embedding, limit), timeout=10.0
            )
            logger.info(f"[TOOLS] Database search completed, {len(results)} results")

            # Filter by topics if provided
            if topics:
                results = [
                    r
                    for r in results
                    if any(topic in (r.get("topics") or []) for topic in topics)
                ]

            # Determine whether to rerank
            should_rerank = self._should_rerank(rerank)

            if should_rerank and reranker is not None and results:
                logger.info("[TOOLS] Applying reranking to semantic search results...")
                results = await reranker.rerank(query, results, top_n=limit)
                logger.info(f"[TOOLS] Reranking complete, {len(results)} results")

            # Enrich with Obsidian paths
            for result in results:
                if result.get("obsidian_path"):
                    result["obsidian_url"] = (
                        f"obsidian://open?file={result['obsidian_path']}"
                    )

            return results

        except asyncio.TimeoutError as e:
            logger.error(f"[TOOLS] semantic_search timed out: {e}")
            return [{"error": "Search timed out", "message": "Search timed out"}]
        except Exception as e:
            logger.error(f"[TOOLS] semantic_search failed: {e}")
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

    async def delete_note(
        self,
        thought_id: Optional[int] = None,
        obsidian_path: Optional[str] = None,
        confirm: bool = False,
        permanent: bool = False,
        reason: str = "",
    ) -> Dict:
        """Delete a note from Supabase and the Obsidian vault.

        Dry run by default. With confirm=true, the file is moved to the
        configured trash (Obsidian's .trash unless overridden), the Supabase
        row is deleted with its links and tag associations, and the result is
        verified. Unindexed files are not deleted.
        """
        try:
            # Some MCP clients send booleans as strings. Treat only explicit
            # truthy strings as true so a stray "false" cannot delete a note.
            if isinstance(confirm, str):
                confirm = confirm.strip().lower() in ("1", "true", "yes", "on")
            if isinstance(permanent, str):
                permanent = permanent.strip().lower() in ("1", "true", "yes", "on")

            if thought_id is None and not obsidian_path:
                return {
                    "success": False,
                    "error": "Provide thought_id and/or obsidian_path",
                }

            row = None
            if thought_id is not None:
                try:
                    thought_id = int(thought_id)
                except (TypeError, ValueError):
                    return {
                        "success": False,
                        "error": "thought_id must be an integer",
                    }
                row = await db_manager.get_thought(thought_id)
                if not row:
                    return {
                        "success": False,
                        "error": f"No thought found with id {thought_id}",
                    }

            supplied_path = None
            by_path = None
            if obsidian_path:
                normalized = self._normalize_obsidian_path(obsidian_path)
                by_path = await db_manager.get_thought_by_obsidian_path(
                    normalized
                )
                if by_path is None:
                    by_path = await db_manager.get_thought_by_obsidian_path(
                        normalized.replace("\\", "/")
                    )

                if by_path is not None:
                    if row is not None and row["id"] != by_path["id"]:
                        return {
                            "success": False,
                            "error": (
                                "thought_id and obsidian_path refer to "
                                "different rows"
                            ),
                        }
                    row = row or by_path
                else:
                    # The note may have moved and the row still points at the
                    # old path. Use the supplied file's frontmatter id.
                    try:
                        supplied_path = obsidian_manager.resolve_note_path(
                            obsidian_path
                        )
                    except ValueError as path_error:
                        if row is None:
                            return {
                                "success": False,
                                "error": str(path_error),
                            }
                        supplied_path = None

                    if supplied_path and supplied_path.is_file() and row is None:
                        supplied_rel = str(
                            supplied_path.relative_to(
                                obsidian_manager.vault_path.resolve()
                            )
                        )
                        content = supplied_path.read_text(encoding="utf-8")
                        metadata = obsidian_manager._extract_frontmatter(
                            content, supplied_rel
                        )
                        frontmatter_id = metadata.get("supabase_id")
                        if frontmatter_id not in (None, ""):
                            try:
                                row = await db_manager.get_thought(
                                    int(frontmatter_id)
                                )
                            except (TypeError, ValueError):
                                row = None
                            if row is None:
                                return {
                                    "success": False,
                                    "error": (
                                        "Note frontmatter points to missing "
                                        f"thought id {frontmatter_id}"
                                    ),
                                }

                    if row is None:
                        return {
                            "success": False,
                            "error": (
                                "No indexed note found at path: "
                                f"{obsidian_path}"
                            ),
                            "message": (
                                "The tool only deletes indexed notes. "
                                "Search/get the note first."
                            ),
                        }

            if row is None:
                return {"success": False, "error": "No thought found"}

            rel_path = row.get("obsidian_path") or ""

            row_ids = [row["id"]]
            if rel_path:
                same_path_ids = await db_manager.get_thought_ids_by_obsidian_path(
                    rel_path
                )
                if same_path_ids:
                    row_ids = same_path_ids

            # If both exist but point at different files, do not guess which
            # one the caller meant.
            if rel_path and supplied_path and supplied_path.is_file():
                try:
                    stored_target = obsidian_manager.resolve_note_path(rel_path)
                except ValueError:
                    stored_target = None
                if (
                    stored_target
                    and stored_target.is_file()
                    and stored_target.resolve() != supplied_path.resolve()
                ):
                    return {
                        "success": False,
                        "error": (
                            "obsidian_path does not match the stored path; "
                            "use the row's path or the same note"
                        ),
                    }

            target = None
            file_exists = False
            frontmatter_id = None
            stale_path_repaired = False

            if rel_path:
                target = obsidian_manager.resolve_note_path(rel_path)
                file_exists = target.is_file()

                if not file_exists:
                    # Prefer an explicitly supplied current path.
                    if supplied_path is None and obsidian_path:
                        try:
                            supplied_path = obsidian_manager.resolve_note_path(
                                obsidian_path
                            )
                        except ValueError:
                            supplied_path = None

                    if supplied_path and supplied_path.is_file():
                        supplied_rel = str(
                            supplied_path.relative_to(
                                obsidian_manager.vault_path.resolve()
                            )
                        )
                        content = supplied_path.read_text(encoding="utf-8")
                        supplied_fm = obsidian_manager._extract_frontmatter(
                            content, supplied_rel
                        )
                        valid_ids = {str(tid) for tid in row_ids}
                        if str(supplied_fm.get("supabase_id")) in valid_ids:
                            target = supplied_path
                            rel_path = supplied_rel
                            file_exists = True
                            stale_path_repaired = True

                    # Otherwise scan by frontmatter id. This is O(vault files)
                    # but only runs when the stored path is stale.
                    if not file_exists:
                        found = obsidian_manager.find_note_path_by_supabase_id(
                            row_ids
                        )
                        if found:
                            target = found
                            rel_path = str(
                                found.relative_to(
                                    obsidian_manager.vault_path.resolve()
                                )
                            )
                            file_exists = True
                            stale_path_repaired = True

            if file_exists:
                content = target.read_text(encoding="utf-8")
                metadata = obsidian_manager._extract_frontmatter(
                    content, rel_path
                )
                frontmatter_id = metadata.get("supabase_id")
                valid_frontmatter_ids = (
                    {None, ""}
                    | {str(tid) for tid in row_ids}
                    | set(row_ids)
                )
                if frontmatter_id not in valid_frontmatter_ids:
                    return {
                        "success": False,
                        "error": (
                            "Frontmatter supabase_id does not match the "
                            "database row"
                        ),
                        "thought_id": row["id"],
                        "obsidian_path": rel_path,
                        "frontmatter_id": frontmatter_id,
                    }

            preview = {
                "thought_id": row["id"],
                "thought_ids": row_ids,
                "duplicate_rows": max(0, len(row_ids) - 1),
                "obsidian_path": rel_path,
                "absolute_path": str(target) if target else None,
                "row_exists": True,
                "file_exists": file_exists,
                "frontmatter_id": frontmatter_id,
                "stale_path_repaired": stale_path_repaired,
                "permanent": permanent,
            }

            if not confirm:
                return {
                    "success": True,
                    "dry_run": True,
                    "note": preview,
                    "message": (
                        "Dry run only. Re-run with confirm=true to delete."
                    ),
                }

            if permanent and not Config.ALLOW_PERMANENT_DELETE:
                return {
                    "success": False,
                    "error": (
                        "Permanent deletes are disabled. Set "
                        "ALLOW_PERMANENT_DELETE=true or use permanent=false."
                    ),
                }

            if stale_path_repaired:
                await db_manager.update_obsidian_path(row["id"], rel_path)

            file_result = {"action": "missing", "path": rel_path}
            if file_exists:
                file_result = await obsidian_manager.delete_note_file(
                    rel_path,
                    permanent=permanent,
                    manifest_extra={
                        "thought_id": row["id"],
                        "thought_ids": row_ids,
                        "file_hash": row.get("file_hash"),
                        "reason": reason,
                    },
                )

            for tid in row_ids:
                await db_manager.delete_thought_by_id(tid)

            still_exists = False
            for tid in row_ids:
                if await db_manager.thought_exists(tid):
                    still_exists = True
                    break
            if still_exists:
                await asyncio.sleep(0.5)
                for tid in row_ids:
                    await db_manager.delete_thought_by_id(tid)
                still_exists = False
                for tid in row_ids:
                    if await db_manager.thought_exists(tid):
                        still_exists = True
                        break

            result = {
                "success": not still_exists,
                "deleted": {
                    "thought_id": row["id"],
                    "thought_ids": row_ids,
                    "duplicate_rows_deleted": max(0, len(row_ids) - 1),
                    "obsidian_path": rel_path,
                    "stale_path_repaired": stale_path_repaired,
                    "file_action": file_result.get("action"),
                    "trash_path": file_result.get("trash_path"),
                    "manifest_path": file_result.get("manifest_path"),
                    "db_deleted": not still_exists,
                },
            }
            if still_exists:
                result["message"] = (
                    "The file was deleted but the Supabase row is still "
                    "present. The watcher/orphan cleanup will retry; re-run "
                    "or check Supabase if it persists."
                )
            return result

        except ValueError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.error(f"[DELETE] delete_note failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Failed to delete note",
            }

    def _normalize_obsidian_path(self, path: str) -> str:
        p = Path(path)
        if p.is_absolute():
            vault = obsidian_manager.vault_path.resolve()
            p = p.resolve().relative_to(vault)
        return str(p).replace("/", "\\")

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
        rerank: Optional[bool] = None,
    ) -> List[Dict]:
        """Hybrid search with vector + keywords"""
        try:
            from search import SearchManager

            search_manager = SearchManager(db_manager, embedding_generator, reranker=reranker)

            # Default weights from config
            if weights is None:
                weights = {
                    "vector": Config.SEARCH_VECTOR_WEIGHT,
                    "keywords": Config.SEARCH_KEYWORD_WEIGHT,
                    "recency": Config.SEARCH_RECENCY_WEIGHT,
                }

            should_rerank = self._should_rerank(rerank)

            results = await search_manager.hybrid_search(
                query, limit, filters, weights, use_rerank=should_rerank
            )

            # Enrich with Obsidian URLs
            for result in results:
                if result.get("obsidian_path"):
                    result["obsidian_url"] = (
                        f"obsidian://open?file={result['obsidian_path']}"
                    )

            return results
        except Exception as e:
            return [{"error": str(e), "message": "Failed to perform hybrid search"}]

    def _should_rerank(self, rerank_param: Optional[bool]) -> bool:
        """Determine whether reranking should be applied.

        Args:
            rerank_param: Per-query override from caller.
                None: use global config default (RERANK_ENABLED).
                True: force reranking on (even if globally disabled).
                False: force reranking off.

        Returns:
            Whether to apply reranking.
        """
        if rerank_param is not None:
            return rerank_param
        return Config.RERANK_ENABLED

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
        store_start_time = datetime.now()
        logger.info(f"[STORE] _store_new_thought started - type: {metadata.get('type', 'unknown')}")
        
        # Determine folder using semantic search if enabled and folders are synced
        if Config.SEMANTIC_FOLDER_PLACEMENT and obsidian_manager._folders_synced:
            logger.info("[STORE] Running semantic folder search...")
            folder, confidence = await obsidian_manager._find_semantic_folder_match(
                content, metadata
            )
            # Override folder in metadata if semantic search found a good match
            if confidence >= 0.6:
                metadata["folder"] = folder
                logger.info(f"[STORE] Semantic folder search selected: {folder} (confidence: {confidence:.2f})")
                print(
                    f"[INFO] Semantic folder search selected: {folder} (confidence: {confidence:.2f})",
                    file=sys.stderr,
                )
            else:
                logger.info(f"[STORE] Semantic folder search confidence too low ({confidence:.2f}), using default")
        else:
            # Default to !To-Sort! folder if semantic placement is disabled
            metadata["folder"] = "!To-Sort!"
            logger.info("[STORE] Semantic folder placement disabled, using !To-Sort! folder")
            print(
                "[INFO] Semantic folder placement disabled, using !To-Sort! folder",
                file=sys.stderr,
            )

        # CRITICAL FIX: Compute file_hash before storing
        # This ensures that future modifications can be detected
        file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        metadata["file_hash"] = file_hash
        logger.info(f"[STORE] File hash computed: {file_hash[:16]}...")

        if DEBUG:
            print(f"[DEBUG] _store_new_thought - Metadata before database store: video_id={metadata.get('video_id')}, url={metadata.get('url')}", file=sys.stderr)
            print(f"[DEBUG] _store_new_thought - All metadata keys: {list(metadata.keys())}", file=sys.stderr)
        
        # Transform metadata to database format
        # This handles: 'type' → 'thought_type', extra fields → metadata JSONB
        transformed_metadata = transform_metadata_for_database(metadata)
        logger.info(f"[STORE] Metadata transformed - thought_type: {transformed_metadata.get('thought_type', 'unknown')}")
        
        # Store in Supabase
        logger.info("[STORE] Storing in Supabase...")
        supabase_start = datetime.now()
        supabase_id = await db_manager.store_thought(content, embedding, transformed_metadata)
        supabase_elapsed = (datetime.now() - supabase_start).total_seconds()
        logger.info(f"[STORE] Stored in Supabase with ID: {supabase_id} (took {supabase_elapsed:.2f}s)")

        # Sync tags to thought_tags table
        logger.info("[STORE] Syncing tags...")
        await sync_tags_for_thought(
            db_manager, supabase_id, content, metadata.get("topics")
        )
        logger.info("[STORE] Tags synced successfully")

        if DEBUG:
            print(f"[DEBUG] _store_new_thought - Stored in Supabase with ID: {supabase_id}", file=sys.stderr)

        # Store in Obsidian (run in thread to avoid blocking event loop)
        logger.info("[STORE] Creating Obsidian note...")
        obsidian_start = datetime.now()
        obsidian_result = await asyncio.to_thread(
            obsidian_manager.create_note,
            content, {**metadata, "supabase_id": supabase_id, "source": source}
        )
        obsidian_elapsed = (datetime.now() - obsidian_start).total_seconds()

        obsidian_path = obsidian_result["path"]
        logger.info(f"[STORE] Created Obsidian note at: {obsidian_path} (took {obsidian_elapsed:.2f}s)")
        
        if DEBUG:
            print(f"[DEBUG] _store_new_thought - Created Obsidian note at: {obsidian_path}", file=sys.stderr)
        
        # CRITICAL FIX: Update database with obsidian_path so downstream logic can find it
        logger.info("[STORE] Updating database with Obsidian path...")
        await db_manager.update_obsidian_path(supabase_id, obsidian_path)
        logger.info("[STORE] Database updated with Obsidian path")

        total_elapsed = (datetime.now() - store_start_time).total_seconds()
        logger.info(f"[STORE] _store_new_thought completed successfully in {total_elapsed:.2f}s")

        result = {
            "success": True,
            "action_taken": "stored",
            "supabase_id": supabase_id,
            "obsidian_path": obsidian_path,
            "message": "Thought stored successfully",
        }

        # Add duplicate warning to Obsidian if duplicate info provided
        if duplicate:
            await asyncio.to_thread(
                self._add_duplicate_warning_to_obsidian, obsidian_path, duplicate
            )
            
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
            obsidian_path = await asyncio.to_thread(
                self._update_obsidian_note,
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
        if reranker is not None:
            await reranker.close()
