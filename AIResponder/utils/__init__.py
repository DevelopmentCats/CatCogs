"""
Utilities Module for AI Responder

This module provides common utilities and helper functions used
throughout the AI Responder system.
"""

from .errors import (
    AIResponderError,
    ToolError,
    ToolExecutionError,
    ToolInitializationError,
    ModelError,
    ModelInitializationError,
    ModelGenerationError,
    ResponseError,
    ResponseParsingError,
    ValidationError,
    FormattingError,
    ChunkingError,
    RateLimitError,
    ConfigError,
    ConversationError,
    AgentError,
    AgentInitializationError,
    AgentExecutionError
)

from .formatting import (
    truncate_text,
    clean_code_blocks,
    format_duration,
    format_timestamp,
    clean_mentions,
    format_list,
    normalize_whitespace,
    escape_markdown
)

from .config import ConfigManager

__all__ = [
    # Errors
    "AIResponderError",
    "ToolError",
    "ToolExecutionError",
    "ToolInitializationError",
    "ModelError",
    "ModelInitializationError",
    "ModelGenerationError",
    "ResponseError",
    "ResponseParsingError",
    "ValidationError",
    "FormattingError",
    "ChunkingError",
    "RateLimitError",
    "ConfigError",
    "ConversationError",
    "AgentError",
    "AgentInitializationError",
    "AgentExecutionError",
    
    # Formatting utilities
    "truncate_text",
    "clean_code_blocks",
    "format_duration",
    "format_timestamp",
    "clean_mentions",
    "format_list",
    "normalize_whitespace",
    "escape_markdown",
    
    # Configuration
    "ConfigManager"
]

# Version information
__version__ = "1.0.0"

# Module metadata
__author__ = "Your Name"
__description__ = "AI Responder Utilities"
__status__ = "Production"
