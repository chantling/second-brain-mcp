import os
import sys
import uuid
import json
import yaml
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from config import Config
from database import transform_metadata_for_database

# Debug flag - use Config.DEBUG
DEBUG = Config.DEBUG

# Local cache file for folder embeddings
EMBEDDINGS_CACHE_FILE = "!Folder_Embeddings.md"
CACHE_VALIDITY_DAYS = 7  # Refresh cache after 7 days


class ObsidianManager:
    """
    Obsidian vault manager for creating and organizing markdown notes.
    Uses Luca Decimal system with intelligent folder detection and confidence scoring.
    """

    def __init__(self, vault_path: str, db_manager=None):
        self.vault_path = Path(vault_path)
        self.all_folders = self._scan_vault_structure()
        self.ensure_special_folders_exist()
        self.db_manager = db_manager
        self._folders_synced = False
        self._last_sync_result = None

    def ensure_special_folders_exist(self):
        """Ensure special folders exist (To-Do, Contacts, Resources/Recipes, ToSort)"""
        special_folders = ["-To-Do-", "Contacts", "Resources/Recipes", "-To-Sort-"]

        for folder in special_folders:
            (self.vault_path / folder).mkdir(parents=True, exist_ok=True)

    def _scan_vault_structure(self) -> List[Path]:
        """
        Scan vault recursively and return all folders.
        Returns: List of Path objects for all folders in vault
        """
        folders = []

        for root, dirs, files in os.walk(self.vault_path):
            # Skip hidden folders
            for dir_name in dirs:
                dir_path = Path(root) / dir_name
                if not dir_name.startswith(".") and dir_name != ".obsidian":
                    folders.append(dir_path)

        return folders

    def create_note(self, content: str, metadata: Dict) -> Dict:
        """
        Create a new note in Obsidian with intelligent folder selection.

        Returns: Dict with 'path' (relative path) and optional '_debug' (debug information)
        """
        debug_info = {} if DEBUG else None

        # Debug: Capture metadata
        if DEBUG:
            debug_info["metadata_keys"] = list(metadata.keys())
            debug_info["metadata_title"] = metadata.get("title", "NOT_SET")
            debug_info["metadata_type"] = metadata.get("type", "NOT_SET")

        # Determine folder with confidence score
        folder_path, confidence = self._determine_folder(content, metadata)
        if DEBUG:
            debug_info["folder"] = folder_path
            debug_info["folder_confidence"] = confidence

        # Ensure folder exists
        self._ensure_folder_exists(folder_path)

        # Generate filename with smart fallback
        title = metadata.get("title", "Untitled")
        if DEBUG:
            debug_info["title_from_metadata"] = title

        sanitized_title = self._sanitize_filename(title)
        if DEBUG:
            debug_info["sanitized_title"] = sanitized_title
            debug_info["sanitized_title_length"] = len(sanitized_title)

        # Check if title is meaningful
        generic_titles = ["untitled", "untitled note", "note"]
        is_generic = (
            len(sanitized_title) < 3
            or sanitized_title.lower() in generic_titles
            or sanitized_title.isdigit()
        )

        if DEBUG:
            debug_info["is_generic"] = is_generic
            debug_info["sanitized_title_lower"] = sanitized_title.lower()
            debug_info["in_generic_titles"] = sanitized_title.lower() in generic_titles
            debug_info["length_lt_3"] = len(sanitized_title) < 3
            debug_info["is_digit"] = sanitized_title.isdigit()

        # Generate filename based on title quality
        if is_generic:
            filename = f"{datetime.now().strftime('%Y-%m-%d')}-{sanitized_title}.md"
            if DEBUG:
                debug_info["filename_format"] = "generic_with_date"
        else:
            filename = f"{sanitized_title}.md"
            if DEBUG:
                debug_info["filename_format"] = "title_only"

        if DEBUG:
            debug_info["filename"] = filename
        filepath = self.vault_path / folder_path / filename

        # Create frontmatter
        frontmatter = self._create_frontmatter(metadata, confidence)

        # Write file
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"{frontmatter}\n\n{content}")

        result = {"path": str(filepath.relative_to(self.vault_path))}

        if DEBUG:
            result["_debug"] = debug_info

        return result

    def _determine_folder(self, content: str, metadata: Dict) -> Tuple[str, float]:
        """
        Determine best folder for a note using confidence scoring.

        Returns: (folder_path, confidence_score)
        Confidence: 0.0-1.0 (higher = more certain)
        """
        thought_type = metadata.get("type", "knowledge")
        topics = metadata.get("topics", [])

        # Priority 1: Special cases (100% confidence)
        if thought_type == "recipe":
            return ("Resources/Recipes", 1.0)
        if thought_type == "todo":
            return ("-To-Do-", 1.0)
        if thought_type == "contact":
            return ("Contacts", 1.0)

        # Priority 2: Manual override via metadata (100% confidence)
        if "folder" in metadata:
            folder = metadata["folder"]
            return (folder, 1.0)

        # Priority 3: Exact folder name match (100% confidence)
        for topic in topics:
            exact_match = self._find_exact_folder(topic)
            if exact_match:
                return (exact_match, 1.0)

        # Priority 4: Semantic matching (0.6-0.9 confidence)
        best_match, confidence = self._find_semantic_match(content, topics)

        # Priority 5: Apply threshold
        if confidence >= 0.7:
            return (best_match, confidence)
        else:
            return ("-To-Sort-", confidence)

    def _find_exact_folder(self, topic: str) -> Optional[str]:
        """
        Find exact folder match, distinguishing numbered folders.
        Returns: Relative path to matching folder or None
        """
        topic_lower = topic.lower()

        for folder in self.all_folders:
            folder_name = folder.name.lower()
            folder_path = str(folder.relative_to(self.vault_path))

            # Exact match with folder name
            if topic_lower == folder_name:
                return folder_path

            # Match with number (e.g., "electronics" matches "300 Electronics")
            if topic_lower in folder_name and len(topic_lower) > 3:
                return folder_path

        return None

    def _find_semantic_match(
        self, content: str, topics: List[str]
    ) -> Tuple[str, float]:
        """
        Find best semantic match using content analysis and folder characteristics.

        Returns: (folder_path, confidence_score)
        """
        best_match = "-To-Sort-"
        best_confidence = 0.0

        content_lower = content.lower()

        for folder in self.all_folders:
            folder_path = str(folder.relative_to(self.vault_path))
            folder_name = folder.name.lower()

            confidence = 0.0

            # Check topic matches with this folder
            for topic in topics:
                topic_lower = topic.lower()

                # Topic matches folder name
                if topic_lower in folder_name:
                    confidence = max(confidence, 0.7)

                # Topic matches full path (e.g., "arduino" in "Resources/Electronics/Arduino")
                if topic_lower in folder_path.lower():
                    confidence = max(confidence, 0.85)

            # Check content keywords against folder
            keywords = self._get_keywords(folder_name)
            keyword_matches = sum(
                1 for keyword in keywords if keyword.lower() in content_lower
            )

            if keyword_matches >= 2:
                confidence = max(confidence, 0.75)
            elif keyword_matches >= 1:
                confidence = max(confidence, 0.65)

            # Extra confidence for numbered folders matching content context
            if folder.name.startswith(("1", "2", "3")):
                if self._matches_numbered_context(folder.name, content_lower):
                    confidence = max(confidence, 0.8)

            if confidence > best_confidence:
                best_match = folder_path
                best_confidence = confidence

        return best_match, best_confidence

    def _get_keywords(self, folder_name: str) -> List[str]:
        """
        Generate keywords for a folder name for matching.
        Returns: List of relevant keywords
        """
        keywords = [folder_name]

        # Common keyword mappings
        keyword_map = {
            "health": ["medical", "doctor", "hospital", "wellness", "fitness"],
            "finance": ["money", "bank", "investment", "budget", "financial"],
            "travel": ["trip", "vacation", "journey", "destination"],
            "electronics": ["circuit", "component", "hardware", "electronic"],
            "computer": ["software", "programming", "coding", "tech", "digital"],
            "ai": ["artificial intelligence", "machine learning", "neural", "model"],
            "garden": ["gardening", "plant", "soil", "vegetable"],
            "recipe": ["cooking", "food", "meal", "ingredient", "baking"],
        }

        for key, synonyms in keyword_map.items():
            if key in folder_name.lower():
                keywords.extend(synonyms)

        return keywords

    def _matches_numbered_context(self, folder_name: str, content: str) -> bool:
        """
        Check if content matches context of a numbered folder (Luca Decimal).
        """
        # Projects (1xx) - time-limited actions
        if folder_name.startswith("1"):
            project_keywords = [
                "project",
                "working on",
                "deadline",
                "complete",
                "finish",
                "in progress",
                "task",
                "milestone",
                "deliverable",
            ]
            return any(kw in content for kw in project_keywords)

        # Areas (2xx) - regular activities
        elif folder_name.startswith("2"):
            area_keywords = [
                "regularly",
                "maintain",
                "daily",
                "weekly",
                "monthly",
                "ongoing",
                "routine",
                "check",
                "monitor",
                "manage",
            ]
            return any(kw in content for kw in area_keywords)

        # Resources (3xx) - reference information
        elif folder_name.startswith("3"):
            resource_keywords = [
                "reference",
                "information",
                "learn",
                "guide",
                "tutorial",
                "documentation",
                "manual",
                "study",
                "note",
                "how to",
            ]
            return any(kw in content for kw in resource_keywords)

        return False

    def _ensure_folder_exists(self, folder_path: str):
        """Create folder path if it doesn't exist"""
        full_path = self.vault_path / folder_path
        full_path.mkdir(parents=True, exist_ok=True)

    def _create_frontmatter(self, metadata: Dict, confidence: float) -> str:
        """Create YAML frontmatter for note"""

        # Fields that are explicitly handled below
        handled_fields = {
            "id",
            "type",
            "topics",
            "people",
            "created",
            "source",
            "supabase_id",
            "folder_confidence",
        }

        # Start with explicitly handled fields
        frontmatter = {
            "id": metadata.get("id", str(uuid.uuid4())),
            "type": metadata.get("type", "knowledge"),
            "topics": metadata.get("topics", []),
            "people": metadata.get("people", []),
            "created": datetime.now().isoformat(),
            "source": metadata.get("source", "manual"),
            "supabase_id": metadata.get("supabase_id", ""),
            "folder_confidence": round(confidence, 2),
        }

        # Add all other metadata fields (this captures video_id, channel, upload_date, title, etc.)
        for key, value in metadata.items():
            if key not in handled_fields and value is not None:
                frontmatter[key] = value

        # Use PyYAML for proper serialization with quoting
        yaml_content = (
            "---\n"
            + yaml.dump(
                frontmatter,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            ).strip()
            + "\n---"
        )

        return yaml_content

    def _sanitize_filename(self, filename: str) -> str:
        """Remove invalid characters from filename"""
        # Remove characters that are invalid in filenames
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, "")

        # Replace multiple spaces with single space
        filename = " ".join(filename.split())

        # Limit length
        if len(filename) > 50:
            filename = filename[:50]

        return filename.strip()

    def get_folder_stats(self) -> Dict:
        """
        Get statistics about detected folders.
        Returns: Dict with folder counts and structure info
        """
        stats = {
            "total_folders": len(self.all_folders),
            "top_level": [],
            "projects": [],
            "areas": [],
            "resources": [],
            "archive": [],
            "other": [],
        }

        for folder in self.all_folders:
            rel_path = folder.relative_to(self.vault_path)
            parts = list(rel_path.parts)

            # Top-level folders
            if len(parts) == 1:
                stats["top_level"].append(parts[0])

            # Categorize by Luca Decimal conventions
            folder_name = folder.name.lower()
            if folder_name.startswith("1"):
                stats["projects"].append(str(rel_path))
            elif folder_name.startswith("2"):
                stats["areas"].append(str(rel_path))
            elif folder_name.startswith("3"):
                stats["resources"].append(str(rel_path))
            elif folder_name.startswith("4"):
                stats["archive"].append(str(rel_path))
            else:
                stats["other"].append(str(rel_path))

        return stats

    async def sync_folders_to_database(self) -> Dict:
        """
        Sync all folders to database with embeddings using two-tier caching.
        This should be called on server startup.
        Also saves folder embeddings to local cache.

        Strategy:
        1. Load local cache if valid (7 days)
        2. Batch query database for missing folders
        3. Generate embeddings only for folders missing from both cache and DB
        4. Sync all folders to database
        5. Save complete cache (local + DB + newly generated)

        Returns: Sync statistics
        """
        if not self.db_manager:
            print(
                "[WARNING] No database manager provided, skipping folder sync",
                file=sys.stderr,
            )
            return {
                "total": 0,
                "created": 0,
                "updated": 0,
                "skipped": 0,
                "errors": ["No database manager"],
            }

        folders_data = []
        skip_folders = ["-To-Do-", "Contacts", "-To-Sort-", ".obsidian", ".ClineData"]

        # Phase 1: Load local cache and scan folders
        folder_embeddings = {}

        if self._is_cache_valid():
            print("[INFO] Using valid local folder cache", file=sys.stderr)
            folder_embeddings = self._load_folder_embeddings_cache()
            print(f"[INFO] Loaded {len(folder_embeddings)} embeddings from local cache", file=sys.stderr)
        else:
            print("[INFO] Local cache invalid or missing, will query database", file=sys.stderr)

        # Scan folders and build folder_data
        folders_to_process = []

        for folder in self.all_folders:
            try:
                rel_path = str(folder.relative_to(self.vault_path))

                if any(skip in rel_path for skip in skip_folders):
                    continue

                # Check if we have embedding from local cache
                if rel_path in folder_embeddings:
                    embedding = folder_embeddings[rel_path]
                    if DEBUG:
                        print(f"[DEBUG] Using cached embedding for {rel_path}", file=sys.stderr)
                else:
                    embedding = None
                    folders_to_process.append(rel_path)

                folder_info = {
                    "path": rel_path,
                    "folder_name": folder.name,
                    "hierarchy": list(folder.relative_to(self.vault_path).parts),
                    "description": self._generate_folder_description(folder),
                    "embedding": embedding,
                }

                folders_data.append(folder_info)

            except Exception as e:
                print(
                    f"[WARNING] Failed to process folder {folder}: {e}", file=sys.stderr
                )

        # Phase 2: Batch fetch missing folders from database
        folders_to_generate = []

        if folders_to_process:
            print(f"[INFO] Fetching {len(folders_to_process)} folder embeddings from database...", file=sys.stderr)

            try:
                # Query DB for all folders at once (Option A: batch query)
                response = self.db_manager.client.table("folders").select("path, embedding").execute()

                if response.data:
                    for db_folder in response.data:
                        path = db_folder.get("path")
                        embedding = db_folder.get("embedding")

                        if path and embedding:
                            # Parse embedding if it's a string
                            if isinstance(embedding, str):
                                import ast

                                embedding = ast.literal_eval(embedding)

                            # Add to embeddings dict
                            folder_embeddings[path] = embedding

                            # Update corresponding folder_data entry
                            for folder_info in folders_data:
                                if folder_info["path"] == path:
                                    folder_info["embedding"] = embedding
                                    if DEBUG:
                                        print(f"[DEBUG] Fetched embedding from DB for {path}", file=sys.stderr)
                                    break

                    # Remove folders we found in database
                    folders_to_generate = [f for f in folders_to_process if f not in folder_embeddings]

                    print(f"[INFO] Found {len(folders_to_process) - len(folders_to_generate)} folders in database", file=sys.stderr)
                else:
                    print("[WARNING] Database query returned no data, will generate all embeddings", file=sys.stderr)
                    folders_to_generate = folders_to_process[:]

            except Exception as e:
                print(f"[ERROR] Database query failed: {e}, generating all embeddings", file=sys.stderr)
                # Fallback: treat all folders as needing generation
                folders_to_generate = folders_to_process[:]
        else:
            print("[INFO] All folders have embeddings from cache", file=sys.stderr)

        # Phase 3: Generate embeddings for folders not in cache or DB
        if folders_to_generate:
            print(f"[INFO] Generating embeddings for {len(folders_to_generate)} folders...", file=sys.stderr)

            from embeddings import EmbeddingGenerator
            embedding_manager = EmbeddingGenerator()

            for folder_path in folders_to_generate:
                try:
                    folder_info = next((f for f in folders_data if f["path"] == folder_path), None)
                    if folder_info:
                        embedding = await embedding_manager.create_embedding(folder_info["description"])
                        folder_info["embedding"] = embedding
                        folder_embeddings[folder_path] = embedding
                except Exception as e:
                    print(f"[ERROR] Failed to generate embedding for {folder_path}: {e}", file=sys.stderr)

            await embedding_manager.close()
        else:
            print("[INFO] No new folder embeddings to generate", file=sys.stderr)

        # Phase 4: Sync to database with pre-computed embeddings
        if folders_data:
            print(f"[INFO] Syncing {len(folders_data)} folders to database...", file=sys.stderr)
            stats = await self.db_manager.sync_folders(folders_data)
            print(
                f"[INFO] Folder sync complete: {stats['created']} created, {stats['updated']} updated, {stats.get('skipped', 0)} skipped",
                file=sys.stderr,
            )
            if stats["errors"]:
                print(
                    f"[WARNING] Errors during sync: {len(stats['errors'])}",
                    file=sys.stderr,
                )

            # Phase 5: Save updated cache (includes all: local + DB + newly generated)
            print(f"[INFO] Saving {len(folder_embeddings)} folder embeddings to local cache...", file=sys.stderr)
            self._save_folder_embeddings_cache(folder_embeddings)
            print(
                f"[INFO] Saved {len(folder_embeddings)} folder embeddings to local cache",
                file=sys.stderr,
            )

            self._folders_synced = True
            return stats
        else:
            print("[INFO] No folders to sync", file=sys.stderr)
            return {"total": 0, "created": 0, "updated": 0, "skipped": 0, "errors": []}

    def _generate_folder_description(self, folder: Path) -> str:
        """
        Generate a descriptive text for a folder based on:
        - Folder name and path hierarchy
        - Sample content from notes in the folder

        Returns: Descriptive text suitable for embedding generation
        """
        parts = list(folder.relative_to(self.vault_path).parts)

        description = f"Folder: {folder.name}\n"
        description += f"Path: {' / '.join(parts)}\n"

        # Add context from folder hierarchy
        if len(parts) > 1:
            parent = parts[-2]
            description += f"Parent category: {parent}\n"

        # Add sample content from notes in folder
        notes = list(folder.glob("*.md"))

        if notes:
            description += f"\nContains {len(notes)} notes\n"

            # Add content from up to 2 sample notes
            for note in notes[:2]:
                try:
                    with open(note, "r", encoding="utf-8") as f:
                        content = f.read(800)  # First 800 chars

                        # Remove YAML frontmatter if present
                        if content.startswith("---"):
                            end_marker = content.find("\n---", 4)
                            if end_marker != -1:
                                content = content[end_marker + 4 :]

                        # Clean up and add
                        content = content.strip()
                        if len(content) > 300:
                            content = content[:300] + "..."

                        description += f"\nSample note: {content}\n"
                except Exception as e:
                    # Skip if we can't read the file
                    pass
        else:
            description += "\nEmpty folder - no notes yet\n"

        return description

    async def _find_semantic_folder_match(
        self, content: str, metadata: Dict
    ) -> Tuple[str, float]:
        """
        Find the best folder using hierarchical semantic search with embeddings.

        Strategy:
        1. Start with top-level folders and find closest match
        2. Navigate down through subfolders iteratively
        3. Continue until reaching a leaf folder (no subfolders)

        Uses local cache for folder embeddings when available.

        Returns: (folder_path, confidence_score)
        """
        if not self.db_manager or not self._folders_synced:
            # Fallback to local matching if database not available
            return self._find_semantic_match(content, metadata.get("topics", []))

        try:
            # Try to use cached folder embeddings first
            folder_cache = self._load_folder_embeddings_cache()
            folders_by_level = self._organize_folders_by_level()

            # Import here to avoid circular dependency
            from embeddings import EmbeddingGenerator

            embedding_manager = EmbeddingGenerator()

            # Create embedding for the note content
            note_embedding = await embedding_manager.create_embedding(content)

            # Start hierarchical search from top level
            current_folder = None
            current_level = 0
            overall_confidence = 1.0

            if DEBUG:
                print(
                    f"[DEBUG] Starting hierarchical folder search for content length: {len(content)}",
                    file=sys.stderr,
                )

            # Iterate through hierarchy levels
            while True:
                # Get folders at current level
                level_folders = folders_by_level.get(current_level, [])

                # If no folders at this level, we're done
                if not level_folders:
                    break

                # If we have a current folder, only look at its subfolders
                if current_folder:
                    # Filter folders that are direct children of current_folder
                    child_folders = [
                        f for f in level_folders if f.startswith(current_folder + "/")
                    ]
                    search_folders = child_folders

                    if DEBUG:
                        print(
                            f"[DEBUG] Level {current_level}: Found {len(child_folders)} subfolders under {current_folder}",
                            file=sys.stderr,
                        )
                else:
                    # Top level - use all folders
                    search_folders = [f for f in level_folders if "/" not in f]

                    if DEBUG:
                        print(
                            f"[DEBUG] Level {current_level}: Searching {len(search_folders)} top-level folders",
                            file=sys.stderr,
                        )

                # If no subfolders found, we've reached a leaf
                if not search_folders:
                    break

                # Find best match at this level
                best_folder_at_level, confidence = await self._find_best_match_at_level(
                    note_embedding, search_folders, folder_cache, embedding_manager
                )

                if DEBUG:
                    print(
                        f"[DEBUG] Level {current_level}: Best match = {best_folder_at_level} (confidence: {confidence:.4f})",
                        file=sys.stderr,
                    )

                # Check if confidence is good enough to proceed
                if confidence < 0.6:
                    # Low confidence - stop here
                    break

                # Update current folder and confidence
                current_folder = best_folder_at_level
                overall_confidence *= confidence
                current_level += 1

                # Safety limit - don't go too deep
                if current_level >= 10:
                    print(
                        "[WARNING] Reached maximum folder depth, stopping",
                        file=sys.stderr,
                    )
                    break

            await embedding_manager.close()

            # Return the final folder found
            if current_folder:
                # Calculate overall confidence (product of all level confidences)
                final_confidence = max(0.0, min(1.0, overall_confidence))

                if DEBUG:
                    print(
                        f"[DEBUG] Final folder: {current_folder} (overall confidence: {final_confidence:.4f})",
                        file=sys.stderr,
                    )

                return (current_folder, final_confidence)
            else:
                # Fallback to local matching
                return self._find_semantic_match(content, metadata.get("topics", []))

        except Exception as e:
            print(
                f"[WARNING] Hierarchical semantic folder search failed: {e}",
                file=sys.stderr,
            )
            import traceback

            traceback.print_exc()
            # Fallback to local matching
            return self._find_semantic_match(content, metadata.get("topics", []))

    def _organize_folders_by_level(self) -> Dict[int, List[str]]:
        """
        Organize all folders by their depth level in the hierarchy.

        Returns: Dict mapping level -> list of folder paths
        """
        folders_by_level = {}

        for folder in self.all_folders:
            rel_path = str(folder.relative_to(self.vault_path))
            parts = rel_path.split("/")
            level = len(parts) - 1  # 0-based level

            if level not in folders_by_level:
                folders_by_level[level] = []
            folders_by_level[level].append(rel_path)

        return folders_by_level

    async def _find_best_match_at_level(
        self,
        note_embedding: List[float],
        folder_paths: List[str],
        folder_cache: Dict[str, List[float]],
        embedding_manager,
    ) -> Tuple[str, float]:
        """
        Find the best matching folder at a specific level.

        Args:
            note_embedding: Embedding vector for the note
            folder_paths: List of folder paths at this level
            folder_cache: Cached embeddings dict {path: embedding}
            embedding_manager: EmbeddingGenerator instance for generating new embeddings

        Returns: (best_folder_path, confidence_score)
        """
        import numpy as np

        note_array = np.array(note_embedding, dtype=np.float64)

        best_folder = folder_paths[0]
        best_similarity = -1.0

        # Calculate similarity for each folder
        for folder_path in folder_paths:
            folder_embedding = None

            # Try to get from cache
            if folder_path in folder_cache:
                folder_embedding = folder_cache[folder_path]
                if DEBUG:
                    print(
                        f"[DEBUG] Using cached embedding for {folder_path}",
                        file=sys.stderr,
                    )

            # If not in cache or cache needs refresh, fetch from database
            if folder_embedding is None and self.db_manager and self._folders_synced:
                try:
                    # Fetch folder from database
                    response = (
                        self.db_manager.client.table("folders")
                        .select("path, embedding")
                        .eq("path", folder_path)
                        .execute()
                    )

                    if response.data and response.data[0].get("embedding"):
                        embedding_data = response.data[0]["embedding"]
                        if isinstance(embedding_data, str):
                            import ast

                            embedding_data = ast.literal_eval(embedding_data)
                        folder_embedding = embedding_data

                        # Update cache
                        folder_cache[folder_path] = folder_embedding
                        self._save_folder_embeddings_cache(folder_cache)

                        if DEBUG:
                            print(
                                f"[DEBUG] Fetched and cached embedding for {folder_path}",
                                file=sys.stderr,
                            )
                except Exception as e:
                    if DEBUG:
                        print(
                            f"[DEBUG] Failed to fetch embedding for {folder_path}: {e}",
                            file=sys.stderr,
                        )

            # If still no embedding, skip this folder
            if folder_embedding is None:
                if DEBUG:
                    print(
                        f"[DEBUG] No embedding available for {folder_path}, skipping",
                        file=sys.stderr,
                    )
                continue

            # Calculate cosine similarity
            folder_array = np.array(folder_embedding, dtype=np.float64)
            dot_product = np.dot(note_array, folder_array)
            norm_note = np.linalg.norm(note_array)
            norm_folder = np.linalg.norm(folder_array)
            similarity = dot_product / (norm_note * norm_folder)

            if similarity > best_similarity:
                best_similarity = similarity
                best_folder = folder_path

        # Return best folder with confidence (similarity as confidence)
        return (best_folder, max(0.0, min(1.0, best_similarity)))

    def _load_folder_embeddings_cache(self) -> Dict[str, List[float]]:
        """
        Load folder embeddings from local cache file.

        Returns: Dict mapping folder paths to embeddings
        """
        cache_path = self.vault_path / EMBEDDINGS_CACHE_FILE

        if not cache_path.exists():
            return {}

        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Parse the markdown file
            lines = content.split("\n")
            cache = {}

            for line in lines:
                if "|" in line:
                    parts = line.split("|")
                    if len(parts) >= 2:
                        folder_path = parts[0].strip()
                        try:
                            # Parse the embedding (remove brackets and split)
                            embedding_str = parts[1].strip()
                            if embedding_str.startswith("[") and embedding_str.endswith(
                                "]"
                            ):
                                embedding_str = embedding_str[1:-1]
                            embedding = [
                                float(x.strip()) for x in embedding_str.split(",")
                            ]
                            cache[folder_path] = embedding
                        except Exception as e:
                            if DEBUG:
                                print(
                                    f"[DEBUG] Failed to parse cache entry for {folder_path}: {e}",
                                    file=sys.stderr,
                                )

            if DEBUG:
                print(
                    f"[DEBUG] Loaded {len(cache)} folder embeddings from cache",
                    file=sys.stderr,
                )

            return cache

        except Exception as e:
            print(
                f"[WARNING] Failed to load folder embeddings cache: {e}",
                file=sys.stderr,
            )
            return {}

    def _save_folder_embeddings_cache(self, cache: Dict[str, List[float]]):
        """
        Save folder embeddings to local cache file as markdown.

        Args:
            cache: Dict mapping folder paths to embeddings
        """
        cache_path = self.vault_path / EMBEDDINGS_CACHE_FILE

        try:
            # Create markdown content
            lines = ["# Folder Embeddings Cache", ""]
            lines.append(f"# Generated: {datetime.now().isoformat()}")
            lines.append(f"# Valid for: {CACHE_VALIDITY_DAYS} days")
            lines.append("")
            lines.append("# Format: |folder_path|embedding_vector|")
            lines.append("")

            for folder_path, embedding in cache.items():
                embedding_str = str(embedding)
                lines.append(f"|{folder_path}|{embedding_str}|")

            content = "\n".join(lines)

            # Write to file
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(content)

            if DEBUG:
                print(
                    f"[DEBUG] Saved {len(cache)} folder embeddings to cache",
                    file=sys.stderr,
                )

        except Exception as e:
            print(
                f"[WARNING] Failed to save folder embeddings cache: {e}",
                file=sys.stderr,
            )

    def _is_cache_valid(self) -> bool:
        """
        Check if the local cache is still valid.

        Returns: True if cache exists and is not too old
        """
        cache_path = self.vault_path / EMBEDDINGS_CACHE_FILE

        if not cache_path.exists():
            return False

        try:
            cache_time = datetime.fromtimestamp(cache_path.stat().st_mtime)
            age = datetime.now() - cache_time

            if age > timedelta(days=CACHE_VALIDITY_DAYS):
                print(
                    f"[INFO] Folder embeddings cache is {age.days} days old, refreshing",
                    file=sys.stderr,
                )
                return False

            return True

        except Exception as e:
            print(f"[WARNING] Failed to check cache validity: {e}", file=sys.stderr)
            return False

    def _extract_frontmatter(self, content: str, file_identifier: str = None) -> Dict:
        """Extract YAML frontmatter from note content and make JSON-serializable

        Args:
            content: The note content
            file_identifier: Optional file name/path for logging (helps identify which file has issues)
        """
        try:
            import yaml
            from datetime import datetime
            import re
        except ImportError:
            print(
                "[WARNING] PyYAML not installed, frontmatter extraction disabled",
                file=sys.stderr,
            )
            return {}

        if not content.startswith("---"):
            return {}

        end_marker = content.find("\n---", 4)
        if end_marker == -1:
            return {}

        frontmatter_text = content[4:end_marker]

        def parse_with_fallback(yaml_text: str):
            """Try parsing, with fallback to quote unquoted values on failure"""

            def parse_yaml(text: str):
                try:
                    data = yaml.load(text, Loader=yaml.SafeLoader) or {}
                    return data, None
                except Exception as e:
                    return None, str(e)

            def quote_unquoted_values(text: str) -> str:
                """Quote unquoted scalar values that might contain colons"""
                lines = text.split("\n")
                fixed = []

                for line in lines:
                    stripped = line.strip()

                    # Skip empty lines, comments, list items, and already quoted values
                    if not stripped or stripped.startswith("#"):
                        fixed.append(line)
                        continue
                    if (
                        stripped.startswith('"')
                        or stripped.startswith("'")
                        or stripped.startswith("-")
                        or stripped.startswith("[")
                        or ":" not in stripped
                    ):
                        fixed.append(line)
                        continue

                    # Match key: value pattern and quote value
                    match = re.match(r"^(\s*)(\w+):\s*(.+)$", line)
                    if match:
                        indent, key, value = match.groups()
                        fixed.append(f'{indent}{key}: "{value}"')
                        continue

                    fixed.append(line)

                return "\n".join(fixed)

            data, error = parse_yaml(yaml_text)

            if error and "mapping values are not allowed here" in error:
                file_info = f" [{file_identifier}]" if file_identifier else ""
                print(
                    f"[WARNING] Auto-fixing malformed frontmatter{file_info} (quoting values): {error.split('in')[0]}",
                    file=sys.stderr,
                )

                fixed_text = quote_unquoted_values(yaml_text)
                data, error2 = parse_yaml(fixed_text)

                if error2:
                    print(
                        f"[WARNING] Frontmatter auto-fix failed{file_info}, using empty metadata",
                        file=sys.stderr,
                    )
                    return {}, True  # True = fix attempted but failed

                print(
                    f"[WARNING] Frontmatter was auto-fixed{file_info}. File content needs to be saved to persist the fix.",
                    file=sys.stderr,
                )
                return data, True  # True = fix was applied

            return data, False  # False = no fix needed

        data, was_fixed = parse_with_fallback(frontmatter_text)

        if not data:
            return {}

        def make_json_serializable(obj):
            """Recursively convert Python types to JSON-serializable formats"""
            if isinstance(obj, datetime):
                return obj.isoformat()
            elif isinstance(obj, dict):
                return {k: make_json_serializable(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [make_json_serializable(item) for item in obj]
            else:
                return obj

        return make_json_serializable(data)

    async def remove_orphaned_supabase_entries(self, exclude_ids: Optional[List[int]] = None):
        """
        Verify and update orphaned Supabase entries.
        
        Handles:
        1. Entries with no obsidian_path - delete them
        2. Entries where file was moved - update the obsidian_path
        3. Entries where file was deleted - delete them
        4. Entries where file exists but has mismatched supabase_id - delete them
        
        exclude_ids: List of entry IDs created in current sync cycle (don't delete these)
                  Used to prevent race condition where orphan cleanup deletes
                  entries that were just created in sync_existing_notes_to_supabase()
        """
        exclude_ids = exclude_ids or []
        try:
            # Get all Supabase entries
            all_entries = await self.db_manager.get_all_thoughts()

            if not all_entries:
                print("[SYNC] No Supabase entries to verify", file=sys.stderr)
                return

            # Build a map of supabase_id (from frontmatter) -> note path
            # Also build a reverse map: path -> supabase_id for validation
            supabase_id_to_path = {}
            path_to_supabase_id = {}
            markdown_files = list(self.vault_path.rglob("*.md"))

            for md_file in markdown_files:
                try:
                    content = md_file.read_text(encoding="utf-8")
                    metadata = self._extract_frontmatter(
                        content, str(md_file.relative_to(self.vault_path))
                    )
                    supabase_id = metadata.get("supabase_id")
                    if supabase_id:
                        rel_path = str(md_file.relative_to(self.vault_path))
                        supabase_id_to_path[supabase_id] = rel_path
                        path_to_supabase_id[rel_path] = supabase_id
                except Exception as e:
                    # Skip files that can't be read
                    pass

            orphaned_count = 0
            updated_count = 0

            # Check each entry
            for entry in all_entries:
                thought_id = entry.get("id")
                
                # Skip entries created in current sync cycle
                if thought_id in exclude_ids:
                    continue
                
                obsidian_path = entry.get("obsidian_path", "")

                # Case 1: Entry has empty or missing obsidian_path
                if not obsidian_path:
                    # Check if any note still has this thought_id as its supabase_id
                    if thought_id not in supabase_id_to_path:
                        # Truly orphaned - no note has this ID
                        await self.db_manager.delete_thought_by_id(thought_id)
                        orphaned_count += 1
                        print(
                            f"[SYNC] Removed orphaned entry with empty path (ID: {thought_id})",
                            file=sys.stderr,
                        )
                    continue

                # Case 2: File doesn't exist at stored path
                full_path = self.vault_path / obsidian_path
                if not full_path.exists():
                    # Check if any note still has this thought_id as its supabase_id (note was moved)
                    if thought_id in supabase_id_to_path:
                        # Note exists at different path - update the entry path
                        new_path = supabase_id_to_path[thought_id]
                        await self.db_manager.update_obsidian_path(thought_id, new_path)
                        updated_count += 1
                        print(
                            f"[SYNC] Updated moved note path (ID: {thought_id}): {obsidian_path} -> {new_path}",
                            file=sys.stderr,
                        )
                    else:
                        # No note has this ID - truly orphaned
                        await self.db_manager.delete_thought_by_id(thought_id)
                        orphaned_count += 1
                        print(
                            f"[SYNC] Removed orphaned entry: {obsidian_path} (ID: {thought_id})",
                            file=sys.stderr,
                        )
                else:
                    # Case 3: File exists at stored path - verify supabase_id matches
                    file_supabase_id = path_to_supabase_id.get(obsidian_path)
                    
                    if file_supabase_id is None:
                        # File has no supabase_id - orphaned
                        await self.db_manager.delete_thought_by_id(thought_id)
                        orphaned_count += 1
                        print(
                            f"[SYNC] Removed orphaned entry with no matching file ID: {obsidian_path} (DB ID: {thought_id})",
                            file=sys.stderr,
                        )
                    elif file_supabase_id != thought_id:
                        # File exists but has DIFFERENT supabase_id
                        # This means the file was hijacked by another entry or manually edited
                        await self.db_manager.delete_thought_by_id(thought_id)
                        orphaned_count += 1
                        print(
                            f"[SYNC] Removed orphaned entry with mismatched ID: {obsidian_path} (DB ID: {thought_id}, File ID: {file_supabase_id})",
                            file=sys.stderr,
                        )

            if orphaned_count > 0:
                print(
                    f"[SYNC] Removed {orphaned_count} orphaned Supabase entries",
                    file=sys.stderr,
                )
            if updated_count > 0:
                print(
                    f"[SYNC] Updated {updated_count} moved note paths",
                    file=sys.stderr,
                )
            if orphaned_count == 0 and updated_count == 0:
                print("[SYNC] No orphaned entries found", file=sys.stderr)

        except Exception as e:
            print(
                f"[WARNING] Failed to verify Supabase entries: {e}",
                file=sys.stderr,
            )
            import traceback

            traceback.print_exc()

    async def sync_existing_notes_to_supabase(self):
        """One-time sync of all existing Obsidian notes to Supabase"""
        import hashlib
        import sys
        from embeddings import EmbeddingGenerator
        from metadata import MetadataExtractor
        
        if Config.DEBUG:
            print(f"[SYNC] DEBUG={Config.DEBUG}, will enable debug logging", file=sys.stderr)

        # Note: We don't run orphan cleanup here to avoid race conditions
        # Orphan cleanup is called separately (e.g., on server startup)
        
        # Collect all markdown files in vault
        markdown_files = list(self.vault_path.rglob("*.md"))
        
        synced_count = 0
        skipped_count = 0
        error_count = 0
        created_ids = []
        
        embedding_generator = EmbeddingGenerator()
        metadata_extractor = MetadataExtractor()

        for md_file in markdown_files:
            try:
                rel_path = str(md_file.relative_to(self.vault_path))

                # Skip special files
                if any(
                    skip in rel_path
                    for skip in [".obsidian", "!Folder_Embeddings.md", ".trash"]
                ):
                    skipped_count += 1
                    continue

                # Read and parse note
                content = md_file.read_text(encoding="utf-8")
                file_rel_path = str(md_file.relative_to(self.vault_path))
                if Config.DEBUG:
                    print(f"[SYNC] Processing file: {file_rel_path}", file=sys.stderr)
                
                metadata = self._extract_frontmatter(
                    content, file_rel_path
                )

                # Check if note has a supabase_id in frontmatter
                # If so, verify it still exists in database
                if metadata and metadata.get("supabase_id"):
                    supabase_id = metadata.get("supabase_id")
                    try:
                        # Try to get the entry with this ID
                        existing_entry = await self.db_manager.get_thought(supabase_id)

                        if existing_entry:
                            # Entry still exists and matches frontmatter - skip
                            # If note was moved, orphan cleanup will handle updating the path
                            # If note needs re-syncing (content changed), we'll handle that separately
                            print(
                                f"[SYNC] Note has valid supabase_id {supabase_id}, skipping",
                                file=sys.stderr,
                            )
                            skipped_count += 1
                            continue
                        else:
                            # Entry doesn't exist (was deleted) - proceed with creating new entry
                            print(
                                f"[SYNC] Note has deleted supabase_id {supabase_id}, re-syncing...",
                                file=sys.stderr,
                            )
                    except Exception as e:
                        # Error checking entry - proceed with creating new entry
                        print(
                            f"[SYNC] Error checking supabase_id {supabase_id}: {e}, re-syncing...",
                            file=sys.stderr,
                        )
                
                # Check if already in Supabase by path (but no frontmatter)
                # This handles case where DB entry exists but file doesn't have frontmatter
                if self.db_manager:
                    existing = await self.db_manager.get_thought_by_obsidian_path(
                        rel_path
                    )
                    if existing and existing.get("id"):
                        # Entry exists but file doesn't have frontmatter
                        # Update frontmatter with existing database ID
                        print(
                            f"[SYNC] Found DB entry (ID: {existing.get('id')}) but no frontmatter, updating...",
                            file=sys.stderr,
                        )
                        self._update_frontmatter(md_file, existing.get("id"))
                        skipped_count += 1
                        continue

                # Extract metadata if needed
                if not metadata or not metadata.get("topics"):
                    metadata = await metadata_extractor.extract_metadata(
                        content, metadata.get("title", "")
                    )

                # Generate embedding
                embedding = await embedding_generator.create_embedding(content)

                # Compute hash
                file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

                # Store in Supabase
                if self.db_manager:
                    if Config.DEBUG:
                        print(f"[SYNC] db_manager is set: True", file=sys.stderr)
                        print(f"[SYNC] Storing with obsidian_path={rel_path}", file=sys.stderr)
                    
                    # Transform metadata to database format
                    # This handles: 'type' → 'thought_type', extra fields → metadata JSONB
                    transformed_metadata = transform_metadata_for_database(metadata)
                    
                    # Add required fields for sync operations
                    store_metadata = {
                        **transformed_metadata,
                        "obsidian_path": rel_path,
                        "file_hash": file_hash,
                        "source": "obsidian_import",
                    }
                    if Config.DEBUG:
                        print(f"[SYNC] store_metadata={store_metadata}", file=sys.stderr)
                    supabase_id = await self.db_manager.store_thought(
                        content,
                        embedding,
                        store_metadata,
                    )
                    if Config.DEBUG:
                        print(f"[SYNC] Stored with supabase_id={supabase_id}", file=sys.stderr)
                    
                    # Update frontmatter with supabase_id
                    self._update_frontmatter(md_file, supabase_id)
                else:
                    if Config.DEBUG:
                        print(f"[SYNC] db_manager is NOT set, skipping store", file=sys.stderr)
                    
                    # Verify path was set (should be in metadata above, but ensure it's in DB)
                    await self.db_manager.update_obsidian_path(supabase_id, rel_path)
                    
                    # Track created entry IDs for orphan cleanup exclusion
                    created_ids.append(supabase_id)
                    
                    synced_count += 1

                    if synced_count % 10 == 0:
                        print(
                            f"[SYNC] Progress: {synced_count} synced, {skipped_count} skipped",
                            file=sys.stderr,
                        )

            except Exception as e:
                error_count += 1
                print(f"[ERROR] Failed to sync {md_file}: {e}", file=sys.stderr)

        await embedding_generator.close()

        print(
            f"[SYNC] Initial sync complete: {synced_count} synced, {skipped_count} skipped, {error_count} errors",
            file=sys.stderr,
        )
        
        return {"created": synced_count, "ids": created_ids}
    
    def get_last_sync_result(self):
        """Get the result from the last sync operation
        
        Returns: Dict with 'created' (count) and 'ids' (list of entry IDs)
        """
        return self._last_sync_result

    async def sync_changed_notes_to_supabase(self):
        """Sync notes that have changed since last sync (hash-based comparison)

        Used during lock takeover to catch changes made during sync gap period.
        Compares file_hash with database to detect changes efficiently.
        """
        import hashlib
        import sys
        from embeddings import EmbeddingGenerator
        from metadata import MetadataExtractor

        markdown_files = list(self.vault_path.rglob("*.md"))
        print(
            f"[SYNC] Scanning {len(markdown_files)} files for changes...",
            file=sys.stderr,
        )

        synced_count = 0
        skipped_count = 0
        error_count = 0

        embedding_generator = EmbeddingGenerator()
        metadata_extractor = MetadataExtractor()

        for md_file in markdown_files:
            try:
                rel_path = str(md_file.relative_to(self.vault_path))

                # Skip special files
                if any(
                    skip in rel_path
                    for skip in [".obsidian", "!Folder_Embeddings.md", ".trash"]
                ):
                    skipped_count += 1
                    continue

                # Read file
                content = md_file.read_text(encoding="utf-8")
                file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

                # Check if in database
                if self.db_manager:
                    existing = await self.db_manager.get_thought_by_obsidian_path(
                        rel_path
                    )

                    if not existing:
                        # New file - sync it
                        metadata = self._extract_frontmatter(
                            content, str(md_file.relative_to(self.vault_path))
                        )
                        if not metadata or not metadata.get("topics"):
                            metadata = await metadata_extractor.extract_metadata(
                                content, metadata.get("title", "")
                            )

                        embedding = await embedding_generator.create_embedding(content)
                        
                        # Transform metadata to database format
                        # This handles: 'type' → 'thought_type', extra fields → metadata JSONB
                        transformed_metadata = transform_metadata_for_database(metadata)
                        
                        # Add required fields for sync operations
                        store_metadata = {
                            **transformed_metadata,
                            "obsidian_path": rel_path,
                            "file_hash": file_hash,
                            "source": "obsidian_sync_takeover",
                        }

                        supabase_id = await self.db_manager.store_thought(
                            content,
                            embedding,
                            store_metadata,
                        )
                        self._update_frontmatter(md_file, supabase_id)

                        synced_count += 1

                    elif existing.get("file_hash") != file_hash:
                        # File changed - update it
                        metadata = self._extract_frontmatter(
                            content, str(md_file.relative_to(self.vault_path))
                        )
                        if not metadata or not metadata.get("topics"):
                            metadata = await metadata_extractor.extract_metadata(
                                content, metadata.get("title", "")
                            )

                        embedding = await embedding_generator.create_embedding(content)
                        await self.db_manager.update_thought(
                            existing["id"], content, embedding, file_hash, metadata
                        )

                        synced_count += 1
                    else:
                        # Unchanged - skip
                        skipped_count += 1

            except Exception as e:
                error_count += 1
                print(f"[ERROR] Failed to sync {md_file}: {e}", file=sys.stderr)

        await embedding_generator.close()

        print(
            f"[SYNC] Change sync complete: {synced_count} changed, {skipped_count} skipped, {error_count} errors",
            file=sys.stderr,
        )

    def _update_frontmatter(self, file_path: Path, supabase_id: int):
        """Update note's frontmatter with supabase_id (always updates existing value)"""
        try:
            import yaml
        except ImportError:
            print(
                "[WARNING] PyYAML not installed, cannot update frontmatter",
                file=sys.stderr,
            )
            return
        
        try:
            content = file_path.read_text(encoding="utf-8")
            lines = content.split("\n")
            
            if not lines or lines[0].strip() != "---":
                # No frontmatter, add it
                frontmatter_block = f"---\nsupabase_id: {supabase_id}\n---\n\n"
                new_content = frontmatter_block + content
                file_path.write_text(new_content, encoding="utf-8")
                return
            
            # Find the CLOSING --- of the frontmatter block (not the first occurrence)
            # Use depth counting to handle files with --- in their content (copilot case)
            frontmatter_end_idx = -1
            depth = 0
            for i in range(1, len(lines)):
                if "---" in lines[i]:
                    depth += 1
                    if depth == 2:
                        frontmatter_end_idx = i
                        break
            
            if frontmatter_end_idx == -1:
                # Malformed frontmatter (no closing ---), just append
                frontmatter = f"---\n{lines[0]}\n---\n"
                new_content = frontmatter + content
                file_path.write_text(new_content, encoding="utf-8")
                return
            
            # Extract frontmatter lines (between first --- and closing ---)
            frontmatter_lines = lines[1:frontmatter_end_idx]
            frontmatter_str = "\n".join(frontmatter_lines)
            
            # Parse existing frontmatter as YAML
            try:
                frontmatter_dict = yaml.safe_load(frontmatter_str) or {}
            except yaml.YAMLError as e:
                print(f"[WARNING] Failed to parse frontmatter as YAML: {e}", file=sys.stderr)
                frontmatter_dict = {}
            
            # Update or add supabase_id
            frontmatter_dict["supabase_id"] = supabase_id
            
            # Convert back to YAML string (preserving formatting)
            try:
                updated_frontmatter = yaml.dump(frontmatter_dict, default_flow_style=False, sort_keys=False, allow_unicode=True).rstrip()
            except yaml.YAMLError as e:
                print(f"[WARNING] Failed to convert frontmatter to YAML: {e}", file=sys.stderr)
                return
            
            # Rebuild complete content: opening --- + updated frontmatter + closing --- + rest of file
            content_after_frontmatter = lines[frontmatter_end_idx + 1:]
            new_content = f"---\n{updated_frontmatter}---\n\n" + "\n".join(content_after_frontmatter)
            
            file_path.write_text(new_content, encoding="utf-8")
        except Exception as e:
            print(f"[ERROR] Failed to update frontmatter: {e}", file=sys.stderr)
