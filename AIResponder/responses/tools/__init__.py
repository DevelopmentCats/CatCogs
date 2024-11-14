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
    required_args: List[str] = []  # List of required arguments
    optional_args: Dict[str, Any] = {}  # Optional arguments with default values
    example_uses: List[str] = []  # Example uses of the tool
    
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
        
    def validate_args(self, args: Dict[str, Any]) -> None:
        """Validate tool arguments.
        
        Args:
            args: Arguments to validate
            
        Raises:
            ValueError: If required arguments are missing or invalid
        """
        # Check required arguments
        missing_args = [arg for arg in self.required_args if arg not in args]
        if missing_args:
            raise ValueError(f"Missing required arguments: {', '.join(missing_args)}")
            
        # Check argument types if specified in optional_args
        for arg_name, value in args.items():
            if arg_name in self.optional_args:
                expected_type = type(self.optional_args[arg_name])
                if not isinstance(value, expected_type):
                    raise ValueError(
                        f"Argument '{arg_name}' must be of type {expected_type.__name__}, "
                        f"got {type(value).__name__}"
                    )
    
    def get_help(self) -> str:
        """Get detailed help information about the tool.
        
        Returns:
            Formatted help string with description, arguments, and examples
        """
        help_text = [
            f"Tool: {self.name}",
            f"Description: {self.description}",
            "\nRequired Arguments:",
            *[f"- {arg}" for arg in self.required_args],
            "\nOptional Arguments:",
            *[f"- {arg}: {type(default).__name__} (default: {default})"
              for arg, default in self.optional_args.items()],
            "\nExample Uses:",
            *[f"- {example}" for example in self.example_uses]
        ]
        return "\n".join(help_text)
    
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
