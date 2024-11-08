"""
Tools Module for AI Responder

This module provides the tool framework and implementations for
various AI assistant capabilities.
"""

from abc import ABC, abstractmethod
from typing import Dict, Type, List, Optional, Any
from redbot.core.bot import Red

class AIResponderTool(ABC):
    """Base class for AI responder tools."""
    
    name: str = ""
    description: str = ""
    
    @classmethod
    def __init_subclass__(cls, **kwargs):
        """Prevent duplicate registration of tools."""
        super().__init_subclass__(**kwargs)
        if any(tool.__name__ == cls.__name__ for tool in ToolRegistry._tools.values()):
            return
            
    def __init__(self, bot: Optional[Red] = None):
        """Initialize tool.
        
        Args:
            bot: Optional Red Discord bot instance
        """
        self.bot = bot
    
    @abstractmethod
    def _run(self, *args: Any, **kwargs: Any) -> str:
        """Synchronous tool execution.
        
        Args:
            *args: Positional arguments
            **kwargs: Keyword arguments
            
        Returns:
            Tool execution result
        """
        pass
    
    @abstractmethod
    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        """Asynchronous tool execution.
        
        Args:
            *args: Positional arguments
            **kwargs: Keyword arguments
            
        Returns:
            Tool execution result
        """
        pass
    
    async def initialize(self) -> None:
        """Initialize tool resources."""
        pass
    
    async def cleanup(self) -> None:
        """Cleanup tool resources."""
        pass

class ToolRegistry:
    """Registry for AI responder tools."""
    
    _tools: Dict[str, Type[AIResponderTool]] = {}
    
    @classmethod
    def register(cls, tool_class: Type[AIResponderTool]) -> Type[AIResponderTool]:
        """Register a tool class.
        
        Args:
            tool_class: Tool class to register
            
        Returns:
            Registered tool class
            
        Raises:
            ValueError: If tool name is invalid or duplicate
        """
        if not tool_class.name:
            raise ValueError(f"Tool class {tool_class.__name__} has no name")
            
        if tool_class.name in cls._tools:
            raise ValueError(f"Duplicate tool name: {tool_class.name}")
            
        cls._tools[tool_class.name] = tool_class
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
