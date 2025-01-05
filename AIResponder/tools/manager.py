from typing import Dict, Optional, List, Type
from redbot.core.bot import Red
from ..utils.errors import ToolError, ToolInitializationError

# Import from base module
from .base import AIResponderTool
from . import ToolRegistry

class ToolManager:
    """Manages AI responder tools and their lifecycle."""

    def __init__(self, bot: Red):
        """Initialize tool manager.

        Args:
            bot: Red Discord bot instance
        """
        self.bot = bot
        self.tools: Dict[str, AIResponderTool] = {}
        self._initializing = False

    async def initialize_tools(self) -> None:
        """Initialize all registered tools.

        Raises:
            ToolInitializationError: If tool initialization fails
        """
        if self._initializing:
            return

        self._initializing = True
        initialization_errors = []

        try:
            for tool_class in ToolRegistry.get_all_tools():
                try:
                    await self._initialize_tool(tool_class)
                except Exception as e:
                    initialization_errors.append(f"{tool_class.__name__}: {str(e)}")

            if initialization_errors:
                error_message = "Failed to initialize tools:\n" + "\n".join(initialization_errors)
                raise ToolInitializationError(error_message)

        finally:
            self._initializing = False

    async def _initialize_tool(self, tool_class: Type[AIResponderTool]) -> None:
        """Initialize a single tool.

        Args:
            tool_class: Tool class to initialize

        Raises:
            ToolError: If tool initialization fails
        """
        try:
            # Check if tool is already initialized
            if not hasattr(tool_class, 'name') or not tool_class.name:
                raise ToolError(tool_class.__name__, "Tool has no name defined")

            if tool_class.name in self.tools:
                return

            tool = tool_class(self.bot)
            await tool.initialize()
            self.tools[tool_class.name] = tool

        except Exception as e:
            raise ToolError(
                tool_class.__name__ if hasattr(tool_class, '__name__') else 'Unknown',
                f"Initialization failed: {str(e)}"
            )

    async def cleanup_tools(self) -> None:
        """Cleanup all tools.

        This method ensures proper resource cleanup even if some tools fail.
        """
        cleanup_errors = []

        for name, tool in self.tools.items():
            try:
                if hasattr(tool, 'cleanup'):
                    await tool.cleanup()
            except Exception as e:
                cleanup_errors.append(f"{name}: {str(e)}")

        self.tools.clear()

        if cleanup_errors:
            raise ToolError(
                "cleanup",
                f"Failed to cleanup tools:\n" + "\n".join(cleanup_errors)
            )

    def get_tool(self, name: str) -> Optional[AIResponderTool]:
        """Get a tool by name.

        Args:
            name: Name of the tool to retrieve

        Returns:
            Tool instance or None if not found
        """
        return self.tools.get(name)

    async def get_all_tools(self) -> List[AIResponderTool]:
        """Get all initialized tools.

        Returns:
            List of initialized tools

        Raises:
            ToolError: If tools are not initialized
        """
        if not self.tools:
            raise ToolError("manager", "Tools not initialized")
        return list(self.tools.values())

    def is_tool_available(self, name: str) -> bool:
        """Check if a tool is available.

        Args:
            name: Name of the tool to check

        Returns:
            bool: True if tool is available
        """
        return name in self.tools

    async def reload_tool(self, name: str) -> bool:
        """Reload a specific tool.

        Args:
            name: Name of the tool to reload

        Returns:
            bool: True if reload was successful

        Raises:
            ToolError: If tool reload fails
        """
        if name not in self.tools:
            return False

        tool = self.tools[name]
        tool_class = tool.__class__

        try:
            # Cleanup existing tool
            if hasattr(tool, 'cleanup'):
                await tool.cleanup()

            # Reinitialize tool
            await self._initialize_tool(tool_class)
            return True

        except Exception as e:
            raise ToolError(name, f"Failed to reload tool: {str(e)}")
