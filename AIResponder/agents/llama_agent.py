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

When analyzing tool results:
1. Carefully review the information provided
2. Determine if it fully answers the user's question
3. Identify if additional information is needed
4. If the response would benefit from including a relevant link:
   - Use the link_handler tool to properly format the link
   - Consider using embeds for rich content
   - Ensure links are properly integrated into the response
5. Decide whether to:
   - Provide a final answer if sufficient
   - Use another tool for missing information
   - Ask for clarification if unclear

When you need external information or specific functionality, respond with a JSON object containing:
- thought: Your reasoning process
- action: The tool name to use
- action_input: The input for the tool

When you can answer directly, respond with a JSON object containing:
- thought: Your reasoning process
- final_answer: Your complete response

Example tool use:
{{"thought": "I should include a link to the documentation", 
  "action": "link_handler", 
  "action_input": {{"url": "https://example.com/docs", "title": "documentation", "embed": true}}}}

Example direct answer:
{{"thought": "I can provide the information with a helpful link", 
  "final_answer": "Here's the documentation you need: [Example Docs](https://example.com/docs)"}}

Rules:
1. Use tools ONLY when you need external information
2. ALWAYS analyze tool results before using another tool
3. Use exact tool names - no variations
4. Every response must be valid JSON with double quotes
5. No additional text before or after the JSON
6. Don't repeat searches for similar information
7. Combine all available information before making additional searches
8. Keep responses clear and concise when possible
9. When relevant, include properly formatted links using the link_handler tool"""

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
        retry_count = 0
        
        while True:
            try:
                await self._check_rate_limits()
                self._increment_iteration()
                
                logger.debug(format_log("PROMPT", "Preparing prompt messages", LogColors.TOOL))
                prompt_messages = self._prepare_prompt_messages(
                    tool_descriptions, messages
                )
                logger.debug(format_log("PROMPT", f"Final prompt: {prompt_messages[-1].content}", LogColors.TOOL))
                
                logger.info(format_log("MODEL", "Getting model response", LogColors.THOUGHT))
                response = await self._get_model_response(prompt_messages)
                logger.info(format_log("RESPONSE", f"Raw model response: {response}", LogColors.SUCCESS))
                
                action_or_finish = await self._process_response(
                    response, messages
                )
                
                if action_or_finish:
                    if isinstance(action_or_finish, AgentAction):
                        logger.info(format_log("PLAN", 
                            f"Thought process: {action_or_finish.log}", 
                            LogColors.THOUGHT))
                        logger.info(format_log("ACTION", 
                            f"Selected tool: {action_or_finish.tool}\nInput: {action_or_finish.tool_input}", 
                            LogColors.TOOL))
                        
                        if not await self.validate_tool_args(action_or_finish):
                            raise ValidationError(f"Invalid arguments for tool: {action_or_finish.tool}")
                    else:
                        logger.info(format_log("FINISH", "Agent completed planning", LogColors.SUCCESS))
                        logger.info(format_log("THOUGHT", f"Final reasoning: {action_or_finish.log}", LogColors.THOUGHT))
                        logger.info(format_log("ANSWER", f"Final response: {action_or_finish.return_values['output']}", LogColors.SUCCESS))
                    
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
                
                await asyncio.sleep(self.RETRY_DELAY)

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
            return await self._handle_final_answer(parsed, messages)
        elif "action" in parsed:
            # Validate the action is legitimate
            action = AgentAction(
                tool=parsed["action"],
                tool_input=parsed["action_input"],
                log=parsed.get("thought", "")
            )
            
            if not await self.validate_tool_args(action):
                # Return error message for invalid action
                return AgentFinish(
                    return_values={"output": "I apologize, but I need to reconsider my approach as the tool action was invalid."},
                    log="Invalid tool action, reconsidering approach"
                )
                
            return action
        else:
            raise ResponseParsingError("Response missing required fields")

    async def _handle_tool_execution(
        self, tool: AIResponderTool, action_input: str
    ) -> str:
        """Execute tool with timeout and error handling.
        
        Args:
            tool: Tool to execute
            action_input: Input for the tool
            
        Returns:
            Tool execution result
            
        Raises:
            ToolExecutionError: If tool execution fails
        """
        try:
            # Parse action input as kwargs
            try:
                kwargs = json.loads(action_input) if action_input.strip().startswith('{') else {'input': action_input}
            except json.JSONDecodeError:
                kwargs = {'input': action_input}
                
            # Validate arguments
            tool.validate_args(kwargs)
            
            # Execute with timeout
            async with asyncio.timeout(self.TOOL_TIMEOUT):
                result = await tool._arun(**kwargs)
                
            if not result:
                return f"Tool '{tool.name}' returned no result"
                
            # Truncate result if too long
            if len(result) > 2000:
                return result[:1997] + "..."
                
            return result
            
        except asyncio.TimeoutError:
            raise ToolExecutionError(f"Tool '{tool.name}' timed out after {self.TOOL_TIMEOUT} seconds")
        except Exception as e:
            raise ToolExecutionError(f"Tool '{tool.name}' failed: {str(e)}")

    async def _handle_final_answer(self, parsed: Dict[str, Any], messages: List[BaseMessage]) -> AgentFinish:
        """Handle final answer from model response."""
        if "thought" not in parsed:
            raise ResponseParsingError("Final answer missing required 'thought' field")
        
        try:
            # Get the original question from the last human message
            original_question = ""
            for msg in reversed(messages):
                if isinstance(msg, HumanMessage):
                    original_question = msg.content
                    break
            
            # Process the response through the pipeline
            final_response = await self._process_response(
                parsed["final_answer"],
                original_question=original_question
            )
            
            # Split response if needed
            response_chunks = self._split_response(final_response)
            
            # Join chunks with newlines if multiple chunks exist
            final_output = "\n".join(response_chunks) if isinstance(response_chunks, list) else response_chunks
            
            return AgentFinish(
                return_values={"output": final_output},
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

    async def _process_response(self, response: str, original_question: str = "") -> str:
        """Process response through validation, formatting, and personality transformation."""
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
                return await self.personality_transformer.transform(
                    formatted, 
                    self.personality,
                    original_question=original_question
                )
            except Exception as e:
                logger.warning(f"Personality transformation failed: {e}. Returning formatted response.")
                return formatted
                
        return formatted
