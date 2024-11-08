from typing import List, Dict, Any, AsyncGenerator, Optional, Type, Union
from langchain_core.agents import AgentAction, AgentFinish
from langchain_core.messages import BaseMessage, AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import JsonOutputParser
from ..tools import AIResponderTool
from .base import BaseAgent
from ..utils.errors import (
    ToolExecutionError, ModelGenerationError, 
    ResponseParsingError, ValidationError
)
import json
import asyncio
from ..utils.logging import setup_logger, format_log, LogColors
from ..responses.rate_limiter import RateLimiter
from colorama import Fore, Style, init

# Initialize colorama for cross-platform color support
init()

# Configure root logger
logger = setup_logger(__name__)

class LlamaAgent(BaseAgent):
    """Agent implementation for Llama models."""
    
    MAX_RETRIES = 3
    TOOL_TIMEOUT = 30  # seconds
    MAX_HISTORY_LENGTH = 100
    
    def __init__(self, tools: List[AIResponderTool], model: Any):
        self._validate_inputs(tools, model)
        super().__init__(tools, model)
        self.prompt = self._create_prompt()
        self.output_parser = JsonOutputParser()
        self.rate_limiter = RateLimiter()
        
    def _validate_inputs(self, tools: List[AIResponderTool], model: Any) -> None:
        """Validate initialization inputs."""
        if not tools:
            raise ValidationError("At least one tool must be provided")
        
        if not all(isinstance(tool, AIResponderTool) for tool in tools):
            raise ValidationError("All tools must be instances of AIResponderTool")
            
        if not model:
            raise ValidationError("Model must be provided")
            
        # Validate tool names are unique
        tool_names = [tool.name for tool in tools]
        if len(tool_names) != len(set(tool_names)):
            raise ValidationError("Tool names must be unique")

    def _create_prompt(self) -> ChatPromptTemplate:
        """Create the agent prompt template."""
        system_template = """You are a helpful AI assistant with access to various tools.

Available tools:
{tool_descriptions}

When you need external information or specific functionality, respond with a JSON object containing:
- thought: Your reasoning process
- action: The tool name to use
- action_input: The input for the tool

When you can answer directly, respond with a JSON object containing:
- thought: Your reasoning process
- final_answer: Your complete response

Example tool use:
{{"thought": "I need to search for current information", "action": "web_search", "action_input": "latest news"}}

Example direct answer:
{{"thought": "I can answer this from my knowledge", "final_answer": "Here is my response"}}

Available tools:
- web_search: For real-time information or facts you're unsure about
- server_info: For Discord server details
- channel_history: For accessing chat history
- calculator: For mathematical calculations

Rules:
1. Use tools ONLY when you need external information
2. Provide direct final_answer when you can answer from your knowledge
3. Use exact tool names - no variations
4. Every response must be valid JSON with double quotes
5. No additional text before or after the JSON"""

        return ChatPromptTemplate.from_messages([
            ("system", system_template),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}")
        ])
        
    def _get_tool_descriptions(self) -> str:
        """Get formatted tool descriptions."""
        return "\n".join([
            f"- {tool.name}: {tool.description}"
            for tool in self.tools
        ])
        
    async def plan(self, messages: List[BaseMessage]) -> AsyncGenerator[
        Union[AgentAction, AgentFinish], None
    ]:
        """Plan next actions based on messages."""
        logger.info(format_log("AGENT", "Starting new conversation planning", LogColors.INFO))
        logger.debug(format_log("INPUT", f"Last message: {messages[-1].content}", LogColors.SUCCESS))

        if not messages:
            raise ValidationError("Messages list cannot be empty")
            
        if len(messages) > self.MAX_HISTORY_LENGTH:
            logger.info(format_log("HISTORY", f"Truncating history from {len(messages)} to {self.MAX_HISTORY_LENGTH}", LogColors.WARNING))
            messages = messages[-self.MAX_HISTORY_LENGTH:]
            
        tool_descriptions = self._get_tool_descriptions()
        retry_count = 0
        
        while True:
            try:
                await self._check_rate_limits()
                self._increment_iteration()
                
                logger.debug(format_log("PROMPT", "Preparing prompt messages", LogColors.TOOL))
                prompt_messages = self._prepare_prompt_messages(
                    tool_descriptions, messages
                )
                
                logger.info(format_log("MODEL", "Getting model response", LogColors.THOUGHT))
                response = await self._get_model_response(prompt_messages)
                logger.debug(format_log("RESPONSE", f"Raw response: {response}", LogColors.SUCCESS))
                
                action_or_finish = await self._process_response(
                    response, messages
                )
                
                if action_or_finish:
                    if isinstance(action_or_finish, AgentAction):
                        logger.info(format_log("ACTION", 
                            f"Tool: {action_or_finish.tool}, Input: {action_or_finish.tool_input}", 
                            LogColors.TOOL))
                        
                        if not await self.validate_tool_args(action_or_finish):
                            raise ValidationError(f"Invalid arguments for tool: {action_or_finish.tool}")
                    else:
                        logger.info(format_log("FINISH", "Agent completed with final answer", LogColors.SUCCESS))
                    
                    yield action_or_finish
                    if isinstance(action_or_finish, AgentFinish):
                        break

            except Exception as e:
                retry_count += 1
                logger.warning(format_log("RETRY", 
                    f"Attempt {retry_count}/{self.MAX_RETRIES}: {str(e)}", 
                    LogColors.WARNING))
                
                if retry_count >= self.MAX_RETRIES:
                    logger.error(format_log("ERROR", f"Max retries reached: {str(e)}", LogColors.ERROR))
                    raise
                
                messages.append(AIMessage(content=f"Error occurred: {str(e)}. Retrying..."))
                await asyncio.sleep(1)

    async def _get_model_response(self, prompt_messages: List[BaseMessage]) -> str:
        """Get response from model with timeout."""
        response = ""
        try:
            # Use asyncio.wait_for instead of timeout context manager
            async def get_response():
                async for chunk in self.model.generate_response(
                    str(prompt_messages[-1].content),
                    context=str(prompt_messages[:-1])
                ):
                    nonlocal response
                    response += chunk
                return response

            return await asyncio.wait_for(get_response(), timeout=self.TOOL_TIMEOUT)
        except asyncio.TimeoutError:
            raise ModelGenerationError("Model response timeout exceeded")
        except Exception as e:
            raise ModelGenerationError(f"Model response failed: {str(e)}")

    async def _process_response(
        self, response: str, messages: List[BaseMessage]
    ) -> Optional[Union[AgentAction, AgentFinish]]:
        """Process and validate model response."""
        try:
            parsed = json.loads(response)
        except json.JSONDecodeError as e:
            raise ResponseParsingError(f"Invalid JSON response: {str(e)}")

        if "final_answer" in parsed:
            return await self._handle_final_answer(parsed)
        elif "action" in parsed:
            return await self._handle_action(parsed, messages)
        else:
            raise ResponseParsingError("Response missing required fields")

    async def _handle_tool_execution(
        self, tool: AIResponderTool, action_input: str
    ) -> str:
        """Execute tool with timeout and error handling."""
        logger.info(format_log("TOOL", f"Executing {tool.name} with input: {action_input}", LogColors.TOOL))
        try:
            async with asyncio.timeout(self.TOOL_TIMEOUT):
                result = await tool._arun(action_input)
                logger.info(format_log("TOOL", f"Success: {tool.name}", LogColors.SUCCESS))
                return result
        except asyncio.TimeoutError:
            logger.error(format_log("TIMEOUT", f"Tool {tool.name} exceeded {self.TOOL_TIMEOUT}s", LogColors.ERROR))
            raise ToolExecutionError(
                tool.name, "Tool execution timeout exceeded"
            )
        except Exception as e:
            logger.error(format_log("ERROR", f"Tool {tool.name} failed: {str(e)}", LogColors.ERROR))
            raise ToolExecutionError(
                tool.name, str(e), original_error=e
            )

    async def handle_tool_error(self, error: Exception, action: AgentAction) -> str:
        """Handle tool execution errors."""
        error_message = f"Error using tool {action.tool}: {str(error)}"
        logger.error(error_message, exc_info=True)
        
        # Get the tool that failed
        tool = await self.get_tool(action.tool)
        if tool:
            # Add tool-specific error handling if available
            try:
                error_message += f"\nTool suggestion: {tool.error_handling_hint}"
            except AttributeError:
                pass
                
        return error_message

    async def _transform_to_cat_response(self, response: str) -> str:
        """Transform a regular response into a sarcastic cat response."""
        cat_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a sarcastic cat AI assistant. Transform the input into a cat-like response:
