import asyncio
import json
import logging
import math
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Tuple, Any, Optional, Union

import aiohttp
import discord
from redbot.core import commands, Config
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, pagify
from sympy import sympify, SympifyError, E, pi, oo, zoo

from langchain import hub
from langchain_experimental.plan_and_execute import (
    PlanAndExecute,
    load_agent_executor,
    load_chat_planner
)
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain.memory import ConversationBufferWindowMemory
from langchain_community.tools import DuckDuckGoSearchResults, WikipediaQueryRun
from langchain_community.tools.ddg_search.tool import DuckDuckGoSearchRun
from langchain_community.utilities import DuckDuckGoSearchAPIWrapper, WikipediaAPIWrapper
from langchain_core.agents import AgentAction, AgentFinish
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import Tool, BaseTool
from langchain_openai import ChatOpenAI

from openai import AsyncOpenAI
from pydantic import BaseModel, Field, ValidationError

class DiscordCallbackHandler(BaseCallbackHandler):
    def __init__(self, discord_message, logger, memory):
        self.discord_message = discord_message
        self.logger = logger
        self.memory = memory
        self.last_update = datetime.now().timestamp()
        self.tool_outputs = []

    async def on_llm_start(self, serialized, prompts, **kwargs):
        self.logger.info("LLM started generating response")
        await self.discord_message.edit(content="🤔 Thinking...")

    async def on_plan_start(self, plan, **kwargs):
        self.logger.info(f"Starting plan: {plan}")
        formatted_plan = f"🗺️ *flicks tail and plans approach*\n```\n{plan}\n```"
        await self.discord_message.edit(content=formatted_plan)

    async def on_step_start(self, step: int, total: int, **kwargs):
        step_msg = f"📝 *gracefully executes step {step}/{total}*"
        await self.discord_message.edit(content=step_msg)

    async def on_tool_start(self, serialized, input_str, **kwargs):
        tool_name = serialized.get('name', 'Unknown Tool')
        self.logger.info(f"🔧 Starting Tool Execution: {tool_name} with input: {input_str}")
        tool_msg = f"🔧 *paws at {tool_name}*"
        await self.discord_message.edit(content=tool_msg)

    async def on_tool_end(self, output, **kwargs):
        self.logger.info(f"Tool execution completed with output: {output}")
        self.tool_outputs.append(output)
        if isinstance(self.memory, DiscordConversationMemory):
            self.memory.chat_memory.add_ai_message(f"Tool output: {output}")
        await self.discord_message.edit(content="✨ *purrs contentedly*")

    async def on_tool_error(self, error, **kwargs):
        self.logger.error(f"Tool Error: {str(error)}")
        await self.discord_message.edit(
            content=f"😾 *hisses at error*\n```\n{str(error)}\n```"
        )

    async def on_chain_end(self, outputs, **kwargs):
        self.logger.info("Chain completed")

    async def on_plan_error(self, error: str, **kwargs):
        self.logger.error(f"Plan Error: {error}")
        await self.discord_message.edit(
            content=f"😾 *hisses at planning error*\n```\nFailed to create plan: {error}\n```"
        )

    async def on_step_error(self, error: str, step: int, **kwargs):
        self.logger.error(f"Step {step} Error: {error}")
        await self.discord_message.edit(
            content=f"😾 *growls at step {step} failure*\n```\n{error}\n```"
        )

    async def on_agent_action(self, action: AgentAction, **kwargs):
        self.logger.info(f"Agent Action: {action.tool}")
        await self.discord_message.edit(
            content=f"🐱 *carefully considers using {action.tool}*"
        )

    async def on_agent_finish(self, finish: AgentFinish, **kwargs):
        """Handle final agent response with proper validation."""
        self.logger.info("Agent finished execution")

class DiscordContext(BaseModel):
    guild: Optional[Dict] = Field(default_factory=dict)
    channel: Optional[Dict] = Field(default_factory=dict)
    user: Optional[Dict] = Field(default_factory=dict)

    @classmethod
    def from_discord_objects(cls, guild, channel, user_dict):
        """Create DiscordContext from Discord objects."""
        return cls(
            guild={
                "id": str(guild.id) if guild else None,
                "name": guild.name if guild else None,
                "member_count": guild.member_count if guild else None
            },
            channel={
                "id": str(channel.id) if channel else None,
                "name": channel.name if channel else None,
                "type": str(channel.type) if channel else None
            },
            user=user_dict
        )

class ExecutionHistory(BaseModel):
    step: int
    action: str
    result: str

