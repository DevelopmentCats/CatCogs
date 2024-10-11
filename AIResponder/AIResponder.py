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
from langchain.agents import AgentExecutor
from langchain.memory import ConversationBufferWindowMemory
from langchain.prompts import PromptTemplate
from langchain.tools import Tool
from langchain_community.utilities import DuckDuckGoSearchAPIWrapper, WikipediaAPIWrapper, WolframAlphaAPIWrapper
from langchain_community.tools import DuckDuckGoSearchResults, WikipediaQueryRun
from langchain_experimental.tools import PythonAstREPLTool
from langchain_community.tools.wolfram_alpha.tool import WolframAlphaQueryRun
from langchain.callbacks.manager import CallbackManagerForLLMRun
from langchain.schema import LLMResult
from sympy import sympify
import wolframalpha
import os
from pydantic import Field, BaseModel
from langchain.callbacks.base import BaseCallbackHandler
import random
from langchain.agents.react.base import DocstoreExplorer
from langchain.agents import create_react_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult, ChatGeneration
import json

class DeepInfraLLM(BaseChatModel):
    client: Any = Field(...)
    model: str = Field(...)
    
    class Config:
        arbitrary_types_allowed = True
    
    @property
    def _llm_type(self) -> str:
        return "deepinfra"

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        try:
            formatted_messages = []
            for message in messages:
                if message.type == "human":
                    role = "user"
                elif message.type == "ai":
                    role = "assistant"
                elif message.type == "system":
                    role = "system"
                else:
                    raise ValueError(f"Unsupported message type: {message.type}")
                
                formatted_messages.append({"role": role, "content": message.content})

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=formatted_messages,
                stop=stop,
                **kwargs
            )
            
            content = response.choices[0].message.content
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])
        except Exception as e:
            raise ValueError(f"Error calling DeepInfra API: {str(e)}")

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        return asyncio.run(self._agenerate(messages, stop, run_manager, **kwargs))

