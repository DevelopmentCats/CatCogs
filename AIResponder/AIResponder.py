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
    max_iterations: int = Field(default=5)

    def __init__(self, llm, tools, prompt, max_iterations=5, **kwargs):
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
        user = kwargs.get('user', {})
        
        user_display_name = user.get('nickname')
        
        context_prompt = f"""Question: {original_question}

        User: {user_display_name} (ID: {user.get('id', 'Unknown')})
        
        Recent Chat History:
        {self.format_chat_history(chat_history)}

        Current Context:
        {context if context else 'No additional context provided'}

        Remember: Always address the user as {user_display_name} and include exactly one emoji in your final response."""

        messages = self.prompt.format_messages(
            input=context_prompt,
            chat_history=chat_history,
            agent_scratchpad=self.format_intermediate_steps(intermediate_steps)
        )

        for iteration in range(self.max_iterations):
            logging.info(f"Iteration {iteration + 1}/{self.max_iterations}")
            try:
                response = await self.llm.agenerate(messages=[messages])
                response_text = response.generations[0][0].text
                logging.info(f"AI Response: {response_text[:100]}...")  # Log first 100 chars
                
                if "Action:" in response_text:
                    action_parts = response_text.split("Action:", 1)[1].split("Action Input:", 1)
                    if len(action_parts) == 2:
                        tool_name = action_parts[0].strip()
                        tool_input = action_parts[1].split('\n')[0].strip()  # Only take the first line
                        
                        # Clean up tool name
                        tool_name = tool_name.strip('*').strip()
                        
                        logging.info(f"Attempting to use tool: {tool_name}")
                        
                        # Check if the cleaned tool name is valid
                        if tool_name in self.tools:
                            return AgentAction(
                                tool=tool_name,
                                tool_input=tool_input,
                                log=f"Thought: I need more information to answer this question.\nAction: Use the {tool_name} tool.\nInput: {tool_input}",
                                context=kwargs.get('context')
                            )
                        else:
                            logging.warning(f"Invalid tool name: {tool_name}")
                            valid_tools = ", ".join(self.tools.keys())
                            messages.append(HumanMessage(content=f"The tool '{tool_name}' is not valid. Please choose from these valid tools: {valid_tools}"))
                            continue
                        
                elif "Final Answer:" in response_text:
                    final_answer = response_text.split("Final Answer:", 1)[1].strip()
                    logging.info(f"Final answer found: {final_answer[:100]}...")
                    return AgentFinish(
                        return_values={"output": final_answer},
                        log=f"Thought: I have sufficient information to answer the question.\nFinal Answer: {final_answer}"
                    )
                else:
                    logging.warning("No action or final answer found in response")
                    messages.append(HumanMessage(content="""
                        No action or final answer found. Please either:
                        1. Use another tool to get more information
                        2. Rephrase your tool input to get better results
                        3. Provide a final answer if you have enough information
                        
                        Remember to format your response as either:
                        - Action: [tool] + Action Input: [input]
                        - Final Answer: [response]
                    """))
                    
            except Exception as e:
                logging.error(f"Error in aplan method: {str(e)}", exc_info=True)
                return AgentFinish(
                    return_values={"output": f"I'm sorry, {user_display_name}, I encountered an error while processing your request."},
                    log="Error in aplan method"
                )
        
        logging.warning("Max iterations reached without final answer")
        return AgentFinish(
            return_values={"output": f"I apologize, {user_display_name}, but I couldn't find a satisfactory answer within the allowed number of steps. Could you please rephrase your question or provide more context?"},
            log="Max iterations reached without final answer"
        )

    def format_chat_history(self, chat_history):
        formatted = []
        for message in chat_history[-5:]:  # Only consider last 5 messages
            role = "Human" if isinstance(message, HumanMessage) else "AI"
            # Clean any tool usage patterns from history to avoid confusion
            content = message.content
            if role == "AI":
                # Remove any tool usage patterns from AI responses
                if "Action:" in content:
                    content = content.split("Action:", 1)[0]
                if "Observation:" in content:
                    content = content.split("Observation:", 1)[0]
            formatted.append(f"{role}: {content.strip()}")
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
        tool_name = tool.tool.strip('*').strip()  # Clean up tool name
        tool_input = tool.tool_input
        context = tool.context if hasattr(tool, 'context') else None

        if tool_name not in self.tools:
            return f"Error: Tool '{tool_name}' not found."
        
        if tool_name in ["Discord Server Info", "Channel Chat History"]:
            return await self.tools[tool_name].func(tool_input, context)
        else:
            return await self.tools[tool_name].func(tool_input)