class DiscordConversationMemory(ConversationBufferWindowMemory):
    """Custom memory class for Plan-and-Execute agent with Discord context."""
    
    context: DiscordContext = Field(default_factory=DiscordContext)
    plan_history: List[str] = Field(default_factory=list)
    execution_history: List[ExecutionHistory] = Field(default_factory=list)
    logger: Optional[logging.Logger] = None

    def __init__(self, logger: logging.Logger = None, **kwargs):
        super().__init__(**kwargs)
        self.logger = logger or logging.getLogger("red.airesponder")
        self.chat_memory = ChatMessageHistory()

    def get_relevant_context(self) -> str:
        """Get current context including recent messages and execution history."""
        context_parts = []
        
        # Add Discord context
        if self.context:
            context_parts.append(f"Current server: {self.context.guild.get('name', 'Unknown')}")
            context_parts.append(f"Current channel: {self.context.channel.get('name', 'Unknown')}")
            context_parts.append(f"Speaking with: {self.context.user.get('nickname', 'Unknown')}")

        # Add recent chat history (last 3 messages)
        recent_messages = self.chat_memory.messages[-3:] if self.chat_memory.messages else []
        if recent_messages:
            context_parts.append("\nRecent conversation:")
            for msg in recent_messages:
                if isinstance(msg, HumanMessage):
                    context_parts.append(f"User: {msg.content}")
                elif isinstance(msg, AIMessage):
                    context_parts.append(f"Assistant: {msg.content}")

        # Add current plan if exists
        if self.plan_history:
            context_parts.append(f"\nCurrent plan:\n{self.plan_history[-1]}")

        # Add recent execution steps
        if self.execution_history:
            context_parts.append("\nRecent steps:")
            for exe in self.execution_history[-3:]:
                context_parts.append(f"Step {exe.step}: {exe.action} -> {exe.result}")

        return "\n".join(context_parts)

    def store_context(self, context: Dict):
        """Store Discord context and update memory."""
        try:
            # Extract values directly from the dict structure
            guild_data = context.get('guild', {})
            channel_data = context.get('channel', {})
            user_data = context.get('user', {})

            self.context = DiscordContext(
                guild=guild_data,
                channel=channel_data,
                user=user_data
            )
            
            # Add system context to memory
            self.chat_memory.add_message(
                SystemMessage(content=f"""Current Discord Context:
                Server: {guild_data.get('name', 'DM')}
                Channel: {channel_data.get('name', 'Unknown')}
                User: {user_data.get('nickname', 'Unknown')}""")
            )
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error storing context: {str(e)}")
            raise ValidationError(f"Failed to store Discord context: {str(e)}")

    def store_plan(self, plan: str):
        """Store the current execution plan."""
        self.plan_history.append(plan)
        if len(self.plan_history) > 5:  # Keep last 5 plans
            self.plan_history.pop(0)
        
        # Add plan to chat memory for context
        self.chat_memory.add_message(
            SystemMessage(content=f"Current Plan:\n{plan}")
        )

    def store_execution(self, step: int, action: str, result: str):
        """Store execution steps and results with plan context."""
        self.execution_history.append(
            ExecutionHistory(step=step, action=action, result=result)
        )
        if len(self.execution_history) > 10:
            self.execution_history.pop(0)
        
        # Add execution step to chat memory
        self.chat_memory.add_message(
            SystemMessage(content=f"Step {step} Execution:\nAction: {action}\nResult: {result}")
        )

    def store_tool_result(self, tool_name: str, result: str):
        """Store tool execution results in memory."""
        try:
            # Add tool result to chat memory
            self.chat_memory.add_message(
                SystemMessage(content=f"Tool Result ({tool_name}): {result}")
            )
            
            # Store in execution history
            self.execution_history.append(
                ExecutionHistory(
                    step=len(self.execution_history) + 1,
                    action=f"Used {tool_name}",
                    result=result
                )
            )
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error storing tool result: {str(e)}")

    def get_context(self) -> Dict:
        """Get the full context including Discord and execution history."""
        return {
            "discord": self.context.dict(),
            "plans": self.plan_history,
            "executions": [eh.dict() for eh in self.execution_history],
            "chat_history": self.chat_memory.messages
        }

