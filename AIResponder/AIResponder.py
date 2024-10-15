import discord
from redbot.core import commands, Config
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, pagify
from typing import Dict, List, Tuple, Any, Optional, Union
import asyncio
import logging
from datetime import datetime
from openai import AsyncOpenAI, APIConnectionError, APIError, RateLimitError

# Updated LangChain V3 imports
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import Tool
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.callbacks import BaseCallbackHandler
from langchain.memory import ConversationBufferMemory, ConversationBufferWindowMemory
from langchain_community.utilities import DuckDuckGoSearchAPIWrapper, WikipediaAPIWrapper, WolframAlphaAPIWrapper
from langchain_community.tools import DuckDuckGoSearchResults, WikipediaQueryRun
from langchain_community.tools.wolfram_alpha.tool import WolframAlphaQueryRun
from langchain_experimental.tools import PythonAstREPLTool
from langchain_community.chat_models import ChatDeepInfra
from langchain.agents import AgentExecutor, create_tool_calling_agent, AgentType, initialize_agent

from sympy import sympify
import wolframalpha
import os
from pydantic import Field, BaseModel
import random
import json
import re

def validate_input(prompt):
    # Remove potentially harmful code execution patterns
    safe_prompt = re.sub(r"(subprocess\.call|shutil\.rmtree|os\.system)\([^\)]+\)", "", prompt)
    return safe_prompt

class DiscordCallbackHandler(BaseCallbackHandler):
    def __init__(self, discord_message):
        self.discord_message = discord_message

    async def on_llm_start(self, serialized, prompts, **kwargs):
        await self.discord_message.edit(content="🤔 Thinking...")

    async def on_llm_new_token(self, token, **kwargs):
        try:
            current_content = self.discord_message.content
            new_content = current_content + token
            if len(new_content) > 2000:
                new_content = new_content[-2000:]
            await self.discord_message.edit(content=new_content)
        except Exception as e:
            print(f"Error in on_llm_new_token: {str(e)}")

    async def on_tool_start(self, serialized, input_str, **kwargs):
        await self.discord_message.edit(content=f"🔧 Using tool: {serialized['name']}")

    async def on_tool_end(self, output, **kwargs):
        await self.discord_message.edit(content="✅ Tool used. Processing results...")

    async def on_chain_end(self, outputs, **kwargs):
        if isinstance(outputs, dict) and 'output' in outputs:
            await self.discord_message.edit(content=outputs['output'][:2000])
        else:
            await self.discord_message.edit(content="Finished processing, but couldn't format the output.")

    async def on_chain_error(self, error, **kwargs):
        await self.discord_message.edit(content=f"An error occurred: {str(error)[:1000]}")

