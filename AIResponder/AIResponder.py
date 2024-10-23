import discord
from redbot.core import commands, Config
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, pagify
from typing import Dict, List, Tuple, Any, Optional, Union
import asyncio
import logging
from datetime import datetime
from openai import AsyncOpenAI

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import Tool
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.callbacks import BaseCallbackHandler
from langchain.agents import AgentExecutor, create_openai_functions_agent
from langchain.memory import ConversationBufferWindowMemory
from langchain_community.utilities import DuckDuckGoSearchAPIWrapper, WikipediaAPIWrapper
from langchain_community.tools import DuckDuckGoSearchResults, WikipediaQueryRun
from langchain_experimental.tools import PythonAstREPLTool
from langchain_openai import ChatOpenAI
from langchain_community.tools.ddg_search.tool import DuckDuckGoSearchRun

from sympy import sympify
import os
import json
import aiohttp

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
            # Format the streaming response
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

class AIResponder(commands.Cog):
    def __init__(self, bot: Red):
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

    async def initialize(self):
        try:
            api_key = await self.config.api_key()
            model = await self.config.model()

            if not api_key:
                self.logger.error("API key not set. Please use the 'air apikey' command to set it.")
                return

            self.logger.info(f"Initializing DeepInfra LLM with model: {model}")
            self.llm = ChatOpenAI(
                model=model,
                api_key=api_key,
                base_url="https://api.deepinfra.com/v1/openai",
                temperature=0.7,
                max_tokens=16384,
                streaming=True
            )

            # Set up tools and agent executor
            self.logger.info("Setting up tools")
            tools = await self.setup_tools()
            memory = ConversationBufferWindowMemory(k=5, memory_key="chat_history", return_messages=True)

            custom_personality = await self.config.custom_personality()
            prompt = ChatPromptTemplate.from_messages([
                ("system", f"You are an AI assistant named Meow with the following personality: {custom_personality}. "
                           "You are in a Discord server, responding to user messages. "
                           "Respond naturally and conversationally, as if you're chatting with a friend. "
                           "Always maintain your assigned personality throughout the conversation. "
                           "You have access to tools that can help you answer questions. "
                           "ALWAYS use the 'Current Date and Time (CST)' tool when asked about the current date or time. "
                           "Use other tools when necessary to provide accurate and up-to-date information. "
                           "After using a tool, incorporate the information into your response naturally. "
                           "Be concise and direct in your responses."),
                ("human", "{input}"),
                ("ai", "{agent_scratchpad}")
            ])

            self.logger.info("Creating agent executor")
            try:
                agent = create_openai_functions_agent(llm=self.llm, tools=tools, prompt=prompt)
                self.agent_executor = AgentExecutor(
                    agent=agent,
                    tools=tools,
                    memory=memory,
                    verbose=True,
                    max_iterations=3,
                    early_stopping_method="generate"
                )
                self.logger.info("Agent executor created successfully")
            except Exception as e:
                self.logger.error(f"Error creating agent executor: {str(e)}", exc_info=True)
                self.agent_executor = None

            await self.verify_api_settings()
        except Exception as e:
            self.logger.error(f"Unexpected error in initialize: {str(e)}", exc_info=True)

    async def setup_tools(self):
        tools = [
            Tool(
                name="DuckDuckGo Search",
                func=DuckDuckGoSearchRun().run,
                description="Useful for searching the internet for current information on various topics."
            ),
            Tool(
                name="Wikipedia",
                func=WikipediaQueryRun(api_wrapper=WikipediaAPIWrapper()).run,
                description="Useful for getting detailed information on a wide range of topics."
            ),
            Tool(
                name="Python REPL",
                func=PythonAstREPLTool().run,
                description="Useful for running Python code and performing calculations."
            ),
            Tool(
                name="Calculator",
                func=self.calculator,
                description="Useful for performing basic and advanced mathematical calculations."
            ),
            Tool(
                name="Current Date and Time (CST)",
                func=self.get_current_date_time_cst,
                description="Use this to get the current date and time in Central Standard Time (CST)."
            )
        ]
        return tools

    def calculator(self, expression: str) -> str:
        try:
            cleaned_expression = ''.join(char for char in expression if char.isdigit() or char in '+-*/().^ ')
            result = sympify(cleaned_expression)
            return str(result.evalf())
        except Exception as e:
            return f"Error: Unable to calculate. Please provide a valid mathematical expression. ({str(e)})"

    async def get_current_date_time_cst(self):
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
        await self.config.api_key.set(api_key)
        await self.update_langchain_components()
        await ctx.send("API key has been set and components updated.")

    @air.command(name="model")
    @commands.is_owner()
    async def set_model(self, ctx: commands.Context, model: str):
        """Set the model to use for AI responses."""
        await self.config.model.set(model)
        await ctx.send(f"Model has been set to {model}.")

    @commands.command()
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

    async def update_langchain_components(self):
        try:
            custom_personality = await self.config.custom_personality()
            memory = ConversationBufferWindowMemory(k=5, memory_key="chat_history", return_messages=True)
            
            # Set up tools first
            tools = await self.setup_tools()
            
            prompt = ChatPromptTemplate.from_messages([
                ("system", f"You are an AI assistant named Meow with the following personality: {custom_personality}. "
                          "You are in a Discord server, responding to user messages. "
                          "Respond naturally and conversationally, as if you're chatting with a friend. "
                          "Always maintain your assigned personality throughout the conversation. "
                          "You have access to several tools that can help you provide accurate information:\n"
                          "- Use 'Current Date and Time (CST)' for current time\n"
                          "- Use 'DuckDuckGo Search' for recent information\n"
                          "- Use 'Wikipedia' for detailed topic information\n"
                          "- Use 'Calculator' for mathematical calculations\n"
                          "When asked about the current time or date, you MUST use the 'Current Date and Time (CST)' tool. "
                          "Do not make up or guess the current time - always use the tool.\n"
                          "When using tools, wait for their response and incorporate the information naturally."),
                ("human", "{input}"),
                ("ai", "{agent_scratchpad}")
            ])

            agent = create_openai_functions_agent(
                llm=self.llm,
                tools=tools,
                prompt=prompt
            )
            
            self.agent_executor = AgentExecutor(
                agent=agent,
                tools=tools,
                memory=memory,
                verbose=True,
                max_iterations=3,
                handle_parsing_errors=True,
                early_stopping_method="generate"
            )

            self.logger.info("LangChain components updated successfully")
        except Exception as e:
            self.logger.error(f"Error updating LangChain components: {str(e)}", exc_info=True)
            self.agent_executor = None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
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
                full_response = await self.process_query(content, message, response_message)
                await response_message.edit(content=full_response)
            except Exception as e:
                self.logger.error(f"Error processing query: {str(e)}", exc_info=True)
                await response_message.edit(content=f"{message.author.mention} 😵 Oops! My circuits got a bit tangled there. Can you try again?")

    async def process_query(self, content: str, message: discord.Message, response_message: discord.Message) -> str:
        try:
            user_mention = message.author.mention
            callback_handler = DiscordCallbackHandler(response_message, self.logger)

            if self.agent_executor is None:
                self.logger.error("Agent executor is not initialized")
                await self.update_langchain_components()
                if self.agent_executor is None:
                    return f"{user_mention} I'm having trouble accessing my knowledge. Please try again later or contact the bot owner."

            self.logger.info(f"Processing query from {message.author.name}: {content}")
            
            result = await self.agent_executor.ainvoke(
                {
                    "input": content,
                    "chat_history": self.agent_executor.memory.chat_memory.messages if self.agent_executor.memory else []
                },
                {"callbacks": [callback_handler]}
            )

            if not result or 'output' not in result:
                raise ValueError("Invalid result from agent executor")

            # Log tool usage if any
            if 'intermediate_steps' in result and result['intermediate_steps']:
                self.logger.info("📊 Tool Usage Summary:")
                for step in result['intermediate_steps']:
                    if isinstance(step, tuple) and len(step) == 2:
                        action, observation = step
                        self.logger.info("------------------------")
                        self.logger.info(f"Tool: {action.tool}")
                        self.logger.info(f"Input: {action.tool_input}")
                        self.logger.info(f"Output: {observation}")
                        self.logger.info("------------------------")
            else:
                self.logger.info("No tools were used in generating this response")

            cleaned_response = self.clean_agent_output(result['output'])
            self.logger.info(f"Final response: {cleaned_response[:200]}...")  # Log first 200 chars of response

            if not cleaned_response.strip():
                cleaned_response = "I apologize, but I couldn't generate a meaningful response. Could you please rephrase your question or provide more context?"

            formatted_response = f"{user_mention}\n\n{cleaned_response}"
            return formatted_response[:2000]  # Truncate to Discord's limit

        except Exception as e:
            self.logger.error(f"Unexpected error in process_query: {str(e)}", exc_info=True)
            return f"{user_mention} I encountered an unexpected error. Please try again or contact the bot owner if the issue persists."

    async def process_intermediate_step(self, step, response_message):
        if isinstance(step, tuple) and len(step) == 2:
            action, observation = step
            if isinstance(action, dict) and 'tool' in action:
                tool_name = action['tool']
                tool_input = action.get('tool_input', '')
                await response_message.edit(content=f"🔧 Using {tool_name}: {tool_input}")
            elif isinstance(observation, str):
                await response_message.edit(content=f"💡 Thinking: {observation[:100]}...")  # Truncate long observations

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
        api_key = await self.config.api_key()
        model = await self.config.model()
        return bool(api_key and model)

    async def verify_api_settings(self):
        api_key = await self.config.api_key()
        model = await self.config.model()
        if not api_key or not model:
            self.logger.error("API key or model not set")
            return False
        try:
            test_prompt = "Hello, world!"
            self.logger.info(f"Testing API with prompt: {test_prompt}")
            messages = [
                SystemMessage(content="You are a helpful AI assistant."),
                HumanMessage(content=test_prompt)
            ]
            response = await self.llm.agenerate(messages=[messages])
            if response and response.generations:
                self.logger.info("API settings verified successfully")
                return True
            else:
                self.logger.error("API response was empty or invalid")
                return False
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

async def setup(bot: Red):
    cog = AIResponder(bot)
    await bot.add_cog(cog)
    await cog.initialize()