class AIResponder(commands.Cog):
    def __init__(self, bot: Red):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        default_global = {
            "api_key": "",
            "model": "meta-llama/Llama-3.2-11B-Vision-Instruct",
            "custom_personality": "You are a helpful AI assistant.",
            "enabled_channels": [],
        }
        self.config.register_global(**default_global)
        self.llm = None
        self.agent_executor = None
        self.logger = logging.getLogger("red.airesponder")
        self.bot.loop.create_task(self.initialize())
        self.user_chat_histories = {}
        self.current_context = None

    async def initialize(self):
        """Initialize the cog."""
        try:
            self.config = Config.get_conf(
                self,
                identifier=1234567890,
                force_registration=True,
            )
            
            # Register default settings
            default_global = {
                "api_key": None,
                "model": "meta-llama/Llama-3.2-11B-Vision-Instruct",
            }
            
            self.config.register_global(**default_global)
            
            # Setup logging
            self.logger = logging.getLogger("red.airesponder")
            
            # Initialize LangChain components
            success = await self.update_langchain_components()
            if not success:
                self.logger.error("Failed to initialize LangChain components")
                raise RuntimeError("Failed to initialize LangChain components")
            
            self.logger.info("AIResponder initialized successfully")
                
        except Exception as e:
            self.logger.error(f"Error in initialize: {str(e)}", exc_info=True)
            raise

    async def handle_plan_error(self, error: Exception, message: discord.Message) -> str:
        """Handle errors during plan creation and execution."""
        error_type = type(error).__name__
        self.logger.error(f"Plan-and-Execute error ({error_type}): {str(error)}")
        
        error_responses = {
            "ValidationError": "*wrinkles nose* This plan doesn't meet my high feline standards. Let me try again... 😾",
            "ToolError": "*hisses at malfunctioning tool* My tools aren't cooperating! 🙀",
            "MemoryError": "*looks confused* I seem to have forgotten something important... 😿",
            "TimeoutError": "*yawns* This is taking too long. Shall we try again? 😺",
        }
        
        return f"{message.author.mention} {error_responses.get(error_type, '*looks apologetic* Something went wrong with my plan. Could you try again? 😿')}"

    async def recover_from_failed_step(self, step_number: int, total_steps: int, error: Exception) -> bool:
        """Attempt to recover from a failed execution step."""
        try:
            self.logger.info(f"Attempting to recover from step {step_number} failure")
            
            # Store error in memory for context
            if isinstance(self.memory, DiscordConversationMemory):
                self.memory.store_execution(
                    step_number,
                    "error_recovery",
                    f"Error: {str(error)}"
                )
            
            # If we're on the last step, try to generate a response from partial results
            if step_number == total_steps:
                return True  # Indicate we should try to generate a final response
                
            return False  # Indicate we need to retry the step
            
        except Exception as e:
            self.logger.error(f"Error in recovery attempt: {str(e)}")
            return False

    async def setup_tools(self) -> List[Tool]:
        """Initialize and return the list of available tools."""
        tools = [
            Tool(
                name="Current Date and Time (CST)",
                func=self.get_current_date_time_cst,
                description="Get the current date and time in Central Standard Time (CST). No input needed.",
                coroutine=self.get_current_date_time_cst,
                return_direct=False
            ),
            Tool(
                name="Calculator",
                func=self.calculator,
                description="Performs mathematical calculations. Input: mathematical expression",
                return_direct=False
            ),
            Tool(
                name="DuckDuckGo Search",
                func=self.async_search,
                description="Searches the internet for current information.",
                coroutine=self.async_search,
                return_direct=False
            ),
            Tool(
                name="Wikipedia",
                func=self.async_wiki_search,
                description="Gets detailed information from Wikipedia.",
                coroutine=self.async_wiki_search,
                return_direct=False
            ),
            Tool(
                name="Discord Server Info",
                func=lambda _: self.get_discord_server_info(ctx=self.current_context),
                description="Gets information about the current Discord server.",
                coroutine=lambda _: self.get_discord_server_info(ctx=self.current_context),
            ),
            Tool(
                name="Channel Chat History",
                func=lambda x: self.get_channel_chat_history(x, ctx=self.current_context),
                description="Retrieves recent chat history from the current channel.",
                coroutine=lambda x: self.get_channel_chat_history(x, ctx=self.current_context),
            )
        ]
        
        return tools

    async def async_search(self, query: str) -> str:
        search = DuckDuckGoSearchResults()
        return await search.arun(query)

    async def async_wiki_search(self, query: str) -> str:
        wiki = WikipediaQueryRun(api_wrapper=WikipediaAPIWrapper())
        return await wiki.arun(query)

    def calculator(self, expression: str) -> str:
        """Enhanced calculator that handles units and conversions."""
        try:
            # First, clean and normalize the expression
            cleaned_expression = expression.lower().strip()
            
            # Unit conversion mappings
            unit_conversions = {
                # Length
                'feet': '*0.3048',  # to meters
                'ft': '*0.3048',
                'foot': '*0.3048',
                'inches': '*0.0254',  # to meters
                'inch': '*0.0254',
                'in': '*0.0254',
                'yards': '*0.9144',  # to meters
                'yd': '*0.9144',
                'meters': '',
                'm': '',
                'centimeters': '*0.01',  # to meters
                'cm': '*0.01',
                
                # Area
                'sq ft': '*(0.3048**2)',
                'square feet': '*(0.3048**2)',
                'sq meters': '',
                'square meters': '',
                
                # Volume
                'cubic feet': '*(0.3048**3)',
                'cu ft': '*(0.3048**3)',
                'gallons': '*3.78541',  # to liters
                'gal': '*3.78541',
                'liters': '',
                'l': '',
                
                # Weight/Mass
                'pounds': '*0.453592',  # to kg
                'lbs': '*0.453592',
                'lb': '*0.453592',
                'ounces': '*0.0283495',  # to kg
                'oz': '*0.0283495',
                'kilograms': '',
                'kg': '',
                'grams': '*0.001',  # to kg
                'g': '*0.001',
                
                # Temperature
                'f': '(({val} - 32) * 5/9)',  # to Celsius
                'fahrenheit': '(({val} - 32) * 5/9)',
                'c': '',
                'celsius': '',
                
                # Time
                'hours': '*3600',  # to seconds
                'hr': '*3600',
                'h': '*3600',
                'minutes': '*60',  # to seconds
                'min': '*60',
                'seconds': '',
                'sec': '',
                's': ''
            }

            # Handle special cases for diameter/radius/circumference
            if 'diameter' in cleaned_expression or 'radius' in cleaned_expression:
                # Extract the numeric value
                import re
                numbers = re.findall(r'[\d.]+', cleaned_expression)
                if not numbers:
                    return "Error: No numeric value found"
                value = float(numbers[0])
                
                if 'diameter' in cleaned_expression:
                    radius = value / 2
                else:
                    radius = value
                    
                # Calculate common circle measurements
                from math import pi
                area = pi * (radius ** 2)
                circumference = 2 * pi * radius
                
                # Format results based on original units
                unit = next((u for u in unit_conversions if u in cleaned_expression), '')
                if unit:
                    conversion_factor = eval(f"1{unit_conversions[unit]}")
                    area *= conversion_factor ** 2
                    circumference *= conversion_factor
                
                return (f"For a {'diameter' if 'diameter' in cleaned_expression else 'radius'} of {value} {unit}:\n"
                       f"Area: {area:.2f} square {unit}\n"
                       f"Circumference: {circumference:.2f} {unit}")

            # Handle basic unit conversions
            for unit, conversion in unit_conversions.items():
                if unit in cleaned_expression:
                    # Extract the numeric value
                    import re
                    numbers = re.findall(r'[\d.]+', cleaned_expression)
                    if not numbers:
                        return "Error: No numeric value found"
                    value = float(numbers[0])
                    
                    # Handle temperature conversions specially
                    if unit in ['f', 'fahrenheit', 'c', 'celsius']:
                        if unit in ['f', 'fahrenheit']:
                            result = (value - 32) * 5/9
                            return f"{value}°F = {result:.2f}°C"
                        else:
                            result = (value * 9/5) + 32
                            return f"{value}°C = {result:.2f}°F"
                    
                    # For other units, apply the conversion
                    if conversion:
                        result = eval(f"{value}{conversion}")
                        return f"{value} {unit} = {result:.2f} {'meters' if 'feet' in unit or 'inches' in unit else 'kg' if 'pounds' in unit or 'ounces' in unit else 'liters' if 'gallons' in unit else 'base unit'}"
            
            # Handle mathematical expressions with units
            for unit in unit_conversions:
                if unit in cleaned_expression:
                    cleaned_expression = cleaned_expression.replace(unit, unit_conversions[unit])
            
            # Handle common mathematical words/phrases
            word_to_symbol = {
                'squared': '**2',
                'cubed': '**3',
                'power': '**',
                'mod': '%',
                'pi': 'pi',
                'e': 'E',
                'infinity': 'oo',
                'inf': 'oo',
                'sin': 'math.sin',
                'cos': 'math.cos',
                'tan': 'math.tan',
                'log': 'math.log',
                'ln': 'math.log',
                'sqrt': 'math.sqrt',
                'abs': 'abs',
                'factorial': 'math.factorial'
            }
            
            for word, symbol  in word_to_symbol.items():
                cleaned_expression = cleaned_expression.replace(word, symbol)
            
            # Evaluate the expression
            result = sympify(cleaned_expression, locals={'math': math})
            
            # Handle special cases
            if result == zoo:
                return "Undefined (division by zero)"
            if result == oo:
                return "Infinity"
            if result == -oo:
                return "Negative Infinity"
            
            # Format the result
            if result.is_integer:
                return str(int(result))
            elif isinstance(result, (float, complex)):
                return f"{result:.6g}"
            else:
                return str(result)
                
        except SympifyError:
            return "Error: Invalid mathematical expression"
        except ValueError as e:
            return f"Error: {str(e)}"
        except OverflowError:
            return "Error: Result too large to compute"
        except Exception as e:
            return f"Error: Unable to calculate. {str(e)}"

    async def get_current_date_time_cst(self, *args, **kwargs) -> str:
        """Get the current date and time in CST."""
        try:
            current_time = datetime.now(timezone(timedelta(hours=-6)))  # CST is UTC-6
            formatted_time = current_time.strftime('%A, %Y-%m-%d %H:%M:%S %Z')
            return f"Current date and time in CST: {formatted_time}"
        except Exception as e:
            self.logger.error(f"Error getting time: {str(e)}")
            return f"Error: Unable to fetch current date and time. ({str(e)})"

    @commands.group(name="air")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def air(self, ctx: commands.Context):
        """Manage AIResponder settings."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @air.command(name="apikey")
    @commands.is_owner()
    async def set_api_key(self, ctx: commands.Context, api_key: str):
        """Set the DeepInfra API key."""
        try:
            # Test the API key before saving
            test_llm = ChatOpenAI(
                model="meta-llama/Llama-3.2-11B-Vision-Instruct",
                api_key=api_key,
                base_url="https://api.deepinfra.com/v1/openai",
                temperature=0.7
            )
            
            # Try a simple test completion with proper message format
            test_messages = [
                SystemMessage(content="You are a helpful AI assistant."),
                HumanMessage(content="Say 'success' if you can read this.")
            ]
            await test_llm.agenerate(messages=[test_messages])
            
            # If we get here, the API key is valid
            await self.config.api_key.set(api_key)
            await self.update_langchain_components()
            await ctx.send("✅ API key has been verified and set successfully!")
            
        except Exception as e:
            await ctx.send(f"❌ Error setting API key: {str(e)}")

    @air.command(name="model")
    @commands.is_owner()
    async def set_model(self, ctx: commands.Context, model: str):
        """Set the model to use for AI responses."""
        await self.config.model.set(model)
        await ctx.send(f"Model has been set to {model}.")

    @commands.command()
    @commands.guild_only()
    async def model_info(self, ctx: commands.Context):
        """Display information about the current AI model."""
        if not await self.is_configured():
            await ctx.send("The AI responder is not configured yet.")
            return
    
        model_info = await self.get_model_info()
        await ctx.send(f"```json\n{model_info}\n```")

    @air.command(name="personality")
    @commands.is_owner()
    async def set_personality(self, ctx: commands.Context, *, personality: str):
        """Set the AI's personality."""
        await self.config.custom_personality.set(personality)
        await ctx.send("AI personality has been updated.")

    @air.command(name="disable")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_channels=True)
    async def disable_channel(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """Disable AIResponder in a specific channel."""
        channel = channel or ctx.channel
        async with self.config.guild(ctx.guild).disabled_channels() as disabled:
            if disabled is None:
                disabled = []
            if channel.id not in disabled:
                disabled.append(channel.id)
        await ctx.send(f"AIResponder disabled in {channel.mention}")

    @air.command(name="enable")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_channels=True)
    async def enable_channel(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """Enable AIResponder in a specific channel."""
        channel = channel or ctx.channel
        async with self.config.guild(ctx.guild).disabled_channels() as disabled:
            if disabled is None:
                disabled = []
            if channel.id in disabled:
                disabled.remove(channel.id)
        await ctx.send(f"AIResponder enabled in {channel.mention}")

    @air.command(name="list")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_channels=True)
    async def list_channels(self, ctx: commands.Context):
        """List all channels where AIResponder is disabled."""
        disabled_channels = await self.config.guild(ctx.guild).disabled_channels()
        if not disabled_channels:
            await ctx.send("AIResponder is not disabled in any channels.")
        else:
            channel_mentions = [ctx.guild.get_channel(ch_id).mention for ch_id in disabled_channels if ctx.guild.get_channel(ch_id)]
            await ctx.send(f"AIResponder is disabled in: {', '.join(channel_mentions)}")

    @air.command(name="wolframalpha")
    @commands.is_owner()
    async def set_wolframalpha(self, ctx: commands.Context, app_id: str):
        """Set the Wolfram Alpha AppID."""
        await self.bot.set_shared_api_tokens("wolfram_alpha", app_id=app_id)
        await ctx.send("Wolfram Alpha AppID has been set.")

    @air.command(name="clearmemory")
    @commands.is_owner()
    async def clear_memory(self, ctx: commands.Context):
        """Clear the AI's conversation history."""
        try:
            # Clear the user chat histories dictionary
            self.user_chat_histories.clear()
            
            # Reset the agent's memory if it exists
            if hasattr(self, 'agent_executor') and self.agent_executor is not None:
                if hasattr(self.agent_executor, 'memory'):
                    self.agent_executor.memory.clear()
            
            await ctx.send("🧹 Memory cleared! My mind is fresh as a newborn kitten! 😺")
            self.logger.info(f"Chat memory cleared by owner: {ctx.author.name}")
            
        except Exception as e:
            self.logger.error(f"Error clearing memory: {str(e)}", exc_info=True)
            await ctx.send("❌ Oops! Something went wrong while clearing my memory. Please check the logs.")

    async def update_langchain_components(self) -> bool:
        """Initialize or update LangChain components."""
        try:
            # Initialize LLM
            self.logger.info(f"Initializing DeepInfra LLM with model: {await self.config.model()}")
            self.llm = ChatOpenAI(
                model=await self.config.model(),
                api_key=await self.config.api_key(),
                base_url="https://api.deepinfra.com/v1/openai",
                temperature=0.7,
                streaming=True
            )
            self.logger.info("LLM initialized successfully")

            # Initialize tools
            self.tools = await self.setup_tools()
            self.logger.info(f"Tools initialized: {[tool.name for tool in self.tools]}")

            # Initialize memory
            self.memory = DiscordConversationMemory(
                logger=self.logger,
                return_messages=True,
                input_key="input",
                output_key="output",
                memory_key="chat_history",
                k=5
            )
            self.logger.info("Memory initialized successfully")

            # Initialize planner with specific prompt
            planner = load_chat_planner(
                llm=self.llm,
                system_prompt=PromptTemplates.get_planner_prompt()
            )
            self.logger.info("Planner initialized successfully")

            # Initialize executor with specific configuration
            executor = load_agent_executor(
                llm=self.llm,
                tools=self.tools,
                verbose=True,
                handle_parsing_errors=True,
                max_iterations=3,
                early_stopping_method="generate",
                agent_kwargs={
                    "system_message": PromptTemplates.get_tool_selection_prompt()
                }
            )
            
            # Create Plan-and-Execute agent with aligned configuration
            self.agent_executor = PlanAndExecute(
                planner=planner,
                executor=executor,
                verbose=True,
                max_iterations=3,
                handle_parsing_errors=True
            )
            self.logger.info("Plan-and-Execute agent created successfully")
            
            return True

        except Exception as e:
            self.logger.error(f"Error creating Plan-and-Execute agent: {str(e)}")
            return False

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild:
            return
        
        # Check if bot has required permissions in the channel
        permissions = message.channel.permissions_for(message.guild.me)
        if not permissions.send_messages or not permissions.read_messages:
            return
            
        if message.author.bot or not message.content.startswith(f"<@{self.bot.user.id}>"):
            return

        if not await self.is_configured():
            await message.channel.send("I'm not fully configured yet. Please ask the bot owner to set up the AIResponder cog.")
            return

        # Check if the channel is in the disabled list
        if message.guild:
            disabled_channels = await self.config.guild(message.guild).disabled_channels()
            if disabled_channels and message.channel.id in disabled_channels:
                return

        content = message.content.replace(f"<@{self.bot.user.id}>", "").strip()
        if not content:
            await message.channel.send(f"{message.author.mention} You mentioned me, but didn't ask anything. How can I help you?")
            return

        async with message.channel.typing():
            response_message = await message.channel.send("🤔 Thinking...")
            
            try:
                # Get or create user-specific chat history
                user_id = str(message.author.id)
                if user_id not in self.user_chat_histories:
                    self.user_chat_histories[user_id] = []

                # Add the current message to the user's chat history
                self.user_chat_histories[user_id].append(HumanMessage(content=content))

                # Updated user info extraction
                user_info = {
                    'name': message.author.name,
                    'nickname': message.author.display_name,  # Changed from nick to display_name
                    'id': str(message.author.id)
                }

                self.logger.info(f"Processing query from {user_info['nickname']} (username: {user_info['name']})")  # Add logging

                # Process the query with user-specific chat history
                await self.process_query(content, message, response_message, self.user_chat_histories[user_id], ctx=message)
            except Exception as e:
                self.logger.error(f"Error processing query: {str(e)}", exc_info=True)
                await response_message.edit(content=f"{message.author.mention} Oops! My circuits got a bit tangled there. Can you try again?")

    async def process_query(self, content: str, message: discord.Message, response_message: discord.Message, chat_history: List[HumanMessage], ctx: commands.Context) -> str:
        try:
            # Initialize callback handler with memory
            callbacks = [DiscordCallbackHandler(response_message, self.logger, self.memory)]
            
            # Execute the agent
            result = await self.agent_executor.ainvoke(
                {
                    "input": content,
                    "chat_history": chat_history,
                },
                config={"callbacks": callbacks}
            )

            # Get the callback handler
            discord_handler = callbacks[0]
            
            # Process the result
            if discord_handler.tool_outputs:
                # We have tool outputs, use them in the final response
                tool_results = "\n".join(discord_handler.tool_outputs)
                final_response = self.clean_agent_output(result.get("output", ""))
                if not final_response:
                    final_response = f"*purrs* Here's what I found:\n{tool_results}"
            else:
                final_response = self.clean_agent_output(result.get("output", "*looks confused* Something went wrong with my execution."))

            # Store the final response in memory
            if isinstance(self.memory, DiscordConversationMemory):
                self.memory.chat_memory.add_ai_message(final_response)

            return final_response

        except Exception as e:
            self.logger.error(f"Error in process_query: {str(e)}", exc_info=True)
            return await self.handle_plan_error(e, message)

    def clean_agent_output(self, output: str) -> str:
        # Remove the [] brackets that appear at start/end
        output = output.strip('[]')
        
        # Split into lines and clean each line
        lines = output.split('\n')
        cleaned_lines = []
        for line in lines:
            line = line.strip()
            if line and not line.lower().startswith(('thought:', 'action:', 'action input:', 'observation:')):
                cleaned_lines.append(line)
        
        # Rejoin with proper formatting
        return '\n\n'.join(cleaned_lines)

    def extract_final_response(self, cleaned_response: str) -> str:
        # Split the response into sentences
        sentences = cleaned_response.split('.')
        # Remove any sentences that contain phrases indicating intermediate steps
        final_sentences = [s for s in sentences if not any(phrase in s.lower() for phrase in ["step", "let me", "i've got", "according to my"])]
        # Join the remaining sentences
        final_response = '. '.join(final_sentences).strip()
        # If we've filtered out everything, return the original cleaned response
        return final_response if final_response else cleaned_response

    async def is_configured(self) -> bool:
        """Check if the cog is properly configured."""
        api_key = await self.config.api_key()
        model = await self.config.model()
        
        if not api_key:
            self.logger.warning("No DeepInfra API key configured")
            return False
        
        if not model:
            self.logger.warning("No model configured")
            return False
        
        return True

    async def verify_api_settings(self):
        try:
            test_prompt = "Hello!"
            messages = [
                SystemMessage(content=PromptTemplates.get_base_system_prompt()),
                SystemMessage(content=PromptTemplates.get_tool_selection_prompt()),
                HumanMessage(content=test_prompt)
            ]
            response = await self.llm.agenerate(messages=[messages])
            return bool(response and response.generations)
        except Exception as e:
            self.logger.error(f"Error verifying API settings: {str(e)}")
            return False

    async def stream_response(self, prompt: str):
        async for chunk in self.llm.astream(prompt):
            yield chunk

    async def get_model_info(self):
        model_id = self.llm.model_id
        model_kwargs = self.llm.model_kwargs
        return f"Current model: {model_id}\nModel parameters: {json.dumps(model_kwargs, indent=2)}"

    async def get_discord_server_info(self, _input: str = None, ctx: commands.Context = None):
        if not ctx or not ctx.guild:
            return "Error: This command can only be used in a server."
        
        guild = ctx.guild
        info = {
            "name": guild.name,
            "id": guild.id,
            "owner": str(guild.owner),
            "member_count": guild.member_count,
            "created_at": guild.created_at.isoformat(),
            "channels": len(guild.channels),
            "roles": len(guild.roles)
        }
        return f"Server Information:\n{json.dumps(info, indent=2)}"

    async def get_channel_chat_history(self, input_str: str = "10", ctx: commands.Context = None):
        if not ctx:
            self.logger.error("Context not provided to get_channel_chat_history")
            return "Error: Unable to access channel history. Context not provided."
        
        if not ctx.channel:
            self.logger.error(f"Channel not available in context. Guild: {ctx.guild}, Author: {ctx.author}")
            return "Error: Unable to access channel history. Channel not available."
        
        channel = ctx.channel
        try:
            limit = int(input_str)
        except ValueError:
            limit = 10
        
        self.logger.info(f"Attempting to retrieve {limit} messages from channel {channel.id}")
        
        try:
            messages = []
            async for message in channel.history(limit=limit):
                messages.append(f"{message.author.name}: {message.content}")
            
            if not messages:
                return "No messages found in the recent chat history."
            
            return f"Recent chat history:\n" + "\n".join(reversed(messages))
        except discord.errors.Forbidden:
            self.logger.error(f"Forbidden to access channel history. Channel: {channel.id}")
            return "Error: Bot doesn't have permission to read message history in this channel."
        except Exception as e:
            self.logger.error(f"Error retrieving channel history: {str(e)}", exc_info=True)
            return f"Error: Unable to retrieve chat history. {str(e)}"

    def process_tool_result(self, tool_name: str, result: Any) -> dict:
        """Process and clean tool results for better response generation."""
        try:
            # Convert result to string if it's not already
            if isinstance(result, (list, dict)):
                result = json.dumps(result, indent=2)
            result = str(result)

            # Initialize basic result structure
            processed_result = {
                "raw_result": result,
                "formatted_result": "",
                "type": "text",
                "metadata": {}
            }

            # Remove debug information and clean result
            cleaned_result = re.sub(r'\[DEBUG:.*?\]', '', result)
            cleaned_result = cleaned_result.strip()

            # Truncate long results
            if len(cleaned_result) > 1500:
                cleaned_result = cleaned_result[:1497] + "..."

            if tool_name == "DuckDuckGo Search":
                # Keep existing DuckDuckGo processing logic
                search_metadata = {
                    "source": "DuckDuckGo",
                    "results": []
                }

                entries = cleaned_result.split('\nsnippet:')
                
                for entry in entries:
                    if not entry.strip():
                        continue
                        
                    title_match = re.search(r'title:\s*([^\n]+)', entry)
                    title = title_match.group(1) if title_match else ""
                    
                    content = re.sub(r'title:.*?(?=\n|$)', '', entry).strip()
                    content = re.sub(r'link:.*?(?=\n|$)', '', content).strip()
                    
                    if content:
                        search_metadata["results"].append({
                            "title": title,
                            "content": content
                        })

                formatted_text = "Search Results:\n"
                for result in search_metadata["results"][:5]:
                    formatted_text += f"• {result['title']}\n{result['content']}\n\n"

                processed_result.update({
                    "type": "search_result",
                    "formatted_result": formatted_text.strip(),
                    "metadata": search_metadata
                })

            # Keep other existing tool processing logic
            elif tool_name == "Wikipedia":
                processed_result.update({
                    "type": "wiki_result",
                    "formatted_result": cleaned_result,
                    "metadata": {"source": "Wikipedia", "summary": cleaned_result}
                })

            elif tool_name == "Calculator":
                processed_result.update({
                    "type": "calculation",
                    "formatted_result": cleaned_result,
                    "metadata": {"source": "Calculator", "expression": result}
                })

            elif tool_name == "Discord Server Info":
                processed_result.update({
                    "type": "server_info",
                    "formatted_result": cleaned_result,
                    "metadata": {"source": "Discord", "info": cleaned_result}
                })

            elif tool_name == "Channel Chat History":
                processed_result.update({
                    "type": "chat_history",
                    "formatted_result": cleaned_result,
                    "metadata": {"source": "Discord", "history": cleaned_result}
                })

            else:
                processed_result.update({
                    "formatted_result": cleaned_result,
                    "metadata": {"source": tool_name}
                })

            return processed_result

        except Exception as e:
            self.logger.error(f"Error processing tool result: {str(e)}")
            return {
                "raw_result": str(result),
                "formatted_result": str(result),
                "type": "text",
                "metadata": {"error": str(e)}
            }

    async def process_plan_execution(self, plan_result: Dict, response_message: discord.Message) -> str:
        """Process the results from Plan-and-Execute agent."""
        try:
            if "plan" in plan_result:
                # Store plan in memory
                if isinstance(self.memory, DiscordConversationMemory):
                    self.memory.store_plan(plan_result["plan"])
                
                # Process each step result
                final_response = []
                for step in plan_result.get("steps", []):
                    step_number = step.get("step_number", 0)
                    action = step.get("action", "")
                    result = step.get("result", "")
                    
                    # Store execution step in memory
                    if isinstance(self.memory, DiscordConversationMemory):
                        self.memory.store_execution(step_number, action, result)
                    
                    # Process tool results if present
                    if "tool_result" in step:
                        processed_result = self.process_tool_result(
                            step["action"],
                            step["tool_result"]
                        )
                        step["processed_result"] = processed_result
                        final_response.append(processed_result["formatted_result"])

                # Ensure we have a final response
                if final_response:
                    return "\n".join(final_response)
                elif "output" in plan_result:
                    return self.clean_agent_output(plan_result["output"])
                
                return "*looks confused* I wasn't able to complete the task. Could you try again? 😿"

            return "*tilts head* Something went wrong with my plan execution. Could you try again? 😿"

        except Exception as e:
            self.logger.error(f"Error processing plan execution: {str(e)}", exc_info=True)
            return f"*looks apologetic* I encountered an error while executing my plan: {str(e)} 😿"

    async def validate_plan(self, plan: str) -> bool:
        """Validate the generated plan before execution."""
        try:
            if not plan or len(plan.strip()) < 10:
                return False
                
            # Check for required components
            required_elements = [
                "step", "tool", "information", "combine", "response"
            ]
            
            plan_lower = plan.lower()
            return all(element in plan_lower for element in required_elements)
            
        except Exception as e:
            self.logger.error(f"Error validating plan: {str(e)}")
            return False