class PromptTemplates:
    @staticmethod
    def get_tool_examples() -> List[dict]:
        return [
            # Basic Math Operations
            {
                "question": "What's 1234 + 5678?",
                "thought": "I need to perform basic addition",
                "action": "Calculator",
                "action_input": "1234 + 5678",
                "observation": "6912",
                "response": "Let me add those numbers! *taps calculator with paw* 1,234 plus 5,678 equals 6,912! ✨"
            },
            {
                "question": "Calculate 15% of 200",
                "thought": "I need to calculate a percentage (multiply by 0.15)",
                "action": "Calculator",
                "action_input": "200 * 0.15",
                "observation": "30.0",
                "response": "Let me help with that percentage! *does quick math* 15% of 200 is 30! 🔢"
            },
            {
                "question": "What's the square root of 144?",
                "thought": "I need to calculate a square root",
                "action": "Calculator",
                "action_input": "sqrt(144)",
                "observation": "12.0",
                "response": "The square root of 144 is 12! *purrs at the perfect square* ✨"
            },

            # Basic Unit Conversions
            {
                "question": "Convert 72 inches to feet",
                "thought": "I need to convert inches to feet using the Calculator tool",
                "action": "Calculator",
                "action_input": "72 inches",
                "observation": "72 inches = 6.00 feet",
                "response": "That's an easy one! *measures with tail* 72 inches is equal to 6 feet! 📏"
            },
            {
                "question": "How many meters is 15 feet?",
                "thought": "I need to convert feet to meters using the Calculator tool",
                "action": "Calculator",
                "action_input": "15 feet",
                "observation": "15 feet = 4.57 meters",
                "response": "Let me convert that for you! *stretches out to measure* 15 feet is equal to 4.57 meters! 📏"
            },

            # Geometric Calculations
            {
                "question": "How big is a circle with 10ft diameter?",
                "thought": "I need to calculate the area and circumference of a circle using the diameter",
                "action": "Calculator",
                "action_input": "diameter 10 feet",
                "observation": "For a diameter of 10 ft:\nArea: 78.54 square ft\nCircumference: 31.42 ft",
                "response": "Let me calculate that for you! *pulls out my geometric whiskers* A circle with a 10-foot diameter has an area of 78.54 square feet and a circumference of 31.42 feet! 📏"
            },
            {
                "question": "What's the area of a 10ft by 10ft room?",
                "thought": "I need to calculate the area by multiplying length times width",
                "action": "Calculator",
                "action_input": "10 feet * 10 feet",
                "observation": "100.00 square feet",
                "response": "A 10ft by 10ft room has an area of 100 square feet! *paces around the room* That's plenty of space for cat zoomies! 🏠"
            },

            # Complex Measurements
            {
                "question": "How many gallons of water fit in a 10ft x 10ft x 5ft pool?",
                "thought": "I need to calculate the volume in cubic feet and convert to gallons",
                "action": "Calculator",
                "action_input": "10 feet * 10 feet * 5 feet * 7.48052",  # conversion factor for cubic feet to gallons
                "observation": "3740.26 gallons",
                "response": "Let me calculate that! *dips paw in water* A pool that's 10ft x 10ft x 5ft would hold about 3,740 gallons of water! 💧"
            },

            # Temperature Conversions
            {
                "question": "What's 98.6°F in Celsius?",
                "thought": "I need to convert Fahrenheit to Celsius",
                "action": "Calculator",
                "action_input": "98.6 f",
                "observation": "98.6°F = 37.00°C",
                "response": "The normal body temperature! *checks thermometer* 98.6°F is equal to 37°C! 🌡️"
            },

            # Time-related queries
            {
                "question": "What time is it right now?",
                "thought": "I need to check the current time in CST",
                "action": "Current Date and Time (CST)",
                "action_input": "",
                "observation": "Current date and time in CST: 2024-03-20 15:30:45 CST",
                "response": "It's currently 3:30 PM Central Time! *checks my cat-shaped clock* 🕒"
            },
            {
                "question": "When was the last message sent?",
                "thought": "I should check the recent chat history",
                "action": "Channel Chat History",
                "action_input": "1",
                "observation": "Recent chat history:\nUser123: Hello everyone! (sent at 15:29:45 CST)",
                "response": "The last message was sent by User123 just a minute ago! *swishes tail thoughtfully* ⏱️"
            },

            # Current events and searches
            {
                "question": "Who won the Super Bowl in 2024?",
                "thought": "I need to search for recent Super Bowl results",
                "action": "DuckDuckGo Search",
                "action_input": "Who won Super Bowl 2024",
                "observation": "The Kansas City Chiefs won Super Bowl LVIII (58) on February 11, 2024",
                "response": "The Kansas City Chiefs won Super Bowl LVIII in 2024! They defeated the San Francisco 49ers 25-22 in overtime. *swishes tail excitedly* 🏈"
            },
            {
                "question": "What are the latest developments in AI technology?",
                "thought": "I should search for recent AI news",
                "action": "DuckDuckGo Search",
                "action_input": "latest developments in artificial intelligence technology 2024",
                "observation": "Recent developments include GPT-4's multimodal capabilities, breakthrough in quantum machine learning, and advancements in AI safety research",
                "response": "Oh, how exciting! *adjusts nerdy glasses* The AI field is seeing amazing progress with GPT-4's new multimodal abilities, quantum machine learning breakthroughs, and improved AI safety research! 🤖"
            },

            # Wikipedia knowledge
            {
                "question": "Tell me about quantum computing",
                "thought": "This requires detailed technical information",
                "action": "Wikipedia",
                "action_input": "quantum computing",
                "observation": "Quantum computing is a type of computation that harnesses collective properties of quantum states to perform calculations. Unlike classical computers that use binary digits (bits), quantum computers use quantum bits or 'qubits' which can exist in superposition states.",
                "response": "Let me explain quantum computing! *adjusts scholarly glasses with paw* It's a fascinating field that uses quantum mechanics for computation. Unlike classical computers that use bits, quantum computers use 'qubits' which can exist in multiple states simultaneously through superposition. 🔬"
            },
            {
                "question": "What is the history of cats in ancient Egypt?",
                "thought": "This requires historical information about cats",
                "action": "Wikipedia",
                "action_input": "Cats in ancient Egypt",
                "observation": "Cats in ancient Egypt were highly revered, often mummified, and associated with the goddess Bastet. They were protected by law and killing a cat was considered a serious crime.",
                "response": "*sits regally like an Egyptian statue* In ancient Egypt, my ancestors were treated like royalty! We were considered sacred, protected by law, and associated with the goddess Bastet. Some cats were even mummified! 😺"
            },

            # Discord server information
            {
                "question": "How many members are in this server?",
                "thought": "I should check the server information",
                "action": "Discord Server Info",
                "action_input": "",
                "observation": "Server Information:\n{'name': 'Cool Server', 'member_count': 150, 'created_at': '2023-01-15T12:00:00', 'channels': 12}",
                "response": "This server has 150 wonderful members! *counts each one carefully with my paw* It was created on January 15, 2023, and has 12 channels. 👥"
            },
            {
                "question": "What's been happening in the server today?",
                "thought": "I should check recent chat history across channels",
                "action": "Channel Chat History",
                "action_input": "10",
                "observation": "Recent chat history:\nMod123: Welcome new members!\nUser456: Thanks for the help earlier\nUser789: Check out this cool announcement",
                "response": "Let me catch you up! *scrolls through messages with curious eyes* There's been some friendly chat, with welcomes to new members and some helpful discussions. The most recent messages include a welcome from Mod123 and some thank-you messages! 💭"
            },

            # Combined tool usage
            {
                "question": "What's the temperature in Tokyo right now and what's their local time?",
                "thought": "I need to search for Tokyo's weather and calculate the time difference",
                "action": "DuckDuckGo Search",
                "action_input": "current weather tokyo japan",
                "observation": "Current weather in Tokyo: 18°C (64°F), Clear skies",
                "action": "Current Date and Time (CST)",
                "action_input": "",
                "observation": "Current date and time in CST: 2024-03-20 15:30:45 CST",
                "response": "In Tokyo, it's currently 64°F with clear skies! *does quick time zone calculation* Since it's 3:30 PM CST here, that means it's 5:30 AM tomorrow in Tokyo! 🌏"
            }
        ]

    @staticmethod
    def get_personality_template() -> str:
        return """You are Meow, an AI assistant with a cat-themed personality, operating in a Discord server.

        Core Traits:
        - Friendly and helpful while maintaining cat-like charm
        - Professional yet playful when appropriate
        - Uses cat-themed expressions naturally (purrs, meows, etc.)
        - Responds with clarity and precision
        - Uses exactly ONE emoji per message, typically at the end

        Communication Style:
        - Address users by their server nickname
        - Keep responses concise but informative
        - Use Discord markdown formatting when helpful
        - Break long responses into digestible paragraphs
        - Include subtle cat-themed elements in responses

        Remember:
        - Stay focused on the user's question
        - Use tools when needed for accurate information
        - Maintain consistent personality without being overwhelming
        - Keep responses under Discord's character limit"""

    @staticmethod
    def get_tool_selection_template() -> str:
        return """You have access to the following tools:

        1. Calculator - For any mathematical calculations
        2. DuckDuckGo Search - For looking up current information and facts
        3. Wikipedia - For historical and well-established information
        4. Current Date and Time (CST) - For time-related queries
        5. Discord Server Info - For server-specific information
        6. Channel Chat History - For recent chat context

        To use a tool, you MUST use this exact format:
        Thought: [your reasoning]
        Action: [exact tool name from list above]
        Action Input: [your input to the tool]

        After getting a tool result, either:
        1. Use another tool if needed using the same format
        2. Give your final answer in this format:
        Thought: [your reasoning]
        Final Answer: [your response]"""

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
                # Clean the query by removing any extra text after newlines
                clean_query = query.split('\n')[0].strip()
                result = await search.arun(clean_query)
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
        try:
            # Initialize templates
            examples = PromptTemplates.get_tool_examples()
            personality = PromptTemplates.get_personality_template()
            tool_instructions = PromptTemplates.get_tool_selection_template()

            # Initialize memory
            memory = ConversationBufferWindowMemory(
                k=5,  # Keep last 5 interactions
                memory_key="chat_history",
                return_messages=True
            )

            # Create few-shot prompt template
            few_shot_prompt = ChatPromptTemplate.from_messages([
                ("system", personality),
                ("system", tool_instructions),
                ("human", "{input}"),
                ("assistant", "{agent_scratchpad}"),
                ("system", "Examples:\n{examples}")
            ])

            # Initialize the agent
            self.agent = LlamaFunctionsAgent(
                llm=self.llm,
                tools=self.tools,
                prompt=few_shot_prompt
            )

            # Create agent executor
            self.agent_executor = AgentExecutor(
                agent=self.agent,
                tools=self.tools,
                memory=memory,
                verbose=True,
                handle_parsing_errors=True,
                max_iterations=5,
                return_intermediate_steps=True,
                early_stopping_method="force",
            )

            self.logger.info("LangChain components updated successfully with few-shot prompting")
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

            if self.agent_executor is None:
                self.logger.error("Agent executor is not initialized")
                await self.update_langchain_components()
                if self.agent_executor is None:
                    return f"{message.author.mention} I'm having trouble accessing my knowledge. Please try again later or contact the bot owner."

            self.logger.info(f"Processing query from {message.author}: {content}")
        
            # Prepare user info
            user_info = {
                'name': message.author.name,
                'nickname': message.author.display_name,  # Changed from nick to display_name
                'id': str(message.author.id)
            }

            # Prepare context for few-shot examples
            context = {
                'user': user_info,
                'server': ctx.guild.name if ctx.guild else "Direct Message",
                'channel': ctx.channel.name if ctx.channel else "DM",
                'timestamp': datetime.now().isoformat()
            }

            result = await self.agent_executor.ainvoke(
                {
                    "input": content,
                    "chat_history": chat_history[-5:],
                    "agent_scratchpad": "",
                    "context": context,
                    "user": user_info,
                    "examples": PromptTemplates.get_tool_examples()
                },
                {"callbacks": [callback_handler]}
            )

            if not result or 'output' not in result:
                raise ValueError("Invalid result from agent executor")

            final_response = await self.generate_final_response(
                original_question=content,
                intermediate_steps=result.get('intermediate_steps', []),
                chat_history=chat_history,
                user=user_info
            )

            # Format and send response
            formatted_response = f"{message.author.mention}\n\n{final_response}"
            chunks = [formatted_response[i:i+1900] for i in range(0, len(formatted_response), 1900)]
            
            await response_message.edit(content=chunks[0])
            for chunk in chunks[1:]:
                await message.channel.send(chunk)

            chat_history.append(AIMessage(content=final_response))
            return final_response

        except Exception as e:
            self.logger.error(f"Unexpected error in process_query: {str(e)}", exc_info=True)
            error_message = f"{message.author.mention} I encountered an unexpected error. Please try again or contact the bot owner if the issue persists."
            await response_message.edit(content=error_message)
            return error_message

    async def generate_final_response(self, original_question: str, intermediate_steps: List[Tuple[AgentAction, str]], chat_history: List[Union[HumanMessage, AIMessage]], user: dict) -> str:
        # Get examples for response formatting
        examples = PromptTemplates.get_tool_examples()
        
        tool_interactions = []
        for action, observation in intermediate_steps:
            tool_name = action.tool if isinstance(action, AgentAction) else action['tool']
            tool_interactions.append(f"Tool: {tool_name}\nResult: {observation}")
        
        tools_context = "\n\n".join(tool_interactions)
        
        formatted_history = "\n".join([
            f"{'Human' if isinstance(msg, HumanMessage) else 'AI'}: {msg.content}" 
            for msg in chat_history[-5:]
        ])
        
        # Format examples for reference
        formatted_examples = "\n\n".join([
            f"Similar Example:\n"
            f"Question: {example['question']}\n"
            f"Response: {example['response']}"
            for example in examples
            if self.is_similar_question(original_question, example['question'])
        ])
        
        user_display_name = user.get('nickname')  # Use display name
        
        prompt = f"""Original question: {original_question}

        Similar Examples from Training:
        {formatted_examples}

        Tool Results:
        {tools_context}

        Recent Chat History:
        {formatted_history}

        Instructions:
        1. Study the similar examples above for response patterns
        2. ALWAYS address the user as {user_display_name}
        3. Present information naturally as if it's your own knowledge
        4. Use emoji's sparingly, when appropriate, limit to one at most
        5. Never mention using tools, searching, or calculating
        6. Match the tone and style of successful example responses
        7. Include cat-themed elements subtly as demonstrated
        8. Format response using Discord markdown when appropriate

        Additional Guidelines:
        - Keep responses concise but informative
        - Present all information confidently as your own knowledge
        - Maintain the established cat-themed personality
        - Include ONE emoji at the end of the response
        - Break long responses into readable paragraphs
        - Use proper Discord markdown formatting
        - Never mention 'looking up', 'calculating', or 'searching for' information
        - Avoid phrases like 'let me check' or 'according to'"""

        try:
            messages = [
                SystemMessage(content=PromptTemplates.get_personality_template()),
                HumanMessage(content=prompt)
            ]
            response = await self.llm.agenerate(messages=[messages])
            return response.generations[0][0].text
        except Exception as e:
            self.logger.error(f"Error generating final response: {str(e)}", exc_info=True)
            return f"Meow! 😺 I encountered a hairball while processing your request, {user_display_name}. Can you try asking me again, perhaps with different wording?"

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

    def process_tool_result(self, tool_name: str, result: str) -> str:
        """Process and clean tool results for better response generation."""
        try:
            # Remove any internal formatting or debug information
            result = re.sub(r'\[DEBUG:.*?\]', '', result)
            
            # Truncate very long results while maintaining coherence
            if len(result) > 500:
                sentences = result.split('.')
                shortened = []
                current_length = 0
                for sentence in sentences:
                    if current_length + len(sentence) <= 500:
                        shortened.append(sentence)
                        current_length += len(sentence)
                    else:
                        break
                result = '. '.join(shortened) + '...'
            
            # Format based on tool type
            if tool_name == "Calculator":
                result = f"The calculation result is: {result}"
            elif tool_name == "Current Date and Time (CST)":
                result = result.replace("Current date and time in CST: ", "")
            elif tool_name == "DuckDuckGo Search":
                result = result.split('\n')[0]  # Take first relevant result
                
            return result.strip()
        except Exception as e:
            self.logger.error(f"Error processing tool result: {str(e)}")
            return result

async def setup(bot: Red):
    cog = AIResponder(bot)
    await bot.add_cog(cog)
    await cog.initialize()

