"""
Memory Module for AI Responder

This module provides conversation history management and memory
persistence functionality for the AI Responder system.
"""

from .conversation import ConversationManager, Message

__all__ = [
    "ConversationManager",
    "Message"
]

# Version information
__version__ = "1.0.0"

# Module metadata
__author__ = "DevelopmentCats"
__description__ = "Memory Management System"
__status__ = "Production"
