"""
Tools Module for AI Responder

This module provides the tool framework and implementations for
various AI assistant capabilities.
"""

from .base import AIResponderTool
from typing import Dict, Type, List, Optional, Any
from redbot.core.bot import Red

class ToolRegistry:
    """Registry for AI responder tools."""
    
    _tools: Dict[str, Type[AIResponderTool]] = {}
    _registered_names = set()  # Track registered names
    
    @classmethod
    def register(cls, tool_class: Type[AIResponderTool]) -> Type[AIResponderTool]:
        """Register a tool class."""
        if not tool_class.name:
            raise ValueError(f"Tool class {tool_class.__name__} has no name")
            
        if tool_class.name in cls._registered_names:
            # Instead of raising an error, just return the class
            return tool_class
            
        cls._tools[tool_class.name] = tool_class
        cls._registered_names.add(tool_class.name)
        return tool_class
    
    @classmethod
    def get_tool(cls, name: str) -> Optional[Type[AIResponderTool]]:
        """Get a tool class by name."""
        return cls._tools.get(name)
    
    @classmethod
    def get_all_tools(cls) -> List[Type[AIResponderTool]]:
        """Get all registered tool classes."""
        return list(cls._tools.values())

from .manager import ToolManager
from .calculator import Calculator
from .search import WebSearch
from .discord_info import ServerInfo, ChannelHistory

__all__ = [
    "AIResponderTool",
    "ToolRegistry",
    "ToolManager",
    "Calculator",
    "WebSearch",
    "ServerInfo",
    "ChannelHistory"
]

# Version information
__version__ = "1.0.0"

# Module metadata
__author__ = "Your Name"
__description__ = "AI Responder Tools Framework"
__status__ = "Production"
