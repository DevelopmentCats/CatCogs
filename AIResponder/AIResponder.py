import discord
from redbot.core import commands, Config
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, pagify
from typing import Dict, List, Tuple, Any, Optional
import asyncio
import logging
from datetime import datetime
from openai import AsyncOpenAI, APIConnectionError, APIError, RateLimitError
from langchain.schema import HumanMessage, AIMessage
from langchain.agents import Tool, AgentExecutor, create_react_agent
from langchain.memory import ConversationBufferWindowMemory
from langchain.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate, MessagesPlaceholder, PromptTemplate
from langchain.tools import StructuredTool
from langchain_community.utilities import DuckDuckGoSearchAPIWrapper, WikipediaAPIWrapper, RequestsWrapper
from langchain_community.tools import DuckDuckGoSearchResults, WikipediaQueryRun
from langchain_experimental.tools import PythonAstREPLTool
from langchain_community.tools.requests.tool import RequestsGetTool
from langchain_community.tools.wolfram_alpha.tool import WolframAlphaQueryRun
from langchain.llms.base import LLM
from langchain.schema import LLMResult, Generation
from langchain.tools import Tool
from langchain_community.utilities import WolframAlphaAPIWrapper
from langchain.callbacks.manager import CallbackManagerForLLMRun
from sympy import sympify, solve
import wolframalpha
import os
from pydantic import Field

