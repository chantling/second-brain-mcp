import os
import json
from typing import Dict, List
from datetime import datetime
from config import Config

# Debug flag - set to True to enable debug output
DEBUG = False

class MetadataExtractor:
    """Metadata extractor using flexible AI provider (any OpenAI-compatible API)"""
    
    def __init__(self):
        """Initialize metadata extractor"""
        self.api_key = Config.METADATA_API_KEY
        self.base_url = Config.METADATA_BASE_URL
        self.model = Config.METADATA_MODEL
        
        # Import OpenAI SDK here to avoid issues if not installed
        try:
            from openai import OpenAI
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=150,  # Increased from 90 to 150 seconds for API reliability
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
            
            # Debug logging
            if DEBUG:
                print(f"[DEBUG] metadata.py - Title being set: '{title}'", file=sys.stderr)
                print(f"[DEBUG] metadata.py - Metadata after title set: {metadata}", file=sys.stderr)
                print(f"[DEBUG] metadata.py - 'title' in metadata: {'title' in metadata}", file=sys.stderr)
                print(f"[DEBUG] metadata.py - Title value after set: {metadata.get('title')}", file=sys.stderr)
                print(f"[DEBUG] extract_metadata - Content length: {len(content)}", file=sys.stderr)
            
            return metadata
            
        except Exception as e:
            # Fallback if JSON parsing fails or API error occurs
            print(f"[WARNING] Metadata extraction failed: {e}, using fallback", file=sys.stderr)
            if DEBUG:
                print(f"[DEBUG] extract_metadata - Fallback title param: '{title}'", file=sys.stderr)
            return {
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
    
    async def close(self):
        """Close the OpenAI client"""
        if hasattr(self, 'client'):
            # OpenAI SDK handles connection pooling automatically
            # No explicit close needed for sync client
            pass