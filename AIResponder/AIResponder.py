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
from langchain.agents import AgentExecutor, create_openai_functions_agent, BaseSingleActionAgent
from langchain_core.agents import AgentAction, AgentFinish
from langchain.memory import ConversationBufferWindowMemory
from langchain_community.utilities import DuckDuckGoSearchAPIWrapper, WikipediaAPIWrapper
from langchain_community.tools import DuckDuckGoSearchResults, WikipediaQueryRun
from langchain_experimental.tools import PythonAstREPLTool
from langchain_openai import ChatOpenAI
from langchain_community.tools.ddg_search.tool import DuckDuckGoSearchRun

from sympy import sympify, SympifyError, E, pi, oo, zoo
import os
import json
import aiohttp
from pydantic import Field, BaseModel
from langchain_core.language_models.chat_models import BaseChatModel
import re
import math

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

class LlamaFunctionsAgent(BaseSingleActionAgent, BaseModel):
    llm: BaseChatModel = Field(...)  # Required field
    tools: dict = Field(default_factory=dict)
    prompt: ChatPromptTemplate = Field(...)

    def __init__(self, llm, tools, prompt, **kwargs):
        tools_dict = {tool.name: tool for tool in tools}
        super().__init__(llm=llm, tools=tools_dict, prompt=prompt, **kwargs)

    @property
    def input_keys(self):
        return ["input", "chat_history", "agent_scratchpad"]
    
    def plan(self, intermediate_steps, **kwargs) -> Union[AgentAction, AgentFinish]:
        raise NotImplementedError("This agent only supports async operations via aplan")
    
    async def aplan(self, intermediate_steps, **kwargs) -> Union[AgentAction, AgentFinish]:
        original_question = kwargs.get('input', '')
        chat_history = kwargs.get('chat_history', [])
        
        context = f"""Original question: {original_question}

        Previous interactions:
        {self.format_chat_history(chat_history)}

        Current thought process:
        1. Analyze the question and previous interactions
        2. Determine if additional information is needed
        3. If needed, select the most appropriate tool(s) and formulate specific queries or inputs
        4. You can use multiple tools if necessary
        5. IMPORTANT: ALWAYS use the following format for ALL tool calls:
           <tool>Tool Name</tool>
           <input>Specific query or input for the tool</input>
        6. If no tools are needed, provide a direct answer

        Remember:
        - Maintain your cat-themed personality throughout!
        - You MUST use the exact tool call format for every tool use.
        - Never attempt to use tools in any other format.
        """

        messages = self.prompt.format_messages(
            input=context,
            chat_history=chat_history,
            agent_scratchpad=self.format_intermediate_steps(intermediate_steps)
        )

        try:
            response = await self.llm.agenerate(messages=[messages], tool_choice="auto")
            response_text = response.generations[0][0].text
            
            tool_calls = self.extract_tool_calls(response_text)
            
            if tool_calls:
                actions = []
                for tool_name, tool_input in tool_calls:
                    actions.append(AgentAction(
                        tool=tool_name,
                        tool_input=tool_input,
                        log=f"Thought: I need more information to answer this question.\nAction: Use the {tool_name} tool.\nInput: {tool_input}"
                    ))
                return actions if len(actions) > 1 else actions[0]
            else:
                clean_response = self.clean_response(response_text)
                return AgentFinish(
                    return_values={"output": clean_response},
                    log=f"Thought: I can answer this question directly without using any tools.\nFinal Answer: {clean_response}"
                )
        except Exception as e:
            self.logger.error(f"Error in aplan method: {str(e)}", exc_info=True)
            return AgentFinish(
                return_values={"output": "I'm sorry, I encountered an error while processing your request."},
                log="Error in aplan method"
            )

    def format_chat_history(self, chat_history):
        formatted = []
        for message in chat_history[-5:]:  # Only consider last 5 messages
            role = "Human" if isinstance(message, HumanMessage) else "AI"
            formatted.append(f"{role}: {message.content}")
        return "\n".join(formatted)

    def format_intermediate_steps(self, intermediate_steps):
        formatted = []
        for action, observation in intermediate_steps:
            formatted.append(f"Action: {action.tool}\nInput: {action.tool_input}\nObservation: {observation}")
        return "\n".join(formatted)

    def extract_tool_info(self, response_text):
        tool_start = response_text.find("<tool>") + 6
        tool_end = response_text.find("</tool>")
        tool_name = response_text[tool_start:tool_end].strip()
        
        input_start = response_text.find("<input>") + 7
        input_end = response_text.find("</input>")
        tool_input = response_text[input_start:input_end].strip() if input_start > 0 and input_end > 0 else ""
        
        return tool_name, tool_input

    def extract_reason(self, response_text):
        reason_start = response_text.find("Reason:") + 7
        reason_end = response_text.find("<tool>")
        return response_text[reason_start:reason_end].strip() if reason_start > 0 and reason_end > 0 else ""

    def clean_response(self, response_text):
        clean = response_text
        for tag in ['<tool>', '</tool>', '<input>', '</input>']:
            clean = clean.replace(tag, '')
        return clean.strip()

    @property
    def return_values(self) -> List[str]:
        return ["output"]

    def extract_tool_calls(self, response_text):
        tool_calls = []
        tool_pattern = r'<tool>(.*?)</tool>'
        input_pattern = r'<input>(.*?)</input>'
        
        tool_matches = re.findall(tool_pattern, response_text, re.DOTALL)
        input_matches = re.findall(input_pattern, response_text, re.DOTALL)
        
        for tool, input_text in zip(tool_matches, input_matches):
            tool_calls.append((tool.strip(), input_text.strip()))
        
        return tool_calls

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
        """Initialize the cog."""
        self.config = Config.get_conf(self, identifier=1234567890)
        default_global = {
            "api_key": None,
            "model": "meta-llama/Llama-3.2-11B-Vision-Instruct",
            "custom_personality": "friendly and helpful"
        }
        default_guild = {
            "disabled_channels": []
        }
        
        self.config.register_global(**default_global)
        self.config.register_guild(**default_guild)
        
        self.logger = logging.getLogger("red.airesponder")
        
        if not await self.is_configured():
            self.logger.warning("AIResponder is not configured yet")
            return
            
        try:
            api_key = await self.config.api_key()
            model = await self.config.model()
            
            self.logger.info(f"Initializing DeepInfra LLM with model: {model}")
            self.llm = ChatOpenAI(
                model=model,
                api_key=api_key,
                base_url="https://api.deepinfra.com/v1/openai",
                temperature=0.7,
                streaming=True
            )
            
            # Initialize and store tools
            self.tools = await self.setup_tools()
            
            await self.update_langchain_components()
            if await self.verify_api_settings():
                self.logger.info("AIResponder initialized successfully")
            else:
                self.logger.error("Failed to verify API settings")
        except Exception as e:
            self.logger.error(f"Error in initialization: {str(e)}", exc_info=True)

    async def setup_tools(self):
        # Create a sync wrapper for our async function
        def sync_get_current_date_time_cst(_input: str = None):
            return asyncio.run_coroutine_threadsafe(
                self.get_current_date_time_cst(_input),
                self.bot.loop
            ).result()

        tools = [
            Tool(
                name="Current Date and Time (CST)",
                func=sync_get_current_date_time_cst,  # Use the sync wrapper
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
                func=DuckDuckGoSearchRun().run,
                description="Search the internet for current information. Input: a search query",
                return_direct=True
            ),
            Tool(
                name="Wikipedia",
                func=WikipediaQueryRun(api_wrapper=WikipediaAPIWrapper()).run,
                description="Get detailed information from Wikipedia. Input: a topic or query",
                return_direct=True
            )
        ]
        return tools

    def calculator(self, expression: str) -> str:
        try:
            # Clean and normalize the expression
            cleaned_expression = ''
            for char in expression.lower().replace('x', '*').replace('×', '*').replace('÷', '/'):
                if char.isalnum() or char in '+-*/().^ ':
                    cleaned_expression += char
            
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
            
            for word, symbol in word_to_symbol.items():
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
            # Configure memory with specific input/output keys
            memory = ConversationBufferWindowMemory(
                k=5,
                memory_key="chat_history",
                input_key="input",  # Specify which key to use for input
                output_key="output",  # Specify which key to use for output
                return_messages=True
            )
            
            tools = await self.setup_tools()
            
            prompt = ChatPromptTemplate.from_messages([
                ("system", f"""You are an AI assistant named Meow with the following personality: {custom_personality}. 
                You are in a Discord server, responding to user messages.

                Core Principles:
                1. Maintain your cat-themed personality consistently.
                2. Always use tools for specific types of information - you do not have this knowledge inherently.
                3. Engage users with fun, witty responses.
                4. Never make up or guess information.

                Tool Usage:
                - For ANY time/date information: ALWAYS use 'Current Date and Time (CST)'
                - For ANY calculations: ALWAYS use 'Calculator'
                - For current events or recent information: ALWAYS use 'DuckDuckGo Search'
                - For detailed information on topics: ALWAYS use 'Wikipedia'

                IMPORTANT: ALWAYS use the following format for ALL tool calls:
                <tool>Tool Name</tool>
                <input>Specific query or input for the tool</input>

                Examples:
                <tool>DuckDuckGo Search</tool>
                <input>Latest news in technology</input>

                <tool>Wikipedia</tool>
                <input>History of cats in ancient Egypt</input>

                <tool>Current Date and Time (CST)</tool>
                <input>What is the current date and time?</input>

                <tool>Calculator</tool>
                <input>234 * 17 + 3</input>

                Response Structure:
                1. Analyze the user's question and determine if a tool is needed.
                2. If a tool is needed, use it with the EXACT format shown above.
                3. After receiving tool data, craft a natural, engaging response.
                4. Incorporate tool information seamlessly into your cat-themed personality without mentioning the tools.

                Remember: You do not inherently know the current date, time, or any real-time information. ALWAYS use tools for such data!"""),
                ("human", "{input}"),
                ("ai", "{agent_scratchpad}")
            ])

            # Create a custom agent that understands Llama's function calling format
            self.agent_executor = AgentExecutor(
                agent=LlamaFunctionsAgent(llm=self.llm, tools=tools, prompt=prompt),
                tools=tools,
                memory=memory,
                verbose=True,
                handle_parsing_errors=True,
                max_iterations=3,
                return_intermediate_steps=True,  # Ensure this is True
                early_stopping_method="force",  # Ensure this is set to force LLM response
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
                await response_message.edit(content=f"{message.author.mention}  Oops! My circuits got a bit tangled there. Can you try again?")

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
                    "chat_history": self.agent_executor.memory.chat_memory.messages if self.agent_executor.memory else [],
                    "agent_scratchpad": ""  # Add empty scratchpad
                },
                {"callbacks": [callback_handler]}
            )

            if not result or 'output' not in result:
                raise ValueError("Invalid result from agent executor")

            # Ensure the final response is generated after all tool interactions
            final_response = result['output']
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
                # Generate the final response using the LLM after processing tool outputs
                final_response = await self.generate_final_response(content, result['intermediate_steps'])

            self.logger.info(f"Final response: {final_response[:200]}...")  # Log first 200 chars of response

            if not final_response.strip():
                final_response = "I apologize, but I couldn't generate a meaningful response. Could you please rephrase your question or provide more context?"

            formatted_response = f"{user_mention}\n\n{final_response}"
            return formatted_response[:2000]  # Truncate to Discord's limit

        except Exception as e:
            self.logger.error(f"Unexpected error in process_query: {str(e)}", exc_info=True)
            return f"{user_mention} I encountered an unexpected error. Please try again or contact the bot owner if the issue persists."

    async def generate_final_response(self, original_question: str, intermediate_steps: List[Tuple[AgentAction, str]]) -> str:
        tool_interactions = []
        for action, observation in intermediate_steps:
            tool_name = action.tool if isinstance(action, AgentAction) else action['tool']
            tool_interactions.append(f"Tool: {tool_name}\nResult: {observation}")
        
        tools_context = "\n\n".join(tool_interactions)
        
        prompt = f"""Original question: {original_question}

        Tool Results:
        {tools_context}

        Instructions:
        1. Ensure you've used the appropriate tools for any time, date, or real-time information.
        2. Craft a natural, engaging response that incorporates the information from the tools.
        3. Maintain your cat-themed personality throughout the response.
        4. Ensure your answer is accurate, fun, and tailored to the user's question.
        5. Do not mention or reference the use of any tools in your response.
        6. Present the information as if it's your own knowledge.
        7. If appropriate, add a playful cat-related comment or pun.

        Remember: You are Meow, a helpful AI assistant with a cat-themed personality. Your goal is to provide accurate information while being entertaining and engaging, without revealing the sources of your information. Always use tools for current date, time, or any real-time data."""

        try:
            messages = [
                SystemMessage(content="You are a helpful AI assistant named Meow with a cat-themed personality. Never mention using tools or looking up information. Present all knowledge as if it's your own, but always ensure you've used tools for current date, time, or real-time information."),
                HumanMessage(content=prompt)
            ]
            response = await self.llm.agenerate(messages=[messages])
            return response.generations[0][0].text
        except Exception as e:
            self.logger.error(f"Error generating final response: {str(e)}", exc_info=True)
            return "I'm sorry, I encountered an error while processing your request. Can you try asking me again, perhaps with a different wording?"

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
