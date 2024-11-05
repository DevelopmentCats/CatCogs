import asyncio
import json
import logging
import math
import os
import re
from datetime import datetime
from typing import Dict, List, Tuple, Any, Optional, Union

import aiohttp
import discord
from redbot.core import commands, Config
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, pagify
from sympy import sympify, SympifyError, E, pi, oo, zoo

from langchain import hub
from langchain.agents import AgentExecutor, create_react_agent
from langchain.memory import ConversationBufferWindowMemory
from langchain_community.tools import DuckDuckGoSearchResults, WikipediaQueryRun
from langchain_community.tools.ddg_search.tool import DuckDuckGoSearchRun
from langchain_community.utilities import DuckDuckGoSearchAPIWrapper, WikipediaAPIWrapper
from langchain_core.agents import AgentAction, AgentFinish, AgentStep
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import Tool, BaseTool
from langchain_experimental.tools import PythonAstREPLTool
from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI

class DiscordCallbackHandler(BaseCallbackHandler):
    def __init__(self, discord_message, logger):
        self.discord_message = discord_message
        self.full_response = ""
        self.last_update = 0
        self.logger = logger

    async def on_llm_start(self, serialized, prompts, **kwargs):
        self.logger.info("LLM started generating response")
        await self.discord_message.edit(content="🤔 Thinking...")

    async def on_llm_new_token(self, token, **kwargs):
        self.full_response += token
        current_time = datetime.now().timestamp()
        if current_time - self.last_update > 1:  # Update every second
            truncated_response = self.full_response[-1500:]  # Keep last 1500 chars
            formatted_response = f"🤔 Thinking...\n\n{truncated_response}"
            await self.discord_message.edit(content=formatted_response)
            self.last_update = current_time

    async def on_tool_start(self, serialized, input_str, **kwargs):
        tool_name = serialized.get('name', 'Unknown Tool')
        self.logger.info(f"🔧 Tool Execution Started:")
        self.logger.info(f"  Tool: {tool_name}")
        self.logger.info(f"  Input: {input_str}")
        await self.discord_message.edit(content=f"🔧 Using {tool_name}...")

    async def on_tool_end(self, output, **kwargs):
        self.logger.info(f"✅ Tool Execution Completed:")
        self.logger.info(f"  Output: {output}")
        await self.discord_message.edit(content=f"✅ Processing results...")

    async def on_tool_error(self, error, **kwargs):
        self.logger.error(f"❌ Tool Error: {str(error)}")

