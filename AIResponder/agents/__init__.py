"""
AI Responder Agent Module

This module provides the core agent implementations for AI response generation
and management. It includes the base agent interface, Llama-based implementation,
and agent management utilities.
"""

from .base import BaseAgent
from .llama_agent import LlamaAgent
from .manager import AgentManager

__all__ = [
    "BaseAgent",
    "LlamaAgent", 
    "AgentManager"
]

# Version info
__version__ = "1.0.0"

# Module metadata
__author__ = "DevelopmentCats"
__description__ = "AI Responder Agent Implementation"
__status__ = "Production"
