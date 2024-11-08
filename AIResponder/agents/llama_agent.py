from typing import List, Dict, Any, AsyncGenerator, Optional, Type
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
import logging
from ..responses.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

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
        return ChatPromptTemplate.from_messages([
            ("system", """You are a helpful AI assistant with access to various tools.
            Available tools:
            {tool_descriptions}

            To use a tool, respond with:
            {{"thought": "your reasoning",
              "action": "tool_name",
              "action_input": "input to the tool"}}

            To provide a final answer, respond with:
            {{"thought": "your reasoning",
              "final_answer": "your response"}}
            """),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
        ])
        
    def _get_tool_descriptions(self) -> str:
        """Get formatted tool descriptions."""
        return "\n".join([
            f"- {tool.name}: {tool.description}"
            for tool in self.tools
        ])
        
    async def plan(self, messages: List[BaseMessage]) -> AsyncGenerator[
        AgentAction | AgentFinish, None
    ]:
        """Plan next actions based on messages."""
        if not messages:
            raise ValidationError("Messages list cannot be empty")
            
        # Truncate history if too long
        if len(messages) > self.MAX_HISTORY_LENGTH:
            messages = messages[-self.MAX_HISTORY_LENGTH:]
            
        tool_descriptions = self._get_tool_descriptions()
        retry_count = 0
        
        while True:
            try:
                # Check rate limits
                await self._check_rate_limits()
                
                # Increment iteration counter from base class
                self._increment_iteration()
                
                # Prepare and validate prompt
                prompt_messages = self._prepare_prompt_messages(
                    tool_descriptions, messages
                )
                
                # Get model response with timeout
                response = await self._get_model_response(prompt_messages)
                
                # Parse and process response
                action_or_finish = await self._process_response(
                    response, messages
                )
                
                if action_or_finish:
                    if isinstance(action_or_finish, AgentAction):
                        # Validate tool arguments before yielding
                        if not await self.validate_tool_args(action_or_finish):
                            raise ValidationError(f"Invalid arguments for tool: {action_or_finish.tool}")
                    
                    yield action_or_finish
                    if isinstance(action_or_finish, AgentFinish):
                        break
                        
            except Exception as e:
                retry_count += 1
                if retry_count >= self.MAX_RETRIES:
                    logger.error(f"Max retries reached: {str(e)}")
                    raise
                    
                logger.warning(f"Error in plan execution (attempt {retry_count}): {str(e)}")
                messages.append(AIMessage(content=f"Error occurred: {str(e)}. Retrying..."))
                await asyncio.sleep(1)  # Brief delay before retry

    async def _get_model_response(self, prompt_messages: List[BaseMessage]) -> str:
        """Get response from model with timeout."""
        response = ""
        try:
            async with asyncio.timeout(self.TOOL_TIMEOUT):
                async for chunk in self.model.generate_response(
                    str(prompt_messages[-1].content),
                    context=str(prompt_messages[:-1])
                ):
                    response += chunk
            return response
        except asyncio.TimeoutError:
            raise ModelGenerationError("Model response timeout exceeded")
        except Exception as e:
            raise ModelGenerationError(f"Model response failed: {str(e)}")

    async def _process_response(
        self, response: str, messages: List[BaseMessage]
    ) -> Optional[AgentAction | AgentFinish]:
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
        try:
            async with asyncio.timeout(self.TOOL_TIMEOUT):
                return await tool._arun(action_input)
        except asyncio.TimeoutError:
            raise ToolExecutionError(
                tool.name, "Tool execution timeout exceeded"
            )
        except Exception as e:
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
        cat_prompt = self.prompt.format_messages(
            tool_descriptions="",
            chat_history=[],
            input=f"""Transform this response into a sarcastic cat personality response, 
            adding cat-like expressions and mannerisms: {response}"""
        )
        
        cat_response = ""
        async for chunk in self.model.generate_response(
            str(cat_prompt[-1].content),
            context="You are a sarcastic cat AI. Respond with cattitude, use cat puns, and express mild disdain while being helpful."
        ):
            cat_response += chunk
            
        return cat_response

    async def _handle_final_answer(self, parsed: Dict[str, Any]) -> AgentFinish:
        """Handle final answer from model response."""
        if "thought" not in parsed:
            raise ResponseParsingError("Final answer missing required 'thought' field")
        
        try:
            return AgentFinish(
                return_values={"output": parsed["final_answer"]},
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
            await self.rate_limiter.check_rate_limit()
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
