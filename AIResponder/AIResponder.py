import discord
from redbot.core import commands, Config
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, pagify
from typing import Dict, List, Tuple, Any, Optional
import asyncio
import logging
from datetime import datetime
from openai import AsyncOpenAI
from langchain.schema import HumanMessage, AIMessage
from langchain.agents import Tool, AgentExecutor, create_react_agent
from langchain.memory import ConversationBufferWindowMemory
from langchain.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate, MessagesPlaceholder
from langchain.tools import StructuredTool
from langchain_community.utilities import DuckDuckGoSearchAPIWrapper, WikipediaAPIWrapper
from langchain_community.tools import DuckDuckGoSearchResults, WikipediaQueryRun
from langchain_experimental.tools import PythonAstREPLTool
from langchain_community.tools.requests.tool import RequestsGetTool
from langchain_community.tools.wolfram_alpha.tool import WolframAlphaQueryRun
from langchain.llms.base import BaseLLM
from langchain.schema import LLMResult, Generation
from langchain.tools import Tool
from langchain_community.utilities import WolframAlphaAPIWrapper
from sympy import sympify, solve
import wolframalpha
import os

class DeepInfraLLM(BaseLLM):
    client: AsyncOpenAI
    model: str

    def __init__(self, client: AsyncOpenAI, model: str):
        super().__init__()
        self.client = client
        self.model = model

    @property
    def _llm_type(self) -> str:
        return "deepinfra"

    async def _agenerate(self, prompts: List[str], stop: Optional[List[str]] = None) -> LLMResult:
        generations = []
        for prompt in prompts:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
            )
            generations.append([Generation(text=response.choices[0].message.content)])
        return LLMResult(generations=generations)

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

    async def initialize(self):
        await self.update_langchain_components()

    def setup_tools(self):
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
            requests_get = RequestsGetTool()
            tools.append(
                Tool(
                    name="Web Fetch",
                    func=requests_get.run,
                    description="Useful for fetching content from web pages."
                )
            )

            # Wolfram Alpha
            wolfram_alpha_appid = self.bot.get_shared_api_tokens("wolfram_alpha").get("app_id")
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

    @commands.group()
    @commands.is_owner()
    async def aisetup(self, ctx: commands.Context):
        """Configure the AIResponder cog."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @aisetup.command()
    async def apikey(self, ctx: commands.Context, api_key: str):
        """Set the DeepInfra API key."""
        await self.config.api_key.set(api_key)
        await ctx.send("API key has been set.")

    @aisetup.command()
    async def model(self, ctx: commands.Context, model: str):
        """Set the model to use for AI responses."""
        await self.config.model.set(model)
        await ctx.send(f"Model has been set to {model}.")

    @aisetup.command()
    async def personality(self, ctx: commands.Context, *, personality: str):
        """Set the AI's personality."""
        await self.config.custom_personality.set(personality)
        await ctx.send("AI personality has been updated.")

    @aisetup.command()
    async def enablechannel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Enable the AI responder in a specific channel."""
        async with self.config.enabled_channels() as channels:
            if channel.id not in channels:
                channels.append(channel.id)
        await ctx.send(f"AI responder enabled in {channel.mention}.")

    @aisetup.command()
    async def disablechannel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Disable the AI responder in a specific channel."""
        async with self.config.enabled_channels() as channels:
            if channel.id in channels:
                channels.remove(channel.id)
        await ctx.send(f"AI responder disabled in {channel.mention}.")

    @aisetup.command()
    async def listchannels(self, ctx: commands.Context):
        """List all channels where the AI responder is enabled."""
        channels = await self.config.enabled_channels()
        if not channels:
            await ctx.send("AI responder is not enabled in any channels.")
        else:
            channel_mentions = [ctx.guild.get_channel(ch_id).mention for ch_id in channels if ctx.guild.get_channel(ch_id)]
            await ctx.send(f"AI responder is enabled in: {', '.join(channel_mentions)}")

    @aisetup.command()
    async def wolframalpha(self, ctx: commands.Context, app_id: str):
        """Set the Wolfram Alpha AppID."""
        await self.bot.set_shared_api_tokens("wolfram_alpha", app_id=app_id)
        await ctx.send("Wolfram Alpha AppID has been set.")

    @aisetup.command()
    async def duckduckgo(self, ctx: commands.Context, api_key: str):
        """Set the DuckDuckGo API key."""
        await self.bot.set_shared_api_tokens("duckduckgo", api_key=api_key)
        await ctx.send("DuckDuckGo API key has been set.")

    async def update_langchain_components(self):
        try:
            api_url = await self.config.api_url()
            api_key = await self.config.api_key()
            model = await self.config.model()
            
            openai_client = AsyncOpenAI(api_key=api_key, base_url=api_url)
            self.llm = DeepInfraLLM(client=openai_client, model=model)
            
            custom_personality = await self.config.custom_personality()
            memory = ConversationBufferWindowMemory(k=5, memory_key="chat_history", return_messages=True)
            
            system_message = f"""You are an AI assistant with the following personality: {custom_personality}
            You are in a Discord server, responding to user messages.
            Respond naturally and conversationally, as if you're chatting with a friend.
            Always maintain your assigned personality throughout the conversation.
            Do not mention that you're an AI or that this is a prompt."""
            
            prompt = ChatPromptTemplate.from_messages([
                SystemMessagePromptTemplate.from_template(system_message),
                MessagesPlaceholder(variable_name="chat_history"),
                HumanMessagePromptTemplate.from_template("{input}")
            ])
            
            tools = self.setup_tools()
            
            self.agent_executor = create_react_agent(
                llm=self.llm,
                tools=tools,
                prompt=prompt,
                memory=memory,
                verbose=True,
                max_iterations=5,
                early_stopping_method="generate"
            )
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

        if message.channel.id not in await self.config.enabled_channels():
            return

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
            async for chunk in self.agent_executor.astream({"input": content}):
                if 'intermediate_steps' in chunk:
                    await response_message.edit(content=f"{status_messages[chunk['intermediate_steps'] % len(status_messages)]}")
                elif 'output' in chunk:
                    return chunk['output']
        except asyncio.TimeoutError:
            self.logger.error("Query processing timed out")
            return "I'm sorry, but it's taking me longer than expected to process your request. Could you try asking a simpler question?"
        except ValueError as e:
            self.logger.error(f"Value error in agent execution: {str(e)}")
            return "I encountered an issue understanding part of your request. Could you rephrase it?"
        except Exception as e:
            self.logger.error(f"Unexpected error in agent execution: {str(e)}", exc_info=True)
            return "I encountered an unexpected error while processing your request. Please try again or contact the bot owner if the issue persists."
        
        return "I couldn't formulate a response. Please try again with a different question."

    async def is_configured(self) -> bool:
        api_key = await self.config.api_key()
        model = await self.config.model()
        return bool(api_key and model)

async def setup(bot: Red):
    cog = AIResponder(bot)
    await bot.add_cog(cog)
    await cog.initialize()