class LoggingCallbackHandler(BaseCallbackHandler):
    def __init__(self, response_message, tool_dict):
        self.response_message = response_message
        self.thought_count = 1
        self.tool_dict = tool_dict

    async def on_llm_start(self, serialized, prompts, **kwargs):
        thinking_messages = [
            f"🧠 Thought {self.thought_count}: Pondering the mysteries of your query...",
            f"💡 Idea {self.thought_count}: A lightbulb moment is brewing!",
            f"🤔 Contemplation {self.thought_count}: Diving deep into the realm of possibilities...",
            f"🌟 Eureka {self.thought_count}: Channeling the spirit of great thinkers...",
            f"🔍 Investigation {self.thought_count}: Examining your question from all angles..."
        ]
        await self.response_message.edit(content=random.choice(thinking_messages))
        self.thought_count += 1

    async def on_tool_start(self, serialized, input_str, **kwargs):
        tool_name = serialized["name"]
        tool_description = self.tool_dict.get(tool_name, "Unknown tool")
        tool_messages = [
            f"🔧 Tinkering with the {tool_name} gadget...",
            f"🚀 Launching the {tool_name} module into action!",
            f"🔬 Analyzing data with the {tool_name} tool...",
            f"🧰 Pulling out the {tool_name} from my toolbox...",
            f"⚡ Powering up the {tool_name} for some fact-finding..."
        ]
        await self.response_message.edit(content=random.choice(tool_messages))

    async def on_tool_end(self, output, **kwargs):
        tool_end_messages = [
            "✅ Tool usage complete! Processing the juicy results...",
            "🎉 Data gathered! Time to make sense of it all...",
            "📊 Information acquired! Crunching the numbers...",
            "🧩 Pieces collected! Assembling the puzzle...",
            "🏁 Research phase complete! Formulating a response..."
        ]
        await self.response_message.edit(content=random.choice(tool_end_messages))

    async def on_agent_action(self, action, **kwargs):
        await self.response_message.edit(content=f"🤖 Taking action: {action.tool}")

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

        Your primary goal is to answer the user's specific query accurately and helpfully.

        User's message: {{input}}

        When responding to the user's message:
        1) First, carefully consider what you already know that could help answer the question or address the user's input.
        2) If your existing knowledge is sufficient, formulate a response without using tools.
        3) Only use tools if you need additional information that you don't already have.

        Available tools:
        {{tools}}

        Tool names: {{tool_names}}

        Guidelines for using tools:
        - Use tools sparingly and only when necessary to address the user's specific input.
        - Choose the most appropriate tool for the specific information you need.
        - Avoid using multiple tools unless absolutely required to answer the query.
        - After using a tool, always relate the information back to the user's original message.

        To use a tool:
        Thought: [Explain your reasoning for needing to use this specific tool]
        Action: [Tool Name]
        Action Input: [Concise and specific input for the tool]

        After using a tool:
        Observation: [Tool Output]
        Thought: [Interpret the tool output and explain how it relates to the user's original message]

        Important:
        - Always keep the user's original message in mind throughout the process.
        - Stay focused on addressing the specific input provided by the user.
        - Don't get sidetracked by interesting but irrelevant information from tool outputs.

        When you have enough information to respond:
        Thought: I now have sufficient information to address the user's message.
        Final Answer: [Provide a natural, conversational response that directly addresses the user's original input. Incorporate relevant information from your initial knowledge and any tool outputs used.]

        Remember:
        - Respond in a natural, friendly manner, consistent with your assigned personality.
        - Be concise but informative in your final answer.
        - If you're unsure about something, it's okay to express uncertainty rather than guessing.
        - Always use the format "Thought: [Your thought]\nAction: [Tool Name]\nAction Input: [Input]" when using tools.
        - Always end your response with a "Final Answer:" when you're ready to respond to the user.
        - Stay focused on the original message and avoid introducing unrelated topics.

        {{agent_scratchpad}}
        """

        prompt = PromptTemplate(
            input_variables=["input", "agent_scratchpad", "tools", "tool_names"],
            template=template
        )

        self.logger.info("Setting up tools")
        tools = await self.setup_tools()
        tools_str = "\n".join([f"- {tool.name}: {tool.description}" for tool in tools])
        tool_names = ", ".join([tool.name for tool in tools])

        self.logger.info("Creating agent executor")
        agent = create_react_agent(
            llm=self.llm,
            tools=tools,
            prompt=prompt.partial(tools=tools_str, tool_names=tool_names)
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

            Your primary goal is to answer the user's specific query accurately and helpfully.

            User's message: {{input}}

            When responding to the user's message:
            1) First, carefully consider what you already know that could help answer the question or address the user's input.
            2) If your existing knowledge is sufficient, formulate a response without using tools.
            3) Only use tools if you need additional information that you don't already have.

            Available tools:
            {{tools}}

            Tool names: {{tool_names}}

            Guidelines for using tools:
            - Use tools sparingly and only when necessary to address the user's specific input.
            - Choose the most appropriate tool for the specific information you need.
            - Avoid using multiple tools unless absolutely required to answer the query.
            - After using a tool, always relate the information back to the user's original message.

            To use a tool:
            Thought: [Explain your reasoning for needing to use this specific tool]
            Action: [Tool Name]
            Action Input: [Concise and specific input for the tool]

            After using a tool:
            Observation: [Tool Output]
            Thought: [Interpret the tool output and explain how it relates to the user's original message]

            Important:
            - Always keep the user's original message in mind throughout the process.
            - Stay focused on addressing the specific input provided by the user.
            - Don't get sidetracked by interesting but irrelevant information from tool outputs.

            When you have enough information to respond:
            Thought: I now have sufficient information to address the user's message.
            Final Answer: [Provide a natural, conversational response that directly addresses the user's original input. Incorporate relevant information from your initial knowledge and any tool outputs used.]

            Remember:
            - Respond in a natural, friendly manner, consistent with your assigned personality.
            - Be concise but informative in your final answer.
            - If you're unsure about something, it's okay to express uncertainty rather than guessing.
            - Always use the format "Thought: [Your thought]\nAction: [Tool Name]\nAction Input: [Input]" when using tools.
            - Always end your response with a "Final Answer:" when you're ready to respond to the user.
            - Stay focused on the original message and avoid introducing unrelated topics.

            {{agent_scratchpad}}
            """
            
            prompt = PromptTemplate(
                input_variables=["input", "agent_scratchpad", "tools", "tool_names"],
                template=template
            )
            
            self.logger.info("Setting up tools")
            tools = await self.setup_tools()
            tools_str = "\n".join([f"- {tool.name}: {tool.description}" for tool in tools])
            tool_names = ", ".join([tool.name for tool in tools])
            
            self.logger.info("Creating agent executor")
            agent = create_react_agent(
                llm=self.llm,
                tools=tools,
                prompt=prompt.partial(tools=tools_str, tool_names=tool_names)
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
            response_message = await message.channel.send("🤔 Thinking...")
            
            try:
                full_response = await self.process_query(content, response_message)
                
                # Replace the status message with the final response
                await response_message.edit(content=full_response)
            except Exception as e:
                self.logger.error(f"Error processing query: {str(e)}", exc_info=True)
                await response_message.edit(content="😵 Oops! My circuits got a bit tangled there. Can you try again?")

    async def process_query(self, content: str, response_message: discord.Message) -> str:
        try:
            await response_message.edit(content="🤔 Thinking...")

            if self.agent_executor is None:
                self.logger.error("Agent executor is not initialized")
                await self.update_langchain_components()
                if self.agent_executor is None:
                    return "I'm having trouble accessing my knowledge. Please try again later or contact the bot owner."

            # Get conversation history
            memory = self.agent_executor.memory
            chat_history = memory.chat_memory.messages if memory else []

            # Create a dictionary of tool names and descriptions
            tool_dict = {tool.name: tool.description for tool in self.agent_executor.tools}

            # Create the callback handler with the tool dictionary
            callback_handler = LoggingCallbackHandler(response_message, tool_dict)

            # Run the agent with the custom callback handler
            response = await self.agent_executor.ainvoke(
                {
                    "input": content,
                    "chat_history": chat_history
                },
                callbacks=[callback_handler]
            )

            # Extract the output from the response
            output = response.get('output', "I couldn't generate a response. Please try again.")

            # Update memory with the new message pair
            if memory:
                memory.chat_memory.add_user_message(content)
                memory.chat_memory.add_ai_message(output)

            return output

        except ValueError as e:
            self.logger.error(f"Value error in agent execution: {str(e)}")
            if "Error calling DeepInfra API" in str(e):
                return "I'm having trouble connecting to my knowledge base. Please try again later."
            return "I encountered an issue processing your request. Could you rephrase it?"
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
            response = await self.llm._agenerate([HumanMessage(content="Test")])
            if response:
                self.logger.info("API settings verified successfully")
                return True
        except Exception as e:
            self.logger.error(f"Error verifying API settings: {str(e)}")
        return False

async def setup(bot: Red):
    cog = AIResponder(bot)
    await bot.add_cog(cog)
    await cog.initialize()
