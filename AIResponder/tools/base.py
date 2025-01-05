"""
Base classes for AI Responder tools.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from redbot.core.bot import Red


class AIResponderTool(ABC):
    """Base class for all AI responder tools."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.initialize()

    @abstractmethod
    def initialize(self) -> None:
        """Initialize the tool. Called after bot is set."""
        pass

    @abstractmethod
    async def execute(self, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Execute the tool with given parameters."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Get the tool's name."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Get the tool's description."""
        pass

    @property
    @abstractmethod
    def parameters(self) -> Dict[str, Any]:
        """Get the tool's parameter schema."""
        pass
