from abc import ABC, abstractmethod
from typing import List, Dict, Any, AsyncGenerator, Optional
from langchain_core.agents import AgentAction, AgentFinish
from langchain_core.messages import BaseMessage
from ..tools import AIResponderTool

class BaseAgent(ABC):
    """Base class for AI Responder agents.
    
    This abstract class defines the core interface and common functionality
    for AI agents that can process messages, plan actions, and handle tool interactions.
    
    Attributes:
        tools (List[AIResponderTool]): Available tools for the agent to use
        model (Any): The underlying language model for the agent
        max_iterations (int): Maximum number of action iterations before forcing completion
        memory_key (str): Key used for storing memory context
    """
    
    def __init__(self, 
                 tools: List[AIResponderTool], 
                 model: Any,
                 max_iterations: int = 10,
                 memory_key: str = "chat_history"):
        self.tools = tools
        self.model = model
        self.max_iterations = max_iterations
        self.memory_key = memory_key
        self._iteration_count = 0
        
    @abstractmethod
    async def plan(self, messages: List[BaseMessage]) -> AsyncGenerator[
        AgentAction | AgentFinish, None
    ]:
        """Plan next actions based on messages.
        
        Args:
            messages: List of messages representing the conversation history
            
        Yields:
            AgentAction: Next action to take with a tool
            AgentFinish: Final response when planning is complete
            
        Raises:
            Exception: If planning fails or maximum iterations are exceeded
        """
        pass
        
    @abstractmethod
    async def handle_tool_error(self, error: Exception, action: AgentAction) -> str:
        """Handle tool execution errors.
        
        Args:
            error: The exception that occurred
            action: The agent action that caused the error
            
        Returns:
            str: Error message or recovery instructions
            
        Raises:
            Exception: If error handling fails
        """
        pass
    
    async def reset(self) -> None:
        """Reset the agent's state.
        
        This method should be called between conversations to clear
        any stored state or context.
        """
        self._iteration_count = 0
    
    def _increment_iteration(self) -> None:
        """Increment the iteration counter and check limits."""
        self._iteration_count += 1
        if self._iteration_count >= self.max_iterations:
            raise RuntimeError(f"Agent exceeded maximum iterations ({self.max_iterations})")
    
    async def get_tool(self, tool_name: str) -> Optional[AIResponderTool]:
        """Get a tool by name.
        
        Args:
            tool_name: Name of the tool to retrieve
            
        Returns:
            The requested tool or None if not found
        """
        for tool in self.tools:
            if tool.name == tool_name:
                return tool
        return None
    
    async def validate_tool_args(self, action: AgentAction) -> bool:
        """Validate that an action's arguments match its tool's requirements.
        
        Args:
            action: The agent action to validate
            
        Returns:
            bool: True if arguments are valid, False otherwise
        """
        tool = await self.get_tool(action.tool)
        if not tool:
            return False
            
        try:
            # Attempt to parse the tool input
            tool.parse_input(action.tool_input)
            return True
        except Exception:
            return False
