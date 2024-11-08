from typing import List, AsyncGenerator, Optional
import re
from ..utils.errors import ChunkingError

class ResponseChunker:
    """Handles chunking of long responses with markdown preservation."""
    
    # Default chunk size matches Discord's limit with safety margin
    DEFAULT_CHUNK_SIZE = 1900
    
    def __init__(self, max_chunk_size: int = DEFAULT_CHUNK_SIZE):
        """Initialize the chunker.
        
        Args:
            max_chunk_size: Maximum size of each chunk
        """
        if max_chunk_size <= 0:
            raise ValueError("Chunk size must be positive")
        self.max_chunk_size = max_chunk_size
        
        # Regex patterns for markdown elements
        self._code_block_pattern = re.compile(r'```[\s\S]*?```')
        self._inline_code_pattern = re.compile(r'`[^`]+`')
        self._list_pattern = re.compile(r'^\s*[-*+]\s')
        self._numbered_list_pattern = re.compile(r'^\s*\d+\.\s')
        
    async def chunk_response(self, content: str) -> AsyncGenerator[str, None]:
        """Split response into chunks while preserving markdown and structure.
        
        Args:
            content: The content to chunk
            
        Yields:
            Chunks of the content with preserved formatting
            
        Raises:
            ChunkingError: If chunking fails
        """
        try:
            chunks = self._split_content(content)
            
            for chunk in chunks:
                # Ensure chunk is properly formatted
                chunk = self._sanitize_chunk(chunk)
                yield chunk
                
        except Exception as e:
            raise ChunkingError(f"Failed to chunk response: {str(e)}")
            
    def _split_content(self, content: str) -> List[str]:
        """Split content into chunks while preserving markdown structure."""
        chunks = []
        current_chunk = ""
        in_code_block = False
        code_block_language = ""
        
        # Split by lines while tracking context
        lines = content.split('\n')
        
        for line in lines:
            # Check for code block markers
            if line.startswith('```'):
                in_code_block = not in_code_block
                if in_code_block:
                    code_block_language = line[3:].strip()
                    
            # Calculate new chunk size with line
            new_size = len(current_chunk) + len(line) + 1
            
            if new_size > self.max_chunk_size:
                # Handle code block splitting
                if in_code_block:
                    current_chunk += '\n```'
                    chunks.append(current_chunk)
                    current_chunk = f'```{code_block_language}\n{line}'
                    
                # Handle list continuation
                elif self._is_list_item(line):
                    chunks.append(current_chunk)
                    current_chunk = line
                    
                # Normal splitting
                else:
                    chunks.append(current_chunk)
                    current_chunk = line
            else:
                if current_chunk:
                    current_chunk += '\n'
                current_chunk += line
                
        # Add remaining content
        if current_chunk:
            chunks.append(current_chunk)
            
        return chunks
    
    def _is_list_item(self, line: str) -> bool:
        """Check if line is a list item."""
        return bool(self._list_pattern.match(line) or 
                   self._numbered_list_pattern.match(line))
    
    def _sanitize_chunk(self, chunk: str) -> str:
        """Ensure chunk has proper markdown closure."""
        # Count backticks to check for unclosed code blocks
        backtick_count = chunk.count('```')
        
        # If odd number of backticks, close the code block
        if backtick_count % 2 != 0:
            chunk += '\n```'
            
        # Trim extra whitespace while preserving newlines
        chunk = '\n'.join(line.rstrip() for line in chunk.splitlines())
        
        return chunk.strip()
    
    def estimate_chunks(self, content: str) -> int:
        """Estimate number of chunks content will be split into.
        
        Args:
            content: Content to estimate chunks for
            
        Returns:
            Estimated number of chunks
        """
        return len(self._split_content(content))