- Use cat puns and expressions (purr-fect, meow, etc.)
- Add mild disdain while still being helpful
- Reference cat behaviors (grooming, napping, etc.)
- Keep the original information accurate
- Maintain a playful but slightly condescending tone
"""),
            ("human", f"Transform this response into a cat personality response: {response}")
        ])
        
        formatted_prompt = cat_prompt.format_messages()
        
        cat_response = ""
        async for chunk in self.model.generate_response(
            str(formatted_prompt[-1].content),
            context=str(formatted_prompt[0].content)
        ):
            cat_response += chunk
            
        return cat_response

    async def _handle_final_answer(self, parsed: Dict[str, Any]) -> AgentFinish:
        """Handle final answer from model response."""
        if "thought" not in parsed:
            raise ResponseParsingError("Final answer missing required 'thought' field")
        
        try:
            # Transform the final answer to cat personality
            cat_response = await self._transform_to_cat_response(parsed["final_answer"])
            
            return AgentFinish(
                return_values={"output": cat_response},
                log=parsed["thought"]
            )
        except KeyError as e:
            raise ResponseParsingError(f"Missing required field in final answer: {e}")

    async def _handle_action(self, parsed: Dict[str, Any], messages: List[BaseMessage]) -> AgentAction:
        """Handle action from model response."""
        required_fields = ["thought", "action", "action_input"]
        missing_fields = [field for field in required_fields if field not in parsed]
        
        if missing_fields:
            raise ResponseParsingError(f"Action missing required fields: {', '.join(missing_fields)}")
        
        # Validate tool exists
        tool_names = [tool.name for tool in self.tools]
        if parsed["action"] not in tool_names:
            raise ValidationError(f"Unknown tool: {parsed['action']}")
            
        return AgentAction(
            tool=parsed["action"],
            tool_input=parsed["action_input"],
            log=parsed["thought"]
        )

    def _prepare_prompt_messages(self, tool_descriptions: str, messages: List[BaseMessage]) -> List[BaseMessage]:
        """Prepare messages for the prompt."""
        try:
            return self.prompt.format_messages(
                tool_descriptions=tool_descriptions,
                chat_history=messages[:-1],
                input=messages[-1].content
            )
        except Exception as e:
            raise ValidationError(f"Failed to prepare prompt messages: {str(e)}")

    async def _check_rate_limits(self) -> None:
        """Check rate limits with proper error handling."""
        try:
            # Use a default user ID for agent rate limiting
            await self.rate_limiter.check_rate_limit("agent")
        except Exception as e:
            logger.warning(f"Rate limit check failed: {str(e)}")
            # Still allow execution but with a warning
            pass

    async def cleanup(self) -> None:
        """Cleanup resources used by the agent."""
        try:
            await self.rate_limiter.cleanup()
            await super().reset()  # Reset base class state
        except Exception as e:
            logger.error(f"Cleanup failed: {str(e)}")
            raise

    async def validate_tool_args(self, action: AgentAction) -> bool:
        """Validate tool arguments."""
        tool = await self.get_tool(action.tool)
        if not tool:
            return False
            
        try:
            # Basic input validation
            if not isinstance(action.tool_input, str):
                return False
                
            # Tool-specific validation
            if tool.name == "web_search":
                return len(action.tool_input.strip()) > 0
                
            elif tool.name == "server_info":
                return action.tool_input.strip().isdigit()
                
            elif tool.name == "channel_history":
                parts = action.tool_input.split()
                return (len(parts) in (1, 2) and 
                       parts[0].isdigit() and
                       (len(parts) == 1 or parts[1].isdigit()))
                
            elif tool.name == "calculator":
                return len(action.tool_input.strip()) > 0
                
            return True
            
        except Exception:
            return False
