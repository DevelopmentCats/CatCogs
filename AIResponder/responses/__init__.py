"""
Response Processing Module for AI Responder

This module provides utilities for processing, formatting, validating,
and managing AI responses including rate limiting and chunking.

Components:
- ResponseFormatter: Handles markdown formatting and citations
- ResponseValidator: Validates response content and structure
- RateLimiter: Manages rate limiting for responses
- ResponseChunker: Handles chunking of long responses
"""

from .formatter import ResponseFormatter
from .validator import ResponseValidator
from .rate_limiter import RateLimiter
from .chunker import ResponseChunker

__all__ = ["ResponseFormatter", "ResponseValidator", "RateLimiter", "ResponseChunker"]

# Version information
__version__ = "1.0.0"

# Module metadata
__author__ = "DevelopmentCats"
__description__ = "Response Processing System"
__status__ = "Production"
