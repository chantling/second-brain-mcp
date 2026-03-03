import os
import sys
import uuid
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# Debug flag - set to True to enable debug output
DEBUG = True

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
    
    def ensure_special_folders_exist(self):
        """Ensure special folders exist (To-Do, Contacts, Resources/Recipes, ToSort)"""
        special_folders = [
            "-To-Do-",
            "Contacts",
            "Resources/Recipes",
            "-To-Sort-"
        ]
        
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
                if not dir_name.startswith('.') and dir_name != '.obsidian':
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
        generic_titles = ['untitled', 'untitled note', 'note']
        is_generic = (len(sanitized_title) < 3 or 
                      sanitized_title.lower() in generic_titles or
                      sanitized_title.isdigit())
        
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
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"{frontmatter}\n\n{content}")
        
        result = {
            "path": str(filepath.relative_to(self.vault_path))
        }
        
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
    
    def _find_semantic_match(self, content: str, topics: List[str]) -> Tuple[str, float]:
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
                1 for keyword in keywords
                if keyword.lower() in content_lower
            )
            
            if keyword_matches >= 2:
                confidence = max(confidence, 0.75)
            elif keyword_matches >= 1:
                confidence = max(confidence, 0.65)
            
            # Extra confidence for numbered folders matching content context
            if folder.name.startswith(('1', '2', '3')):
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
            "recipe": ["cooking", "food", "meal", "ingredient", "baking"]
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
        if folder_name.startswith('1'):
            project_keywords = ['project', 'working on', 'deadline', 'complete', 'finish',
                           'in progress', 'task', 'milestone', 'deliverable']
            return any(kw in content for kw in project_keywords)
        
        # Areas (2xx) - regular activities
        elif folder_name.startswith('2'):
            area_keywords = ['regularly', 'maintain', 'daily', 'weekly', 'monthly',
                          'ongoing', 'routine', 'check', 'monitor', 'manage']
            return any(kw in content for kw in area_keywords)
        
        # Resources (3xx) - reference information
        elif folder_name.startswith('3'):
            resource_keywords = ['reference', 'information', 'learn', 'guide', 'tutorial',
                             'documentation', 'manual', 'study', 'note', 'how to']
            return any(kw in content for kw in resource_keywords)
        
        return False
    
    def _ensure_folder_exists(self, folder_path: str):
        """Create folder path if it doesn't exist"""
        full_path = self.vault_path / folder_path
        full_path.mkdir(parents=True, exist_ok=True)
    
    def _create_frontmatter(self, metadata: Dict, confidence: float) -> str:
        """Create YAML frontmatter for note"""
        frontmatter = {
            "id": metadata.get("id", str(uuid.uuid4())),
            "type": metadata.get("type", "knowledge"),
            "topics": metadata.get("topics", []),
            "people": metadata.get("people", []),
            "created": datetime.now().isoformat(),
            "source": metadata.get("source", "manual"),
            "supabase_id": metadata.get("supabase_id", ""),
            "folder_confidence": round(confidence, 2)
        }
        
        yaml = "---\n"
        for key, value in frontmatter.items():
            if isinstance(value, list):
                if value:
                    yaml += f"{key}: {value}\n"
            elif value:
                yaml += f"{key}: {value}\n"
        yaml += "---"
        
        return yaml
    
    def _sanitize_filename(self, filename: str) -> str:
        """Remove invalid characters from filename"""
        # Remove characters that are invalid in filenames
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '')
        
        # Replace multiple spaces with single space
        filename = ' '.join(filename.split())
        
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
            "other": []
        }
        
        for folder in self.all_folders:
            rel_path = folder.relative_to(self.vault_path)
            parts = list(rel_path.parts)
            
            # Top-level folders
            if len(parts) == 1:
                stats["top_level"].append(parts[0])
            
            # Categorize by Luca Decimal conventions
            folder_name = folder.name.lower()
            if folder_name.startswith('1'):
                stats["projects"].append(str(rel_path))
            elif folder_name.startswith('2'):
                stats["areas"].append(str(rel_path))
            elif folder_name.startswith('3'):
                stats["resources"].append(str(rel_path))
            elif folder_name.startswith('4'):
                stats["archive"].append(str(rel_path))
            else:
                stats["other"].append(str(rel_path))
        
        return stats
    
    async def sync_folders_to_database(self) -> Dict:
        """
        Sync all folders to database with embeddings.
        This should be called on server startup.
        Also saves folder embeddings to local cache.
        
        Returns: Sync statistics
        """
        if not self.db_manager:
            print("[WARNING] No database manager provided, skipping folder sync", file=sys.stderr)
            return {"total": 0, "created": 0, "updated": 0, "errors": ["No database manager"]}
        
        folders_data = []
        
        # Skip special folders
        skip_folders = ["-To-Do-", "Contacts", "-To-Sort-", ".obsidian", ".ClineData"]
        
        for folder in self.all_folders:
            try:
                rel_path = folder.relative_to(self.vault_path)
                path_str = str(rel_path)
                
                # Skip special folders
                if any(skip in path_str for skip in skip_folders):
                    continue
                
                # Generate folder info
                folder_info = {
                    "path": path_str,
                    "folder_name": folder.name,
                    "hierarchy": list(rel_path.parts),
                    "description": self._generate_folder_description(folder)
                }
                
                folders_data.append(folder_info)
                
            except Exception as e:
                print(f"[WARNING] Failed to process folder {folder}: {e}", file=sys.stderr)
        
        # Sync to database
        if folders_data:
            print(f"[INFO] Syncing {len(folders_data)} folders to database...", file=sys.stderr)
            stats = await self.db_manager.sync_folders(folders_data)
            print(f"[INFO] Folder sync complete: {stats['created']} created, {stats['updated']} updated", file=sys.stderr)
            if stats['errors']:
                print(f"[WARNING] Errors during sync: {len(stats['errors'])}", file=sys.stderr)
            
            # Save embeddings to local cache
            print("[INFO] Saving folder embeddings to local cache...", file=sys.stderr)
            folder_cache = {}
            for folder_data in folders_data:
                path = folder_data["path"]
                # Fetch embedding from database
                try:
                    response = self.db_manager.client.table("folders").select(
                        "path, embedding"
                    ).eq("path", path).execute()
                    
                    if response.data and response.data[0].get('embedding'):
                        embedding = response.data[0]['embedding']
                        if isinstance(embedding, str):
                            import ast
                            embedding = ast.literal_eval(embedding)
                        folder_cache[path] = embedding
                except Exception as e:
                    if DEBUG:
                        print(f"[DEBUG] Failed to fetch embedding for {path}: {e}", file=sys.stderr)
            
            self._save_folder_embeddings_cache(folder_cache)
            print(f"[INFO] Saved {len(folder_cache)} folder embeddings to local cache", file=sys.stderr)
            
            self._folders_synced = True
            return stats
        else:
            print("[INFO] No folders to sync", file=sys.stderr)
            return {"total": 0, "created": 0, "updated": 0, "errors": []}
    
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
                    with open(note, 'r', encoding='utf-8') as f:
                        content = f.read(800)  # First 800 chars
                        
                        # Remove YAML frontmatter if present
                        if content.startswith('---'):
                            end_marker = content.find('\n---', 4)
                            if end_marker != -1:
                                content = content[end_marker+4:]
                        
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
    
    async def _find_semantic_folder_match(self, content: str, metadata: Dict) -> Tuple[str, float]:
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
            from embeddings import EmbeddingManager
            embedding_manager = EmbeddingManager()
            
            # Create embedding for the note content
            note_embedding = await embedding_manager.create_embedding(content)
            
            # Start hierarchical search from top level
            current_folder = None
            current_level = 0
            overall_confidence = 1.0
            
            if DEBUG:
                print(f"[DEBUG] Starting hierarchical folder search for content length: {len(content)}", file=sys.stderr)
            
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
                    child_folders = [f for f in level_folders 
                                 if f.startswith(current_folder + "/")]
                    search_folders = child_folders
                    
                    if DEBUG:
                        print(f"[DEBUG] Level {current_level}: Found {len(child_folders)} subfolders under {current_folder}", file=sys.stderr)
                else:
                    # Top level - use all folders
                    search_folders = [f for f in level_folders if "/" not in f]
                    
                    if DEBUG:
                        print(f"[DEBUG] Level {current_level}: Searching {len(search_folders)} top-level folders", file=sys.stderr)
                
                # If no subfolders found, we've reached a leaf
                if not search_folders:
                    break
                
                # Find best match at this level
                best_folder_at_level, confidence = await self._find_best_match_at_level(
                    note_embedding, 
                    search_folders, 
                    folder_cache,
                    embedding_manager
                )
                
                if DEBUG:
                    print(f"[DEBUG] Level {current_level}: Best match = {best_folder_at_level} (confidence: {confidence:.4f})", file=sys.stderr)
                
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
                    print("[WARNING] Reached maximum folder depth, stopping", file=sys.stderr)
                    break
            
            await embedding_manager.close()
            
            # Return the final folder found
            if current_folder:
                # Calculate overall confidence (product of all level confidences)
                final_confidence = max(0.0, min(1.0, overall_confidence))
                
                if DEBUG:
                    print(f"[DEBUG] Final folder: {current_folder} (overall confidence: {final_confidence:.4f})", file=sys.stderr)
                
                return (current_folder, final_confidence)
            else:
                # Fallback to local matching
                return self._find_semantic_match(content, metadata.get("topics", []))
            
        except Exception as e:
            print(f"[WARNING] Hierarchical semantic folder search failed: {e}", file=sys.stderr)
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
            parts = rel_path.split('/')
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
        embedding_manager
    ) -> Tuple[str, float]:
        """
        Find the best matching folder at a specific level.
        
        Args:
            note_embedding: Embedding vector for the note
            folder_paths: List of folder paths at this level
            folder_cache: Cached embeddings dict {path: embedding}
            embedding_manager: EmbeddingManager instance for generating new embeddings
        
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
                    print(f"[DEBUG] Using cached embedding for {folder_path}", file=sys.stderr)
            
            # If not in cache or cache needs refresh, fetch from database
            if folder_embedding is None and self.db_manager and self._folders_synced:
                try:
                    # Fetch folder from database
                    response = self.db_manager.client.table("folders").select(
                        "path, embedding"
                    ).eq("path", folder_path).execute()
                    
                    if response.data and response.data[0].get('embedding'):
                        embedding_data = response.data[0]['embedding']
                        if isinstance(embedding_data, str):
                            import ast
                            embedding_data = ast.literal_eval(embedding_data)
                        folder_embedding = embedding_data
                        
                        # Update cache
                        folder_cache[folder_path] = folder_embedding
                        self._save_folder_embeddings_cache(folder_cache)
                        
                        if DEBUG:
                            print(f"[DEBUG] Fetched and cached embedding for {folder_path}", file=sys.stderr)
                except Exception as e:
                    if DEBUG:
                        print(f"[DEBUG] Failed to fetch embedding for {folder_path}: {e}", file=sys.stderr)
            
            # If still no embedding, skip this folder
            if folder_embedding is None:
                if DEBUG:
                    print(f"[DEBUG] No embedding available for {folder_path}, skipping", file=sys.stderr)
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
            with open(cache_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Parse the markdown file
            lines = content.split('\n')
            cache = {}
            
            for line in lines:
                if '|' in line:
                    parts = line.split('|')
                    if len(parts) >= 2:
                        folder_path = parts[0].strip()
                        try:
                            # Parse the embedding (remove brackets and split)
                            embedding_str = parts[1].strip()
                            if embedding_str.startswith('[') and embedding_str.endswith(']'):
                                embedding_str = embedding_str[1:-1]
                            embedding = [float(x.strip()) for x in embedding_str.split(',')]
                            cache[folder_path] = embedding
                        except Exception as e:
                            if DEBUG:
                                print(f"[DEBUG] Failed to parse cache entry for {folder_path}: {e}", file=sys.stderr)
            
            if DEBUG:
                print(f"[DEBUG] Loaded {len(cache)} folder embeddings from cache", file=sys.stderr)
            
            return cache
            
        except Exception as e:
            print(f"[WARNING] Failed to load folder embeddings cache: {e}", file=sys.stderr)
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
            
            content = '\n'.join(lines)
            
            # Write to file
            with open(cache_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            if DEBUG:
                print(f"[DEBUG] Saved {len(cache)} folder embeddings to cache", file=sys.stderr)
            
        except Exception as e:
            print(f"[WARNING] Failed to save folder embeddings cache: {e}", file=sys.stderr)
    
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
                print(f"[INFO] Folder embeddings cache is {age.days} days old, refreshing", file=sys.stderr)
                return False
            
            return True
            
        except Exception as e:
            print(f"[WARNING] Failed to check cache validity: {e}", file=sys.stderr)
            return False