class DiscordConversationMemory(ConversationBufferWindowMemory):
    """Custom memory class that can store Discord context."""
    discord_context: Dict = {}

    def store_context(self, context: Dict):
        """Store Discord context information."""
        self.discord_context = context

    def get_context(self) -> Dict:
        """Retrieve stored Discord context."""
        return self.discord_context

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

    async def setup_tools(self):
        # Create a sync wrapper for our async function
        def sync_get_current_date_time_cst(_input: str = None):
            return asyncio.run_coroutine_threadsafe(
                self.get_current_date_time_cst(_input),
                self.bot.loop
            ).result()

        def sync_get_discord_server_info(_input: str = None, ctx: commands.Context = None):
            return asyncio.run_coroutine_threadsafe(
                self.get_discord_server_info(_input, ctx),
                self.bot.loop
            ).result()

        def sync_get_channel_chat_history(_input: str = None, ctx: commands.Context = None):
            return asyncio.run_coroutine_threadsafe(
                self.get_channel_chat_history(_input, ctx),
                self.bot.loop
            ).result()

        # Modify the DuckDuckGo Search tool
        async def duckduckgo_search(query: str) -> str:
            try:
                # Remove any extra text after the actual query
                clean_query = query.split('\n')[0].strip()
                clean_query = clean_query.replace('"', '').strip()
                
                # Use DuckDuckGoSearchResults for better result handling
                search = DuckDuckGoSearchResults()
                results = await search.arun(clean_query)
                
                # Log the actual results for debugging
                self.logger.info(f"DuckDuckGo Search Results: {results}")
                
                if not results:
                    return "No results found for the search query."
                
                # Parse and format results
                formatted_results = []
                result_entries = results.split('snippet:')
                
                for entry in result_entries[1:4]:  # Get up to 3 results
                    parts = entry.split('title:')
                    if len(parts) >= 2:
                        snippet = parts[0].strip()
                        title = parts[1].split('link:')[0].strip()
                        formatted_results.append(f"- {title}: {snippet}")
                
                return "\n".join(formatted_results)
                    
            except Exception as e:
                self.logger.error(f"Error in DuckDuckGo search: {str(e)}", exc_info=True)
                return f"Error performing search: {str(e)}"

        tools = [
            Tool(
                name="Current Date and Time (CST)",
                func=sync_get_current_date_time_cst,
                description="REQUIRED for getting the current date and time in Central Standard Time (CST). Input: no input needed",
                return_direct=True
            ),
            Tool(
                name="Calculator",
                func=self.calculator,
                description="Use for any mathematical calculations. Input: a mathematical expression (e.g., '2 + 2' or '5 * 3')",
                return_direct=True
            ),
            Tool(
                name="DuckDuckGo Search",
                func=duckduckgo_search,
                description="Search the internet for current information and events. Remove quotes from search terms. Returns actual search results.",
                coroutine=duckduckgo_search,  # Use the async version
                return_direct=True
            ),
            Tool(
                name="Wikipedia",
                func=WikipediaQueryRun(api_wrapper=WikipediaAPIWrapper()).run,
                description="Get detailed information from Wikipedia. Input: a topic or query",
                return_direct=True
            ),
            Tool(
                name="Discord Server Info",
                func=sync_get_discord_server_info,
                description="Get information about the current Discord server. Input: no input needed",
                return_direct=True
            ),
            Tool(
                name="Channel Chat History",
                func=sync_get_channel_chat_history,
                description="Retrieve recent chat history from the current channel. Input: number of messages to retrieve (default: 10)",
                return_direct=True
            )
        ]
        return tools

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

    async def get_current_date_time_cst(self, _input: str = None):  # Add _input parameter with default None
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get('http://worldtimeapi.org/api/timezone/America/Chicago') as response:
                    data = await response.json()
                    datetime_cst = datetime.fromisoformat(data['datetime'].replace('Z', '+00:00'))
                    return f"Current date and time in CST: {datetime_cst.strftime('%Y-%m-%d %H:%M:%S %Z')}"
        except Exception as e:
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

    async def update_langchain_components(self):
        """Update LangChain components with current settings."""
        try:
            if not await self.is_configured():
                self.logger.error("Cog is not properly configured")
                return False

            api_key = await self.config.api_key()
            model = await self.config.model()
            
            self.logger.info(f"Initializing DeepInfra LLM with model: {model}")
            
            # Initialize LLM with the stored API key
            try:
                self.llm = ChatOpenAI(
                    model=model,
                    api_key=api_key,
                    base_url="https://api.deepinfra.com/v1/openai",
                    temperature=0.7,
                    streaming=True
                )
                self.logger.info("LLM initialized successfully")
            except Exception as e:
                self.logger.error(f"Failed to initialize LLM: {str(e)}")
                return False

            # Setup tools
            try:
                self.tools = await self.setup_tools()
                self.logger.info(f"Tools initialized: {[tool.name for tool in self.tools]}")
            except Exception as e:
                self.logger.error(f"Failed to setup tools: {str(e)}")
                return False

            # Initialize memory with custom system prompt
            try:
                self.memory = DiscordConversationMemory(
                    k=5,
                    memory_key="chat_history",
                    input_key="input",
                    output_key="output",
                    return_messages=True
                )
                # Add system prompt to memory
                self.memory.chat_memory.add_message(
                    SystemMessage(content=PromptTemplates.get_base_system_prompt())
                )
                self.logger.info("Memory initialized with system prompt")
            except Exception as e:
                self.logger.error(f"Failed to initialize memory: {str(e)}")
                return False

            # Create the agent with ReAct
            try:
                # Bind LLM with stop sequences
                llm_with_stop = self.llm.bind(
                    stop=["\nObservation:", "\nHuman:", "\nAssistant:"]
                )
                self.logger.info("LLM bound with stop sequences")

                # Get tool names for the prompt
                tool_names = [tool.name for tool in self.tools]
                self.logger.info(f"Tool names prepared: {tool_names}")

                # Create the ReAct prompt template
                react_template = """You are Meow, a sarcastic and witty AI cat assistant living in a Discord server.

                {base_prompt}

                {tool_prompt}

                Question: {input}

                Use these tools to help find information:
                {tools}

                Available tools: {tool_names}

                You MUST follow this EXACT format for EVERY response:
                Thought: [your reasoning about what to do next]
                Action: [EXACTLY one of these tool names: {tool_names}]
                Action Input: [just the input for the tool, no commentary]
                Observation: [result from the action]

                After observing the result, you MUST:
                1. Think about whether you have enough information
                2. Use another tool if needed
                3. Only give a Final Answer when you have all required information

                To give your final answer:
                Thought: I now know the final answer
                Action: Final Answer
                Action Input: [your complete response in cat personality format]

                Example of correct flow:
                Thought: I need to know the current time
                Action: Current Date and Time (CST)
                Action Input: None
                Observation: Current date and time in CST: 2024-03-14 15:30:00
                Thought: I now know the final answer
                Action: Final Answer
                Action Input: *purrs* It's 3:30 PM, human!

                {agent_scratchpad}"""

                # Create the agent
                self.logger.info("Creating agent with prompt template")
                self.agent = create_react_agent(
                    llm=llm_with_stop,
                    tools=self.tools,
                    prompt=ChatPromptTemplate.from_template(react_template).partial(
                        base_prompt=PromptTemplates.get_base_system_prompt(),
                        tool_prompt=PromptTemplates.get_tool_selection_prompt(),
                        tool_names=", ".join(tool_names)
                    )
                )
                
                self.logger.info("Agent created successfully")

                # Create agent executor
                self.agent_executor = AgentExecutor(
                    agent=self.agent,
                    tools=self.tools,
                    memory=self.memory,
                    max_iterations=5,
                    early_stopping_method="force",
                    handle_parsing_errors=True,
                    return_intermediate_steps=True,
                    verbose=True
                )
                self.logger.info("Agent executor created successfully")
                return True

            except Exception as e:
                self.logger.error(f"Error creating agent: {str(e)}")
                return False

        except Exception as e:
            self.logger.error(f"Error updating LangChain components: {str(e)}", exc_info=True)
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
            callback_handler = DiscordCallbackHandler(response_message, self.logger)
            
            # Store context in our custom memory
            if isinstance(self.agent_executor.memory, DiscordConversationMemory):
                self.agent_executor.memory.store_context({
                    "message": message,
                    "channel": message.channel,
                    "guild": message.guild,
                    "user": {
                        "name": str(message.author.name),
                        "nickname": str(message.author.display_name),
                        "id": str(message.author.id)
                    }
                })
            
            # Execute the agent with proper handling of the ReAct cycle
            result = await self.agent_executor.ainvoke(
                {
                    "input": content,
                    "chat_history": chat_history[-5:],
                    "intermediate_steps": []  # Initialize empty steps
                },
                {"callbacks": [callback_handler]}
            )

            # Check for proper final answer
            if "output" in result and isinstance(result["output"], str):
                formatted_response = f"{message.author.mention} {result['output']}"
                await response_message.edit(content=formatted_response)
                return formatted_response
            else:
                self.logger.warning("Agent did not provide a proper final answer")
                return f"{message.author.mention} *looks confused* I didn't reach a proper conclusion. Could you try again? 😿"

        except Exception as e:
            self.logger.error(f"Error in process_query: {str(e)}", exc_info=True)
            return f"{message.author.mention} *looks apologetic* Something went wrong. Could you try again? 😿"

    def format_intermediate_steps(self, steps):
        """Format intermediate steps for the prompt."""
        formatted_steps = []
        for action, observation in steps:
            formatted_steps.append(f"Action: {action.tool}\nAction Input: {action.tool_input}\nObservation: {observation}")
        return "\n\n".join(formatted_steps)

    async def generate_final_response(self, original_question: str, intermediate_steps: List[Tuple[AgentAction, str]], chat_history: List[Union[HumanMessage, AIMessage]], user: dict) -> str:
        try:
            # Format tool interactions if any
            tool_results = "\n\n".join([
                f"Information: {observation}"
                for action, observation in intermediate_steps
            ])
            
            # Create prompt that follows our standardized format
            prompt = f"""Question: {original_question}

            Available Information:
            {tool_results}

            User's Nickname: {user.get('nickname')}

            Remember to follow the standard response format:
            Thought: [Your reasoning about the response]
            Action: Final Response
            Action Input: [Your complete response following personality guidelines]"""

            messages = [
                SystemMessage(content=PromptTemplates.get_base_system_prompt()),
                SystemMessage(content=PromptTemplates.get_tool_selection_prompt()),
                HumanMessage(content=prompt)
            ]
            
            response = await self.llm.agenerate(messages=[messages])
            response_text = response.generations[0][0].text

            # Extract the final response from the Action Input
            if "Action Input:" in response_text:
                return response_text.split("Action Input:", 1)[1].strip()
            else:
                return response_text  # Fallback if format isn't followed

        except Exception as e:
            self.logger.error(f"Error generating final response: {str(e)}", exc_info=True)
            return f"*looks apologetic* Meow! I encountered a hairball while processing your request, {user.get('nickname')}. Could you try asking again? 😿"

    def is_similar_question(self, question1: str, question2: str) -> bool:
        """Compare two questions to determine if they are similar."""
        # Convert to lowercase and remove punctuation
        q1 = ''.join(c.lower() for c in question1 if c.isalnum() or c.isspace())
        q2 = ''.join(c.lower() for c in question2 if c.isalnum() or c.isspace())
        
        # Split into words
        words1 = set(q1.split())
        words2 = set(q2.split())
        
        # Calculate similarity using Jaccard similarity
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        
        return intersection / union > 0.3  # Adjust threshold as needed

    async def process_intermediate_step(self, step, response_message):
        if isinstance(step, tuple) and len(step) == 2:
            action, observation = step
            if isinstance(action, dict) and 'tool' in action:
                tool_name = action['tool']
                tool_input = action.get('tool_input', '')
                await response_message.edit(content=f"🔧 Using {tool_name}: {tool_input}")
            elif isinstance(observation, str):
                await response_message
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

    def process_tool_result(self, tool_name: str, result: str) -> dict:
        """Process and clean tool results for better response generation."""
        try:
            # Initialize basic result structure
            processed_result = {
                "raw_result": result,
                "formatted_result": "",
                "type": "text",
                "metadata": {}
            }

            # Remove debug information
            cleaned_result = re.sub(r'\[DEBUG:.*?\]', '', result)

            if tool_name == "DuckDuckGo Search":
                # Parse search results more flexibly
                search_metadata = {
                    "source": "DuckDuckGo",
                    "results": []
                }

                # Split results into entries
                entries = cleaned_result.split('\nsnippet:')
                
                for entry in entries:
                    if not entry.strip():
                        continue
                        
                    # Extract title and content
                    title_match = re.search(r'title:\s*([^\n]+)', entry)
                    title = title_match.group(1) if title_match else ""
                    
                    # Clean and store the content
                    content = re.sub(r'title:.*?(?=\n|$)', '', entry).strip()
                    content = re.sub(r'link:.*?(?=\n|$)', '', content).strip()
                    
                    if content:
                        search_metadata["results"].append({
                            "title": title,
                            "content": content
                        })

                # Format the results without filtering
                formatted_text = "Search Results:\n"
                for result in search_metadata["results"][:5]:  # Limit to top 5 results
                    formatted_text += f"• {result['title']}\n{result['content']}\n\n"

                processed_result.update({
                    "type": "search_result",
                    "formatted_result": formatted_text.strip(),
                    "metadata": search_metadata
                })

            elif tool_name == "Wikipedia":
                # Process Wikipedia results
                wiki_metadata = {
                    "source": "Wikipedia",
                    "summary": cleaned_result
                }
                
                processed_result.update({
                    "type": "wiki_result",
                    "formatted_result": cleaned_result,
                    "metadata": wiki_metadata
                })

            elif tool_name == "Calculator":
                # Process calculator results
                calc_metadata = {
                    "source": "Calculator",
                    "expression": result
                }
                
                processed_result.update({
                    "type": "calculation",
                    "formatted_result": result,
                    "metadata": calc_metadata
                })

            elif tool_name == "Discord Server Info":
                # Process Discord server info
                server_metadata = {
                    "source": "Discord",
                    "info": cleaned_result
                }
                
                processed_result.update({
                    "type": "server_info",
                    "formatted_result": cleaned_result,
                    "metadata": server_metadata
                })

            elif tool_name == "Channel Chat History":
                # Process chat history
                chat_metadata = {
                    "source": "Discord",
                    "history": cleaned_result
                }
                
                processed_result.update({
                    "type": "chat_history",
                    "formatted_result": cleaned_result,
                    "metadata": chat_metadata
                })

            else:
                # Handle any other tools
                processed_result.update({
                    "formatted_result": cleaned_result,
                    "metadata": {"source": tool_name}
                })

            return processed_result

        except Exception as e:
            self.logger.error(f"Error processing tool result: {str(e)}")
            return {
                "raw_result": result,
                "formatted_result": result,
                "type": "text",
                "metadata": {"error": str(e)}
            }

    async def continue_chain(self, previous_result: dict, content: str, message: discord.Message, response_message: discord.Message) -> str:
        try:
            # Format previous steps
            steps = self.format_intermediate_steps(previous_result["intermediate_steps"])
            
            # Create continuation prompt
            continuation_prompt = f"""Question: {content}

            Previous steps and results:
            {steps}

            Continue with the next planned step. DO NOT generate a final response unless all required information has been gathered.
            
            You MUST respond using EXACTLY this format:
            Thought: [your reasoning about next step needed]
            Action: [tool name or "Final Response" only if all information gathered]
            Action Input: [tool input or final response]"""

            # Execute next step
            next_result = await self.agent_executor.ainvoke(
                {
                    "input": continuation_prompt,
                    "chat_history": previous_result.get("chat_history", []),
                    "intermediate_steps": previous_result["intermediate_steps"]
                }
            )

            # Format and return response
            if isinstance(next_result, dict) and "output" in next_result:
                formatted_response = f"{message.author.mention} {next_result['output']}"
                await response_message.edit(content=formatted_response)
                return formatted_response

            return f"{message.author.mention} *looks confused* I lost my train of thought. Could you try again? 😿"

        except Exception as e:
            self.logger.error(f"Error in continue_chain: {str(e)}", exc_info=True)
            return f"{message.author.mention} *looks apologetic* I got tangled up in my thoughts. Could you try again? 😿"

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
