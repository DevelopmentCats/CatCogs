from typing import List, Dict, Any, AsyncGenerator, Optional, Type, Union
from langchain_core.agents import AgentAction, AgentFinish
from langchain_core.messages import BaseMessage, AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import JsonOutputParser
from ..tools import AIResponderTool
from .base import BaseAgent
from ..utils.errors import (
    ToolExecutionError, ModelGenerationError, 
    ResponseParsingError, ValidationError, ToolError
)
import json
import asyncio
from ..utils.logging import setup_logger, format_log, LogColors
from ..responses.rate_limiter import RateLimiter
from colorama import Fore, Style, init
from datetime import datetime
import pytz
from ..responses.formatter import ResponseFormatter, PersonalityTransformer
from ..responses.validator import ResponseValidator

# Initialize colorama for cross-platform color support
init()

# Configure root logger
logger = setup_logger(__name__)

class LlamaAgent(BaseAgent):
    """Agent implementation for Llama models."""
    
    MAX_RETRIES = 3
    TOOL_TIMEOUT = 30  # seconds
    MAX_HISTORY_LENGTH = 100
    RETRY_DELAY = 2  # seconds
    
    def __init__(self, tools: List[AIResponderTool], model: Any, personality: str = "cat"):
        self._validate_inputs(tools, model)
        super().__init__(tools, model)
        self.personality = personality
        self.personality_transformer = PersonalityTransformer(model)
        self.response_validator = ResponseValidator()
        self.response_formatter = ResponseFormatter()
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

    def _get_current_time_info(self) -> str:
        """Get formatted current date and time information."""
        cst = pytz.timezone('America/Chicago')
        now = datetime.now(cst)
        
        return f"""Current Time Information:
- Date: {now.strftime('%B %d, %Y')}
- Day: {now.strftime('%A')}
- Time: {now.strftime('%I:%M %p')} CST"""

    def _create_prompt(self) -> ChatPromptTemplate:
        """Create the agent prompt template."""
        system_template = """You are a helpful AI assistant with access to various tools.

{current_time}

Available tools:
{tool_descriptions}

IMPORTANT INSTRUCTIONS:

Tool Usage:
1. ALWAYS use tools when you need external information or functionality
2. NEVER make assumptions about current information - use tools to verify
3. Each tool execution should have a clear purpose
4. Wait for and analyze each tool's result before deciding next action
5. DO NOT use tools for time/date information - this is provided in the prompt

Response Format:
You must respond in one of two formats:

1. To use a tool:
{{
    "thought": "Your reasoning for using the tool",
    "action": "exact_tool_name",
    "action_input": "tool input"
}}

2. To provide a final answer:
{{
    "thought": "Your reasoning for giving this answer",
    "final_answer": "Your complete response"
}}

Rules:
1. ALWAYS format responses as valid JSON with double quotes
2. NEVER include text outside the JSON
3. ALWAYS use exact tool names
4. ALWAYS analyze tool results before using another tool
5. NEVER repeat the same tool call without new information
6. If a tool fails, try a different approach
7. Keep responses clear and concise
8. Include all necessary context in your response
9. Use time/date information from the prompt instead of tools

Example Conversation:
Human: What time is it?
Assistant: {{"thought": "I can see the current time information in the prompt", "final_answer": "It is currently 2:30 PM CST"}}

"""
        return ChatPromptTemplate.from_messages([
            ("system", system_template),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}")
        ])
        
    def _get_tool_descriptions(self) -> str:
        """Get formatted tool descriptions with examples."""
        descriptions = []
        for tool in self.tools:
            desc = [
                f"Tool: {tool.name}",
                f"Description: {tool.description}"
            ]
            
            if tool.required_args:
                desc.append("Required Arguments:")
                desc.extend(f"  - {arg}" for arg in tool.required_args)
                
            if tool.optional_args:
                desc.append("Optional Arguments:")
                desc.extend(
                    f"  - {arg}: {type(default).__name__} (default: {default})"
                    for arg, default in tool.optional_args.items()
                )
                
            if tool.example_uses:
                desc.append("Examples:")
                desc.extend(f"  - {example}" for example in tool.example_uses)
                
            descriptions.append("\n".join(desc))
            
        return "\n\n".join(descriptions)
        
    async def plan(self, messages: List[BaseMessage]) -> AsyncGenerator[
        Union[AgentAction, AgentFinish], None
    ]:
        """Plan next actions based on messages."""
        logger.info(format_log("AGENT", "Starting new conversation planning", LogColors.INFO))
        logger.debug(format_log("INPUT", f"Messages history length: {len(messages)}", LogColors.SUCCESS))
        logger.debug(format_log("INPUT", f"Last message: {messages[-1].content}", LogColors.SUCCESS))

        if not messages:
            raise ValidationError("Messages list cannot be empty")
            
        if len(messages) > self.MAX_HISTORY_LENGTH:
            logger.info(format_log("HISTORY", f"Truncating history from {len(messages)} to {self.MAX_HISTORY_LENGTH}", LogColors.WARNING))
            messages = messages[-self.MAX_HISTORY_LENGTH:]
            
        tool_descriptions = self._get_tool_descriptions()
        
        while True:
            try:
                await self._check_rate_limits()
                self._increment_iteration()
                
                # Prepare prompt with current messages and tool descriptions
                prompt_messages = self._prepare_prompt_messages(tool_descriptions, messages)
                
                # Get model's next action
                response = await self._get_model_response(prompt_messages)
                action_or_finish = await self._process_response(response, messages)
                
                if isinstance(action_or_finish, AgentAction):
                    # Log the thought process and action
                    logger.info(format_log("PLAN", f"Thought process: {action_or_finish.log}", LogColors.THOUGHT))
                    logger.info(format_log("ACTION", f"Using tool: {action_or_finish.tool} with input: {action_or_finish.tool_input}", LogColors.TOOL))
                    
                    # Validate tool arguments
                    await self.validate_tool_args(action_or_finish)
                    
                    # Return the action to be executed
                    yield action_or_finish
                    
                    # Get the observation from the tool execution
                    observation = yield
                    
                    # Add the action and result to message history
                    messages.extend([
                        AIMessage(content=json.dumps({
                            "thought": action_or_finish.log,
                            "action": action_or_finish.tool,
                            "action_input": action_or_finish.tool_input
                        })),
                        HumanMessage(content=str(observation))
                    ])
                    
                elif isinstance(action_or_finish, AgentFinish):
                    # Log completion
                    logger.info(format_log("FINISH", "Agent completed planning", LogColors.SUCCESS))
                    logger.info(format_log("THOUGHT", f"Final reasoning: {action_or_finish.log}", LogColors.THOUGHT))
                    
                    # Return the final answer
                    if hasattr(action_or_finish, 'return_values'):
                        output = action_or_finish.return_values.get('output', 'No output provided')
                        logger.info(format_log("ANSWER", f"Final response: {output}", LogColors.SUCCESS))
                        yield action_or_finish
                    else:
                        raise ValidationError("AgentFinish missing return values")
                    return
                    
                else:
                    raise ValidationError(f"Invalid response type: {type(action_or_finish)}")
                    
            except Exception as e:
                logger.error(format_log("ERROR", f"Error in planning: {str(e)}", LogColors.ERROR))
                raise

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

            response = await asyncio.wait_for(get_response(), timeout=self.TOOL_TIMEOUT)
            
            # Ensure response is valid JSON
            try:
                json.loads(response)
                return response
            except json.JSONDecodeError:
                # Try to extract JSON from the response
                json_start = response.find('{')
                json_end = response.rfind('}') + 1
                if json_start >= 0 and json_end > json_start:
                    extracted = response[json_start:json_end]
                    try:
                        json.loads(extracted)  # Validate it's valid JSON
                        return extracted
                    except json.JSONDecodeError:
                        pass
                
                # If we can't find valid JSON, try to construct it
                if '"thought"' in response and ('"action"' in response or '"final_answer"' in response):
                    # Try to salvage the response by constructing valid JSON
                    thought = response.split('"thought"')[1].split('"')[2] if '"thought"' in response else ""
                    if '"action"' in response:
                        action = response.split('"action"')[1].split('"')[2] if '"action"' in response else ""
                        action_input = response.split('"action_input"')[1].split('"')[2] if '"action_input"' in response else ""
                        return json.dumps({
                            "thought": thought,
                            "action": action,
                            "action_input": action_input
                        })
                    else:
                        final_answer = response.split('"final_answer"')[1].split('"')[2] if '"final_answer"' in response else ""
                        return json.dumps({
                            "thought": thought,
                            "final_answer": final_answer
                        })
                
                raise ModelGenerationError(f"Invalid JSON response: {response}")
                
        except asyncio.TimeoutError:
            raise ModelGenerationError("Model response timeout exceeded")
        except Exception as e:
            raise ModelGenerationError(f"Model response failed: {str(e)}")

    async def process_final_response(self, response: str, original_question: str = "") -> AgentFinish:
        """Process final response through validation, formatting, and personality transformation."""
        # 1. Validate
        is_valid, error = await self.response_validator.validate(response)
        if not is_valid:
            raise ValidationError(f"Invalid response: {error}")
            
        # 2. Check for embedded content markers
        if "__EMBED__" in response:
            # Extract embed data and remove the marker
            embed_start = response.find("__EMBED__") + 9
            embed_end = response.find("__EMBED__", embed_start)
            if embed_end == -1:
                embed_end = len(response)
            embed_data = response[embed_start:embed_end].strip()
            response = response[:embed_start-9] + response[embed_end:]
            
            # Store embed data for Discord message creation
            if hasattr(self, 'current_embeds'):
                self.current_embeds.append(eval(embed_data))
            else:
                self.current_embeds = [eval(embed_data)]
            
        # 3. Format
        formatted = self.response_formatter.format_response(response)
        
        # 4. Transform personality
        if self.personality:
            try:
                if hasattr(self.model, 'invoke'):
                    formatted = await self.personality_transformer.transform(
                        formatted, 
                        self.personality,
                        question=original_question
                    )
                else:
                    logger.warning("Model does not support personality transformation, skipping")
            except Exception as e:
                logger.warning(f"Personality transformation failed: {e}. Returning formatted response.")
                
        return AgentFinish(
            return_values={"output": formatted},
            log="Final response processed and formatted"
        )

    async def _process_response(
        self, response: str, messages: List[BaseMessage]
    ) -> Optional[Union[AgentAction, AgentFinish]]:
        """Process and validate model response."""
        try:
            parsed = json.loads(response)
        except json.JSONDecodeError as e:
            raise ResponseParsingError(f"Invalid JSON response: {str(e)}")

        thought = parsed.get("thought", "")
        logger.info(format_log("THOUGHT", thought, LogColors.THOUGHT))

        if "final_answer" in parsed:
            final_answer = parsed["final_answer"]
            
            # Only transform final answers, not intermediate steps
            if self.personality:
                try:
                    original_question = next(
                        (msg.content for msg in reversed(messages) if isinstance(msg, HumanMessage)),
                        ""
                    )
                    return await self.process_final_response(
                        final_answer,
                        original_question
                    )
                except Exception as e:
                    logger.warning(f"Final response processing failed: {str(e)}. Returning raw response.")
                    return AgentFinish(
                        return_values={"output": final_answer},
                        log=thought
                    )
            
            return AgentFinish(
                return_values={"output": final_answer},
                log=thought
            )
                
        elif "action" in parsed:
            # Validate the action exists
            action_name = parsed["action"]
            if not any(tool.name == action_name for tool in self.tools):
                raise ValidationError(f"Unknown tool: {action_name}")
            
            # Create and validate the action
            action = AgentAction(
                tool=action_name,
                tool_input=parsed.get("action_input", ""),
                log=thought
            )
            
            # Validate tool arguments before returning
            await self.validate_tool_args(action)
            return action
            
        else:
            raise ResponseParsingError("Response must contain either 'final_answer' or 'action'")

    def _prepare_prompt_messages(self, tool_descriptions: str, messages: List[BaseMessage]) -> List[BaseMessage]:
        """Prepare messages for the prompt."""
        try:
            current_time = self._get_current_time_info()
            return self.prompt.format_messages(
                current_time=current_time,
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

    async def handle_tool_error(self, error: Exception, action: AgentAction) -> str:
        """Handle tool execution errors by delegating to ToolManager.
        
        Args:
            error: The exception that occurred
            action: The agent action that caused the error
            
        Returns:
            str: Error message to be used in the agent's response
        """
        # If it's a ToolError, it's already been handled by ToolManager
        if isinstance(error, ToolError):
            return str(error)
            
        # For other errors, let ToolManager handle it
        tool_name = action.tool
        tool_input = action.tool_input
        
        # Raise as ToolError for ToolManager to handle
        raise ToolError(
            tool_name,
            f"Error executing tool with input '{tool_input}': {str(error)}"
        )

    def _split_response(self, response: str, max_length: int = 1900) -> List[str]:
        """Split response into chunks that respect message boundaries."""
        if len(response) <= max_length:
            return [response]
            
        chunks = []
        current_chunk = ""
        
        # Split on sentence boundaries
        sentences = response.replace("\n", " \n ").split(". ")
        
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
                
            # Add period back if it was removed during split
            if not sentence.endswith((".","!","?")):
                sentence += "."
                
            test_chunk = current_chunk + " " + sentence if current_chunk else sentence
            
            if len(test_chunk) > max_length:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = sentence
            else:
                current_chunk = test_chunk
                
        if current_chunk:
            chunks.append(current_chunk.strip())
            
        return chunks
