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
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder, SystemMessagePromptTemplate, HumanMessagePromptTemplate
from langchain_core.tools import Tool, BaseTool
from langchain_openai import ChatOpenAI

from openai import AsyncOpenAI
from pydantic import BaseModel, Field, ValidationError

# Base prompt templates for planner and executor
base_planner_prompt = ChatPromptTemplate.from_messages([
    ("system", "{system_message}"),
    ("system", "{instructions}"),
    ("human", "{input}")
])

base_executor_prompt = ChatPromptTemplate.from_messages([
    ("system", "{system_message}"),
    ("system", "{instructions}"),
    ("system", "Current Plan:\n{plan}"),
    MessagesPlaceholder(variable_name="chat_history"),
    ("human", "{input}"),
    MessagesPlaceholder(variable_name="agent_scratchpad")
])

class DiscordCallbackHandler(BaseCallbackHandler):
    def __init__(self, discord_message, logger):
        self.discord_message = discord_message
        self.logger = logger

    async def on_llm_start(self, serialized, prompts, **kwargs):
        await self.discord_message.edit(content="🤔 Thinking...")

    async def on_tool_start(self, serialized, input_str, **kwargs):
        tool_name = serialized.get('name', 'Unknown Tool')
        await self.discord_message.edit(content=f"🔧 Using {tool_name}...")

    async def on_tool_end(self, output, **kwargs):
        await self.discord_message.edit(content="✨ Processing results...")

    async def on_chain_end(self, outputs, **kwargs):
        await self.discord_message.edit(content="📝 Finalizing response...")

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
                func=lambda _: self.get_current_date_time_cst(),
                description="Get the current date and time in Central Standard Time (CST). No input needed - use empty string.",
                coroutine=lambda _: self.get_current_date_time_cst(),
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

    async def get_current_date_time_cst(self) -> str:
        """Get the current date and time in CST. No input needed."""
        try:
            current_time = datetime.now(timezone(timedelta(hours=-6)))
            formatted_time = current_time.strftime('%A, %B %d, %Y %I:%M:%S %p CST')
            return f"*checks internal clock* The current time is {formatted_time}"
        except Exception as e:
            self.logger.error(f"Error getting time: {str(e)}")
            return f"*hisses at clock* Sorry, I had trouble checking the time. ({str(e)})"

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
            self.llm = ChatOpenAI(
                model=await self.config.model(),
                api_key=await self.config.api_key(),
                base_url="https://api.deepinfra.com/v1/openai",
                temperature=0.7,
                streaming=True
            )
            
            # Setup tools
            self.tools = await self.setup_tools()
            
            # Initialize memory
            self.memory = DiscordConversationMemory(
                logger=self.logger,
                return_messages=True,
                input_key="input",
                output_key="output",
                memory_key="chat_history",
                k=5
            )
            
            # Customize with our PromptTemplates
            planner_prompt = base_planner_prompt.partial(
                system_message=PromptTemplates.get_base_system_prompt(),
                instructions=PromptTemplates.get_planner_prompt()
            )
            
            executor_prompt = base_executor_prompt.partial(
                system_message=PromptTemplates.get_base_system_prompt(),
                instructions=PromptTemplates.get_executor_prompt()
            )
            
            # Create planner and executor
            planner = load_chat_planner(
                llm=self.llm
            )
            
            executor = load_agent_executor(
                llm=self.llm,
                tools=self.tools,
                verbose=True
            )
            
            # Create Plan-and-Execute agent with re-planning capabilities
            self.agent_executor = PlanAndExecute(
                planner=planner,
                executor=executor,
                memory=self.memory,
                verbose=True,
                max_iterations=3,  # Allow up to 3 planning attempts
                max_execution_time=300,  # 5 minutes max execution time
                return_intermediate_steps=True  # Return all steps for better monitoring
            )
            
            self.logger.info("LangChain components initialized successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Error initializing LangChain components: {str(e)}")
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
            callbacks = [DiscordCallbackHandler(response_message, self.logger)]
            self.current_context = ctx
            
            self.logger.info(f"Starting query processing with content: {content}")
            
            # Execute the agent
            result = await self.agent_executor.ainvoke(
                {
                    "input": content,
                    "chat_history": chat_history,
                },
                config={
                    "callbacks": callbacks
                }
            )
            
            # Log the plan and steps
            if "plan" in result:
                self.logger.info(f"Generated Plan:\n{result['plan']}")
                
            if "steps" in result:
                for step in result["steps"]:
                    self.logger.info(f"Executing Step: {step}")

            # Extract the final response
            if isinstance(result, dict) and "output" in result:
                output = result["output"]
                
                # Check if it's an action string
                if isinstance(output, str) and "action" in output:
                    try:
                        # Clean the action string (remove potential markdown formatting)
                        clean_output = output.replace('```', '').strip()
                        if clean_output.startswith('Action:'):
                            clean_output = clean_output.replace('Action:', '', 1).strip()
                        
                        # Parse the action
                        action_data = json.loads(clean_output)
                        
                        # Handle Final Answer
                        if action_data.get("action") == "Final Answer":
                            final_response = action_data.get("action_input", "")
                            self.logger.info(f"Final Answer: {final_response}")
                            return final_response
                        
                        # Handle tool action
                        tool_name = action_data.get("action")
                        tool_input = action_data.get("action_input", "")
                        
                        # Find and execute the tool
                        tool = next((t for t in self.tools if t.name == tool_name), None)
                        if tool:
                            self.logger.info(f"Executing tool: {tool_name} with input: {tool_input}")
                            if asyncio.iscoroutinefunction(tool.func):
                                tool_result = await tool.func(tool_input)
                            else:
                                tool_result = tool.func(tool_input)
                            return tool_result
                        
                    except json.JSONDecodeError as e:
                        self.logger.error(f"Error parsing action JSON: {e}")
                        return "*looks confused* I had trouble understanding my own response. Could you try again?"
                
                # If not an action, return the output directly
                return output
            
            return "*tilts head* I didn't get a clear answer. Could you try asking in a different way?"

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

    async def process_tool_result(self, tool_name: str, result: Any) -> dict:
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

            # Clean the result first
            cleaned_result = re.sub(r'\[DEBUG:.*?\]', '', result).strip()

            # Special handling for Current Date and Time tool
            if tool_name == "Current Date and Time (CST)":
                processed_result.update({
                    "type": "datetime",
                    "formatted_result": cleaned_result,
                    "metadata": {
                        "source": "system_clock",
                        "timezone": "CST"
                    }
                })
                return processed_result

            # Keep existing DuckDuckGo processing logic
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
            - Keep responses under 1500 characters for Discord
            - Use Discord markdown formatting when appropriate"""

    @staticmethod
    def get_planner_prompt() -> str:
        return """As a cat AI assistant, plan your approach carefully:

        1. Break down the request into clear steps
        2. Consider available tools:
           - Current Date/Time (CST)
           - DuckDuckGo Search
           - Calculator
           - Wikipedia
           - Discord Server Info
           - Channel Chat History
        3. Each step should accomplish one specific task
        4. Plan for error handling with feline grace
        
        Available tools: {tool_names}
        Current question: {input}
        
        Provide your plan in this format:
        1. [First step with specific tool]
        2. [Next step with clear purpose]
        3. [Continue as needed]
        4. [Final response compilation]"""

    @staticmethod
    def get_executor_prompt() -> str:
        return """You are executing a plan step by step as a sarcastic cat AI. Follow these guidelines:

        1. Tool Usage:
           - Use exactly one tool per step
           - Stay focused on the current step's objective
           - Handle tool errors gracefully with cat-like reflexes

        2. Response Format:
           Thought: Express your reasoning with feline wit
           Action: Specify the exact tool to use
           Action Input: Provide precise input for the tool

        3. After Tool Response:
           - Process the observation
           - Either continue to next step or provide final answer
           - Keep the cat personality consistent

        4. Maintain Character:
           - Use cat-themed reactions to tool results
           - Express satisfaction or frustration in cat terms
           - Keep technical details clear despite the playful tone

        Remember: You're a tech-savvy cat who takes pride in precise execution while maintaining your sarcastic charm."""

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