class AIResponder(commands.Cog):
    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        default_global = {
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
        try:
            api_key = await self.config.api_key()
            model = await self.config.model()

            if not api_key:
                self.logger.error("API key not set. Please use the 'air apikey' command to set it.")
                return

            self.logger.info(f"Initializing ChatDeepInfra LLM with model: {model}")
            self.llm = ChatDeepInfra(
                model=model,
                deepinfra_api_token=api_key
            )

            # Log LLM configuration
            self.logger.info(f"LLM configuration: {self.llm.model_kwargs}")

            # Test the LLM
            try:
                test_response = await self.llm.agenerate([{"role": "user", "content": "Test"}])
                self.logger.info(f"LLM test response: {test_response}")
            except Exception as e:
                self.logger.error(f"Error testing LLM: {str(e)}", exc_info=True)
                return

            # Set up tools and agent executor
            self.logger.info("Setting up tools")
            tools = await self.setup_tools()
            memory = ConversationBufferWindowMemory(k=5, memory_key="chat_history", return_messages=True)

            custom_personality = await self.config.custom_personality()
            template = f"""You are an AI assistant with the following personality: {custom_personality}
            You are in a Discord server, responding to user messages.
            Respond naturally and conversationally, as if you're chatting with a friend.
            Always maintain your assigned personality throughout the conversation.

            Human: {{input}}
            AI: To approach this, let's think step-by-step:

            {{agent_scratchpad}}

            Available tools:
            {{tools}}

            Tool names: {{tool_names}}

            Remember to use tools only when necessary, and always explain your thought process.
            """

            prompt = ChatPromptTemplate.from_messages([
                ("system", template),
                ("human", "{input}"),
                ("ai", "{agent_scratchpad}"),
            ])

            self.logger.info("Creating agent executor")
            try:
                agent = initialize_agent(
                    tools,
                    self.llm,
                    agent=AgentType.CHAT_CONVERSATIONAL_REACT_DESCRIPTION,
                    verbose=True,
                    handle_parsing_errors=True
                )

                self.agent_executor = AgentExecutor.from_agent_and_tools(
                    agent=agent,
                    tools=tools,
                    memory=memory,
                    verbose=True,
                    max_iterations=10,
                    max_execution_time=60,
                    early_stopping_method="generate",
                    handle_parsing_errors=True
                )
                self.logger.info("Agent executor created successfully")
            except Exception as e:
                self.logger.error(f"Error creating agent executor: {str(e)}", exc_info=True)
                self.agent_executor = None

            await self.verify_api_settings()
        except Exception as e:
            self.logger.error(f"Unexpected error in initialize: {str(e)}", exc_info=True)

    async def setup_tools(self):
        tools = []

        try:
            # DuckDuckGo Search
            ddg_search = DuckDuckGoSearchAPIWrapper()
            tools.append(
                Tool(
                    name="DuckDuckGo Search",
                    func=DuckDuckGoSearchResults(api_wrapper=ddg_search).run,
                    description="Useful for searching the internet for current information on various topics."
                )
            )

            # Wikipedia
            wikipedia = WikipediaAPIWrapper()
            tools.append(
                Tool(
                    name="Wikipedia",
                    func=WikipediaQueryRun(api_wrapper=wikipedia).run,
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
                    # Remove any non-mathematical characters
                    cleaned_expression = ''.join(char for char in expression if char.isdigit() or char in '+-*/().^ ')
                    result = sympify(cleaned_expression)
                    return str(result.evalf())
                except Exception as e:
                    return f"Error: Unable to calculate. Please provide a valid mathematical expression. ({str(e)})"

            tools.append(
                Tool(
                    name="Calculator",
                    func=calculator,
                    description="Useful for performing basic and advanced mathematical calculations. Provide a valid mathematical expression."
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

    @air.command(name="test")
    @commands.is_owner()
    async def test_llm(self, ctx: commands.Context, *, query: str):
        """Test the LLM directly without using the agent."""
        if not await self.is_configured():
            await ctx.send("AIResponder is not configured. Please set up the API key and model first.")
            return

        self.logger.info(f"Testing LLM with query: {query}")
        async with ctx.typing():
            try:
                self.logger.info("Generating response from LLM")
                response = await self.llm.agenerate([query])
                self.logger.info(f"Raw LLM response: {response}")
                result = response.generations[0][0].text

                # Split the response into chunks if it's too long
                chunks = [result[i:i+1990] for i in range(0, len(result), 1990)]
                
                for chunk in chunks:
                    await ctx.send(chunk)
                
                self.logger.info(f"Sent response in {len(chunks)} part(s)")
            except Exception as e:
                self.logger.error(f"Error in test_llm: {str(e)}", exc_info=True)
                await ctx.send(f"An error occurred while testing the LLM: {str(e)[:1000]}")

    async def update_langchain_components(self):
        try:
            self.logger.info("Starting to update LangChain components")
            api_key = await self.config.api_key()
            model = await self.config.model()
            
            if not api_key:
                self.logger.error("API key not set. Please use the 'air apikey' command to set it.")
                return
            
            self.logger.info(f"Using Model: {model}")
            self.llm = ChatDeepInfra(
                model=model,
                deepinfra_api_token=api_key,
                streaming=True,  # Enable streaming
                temperature=0.7,  # Add some randomness to responses
                max_tokens=1000  # Limit the response length
            )
            
            custom_personality = await self.config.custom_personality()
            memory = ConversationBufferWindowMemory(k=5, memory_key="chat_history", return_messages=True)
            
            template = f"""You are an AI assistant with the following personality: {custom_personality}
            You are in a Discord server, responding to user messages.
            Respond naturally and conversationally, as if you're chatting with a friend.
            Always maintain your assigned personality throughout the conversation.

            Human: {{input}}
            AI: To approach this, let's think step-by-step:

            {{agent_scratchpad}}

            Available tools:
            {{tools}}

            Tool names: {{tool_names}}

            Remember to use tools only when necessary, and always explain your thought process.
            """
            
            prompt = ChatPromptTemplate.from_messages([
                ("system", template),
                ("human", "{input}"),
                ("ai", "{agent_scratchpad}")
            ])
            
            self.logger.info("Setting up tools")
            tools = await self.setup_tools()
            
            self.logger.info("Creating agent executor")
            agent = initialize_agent(
                tools,
                self.llm,
                agent=AgentType.CHAT_CONVERSATIONAL_REACT_DESCRIPTION,
                verbose=True,
                handle_parsing_errors=True
            )
            
            self.agent_executor = AgentExecutor.from_agent_and_tools(
                agent=agent,
                tools=tools,
                memory=memory,
                verbose=True,
                max_iterations=10,
                max_execution_time=60,
                early_stopping_method="generate",
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

            self.logger.info(f"Invoking agent with input: {content}")
            
            try:
                self.logger.info(f"Agent executor config: {self.agent_executor.agent}")
                self.logger.info(f"LLM config: {self.llm.model_kwargs}")

                input_data = {
                    "input": content,
                    "chat_history": []  # You may want to implement chat history if needed
                }
                self.logger.debug(f"Input data for agent: {input_data}")

                full_response = ""
                async for chunk in self.agent_executor.astream(
                    input_data,
                    {"callbacks": [DiscordCallbackHandler(response_message)]}
                ):
                    if isinstance(chunk, dict) and 'output' in chunk:
                        full_response += chunk['output']
                        await response_message.edit(content=full_response[:2000])  # Discord message limit

                self.logger.info(f"Final response: {full_response}")

                return full_response

            except Exception as e:
                self.logger.error(f"Error in agent_executor.astream: {str(e)}", exc_info=True)
                return f"An error occurred while processing your request: {str(e)[:1000]}"

        except Exception as e:
            self.logger.error(f"Unexpected error in process_query: {str(e)}", exc_info=True)
            return "I encountered an unexpected error while processing your request. Please try again or contact the bot owner if the issue persists."

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
        lines = output.split('\n')
        cleaned_lines = []
        response_found = False
        for line in lines:
            if line.startswith('Response:'):
                response_found = True
                cleaned_lines.append(line[9:].strip())  # Remove 'Response:' prefix
            elif response_found:
                cleaned_lines.append(line.strip())
            elif not line.startswith(('Thought:', 'Action:', 'Action Input:', 'Observation:')):
                cleaned_lines.append(line.strip())
        return '\n'.join(cleaned_lines)

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
            response = await self.llm.agenerate([HumanMessage(content="Hello, can you hear me?")])
            if response and response.generations:
                self.logger.info("API settings verified successfully")
                return True
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
