from typing import Optional, Tuple, List, Pattern
import re
from ..utils.errors import ValidationError

class ResponseValidator:
    """Validates AI responses before sending."""
    
    def __init__(self, max_length: int = 2000, max_code_blocks: int = 5):
        """Initialize validator with constraints.
        
        Args:
            max_length: Maximum allowed response length
            max_code_blocks: Maximum number of code blocks allowed
        """
        if max_length <= 0:
            raise ValueError("max_length must be positive")
            
        self.max_length = max_length
        self.max_code_blocks = max_code_blocks
        self._compile_patterns()
        
    def _compile_patterns(self) -> None:
        """Compile regex patterns for validation."""
        self.patterns = {
            'code_block': re.compile(r'```.*?```', re.DOTALL),
            'inline_code': re.compile(r'`[^`]+`'),
            'links': re.compile(r'\[([^\]]+)\]\(([^)]+)\)'),
            'images': re.compile(r'!\[([^\]]+)\]\(([^)]+)\)'),
            'tables': re.compile(r'\|[^|]+\|'),
            'mentions': re.compile(r'@(everyone|here|&?\d+)'),
            'invite_links': re.compile(r'discord\.gg/[a-zA-Z0-9]+'),
            'spoilers': re.compile(r'\|\|.*?\|\|'),
            'custom_emojis': re.compile(r'<a?:\w+:\d+>')
        }
        
        self.harmful_patterns: List[Pattern] = [
            re.compile(pattern) for pattern in [
                r'@everyone',
                r'@here',
                r'discord\.gg/[a-zA-Z0-9]+',
                r'<@&?\d+>',  # Role mentions
                r'https?://(?!(?:[\w-]+\.)*discord\.com/)',  # Non-Discord URLs
                r'```(?:js|javascript|python)\s*[\s\S]*?eval\(',  # Eval in code
                r'```(?:js|javascript|python)\s*[\s\S]*?exec\('   # Exec in code
            ]
        ]
        
    async def validate(self, content: str) -> Tuple[bool, Optional[str]]:
        """Validate the response content.
        
        Args:
            content: Content to validate
            
        Returns:
            Tuple of (is_valid, error_message)
            
        Raises:
            ValidationError: If validation fails unexpectedly
        """
        try:
            # Basic content checks
            if not content or not content.strip():
                return False, "Response is empty"
                
            if len(content) > self.max_length:
                return False, f"Response exceeds maximum length ({len(content)} > {self.max_length})"
            
            # Markdown validation
            markdown_valid, markdown_error = self._validate_markdown(content)
            if not markdown_valid:
                return False, f"Invalid markdown: {markdown_error}"
            
            # Content safety checks
            if harmful_content := self._detect_harmful_content(content):
                return False, f"Potentially harmful content detected: {harmful_content}"
            
            # Structure validation
            if structure_error := self._validate_structure(content):
                return False, f"Invalid structure: {structure_error}"
            
            return True, None
            
        except Exception as e:
            raise ValidationError(f"Validation failed: {str(e)}")
    
    def _validate_markdown(self, content: str) -> Tuple[bool, Optional[str]]:
        """Validate markdown syntax and structure."""
        # Check code blocks
        code_blocks = self.patterns['code_block'].findall(content)
        if len(code_blocks) > self.max_code_blocks:
            return False, f"Too many code blocks ({len(code_blocks)} > {self.max_code_blocks})"
            
        if content.count('```') % 2 != 0:
            return False, "Unclosed code block"
            
        # Check inline code
        if content.count('`') % 2 != 0:
            return False, "Unclosed inline code"
            
        # Validate links
        for match in self.patterns['links'].finditer(content):
            if not self._validate_link(match.group(2)):
                return False, f"Invalid link: {match.group(2)}"
                
        return True, None
    
    def _validate_structure(self, content: str) -> Optional[str]:
        """Validate response structure."""
        # Check for nested code blocks
        if '```' in content and re.search(r'```.*```.*```', content, re.DOTALL):
            return "Nested code blocks are not allowed"
            
        # Check table structure
        if '|' in content:
            lines = content.split('\n')
            for i, line in enumerate(lines):
                if line.strip().startswith('|'):
                    if not self._validate_table_row(line):
                        return f"Invalid table structure at line {i+1}"
                        
        return None
    
    def _validate_table_row(self, row: str) -> bool:
        """Validate a table row structure."""
        # Check for equal number of cells
        cells = row.strip('|').split('|')
        return all(cell.strip() for cell in cells)
    
    def _validate_link(self, url: str) -> bool:
        """Validate a markdown link URL."""
        # Basic URL validation
        return bool(re.match(r'^https?://', url) or url.startswith('/'))
    
    def _detect_harmful_content(self, content: str) -> Optional[str]:
        """Detect potentially harmful content."""
        for pattern in self.harmful_patterns:
            if match := pattern.search(content):
                return match.group(0)
                
        # Check for excessive mentions
        mention_count = len(self.patterns['mentions'].findall(content))
        if mention_count > 5:
            return f"Too many mentions ({mention_count})"
            
        return None
