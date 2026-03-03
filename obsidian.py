import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional

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
    
    def create_note(self, content: str, metadata: Dict) -> str:
        """
        Create a new note in Obsidian with intelligent folder selection.
        
        Returns: Relative path to created note
        """
        # Determine folder with confidence score
        folder_path, confidence = self._determine_folder(content, metadata)
        
        # Ensure folder exists
        self._ensure_folder_exists(folder_path)
        
        # Generate filename
        title = metadata.get("title", "Untitled")
        filename = f"{datetime.now().strftime('%Y-%m-%d')}-{self._sanitize_filename(title)}.md"
        filepath = self.vault_path / folder_path / filename
        
        # Create frontmatter
        frontmatter = self._create_frontmatter(metadata, confidence)
        
        # Write file
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"{frontmatter}\n\n{content}")
        
        return str(filepath.relative_to(self.vault_path))
    
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
        Sync all folders to the database with embeddings.
        This should be called on server startup.
        
        Returns: Sync statistics
        """
        if not self.db_manager:
            print("[WARNING] No database manager provided, skipping folder sync")
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
                print(f"[WARNING] Failed to process folder {folder}: {e}")
        
        # Sync to database
        if folders_data:
            print(f"[INFO] Syncing {len(folders_data)} folders to database...")
            stats = await self.db_manager.sync_folders(folders_data)
            print(f"[INFO] Folder sync complete: {stats['created']} created, {stats['updated']} updated")
            if stats['errors']:
                print(f"[WARNING] Errors during sync: {len(stats['errors'])}")
            self._folders_synced = True
            return stats
        else:
            print("[INFO] No folders to sync")
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
        Find the best folder using semantic search with embeddings.
        This is a synchronous wrapper that returns a cached result or default.
        
        Returns: (folder_path, confidence_score)
        """
        if not self.db_manager or not self._folders_synced:
            # Fallback to local matching if database not available
            return self._find_semantic_match(content, metadata.get("topics", []))
        
        try:
            # Import here to avoid circular dependency
            from embeddings import EmbeddingManager
            embedding_manager = EmbeddingManager()
            
            # Create embedding for the note content
            note_embedding = await embedding_manager.create_embedding(content)
            
            # Search for similar folders
            similar_folders = await self.db_manager.search_folders_by_embedding(
                note_embedding, 
                limit=3
            )
            
            await embedding_manager.close()
            
            if similar_folders and len(similar_folders) > 0:
                best_folder = similar_folders[0]
                similarity = best_folder.get('similarity', 0.0)
                
                # Convert similarity to confidence (lower distance = higher confidence)
                # Cosine distance: 0 = identical, 2 = opposite
                # We'll convert: confidence = 1.0 - (similarity / 2)
                confidence = max(0.0, min(1.0, 1.0 - (similarity / 2)))
                
                # Only use if confidence is above threshold
                if confidence >= 0.6:
                    return (best_folder['path'], confidence)
            
            # If no good match found, fallback to local matching
            return self._find_semantic_match(content, metadata.get("topics", []))
            
        except Exception as e:
            print(f"[WARNING] Semantic folder search failed: {e}")
            # Fallback to local matching
            return self._find_semantic_match(content, metadata.get("topics", []))
