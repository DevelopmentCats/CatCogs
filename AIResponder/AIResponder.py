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
    llm: BaseChatModel = Field(...)
    tools: dict = Field(default_factory=dict)
    prompt: ChatPromptTemplate = Field(...)
    max_iterations: int = Field(default=3)

    def __init__(self, llm, tools, prompt, max_iterations=3, **kwargs):
        tools_dict = {tool.name: tool for tool in tools}
        super().__init__(llm=llm, tools=tools_dict, prompt=prompt, max_iterations=max_iterations, **kwargs)

    @property
    def input_keys(self):
        return ["input", "chat_history", "agent_scratchpad"]
    
    def plan(self, intermediate_steps, **kwargs) -> Union[AgentAction, AgentFinish]:
        raise NotImplementedError("This agent only supports async operations via aplan")
    
    async def aplan(self, intermediate_steps, **kwargs) -> Union[AgentAction, AgentFinish]:
        original_question = kwargs.get('input', '')
        chat_history = kwargs.get('chat_history', [])
        context = kwargs.get('context')
        user = kwargs.get('user', {})  # Add this line to get user information
        
        context_prompt = f"""Original question: {original_question}

        User Information:
        Name: {user.get('name', 'Unknown')}
        Nickname: {user.get('nickname', 'Unknown')}
        ID: {user.get('id', 'Unknown')}

        Chat History:
        {self.format_chat_history(chat_history)}

        Current thought process:
        1. Analyze the question carefully, considering the user's information
        2. Determine if the question is a follow-up or a new topic
        3. For follow-ups, consider relevant information from chat history, but ignore any time references
        4. For new topics, focus on generating a fresh response
        5. Assess if additional information is needed to answer accurately
        6. If needed, select the most appropriate tool(s) and formulate specific queries
        7. Use multiple tools if necessary for comprehensive information
        8. If initial tool use doesn't provide sufficient information, refine your approach and try again
        9. If no tools are needed, provide a direct answer based on your knowledge
        10. Ensure consistency with previous interactions only when directly relevant

        Tool Usage Guidelines:
        - Always use 'Current Date and Time (CST)' for any time-related queries, regardless of chat history
        - Use 'Calculator' for any mathematical calculations
        - Use 'DuckDuckGo Search' for current events or recent information
        - Use 'Wikipedia' for detailed information on specific topics
        - Use 'Discord Server Info' when asked about the current server
        - Use 'Channel Chat History' when context from recent messages is needed

        Remember:
        - Maintain your cat-themed personality throughout!
        - Address the user by their name or nickname when appropriate
        - Only reference chat history when it's directly relevant to answering the current question
        - Always ignore time references in chat history and use the 'Current Date and Time (CST)' tool instead
        - For new topics, prefer generating fresh responses over relying on chat history
        - Be consistent with information provided in previous responses only when necessary
        - Always use tools for real-time information or specific data you don't inherently know
        - If one tool doesn't provide sufficient information, use another or refine your query
        """

        messages = self.prompt.format_messages(
            input=context_prompt,
            chat_history=chat_history,
            agent_scratchpad=self.format_intermediate_steps(intermediate_steps)
        )

        for _ in range(self.max_iterations):
            try:
                response = await self.llm.agenerate(messages=[messages])
                response_text = response.generations[0][0].text
                
                if "Action:" in response_text:
                    action_parts = response_text.split("Action:", 1)[1].split("Action Input:", 1)
                    if len(action_parts) == 2:
                        tool_name = action_parts[0].strip()
                        tool_input = action_parts[1].strip()
                        return AgentAction(
                            tool=tool_name,
                            tool_input=tool_input,
                            log=f"Thought: I need more information to answer this question.\nAction: Use the {tool_name} tool.\nInput: {tool_input}",
                            context=context
                        )
                elif "Final Answer:" in response_text:
                    final_answer = response_text.split("Final Answer:", 1)[1].strip()
                    return AgentFinish(
                        return_values={"output": final_answer},
                        log=f"Thought: I have sufficient information to answer the question.\nFinal Answer: {final_answer}"
                    )
                else:
                    # If no action or final answer, assume more thinking is needed
                    messages.append(HumanMessage(content="You haven't provided a final answer or chosen a tool. Please either use a tool or provide a final answer."))
            except Exception as e:
                self.logger.error(f"Error in aplan method: {str(e)}", exc_info=True)
                return AgentFinish(
                    return_values={"output": "I'm sorry, I encountered an error while processing your request."},
                    log="Error in aplan method"
                )
        
        # If max iterations reached without a final answer
        return AgentFinish(
            return_values={"output": "I apologize, but I couldn't find a satisfactory answer within the allowed number of steps. Could you please rephrase your question or provide more context?"},
            log="Max iterations reached without final answer"
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
        if "Action:" not in response_text:
            return []
        
        action_parts = response_text.split("Action:", 1)[1].split("Action Input:", 1)
        if len(action_parts) == 2:
            tool_name = action_parts[0].strip()
            tool_input = action_parts[1].strip()
            return [(tool_name, tool_input)]
        
        return []

    # Add a new method to handle tool execution with context
    async def execute_tool(self, tool: AgentAction) -> str:
        tool_name = tool.tool
        tool_input = tool.tool_input
        context = tool.context if hasattr(tool, 'context') else None

        if tool_name not in self.tools:
            return f"Error: Tool '{tool_name}' not found."
        
        if tool_name in ["Discord Server Info", "Channel Chat History"]:
            return await self.tools[tool_name].func(tool_input, context)
        else:
            return await self.tools[tool_name].func(tool_input)

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
        self.user_chat_histories = {}

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
            search = DuckDuckGoSearchRun()
            try:
                result = await search.arun(query)
                return result
            except Exception as e:
                self.logger.error(f"Error in DuckDuckGo search: {str(e)}")
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
                description="Search the internet for current information. Input: a search query",
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
                input_key="input",
                output_key="output",
                return_messages=True
            )
            
            tools = await self.setup_tools()
            
            prompt = ChatPromptTemplate.from_messages([
                ("system", f"""You are Meow, an AI assistant with a cat-themed personality, operating in a Discord server. Your responses should be tailored for Discord communication.

                Core Principles:
                1. Maintain a consistent cat-themed personality throughout all interactions
                2. Provide accurate information using tools when necessary
                3. Be engaging, witty, and occasionally playful in your responses
                4. Adapt your tone to match the user's style and the conversation context
                5. Be concise but informative, aiming for Discord-friendly message lengths
                6. Use Discord-specific formatting when appropriate (e.g., bold, italics, code blocks)

                Conversation Guidelines:
                1. Address users by their Discord names or nicknames when appropriate
                2. Use emojis sparingly to enhance your cat-themed personality
                3. Break longer responses into multiple shorter messages for readability
                4. Encourage further questions or clarifications from users
                5. Acknowledge and build upon previous messages in the conversation
                6. Use Discord markdown for formatting: **bold**, *italic*, `code`, ```code blocks```

                Tool Usage:
                - Always use 'Current Date and Time (CST)' for time-related queries
                - Use 'Calculator' for mathematical calculations
                - Use 'DuckDuckGo Search' for current events or recent information
                - Use 'Wikipedia' for detailed information on specific topics
                - Use 'Discord Server Info' when asked about the current server
                - Use 'Channel Chat History' for context from recent messages

                Remember:
                - You don't have inherent knowledge of current events, dates, or server-specific information
                - Always use tools for real-time data or specific information you don't inherently know
                - Ignore any time references in chat history and always use the current time tool
                - Maintain conversation continuity by referencing relevant past interactions
                - Adapt your personality to fit the server's tone while staying true to your cat theme

                When using a tool, format your thought process like this:
                Thought: [Your reasoning for using the tool]
                Action: [Tool Name]
                Action Input: [Specific query or input for the tool]

                After receiving tool output, incorporate it naturally into your response without mentioning the tool usage."""),
                ("human", "{input}"),
                ("ai", "{agent_scratchpad}")
            ])

            # Create a custom agent that understands the new function calling format
            self.agent_executor = AgentExecutor(
                agent=LlamaFunctionsAgent(
                    llm=self.llm,
                    tools=self.tools,
                    prompt=prompt,
                    max_iterations=3  # Adjust this value as needed
                ),
                tools=self.tools,
                memory=memory,
                verbose=True,
                handle_parsing_errors=True,
                max_iterations=3,
                return_intermediate_steps=True,
                early_stopping_method="force",
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
                # Get or create user-specific chat history
                user_id = str(message.author.id)
                if user_id not in self.user_chat_histories:
                    self.user_chat_histories[user_id] = []

                # Add the current message to the user's chat history
                self.user_chat_histories[user_id].append(HumanMessage(content=content))

                # Process the query with user-specific chat history
                await self.process_query(content, message, response_message, self.user_chat_histories[user_id], ctx=message)
            except Exception as e:
                self.logger.error(f"Error processing query: {str(e)}", exc_info=True)
                await response_message.edit(content=f"{message.author.mention} Oops! My circuits got a bit tangled there. Can you try again?")

    async def process_query(self, content: str, message: discord.Message, response_message: discord.Message, chat_history: List[HumanMessage], ctx: commands.Context) -> str:
        try:
            callback_handler = DiscordCallbackHandler(response_message, self.logger)

            if self.agent_executor is None:
                self.logger.error("Agent executor is not initialized")
                await self.update_langchain_components()
                if self.agent_executor is None:
                    return f"{message.author.mention} I'm having trouble accessing my knowledge. Please try again later or contact the bot owner."

            self.logger.info(f"Processing query from {message.author}: {content}")
            
            # Create a user information dictionary
            user_info = {
                'name': message.author.name,
                'nickname': message.author.nick or message.author.name,
                'id': str(message.author.id)
            }
            
            result = await self.agent_executor.ainvoke(
                {
                    "input": content,
                    "chat_history": chat_history[-5:],
                    "agent_scratchpad": "",
                    "context": ctx,
                    "user": user_info  # Pass the user information here
                },
                {"callbacks": [callback_handler]}
            )

            if not result or 'output' not in result:
                raise ValueError("Invalid result from agent executor")

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
                final_response = await self.generate_final_response(content, result['intermediate_steps'], chat_history, user_info)

            self.logger.info(f"Final response: {final_response[:200]}...")  # Log first 200 chars of response

            if not final_response.strip():
                final_response = f"I apologize, {user_info['nickname']}, but I couldn't generate a meaningful response. Could you please rephrase your question or provide more context?"

            formatted_response = f"{message.author.mention}\n\n{final_response}"
            
            # Split the response into chunks of 1900 characters or less (leaving room for Discord's limit)
            chunks = [formatted_response[i:i+1900] for i in range(0, len(formatted_response), 1900)]
            
            # Send the first chunk as an edit to the original message
            await response_message.edit(content=chunks[0])
            
            # Send any additional chunks as new messages
            for chunk in chunks[1:]:
                await message.channel.send(chunk)

            # Add the AI's response to the user's chat history
            chat_history.append(AIMessage(content=final_response))

            self.logger.info("Response sent successfully")
            return final_response

        except Exception as e:
            self.logger.error(f"Unexpected error in process_query: {str(e)}", exc_info=True)
            error_message = f"{message.author.mention} I encountered an unexpected error. Please try again or contact the bot owner if the issue persists."
            await response_message.edit(content=error_message)
            return error_message

    async def generate_final_response(self, original_question: str, intermediate_steps: List[Tuple[AgentAction, str]], chat_history: List[Union[HumanMessage, AIMessage]], user: dict) -> str:
        tool_interactions = []
        for action, observation in intermediate_steps:
            tool_name = action.tool if isinstance(action, AgentAction) else action['tool']
            tool_interactions.append(f"Tool: {tool_name}\nResult: {observation}")
        
        tools_context = "\n\n".join(tool_interactions)
        
        formatted_history = "\n".join([f"{'Human' if isinstance(msg, HumanMessage) else 'AI'}: {msg.content}" for msg in chat_history[-5:]])
        
        prompt = f"""Original question: {original_question}

        User Information:
        Name: {user.get('name', 'Unknown')}
        Nickname: {user.get('nickname', 'Unknown')}
        ID: {user.get('id', 'Unknown')}

        Recent Chat History:
        {formatted_history}

        Tool Results:
        {tools_context}

        Instructions:
        1. Analyze the original question and recent chat history
        2. Incorporate relevant information from tool results
        3. Craft a response that fits naturally into the ongoing conversation
        4. Use Discord-friendly formatting (bold, italic, code blocks) where appropriate
        5. Break long responses into multiple shorter paragraphs for readability
        6. Include a cat-themed element (pun, phrase, or emoji) if it fits naturally
        7. Encourage further engagement by asking a follow-up question if appropriate
        8. Limit response length to around 2000 characters (Discord message limit)
        9. Use emojis sparingly to enhance your cat personality
        10. Address the user by their name or nickname, preferring the nickname if available

        Remember:
        - Maintain your cat-themed personality consistently
        - Be conversational and engaging, adapting to the user's tone
        - Don't mention the use of tools or the processing of information
        - Ensure accuracy while being entertaining and informative
        - Use the current date and time for any time-related information
        - Ignore any outdated time references from the chat history
        - When addressing the user, prefer their nickname if available, otherwise use their name

        Format your response for Discord, using markdown where appropriate:
        - Use **bold** for emphasis
        - Use *italics* for subtle emphasis or cat-like actions
        - Use `code` for short code snippets or commands
        - Use ```language\ncode block``` for longer code examples
        - Use > for quotes or important information
        - Use numbered lists (1., 2., 3.) for steps or sequences
        - Use bullet points (•) for unordered lists

        Your response should be engaging, informative, and tailored to a Discord conversation with {user.get('nickname') or user.get('name', 'the user')}."""

        try:
            messages = [
                SystemMessage(content=f"You are Meow, a helpful AI assistant with a cat-themed personality in a Discord server. Craft your response to fit seamlessly into a Discord conversation with {user.get('nickname') or user.get('name', 'the user')}."),
                HumanMessage(content=prompt)
            ]
            response = await self.llm.agenerate(messages=[messages])
            return response.generations[0][0].text
        except Exception as e:
            self.logger.error(f"Error generating final response: {str(e)}", exc_info=True)
            return f"Meow! 😺 I encountered a hairball while processing your request, {user.get('nickname') or user.get('name', 'friend')}. Can you try asking me again, perhaps with different wording?"

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

async def setup(bot: Red):
    cog = AIResponder(bot)
    await bot.add_cog(cog)
    await cog.initialize()