class DeepInfraLLM(LLM):
    client: AsyncOpenAI = Field(...)
    model: str = Field(...)
    
    @property
    def _llm_type(self) -> str:
        return "deepinfra"

    async def _acall(
        self,
        messages: List[Dict[str, str]],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> str:
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stop=stop,
                **kwargs
            )
            return response.choices[0].message.content
        except APIConnectionError as e:
            raise ValueError(f"Connection error with DeepInfra API: {str(e)}")
        except APIError as e:
            raise ValueError(f"API error from DeepInfra: {str(e)}")
        except RateLimitError as e:
            raise ValueError(f"Rate limit exceeded: {str(e)}")
        except Exception as e:
            raise ValueError(f"Unexpected error calling DeepInfra API: {str(e)}")

    def _call(
        self,
        prompt: str,
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> str:
        messages = [{"role": "user", "content": prompt}]
        return asyncio.run(self._acall(messages, stop, run_manager, **kwargs))

class AIResponder(commands.Cog):
    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        default_global = {
            "api_url": "https://api.deepinfra.com/v1/openai",
            "api_key": "",
            "model": "meta-llama/Llama-3.2-11B-Vision-Instruct",
            "custom_personality": "You are a helpful AI assistant.",
            "enabled_channels": [],
            "wolfram_alpha_appid": "",
        }
        self.config.register_global(**default_global)
        self.llm = None
        self.agent_executor = None
        self.logger = logging.getLogger("red.airesponder")
        self.bot.loop.create_task(self.initialize())

    async def initialize(self):
        api_url = await self.config.api_url()
        api_key = await self.config.api_key()
        model = await self.config.model()

        openai_client = AsyncOpenAI(
            api_key=api_key,
            base_url=api_url,
        )

        self.llm = DeepInfraLLM(client=openai_client, model=model)

        # Set up tools and agent executor
        tools = await self.setup_tools()
        memory = ConversationBufferWindowMemory(k=5, memory_key="chat_history", return_messages=True)

        custom_personality = await self.config.custom_personality()
        template = f"""\
        You are an AI assistant with the following personality: {custom_personality}
        You are in a Discord server, responding to user messages.
        Respond naturally and conversationally, as if you're chatting with a friend.
        Always maintain your assigned personality throughout the conversation.
        Do not mention that you're an AI or that this is a prompt.
        Human: {{input}}
        When you receive a query:
        1) First, think about what you already know that could help answer the question.
        2) If you need more information or need to perform a calculation, consider which tools you have available:
        {{tools}}
        3) Decide if using a tool is necessary. If so, choose the most appropriate tool from the available options: {{tool_names}}
        4) Use the selected tool to gather information or perform the necessary action.
        5) Formulate a response based on your knowledge and any additional information obtained.

        {{agent_scratchpad}}
        """
        
        prompt = PromptTemplate(
            input_variables=["input", "tools", "tool_names", "agent_scratchpad"],
            template=template,
        )

        agent = create_react_agent(
            llm=self.llm,
            tools=tools,
            prompt=prompt,
        )
        self.agent_executor = AgentExecutor.from_agent_and_tools(
            agent=agent,
            tools=tools,
            memory=memory,
            verbose=True,
            max_iterations=5,
            handle_parsing_errors=True
        )

        await self.verify_api_settings()

    async def setup_tools(self):
        tools = []

        try:
            # DuckDuckGo Search
            ddg_search = DuckDuckGoSearchAPIWrapper()
            tools.append(
                Tool(
                    name="DuckDuckGo Search",
                    func=ddg_search.run,
                    description="Useful for searching the internet for current information on various topics."
                )
            )

            # Wikipedia
            wikipedia = WikipediaAPIWrapper()
            tools.append(
                Tool(
                    name="Wikipedia",
                    func=wikipedia.run,
                    description="Useful for getting detailed information on a wide range of topics."
                )
            )

            # Python REPL
            python_repl = PythonAstREPLTool()
            tools.append(
                Tool(
                    name="Python REPL",
                    func=python_repl.run,
                    description="Useful for running Python code and performing calculations."
                )
            )

            # Requests Get
            requests_wrapper = RequestsWrapper()
            requests_get = RequestsGetTool(requests_wrapper=requests_wrapper, allow_dangerous_requests=True)
            tools.append(
                Tool(
                    name="Web Fetch",
                    func=requests_get.run,
                    description="Useful for fetching content from web pages."
                )
            )

            # Wolfram Alpha
            wolfram_alpha_tokens = await self.bot.get_shared_api_tokens("wolfram_alpha")
            wolfram_alpha_appid = wolfram_alpha_tokens.get("app_id")
            if wolfram_alpha_appid:
                wolfram = WolframAlphaAPIWrapper(wolfram_alpha_appid=wolfram_alpha_appid)
                tools.append(
                    Tool(
                        name="Wolfram Alpha",
                        func=wolfram.run,
                        description="Useful for complex calculations and queries about math, science, and more."
                    )
                )
            else:
                self.logger.warning("Wolfram Alpha AppID not found. Wolfram Alpha tool will not be available.")

            # Calculator
            def calculator(expression: str) -> str:
                try:
                    result = sympify(expression)
                    return str(result.evalf())
                except Exception as e:
                    return f"Error: {str(e)}"

            tools.append(
                Tool(
                    name="Calculator",
                    func=calculator,
                    description="Useful for performing basic and advanced mathematical calculations."
                )
            )

        except Exception as e:
            self.logger.error(f"Error setting up tools: {str(e)}", exc_info=True)

        return tools

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
        await ctx.send("API key has been set.")

    @air.command(name="model")
    @commands.is_owner()
    async def set_model(self, ctx: commands.Context, model: str):
        """Set the model to use for AI responses."""
        await self.config.model.set(model)
        await ctx.send(f"Model has been set to {model}.")

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
            self.logger.info("Starting to update LangChain components")
            api_url = await self.config.api_url()
            api_key = await self.config.api_key()
            model = await self.config.model()
            
            self.logger.info(f"Using API URL: {api_url}, Model: {model}")
            openai_client = AsyncOpenAI(
                api_key=api_key,
                base_url=api_url,
            )
            self.llm = DeepInfraLLM(client=openai_client, model=model)
            
            custom_personality = await self.config.custom_personality()
            memory = ConversationBufferWindowMemory(k=5, memory_key="chat_history", return_messages=True)
            
            template = f"""\
            You are an AI assistant with the following personality: {custom_personality}
            You are in a Discord server, responding to user messages.
            Respond naturally and conversationally, as if you're chatting with a friend.
            Always maintain your assigned personality throughout the conversation.
            Do not mention that you're an AI or that this is a prompt.
            Human: {{input}}
            When you receive a query:
            1) First, think about what you already know that could help answer the question.
            2) If you need more information or need to perform a calculation, consider which tools you have available:
            {{tools}}
            3) Decide if using a tool is necessary. If so, choose the most appropriate tool from the available options: {{tool_names}}
            4) Use the selected tool to gather information or perform the necessary action.
            5) Formulate a response based on your knowledge and any additional information obtained.

            {{agent_scratchpad}}
            """
            
            prompt = PromptTemplate(
                input_variables=["input", "tools", "tool_names", "agent_scratchpad"],
                template=template,
            )
            
            self.logger.info("Setting up tools")
            tools = await self.setup_tools()
            
            self.logger.info("Creating agent executor")
            agent = create_react_agent(
                llm=self.llm,
                tools=tools,
                prompt=prompt,
            )
            self.agent_executor = AgentExecutor.from_agent_and_tools(
                agent=agent,
                tools=tools,
                memory=memory,
                verbose=True,
                max_iterations=5,
                handle_parsing_errors=True
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
        else:
            # Handle DMs if needed
            pass

        content = message.content.replace(f"<@{self.bot.user.id}>", "").strip()
        if not content:
            await message.channel.send("You mentioned me, but didn't ask anything. How can I help you?")
            return

        async with message.channel.typing():
            response_message = await message.channel.send("🤔 Pondering the depths of knowledge...")
            
            try:
                full_response = await self.process_query(content, response_message)
                
                for chunk in pagify(full_response, delims=["\n", " "], page_length=1900):
                    await message.channel.send(chunk)
                
                await response_message.delete()
            except Exception as e:
                self.logger.error(f"Error processing query: {str(e)}", exc_info=True)
                await response_message.edit(content="😵 Oops! My circuits got a bit tangled there. Can you try again?")

    async def process_query(self, content: str, response_message: discord.Message) -> str:
        status_messages = [
            "🔍 Diving into the sea of information...",
            "🧠 Neurons firing at maximum capacity...",
            "🌟 Consulting the cosmic database...",
            "🔮 Peering into the crystal ball of knowledge...",
            "🚀 Launching thought experiments...",
        ]
        
        try:
            for i in range(len(status_messages)):
                await response_message.edit(content=status_messages[i])
                await asyncio.sleep(1)  # Add a small delay between status updates
            
            if self.agent_executor is None:
                self.logger.error("Agent executor is not initialized")
                await self.update_langchain_components()
                if self.agent_executor is None:
                    return "I'm having trouble accessing my knowledge. Please try again later or contact the bot owner."
            
            # Get conversation history
            memory = self.agent_executor.memory
            chat_history = memory.chat_memory.messages if memory else []
            
            # Prepare messages for the API call
            messages = [{"role": "system", "content": await self.config.custom_personality()}]
            for message in chat_history:
                if isinstance(message, HumanMessage):
                    messages.append({"role": "user", "content": message.content})
                elif isinstance(message, AIMessage):
                    messages.append({"role": "assistant", "content": message.content})
            messages.append({"role": "user", "content": content})
            
            # Make the API call
            response = await self.llm._acall(messages=messages)
            
            # Update memory with the new message pair
            if memory:
                memory.chat_memory.add_user_message(content)
                memory.chat_memory.add_ai_message(response)
            
            return response
        except ValueError as e:
            self.logger.error(f"Value error in agent execution: {str(e)}")
            return f"I encountered an issue: {str(e)}. Could you rephrase your request?"
        except asyncio.TimeoutError:
            self.logger.error("Query processing timed out")
            return "I'm sorry, but it's taking me longer than expected to process your request. Could you try asking a simpler question?"
        except APIConnectionError as e:
            self.logger.error(f"API Connection Error: {str(e)}")
            return "I'm having trouble connecting to my knowledge base. Please try again later."
        except Exception as e:
            self.logger.error(f"Unexpected error in agent execution: {str(e)}", exc_info=True)
            return "I encountered an unexpected error while processing your request. Please try again or contact the bot owner if the issue persists."

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
            # Make a simple API call to verify the settings
            test_messages = [{"role": "user", "content": "Test"}]
            test_response = await self.llm._acall(messages=test_messages)
            if test_response:
                self.logger.info("API settings verified successfully")
                return True
        except Exception as e:
            self.logger.error(f"Error verifying API settings: {str(e)}")
        return False

async def setup(bot: Red):
    cog = AIResponder(bot)
    await bot.add_cog(cog)
    await cog.initialize()
