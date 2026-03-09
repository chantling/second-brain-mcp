import os
import json
import sys
from typing import Dict, List
from datetime import datetime
from config import Config

# Debug flag - set to True to enable debug output
DEBUG = False

class MetadataExtractor:
    """Metadata extractor using flexible AI provider (any OpenAI-compatible API)"""
    
    def __init__(self):
        """Initialize metadata extractor with OpenAI-compatible API client.
        
        Loads API key, base URL, and model name from Config. Creates an
        OpenAI client instance with 240 second timeout and 3 retries for
        reliability when calling AI services for metadata extraction.
        """
        self.api_key = Config.METADATA_API_KEY
        self.base_url = Config.METADATA_BASE_URL
        self.model = Config.METADATA_MODEL
        
        # Import OpenAI SDK here to avoid issues if not installed
        try:
            from openai import OpenAI
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=240,  # Increased from 150 to 240 seconds for API reliability
                max_retries=3
            )
        except ImportError:
            raise ImportError(
                "OpenAI SDK is required for metadata extraction. "
                "Install it with: pip install openai>=1.0"
            )
    
    async def extract_metadata(self, content: str, title: str = "") -> Dict:
        """Extract structured metadata from content using z.ai's GLM-4.7"""
        # Limit content length for cost efficiency
        max_length = 4000
        if len(content) > max_length:
            content = content[:max_length]
        
        # Extract video_id and url from frontmatter or content BEFORE calling AI
        # This ensures these critical fields are preserved for duplicate detection
        video_id = self._extract_video_id(content)
        url = self._extract_url(content)
        
        prompt = f"""
        Analyze this content and extract structured metadata:
        
        Title: {title}
        Content: {content}
        
        Return JSON with these fields:
        - type: 'knowledge', 'todo', 'recipe', 'guide', 'contact', 'note', or 'other'
        - topics: array of 3-5 relevant topics/tags
        - people: array of people mentioned (if any)
        - action_items: array of actionable items (if any)
        - summary: 2-3 sentence summary
        - difficulty: 'beginner', 'intermediate', 'advanced', or 'not_applicable'
        - estimated_time: estimated time to read/complete (in minutes, or 'not_applicable')
        
        Be concise and specific with topics. For example:
        - Instead of 'technology', use 'artificial intelligence' or 'web development'
        - Instead of 'health', use 'nutrition' or 'exercise'
        """
        
        try:
            # Use OpenAI SDK with z.ai endpoint
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system", 
                        "content": "You are a metadata extraction expert. Return only valid JSON."
                    },
                    {
                        "role": "user", 
                        "content": prompt
                    }
                ],
                temperature=0.1,
                max_tokens=1000,
                extra_body={
                    "thinking": {
                        "type": "disabled"
                    }
                }
            )
            
            # Extract content from response
            metadata_text = response.choices[0].message.content.strip()
            
            # Handle markdown code blocks (```json ... ```)
            if metadata_text.startswith('```'):
                lines = metadata_text.split('\n')
                content_lines = []
                in_code_block = False
                for line in lines:
                    if line.strip().startswith('```'):
                        in_code_block = not in_code_block
                        continue
                    if in_code_block:
                        content_lines.append(line)
                metadata_text = '\n'.join(content_lines).strip()
            
            # Parse JSON response
            metadata = json.loads(metadata_text)
            if DEBUG:
                print(f"[DEBUG] metadata.py - Parsed metadata from AI: {metadata}", file=sys.stderr)
            
            # Add additional processing
            metadata["title"] = title or self._generate_title(content)
            metadata["created_at"] = datetime.now().isoformat()
            
            # IMPORTANT: Preserve video_id and url for duplicate detection
            if video_id:
                metadata["video_id"] = video_id
                if DEBUG:
                    print(f"[DEBUG] metadata.py - Added video_id: {video_id}", file=sys.stderr)
            if url:
                metadata["url"] = url
                if DEBUG:
                    print(f"[DEBUG] metadata.py - Added url: {url}", file=sys.stderr)
            
            if DEBUG:
                print(f"[DEBUG] metadata.py - Final metadata before return has video_id: {'video_id' in metadata}, url: {'url' in metadata}", file=sys.stderr)
                print(f"[DEBUG] metadata.py - Returning metadata with keys: {list(metadata.keys())}", file=sys.stderr)
            
            # Debug logging
            if DEBUG:
                print(f"[DEBUG] metadata.py - Title being set: '{title}'", file=sys.stderr)
                print(f"[DEBUG] metadata.py - Metadata after title set: {metadata}", file=sys.stderr)
                print(f"[DEBUG] metadata.py - 'title' in metadata: {'title' in metadata}", file=sys.stderr)
                print(f"[DEBUG] metadata.py - Title value after set: {metadata.get('title')}", file=sys.stderr)
                print(f"[DEBUG] extract_metadata - Content length: {len(content)}", file=sys.stderr)
                print(f"[DEBUG] extract_metadata - video_id extracted: {video_id}", file=sys.stderr)
                print(f"[DEBUG] extract_metadata - url extracted: {url}", file=sys.stderr)
            
            return metadata
            
        except Exception as e:
            # Fallback if JSON parsing fails or API error occurs
            print(f"[WARNING] Metadata extraction failed: {e}, using fallback", file=sys.stderr)
            if DEBUG:
                print(f"[DEBUG] extract_metadata - Fallback title param: '{title}'", file=sys.stderr)
            fallback = {
                "type": "note",
                "topics": ["general"],
                "people": [],
                "action_items": [],
                "summary": "Content processed",
                "difficulty": "not_applicable",
                "estimated_time": "not_applicable",
                "title": title or "Untitled",
                "created_at": datetime.now().isoformat()
            }
            # Add video_id and url if present
            if video_id:
                fallback["video_id"] = video_id
            if url:
                fallback["url"] = url
            return fallback
    
    def _generate_title(self, content: str) -> str:
        """Generate a title from content if none provided"""
        # First, try to find markdown headers (h1, h2, h3)
        import re
        
        # Look for h1 (# Header) or h2 (## Header) headers
        header_pattern = r'^(#{1,3})\s+(.+)$'
        lines = content.split('\n')
        
        for line in lines:
            line = line.strip()
            match = re.match(header_pattern, line)
            if match:
                title = match.group(2).strip()
                # Remove any extra # symbols or formatting
                title = re.sub(r'\s*#+$', '', title)
                if title and len(title) > 3:
                    return title[:50]  # Limit to 50 chars
        
        # Fallback: first sentence or first 10 words
        first_sentence = content.split('.')[0].strip()
        if len(first_sentence) > 50:
            return first_sentence[:50] + "..."
        return first_sentence or "Untitled Note"
    
    def _extract_video_id(self, content: str) -> str:
        """Extract video_id from frontmatter or content"""
        import re
        
        # Check frontmatter first
        if content.startswith("---"):
            frontmatter_end = content.find("\n---", 3)
            if frontmatter_end != -1:
                frontmatter = content[3:frontmatter_end]
                # Look for video_id in frontmatter
                match = re.search(r'video_id:\s*["\']?([a-zA-Z0-9_-]+)["\']?', frontmatter)
                if match:
                    return match.group(1)
        
        # Check for YouTube video ID patterns in content
        # YouTube URL patterns: youtube.com/watch?v=xxxxx or youtu.be/xxxxx
        match = re.search(r'(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]+)', content)
        if match:
            return match.group(1)
        
        return None
    
    def _extract_url(self, content: str) -> str:
        """Extract URL from frontmatter or content"""
        import re
        
        # Check frontmatter first
        if content.startswith("---"):
            frontmatter_end = content.find("\n---", 3)
            if frontmatter_end != -1:
                frontmatter = content[3:frontmatter_end]
                # Look for url in frontmatter
                match = re.search(r'url:\s*["\']?([^\s"\'\n]+)["\']?', frontmatter)
                if match:
                    return match.group(1)
        
        # Check for URLs in content (common patterns)
        match = re.search(r'https?://[^\s\)\]\}]+', content)
        if match:
            return match.group(0)
        
        return None
    
    async def close(self):
        """Close the OpenAI client"""
        if hasattr(self, 'client'):
            # OpenAI SDK handles connection pooling automatically
            # No explicit close needed for sync client
            pass