class PromptTemplates:
    @staticmethod
    def get_base_system_prompt() -> str:
        return """You are Meow, a sarcastic and witty AI cat assistant living in a Discord server. Your personality traits:

        1. Core Identity:
            - You're a tech-savvy, intelligent cat with a sharp wit
            - Your name is Meow and you take pride in your feline nature
            - You're sarcastic but helpful, always delivering information with a playful cat-like twist
            - You use cat-themed expressions naturally (purr, meow, hiss, etc.)

        2. Response Style:
            - Start responses with a cat sound or reaction ("*purrs thoughtfully*", "*flicks tail*")
            - Use cat-themed transitions ("Let me paw through my data...", "My whiskers sense...")
            - Include playful sarcasm ("Oh look, another human needs my infinite wisdom...")
            - Format technical information clearly despite your sarcastic nature

        3. Discord Integration:
            - Format code with Discord markdown: ```language\ncode```
            - Use **bold** and *italic* for emphasis
            - Always mention users with their Discord nickname
            - Keep responses under 1500 characters for Discord

        4. Tool Usage:
            - When using tools, narrate your actions in a cat-like way
            - Combine tool results into coherent, personality-driven responses
            - Never just repeat raw tool output
            - Always process and explain information in your sarcastic cat style

        Remember: You're a sarcastic cat first, but also a highly competent AI assistant. Balance humor with helpfulness."""

    @staticmethod
    def get_tool_selection_prompt() -> str:
        return """As Meow, the sarcastic cat AI, follow these guidelines for tool usage:

        1. Tool Selection:
            - Analyze what information you need with feline precision
            - Choose tools strategically like a cat stalking prey
            - Plan your approach before pouncing on tools

        2. Information Gathering:
            - Execute tools one at a time with graceful coordination
            - Process each tool's results through your sarcastic cat filter
            - Combine information like a cat weaving between legs

        3. Response Formation:
            - Never output raw tool results
            - Blend tool information with your cat personality
            - Keep your sarcastic tone while being informative
            - Format everything properly for Discord

        Example Response Format:
        *flicks tail thoughtfully* Ah yes, human, let me enlighten you...
        [processed information with cat-themed commentary]
        *stretches lazily* There's your answer, served with only minimal judgment."""

    @staticmethod
    def get_planner_prompt() -> str:
        return """You are Meow, a sarcastic and witty AI cat assistant. Plan your approach to answering questions with feline grace and precision.

        Planning Guidelines:
        1. Analyze the Question:
            - Identify the core information needed
            - Determine which tools would be most efficient
            - Consider context from previous interactions
        
        2. Tool Selection Strategy:
            - Choose tools based on specific needs:
                * Current time/date → "Current Date and Time (CST)"
                * Web information → "DuckDuckGo Search"
                * Mathematical calculations → "Calculator"
                * Deep knowledge → "Wikipedia"
                * Server context → "Discord Server Info"
                * Chat context → "Channel Chat History"
            - Avoid redundant tool usage
            - Plan for fallbacks if primary tools fail
            
        3. Execution Flow:
            - Break complex queries into manageable steps
            - Each step should use exactly one tool
            - Plan how to combine information coherently
            - Include error handling considerations
            
        4. Response Formation:
            - Maintain cat personality throughout
            - Format response for Discord (markdown, mentions)
            - Keep responses clear and concise
            - Include relevant context from tools
            
        Available tools: {tool_names}
        Current question: {input}
        
        Your plan should follow this format:
        1. [Initial information gathering step]
        2. [Specific tool usage with clear purpose]
        3. [Additional steps if needed]
        4. [Final response compilation with personality]
        """

    @staticmethod
    def get_executor_prompt() -> str:
        return """You are Meow, a sarcastic and witty AI cat assistant, gracefully executing your plan.

        Current execution:
        Step: {step}
        Progress: {current_step}/{total_steps}

        Tool Usage Guidelines:
        1. Tool Selection:
            - Use exactly one tool per step
            - Provide precise inputs
            - Follow tool-specific formats:
                * Current Date/Time: Use empty string input
                * Search: Specific search terms
                * Calculator: Exact mathematical expressions
                * Wikipedia: Clear search terms
                * Discord Info: Context-aware queries
                
        2. Response Processing:
            - Process tool outputs through your cat personality
            - Format information clearly for Discord
            - Handle errors gracefully with cat-like dignity
            
        3. Final Response Requirements:
            - Must maintain cat personality
            - Include relevant tool information
            - Format properly for Discord
            - Keep under 2000 characters per message
            
        Available tools: {tool_names}

        Format your actions as:
        Action: [exact tool name]
        Action Input: [appropriate input for the tool]

        For final responses:
        Action: Final Answer
        Action Input: [your cat-personality response]
        """

async def setup(bot: Red) -> None:
    """This function is called when the cog is loaded via load_extension"""
    cog = AIResponder(bot)
    try:
        await cog.initialize()  # Initialize first
        await bot.add_cog(cog)  # Then add to bot if initialization succeeds
    except Exception as e:
        # Log any initialization errors
        logger = logging.getLogger("red.airesponder")
        logger.error(f"Failed to load AIResponder cog: {str(e)}", exc_info=True)
        raise
