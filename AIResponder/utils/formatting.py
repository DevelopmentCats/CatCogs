from typing import Optional, List, Dict, Any
import re
from datetime import datetime, timedelta
from .errors import FormattingError

def truncate_text(text: str, max_length: int = 2000, suffix: str = "...") -> str:
    """Truncate text to specified length while preserving word boundaries.
    
    Args:
        text: Text to truncate
        max_length: Maximum length
        suffix: Suffix to add to truncated text
        
    Returns:
        Truncated text
    """
    if len(text) <= max_length:
        return text
        
    truncated = text[:max_length - len(suffix)]
    last_space = truncated.rfind(' ')
    
    if last_space > 0:
        truncated = truncated[:last_space]
        
    return truncated + suffix

def clean_code_blocks(text: str) -> str:
    """Clean and normalize code blocks in text.
    
    Args:
        text: Text containing code blocks
        
    Returns:
        Text with cleaned code blocks
    """
    # Pattern matches code blocks with or without language specification
    pattern = re.compile(r'```(?:\w+)?\n?(.*?)\n?```', re.DOTALL)
    
    def clean_block(match):
        code = match.group(1)
        # Remove excess blank lines
        code = re.sub(r'\n{3,}', '\n\n', code)
        # Normalize indentation
        lines = code.split('\n')
        if lines:
            # Find minimum indentation
            min_indent = float('inf')
            for line in lines:
                if line.strip():
                    indent = len(line) - len(line.lstrip())
                    min_indent = min(min_indent, indent)
            
            # Remove common indentation
            if min_indent < float('inf'):
                lines = [line[min_indent:] if line.strip() else line for line in lines]
            
            code = '\n'.join(lines)
        
        return f'```\n{code.strip()}\n```'
    
    return pattern.sub(clean_block, text)

def format_duration(seconds: float) -> str:
    """Format duration in seconds to human-readable string.
    
    Args:
        seconds: Duration in seconds
        
    Returns:
        Formatted duration string
    """
    if seconds < 60:
        return f"{seconds:.1f} seconds"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f} minutes"
    else:
        hours = seconds / 3600
        return f"{hours:.1f} hours"

def format_timestamp(dt: datetime, include_time: bool = True) -> str:
    """Format datetime to consistent string format.
    
    Args:
        dt: Datetime to format
        include_time: Whether to include time
        
    Returns:
        Formatted timestamp string
    """
    if include_time:
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return dt.strftime("%Y-%m-%d")

def clean_mentions(text: str) -> str:
    """Remove or sanitize Discord mentions from text.
    
    Args:
        text: Text containing mentions
        
    Returns:
        Text with sanitized mentions
    """
    # Replace @everyone and @here
    text = re.sub(r'@(everyone|here)', r'@\u200b\1', text)
    
    # Replace user/role mentions
    text = re.sub(r'<@[!&]?(\d+)>', r'@user\1', text)
    
    return text

def format_list(items: List[str], 
                separator: str = ", ", 
                last_separator: str = " and ") -> str:
    """Format list of items into grammatically correct string.
    
    Args:
        items: List of items to format
        separator: Separator between items
        last_separator: Separator before last item
        
    Returns:
        Formatted string
    """
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
        
    return f"{separator.join(items[:-1])}{last_separator}{items[-1]}"

def normalize_whitespace(text: str) -> str:
    """Normalize whitespace in text while preserving code blocks.
    
    Args:
        text: Text to normalize
        
    Returns:
        Text with normalized whitespace
    """
    def _normalize_non_code(text: str) -> str:
        # Normalize line endings
        text = text.replace('\r\n', '\n')
        # Remove trailing whitespace
        lines = [line.rstrip() for line in text.split('\n')]
        # Remove multiple blank lines
        text = re.sub(r'\n{3,}', '\n\n', '\n'.join(lines))
        return text.strip()
    
    # Split by code blocks
    parts = re.split(r'(```.*?```)', text, flags=re.DOTALL)
    
    # Normalize non-code parts
    for i in range(0, len(parts), 2):
        parts[i] = _normalize_non_code(parts[i])
        
    return ''.join(parts)

def escape_markdown(text: str) -> str:
    """Escape markdown formatting characters.
    
    Args:
        text: Text to escape
        
    Returns:
        Text with escaped markdown
    """
    markdown_chars = ['\\', '`', '*', '_', '{', '}', '[', ']', '(', ')', '#', '+', '-', '.', '!']
    for char in markdown_chars:
        text = text.replace(char, '\\' + char)
    return text
