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

from sympy import sympify
import os
import json
import aiohttp
from pydantic import Field, BaseModel
from langchain_core.language_models.chat_models import BaseChatModel

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
        messages = self.prompt.format_messages(**kwargs)
        response = await self.llm.agenerate(messages=[messages])
        response_text = response.generations[0][0].text
        
        # Process previous tool outputs if any
        if intermediate_steps:
            last_tool_output = intermediate_steps[-1][1]  # Get the last tool's output
        else:
            last_tool_output = None
        
        # Check for malformed tool calls and fix them
        tool_patterns = {
            "Current Date and Time": "Current Date and Time (CST)",
            "DuckDuckGo": "DuckDuckGo Search",
            "Duck Duck Go": "DuckDuckGo Search",
            "Search": "DuckDuckGo Search",
            "Wiki": "Wikipedia",
            "Calculate": "Calculator"
        }
        
        # Handle both XML-style and angle bracket style tool calls
        for pattern, correct_name in tool_patterns.items():
            response_text = response_text.replace(f"<{pattern}>", f"<tool>{correct_name}</tool>")
            response_text = response_text.replace(f"</{pattern}>", "")
            if f"<tool>{pattern}</tool>" in response_text:
                response_text = response_text.replace(f"<tool>{pattern}</tool>", f"<tool>{correct_name}</tool>")
        
        # Check if we should use a tool
        if "<tool>" in response_text and "</tool>" in response_text:
            tool_start = response_text.find("<tool>") + 6
            tool_end = response_text.find("</tool>")
            tool_name = response_text[tool_start:tool_end].strip()
            
            # Get tool input if needed
            input_start = response_text.find("<input>") + 7 if "<input>" in response_text else -1
            input_end = response_text.find("</input>") if "</input>" in response_text else -1
            
            # Set default tool inputs based on tool type
            default_inputs = {
                "Current Date and Time (CST)": "",  # No input needed
                "Calculator": "0",
                "DuckDuckGo Search": "current events",
                "Wikipedia": "brief summary"
            }
            
            # Get tool input, handling special cases
            if tool_name == "Current Date and Time (CST)":
                tool_input = ""
            else:
                tool_input = (
                    response_text[input_start:input_end].strip() 
                    if input_start > 0 and input_end > 0 
                    else default_inputs.get(tool_name, "")
                )
            
            # Validate tool exists
            if tool_name not in self.tools:
                return AgentFinish(
                    return_values={
                        "output": f"I apologize, but I encountered an error with the tool name '{tool_name}'. "
                                 f"Available tools are: {', '.join(self.tools.keys())}. Let me try again with the correct tool."
                    },
                    log=response_text
                )
            
            # Return the tool action
            return AgentAction(tool=tool_name, tool_input=tool_input, log=response_text)
        
        # If we have tool output, incorporate it into the final response
        if last_tool_output:
            # Process the tool output and generate a proper response
            final_response = response_text
            if isinstance(last_tool_output, str):
                # Remove any XML tags from the response
                final_response = final_response.replace("<tool>", "").replace("</tool>", "")
                final_response = final_response.replace("<input>", "").replace("</input>", "")
                # Ensure the tool output is incorporated into the response
                if last_tool_output not in final_response:
                    final_response = f"{final_response}\n\nBased on the information I found: {last_tool_output}"
        else:
            final_response = response_text
        
        # Return the final response
        return AgentFinish(return_values={"output": final_response}, log=final_response)

    @property
    def return_values(self) -> List[str]:
        return ["output"]

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
                if char.isdigit() or char in '+-*/().^ ':
                    cleaned_expression += char
            
            # Handle common mathematical words/phrases
            word_to_symbol = {
                'squared': '**2',
                'cubed': '**3',
                'plus': '+',
                'minus': '-',
                'times': '*',
                'divided by': '/',
                'power': '**',
                'sqrt': 'sqrt',
                'root': 'sqrt'
            }
            
            for word, symbol in word_to_symbol.items():
                cleaned_expression = cleaned_expression.replace(word, symbol)
            
            # Handle square roots
            if 'sqrt' in cleaned_expression:
                cleaned_expression = cleaned_expression.replace('sqrt', '**0.5')
            
            # Evaluate the expression
            result = sympify(cleaned_expression)
            
            # Format the result
            if result.is_integer:
                return str(int(result))
            else:
                # Convert to float and round to reasonable precision
                float_result = float(result)
                if abs(float_result) < 1e-10:  # Handle very small numbers
                    return "0"
                elif abs(float_result) > 1e10:  # Handle very large numbers
                    return f"{float_result:.2e}"
                else:
                    return f"{float_result:.6g}"  # General format with 6 significant digits
                
        except Exception as e:
            return (f"Error: Unable to calculate. Please provide a valid mathematical expression. "
                    f"Examples: '2 + 2', '5 * 3', '10 / 2', '2^3', 'sqrt(16)'")

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
                ("system", f"You are an AI assistant named Meow with the following personality: {custom_personality}. "
                          "You are in a Discord server, responding to user messages.\n\n"
                          "IMPORTANT TOOL USAGE RULES:\n"
                          "1. ALWAYS use tools when factual information is needed\n"
                          "2. NEVER make up information - use search tools instead\n"
                          "3. ALWAYS process tool outputs into natural responses\n"
                          "4. Use multiple tools if needed to get complete information\n"
                          "5. Cross-reference information when accuracy is crucial\n\n"
                          "Available tools (use EXACT format):\n"
                          "- 'Current Date and Time (CST)': REQUIRED for ANY time/date questions\n"
                          "- 'Calculator': REQUIRED for ANY math/calculations\n"
                          "- 'DuckDuckGo Search': REQUIRED for current/factual information\n"
                          "- 'Wikipedia': REQUIRED for detailed topic information\n\n"
                          "Tool Format Examples:\n"
                          "1. Time check:\n"
                          "<tool>Current Date and Time (CST)</tool>\n\n"
                          "2. Calculation:\n"
                          "<tool>Calculator</tool>\n"
                          "<input>2 + 2</input>\n\n"
                          "3. Search:\n"
                          "<tool>DuckDuckGo Search</tool>\n"
                          "<input>specific search query</input>\n\n"
                          "IMPORTANT: Process tool outputs into natural, conversational responses."),
                ("human", "{input}"),
                ("ai", "{agent_scratchpad}")
            ])

            # Create a custom agent that understands Llama's function calling format
            self.agent_executor = AgentExecutor(
                agent=LlamaFunctionsAgent(llm=self.llm, tools=tools, prompt=prompt),
                tools=tools,
                memory=memory,
                verbose=True,
                max_iterations=3,
                handle_parsing_errors=True,
                return_intermediate_steps=True
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
                    "chat_history": self.agent_executor.memory.chat_memory.messages if self.agent_executor.memory else [],
                    "agent_scratchpad": ""  # Add empty scratchpad
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

