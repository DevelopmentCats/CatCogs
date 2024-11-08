from typing import List, Optional, Dict, Any, AsyncGenerator
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_core.agents import AgentAction, AgentFinish
from ..tools import ToolManager
from .llama_agent import LlamaAgent
from ..utils.errors import AgentError, ToolExecutionError
from ..utils.logging import setup_logger, format_log, LogColors
from colorama import Fore

# Configure manager logger
logger = setup_logger(__name__)

class AgentManager:
    """Manages agent creation and execution."""
    
    def __init__(self, model: Any, tool_manager: ToolManager):
        """Initialize the agent manager.
        
        Args:
            model: The language model to use
            tool_manager: Tool manager instance for handling tools
        """
        self.model = model
        self.tool_manager = tool_manager
        self._active_agents: Dict[str, LlamaAgent] = {}
        
    async def create_agent(self, session_id: str = "default") -> LlamaAgent:
        """Create a new agent instance.
        
        Args:
            session_id: Unique identifier for the agent session
            
        Returns:
            LlamaAgent: New agent instance
            
        Raises:
            AgentError: If agent creation fails
        """
        try:
            tools = await self.tool_manager.get_all_tools()
            agent = LlamaAgent(tools, self.model)
            self._active_agents[session_id] = agent
            return agent
        except Exception as e:
            logger.error(f"Failed to create agent: {str(e)}")
            raise AgentError(f"Agent creation failed: {str(e)}")

    async def process_message(
        self, 
        content: str, 
        history: List[Dict[str, str]], 
        session_id: str = "default"
    ) -> AsyncGenerator[str, None]:
        """Process a message and generate a response.
        
        Args:
            content: The message content to process
            history: List of previous messages
            session_id: Session identifier for agent management
            
        Yields:
            Chunks of the response as they're generated
            
        Raises:
            AgentError: If message processing fails
        """
        try:
            # Convert history to BaseMessage format
            messages = [
                HumanMessage(content=msg["content"]) if msg["role"] == "user"
                else AIMessage(content=msg["content"])
                for msg in history
            ]
            
            # Add current message
            messages.append(HumanMessage(content=content))
            
            # Create or get existing agent
            agent = await self._get_or_create_agent(session_id)
            
            # Process message
            async for chunk in self._process_agent_steps(agent, messages):
                yield chunk
                
        except Exception as e:
            error_msg = f"Error processing message: {str(e)}"
            logger.error(error_msg, exc_info=True)
            yield f"Error: {error_msg}"
        finally:
            # Cleanup after processing
            await self._cleanup_agent(session_id)

    async def _get_or_create_agent(self, session_id: str) -> LlamaAgent:
        """Get existing agent or create new one."""
        if session_id in self._active_agents:
            agent = self._active_agents[session_id]
            await agent.reset()  # Reset state for new conversation
            return agent
        return await self.create_agent(session_id)

    async def _process_agent_steps(
        self, 
        agent: LlamaAgent, 
        messages: List[BaseMessage]
    ) -> AsyncGenerator[str, None]:
        """Process agent steps and handle tool execution."""
        logger.info(format_log("MANAGER", f"Processing message: {messages[-1].content}", Fore.CYAN))
        try:
            async for step in agent.plan(messages):
                if isinstance(step, AgentFinish):
                    logger.info(format_log("MANAGER", "Agent finished with response", Fore.GREEN))
                    yield step.return_values["output"]
                    break
                    
                # For actions, yield thoughts and execute tools
                logger.info(format_log("MANAGER", f"Agent thought: {step.log}", Fore.YELLOW))
                yield f"Thinking: {step.log}\n"
                logger.info(format_log("MANAGER", f"Using tool: {step.tool}", Fore.BLUE))
                yield f"Using tool: {step.tool}\n"
                
                try:
                    tool = await agent.get_tool(step.tool)
                    if tool:
                        logger.info(format_log("MANAGER", f"Executing tool: {step.tool}", Fore.MAGENTA))
                        result = await tool._arun(step.tool_input)
                        logger.info(format_log("MANAGER", f"Tool result: {result[:100]}...", Fore.GREEN))
                        yield f"Tool result: {result}\n"
                    else:
                        error_msg = f"Tool not found: {step.tool}"
                        logger.error(format_log("MANAGER", error_msg, Fore.RED))
                        yield f"Error: {error_msg}\n"
                        
                except ToolExecutionError as e:
                    error_msg = await agent.handle_tool_error(e, step)
                    logger.error(format_log("MANAGER", f"Tool error: {error_msg}", Fore.RED))
                    yield f"Tool error: {error_msg}\n"
                    
        except Exception as e:
            error_msg = f"Error in agent execution: {str(e)}"
            logger.error(format_log("MANAGER", error_msg, Fore.RED), exc_info=True)
            yield f"Error: {error_msg}"

    async def _cleanup_agent(self, session_id: str) -> None:
        """Clean up agent resources."""
        try:
            if session_id in self._active_agents:
                agent = self._active_agents[session_id]
                await agent.cleanup()
                del self._active_agents[session_id]
        except Exception as e:
            logger.error(f"Error cleaning up agent: {str(e)}")

    async def cleanup_all(self) -> None:
        """Clean up all active agents."""
        for session_id in list(self._active_agents.keys()):
            await self._cleanup_agent(session_id)
