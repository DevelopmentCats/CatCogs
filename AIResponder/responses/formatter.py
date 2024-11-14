"""Response formatting and personality transformation for Discord messages."""

from typing import Dict, Any, List, Optional, Union
from langchain_core.prompts import ChatPromptTemplate
import discord
import re
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class ResponseFormatter:
    """Handles response formatting and personality transformation for Discord."""
    
    def __init__(self, model: Optional[Any] = None):
        """Initialize formatter with language model for personality transformation.
        
        Args:
            model: Language model for personality transformation (optional)
        """
        self.model = model
        self.max_message_length = 2000
        self.max_embed_length = 4096
        self.personality_transformer = None if model is None else PersonalityTransformer(model)
        
    def set_model(self, model: Any) -> None:
        """Set the language model and initialize personality transformer.
        
        Args:
            model: Language model for personality transformation
        """
        self.model = model
        self.personality_transformer = PersonalityTransformer(model)

    async def transform_personality(self, response: str, personality: str = "cat", question: str = "") -> str:
        """Transform response with specified personality."""
        if self.personality_transformer is None:
            return response
            
        try:
            return await self.personality_transformer.transform(response, personality, question)
        except Exception as e:
            logger.warning(f"Personality transformation failed: {e}. Returning original response.")
            return response

    # Discord Formatting Methods
    def format_user_mention(self, user_id: int) -> str:
        """Format a user mention."""
        return f"<@{user_id}>"
        
    def format_channel_mention(self, channel_id: int) -> str:
        """Format a channel mention."""
        return f"<#{channel_id}>"
        
    def format_role_mention(self, role_id: int) -> str:
        """Format a role mention."""
        return f"<@&{role_id}>"

    def format_code_block(self, content: str, language: str = "") -> str:
        """Format content as a code block."""
        return f"```{language}\n{content}\n```"
        
    def format_inline_code(self, content: str) -> str:
        """Format content as inline code."""
        return f"`{content}`"
        
    def format_quote(self, content: str) -> str:
        """Format content as a quote."""
        return "\n".join(f"> {line}" for line in content.split("\n"))

    def format_error(self, error: str) -> str:
        """Format an error message."""
        return f"❌ {error}"
        
    def format_success(self, message: str) -> str:
        """Format a success message."""
        return f"✅ {message}"
        
    def format_warning(self, message: str) -> str:
        """Format a warning message."""
        return f"⚠️ {message}"
        
    def format_info(self, message: str) -> str:
        """Format an info message."""
        return f"ℹ️ {message}"

    # Message Handling Methods
    def split_message(self, content: str, max_length: int = 2000) -> List[str]:
        """Split a message into chunks that respect Discord's length limits and code blocks."""
        if len(content) <= max_length:
            return [content]
            
        chunks = []
        current_chunk = ""
        code_block = False
        lines = content.split("\n")
        
        for line in lines:
            # Check for code block markers
            if line.startswith("```"):
                code_block = not code_block
                
            # If adding this line would exceed the limit
            if len(current_chunk) + len(line) + 1 > max_length:
                # If we're in a code block, close it
                if code_block:
                    current_chunk += "\n```"
                    code_block = False
                    
                chunks.append(current_chunk)
                current_chunk = ""
                
                # If we were in a code block, start a new one
                if code_block:
                    current_chunk = "```\n"
                    
            current_chunk += line + "\n"
            
        if current_chunk:
            # Close any open code block
            if code_block:
                current_chunk += "```"
            chunks.append(current_chunk)
            
        return chunks

    # Embed Creation Methods
    def create_embed(self, 
                    title: Optional[str] = None,
                    description: Optional[str] = None,
                    color: int = 0x3498db,  # Discord blue
                    fields: Optional[List[Dict[str, str]]] = None,
                    footer: Optional[str] = None,
                    thumbnail: Optional[str] = None,
                    image: Optional[str] = None) -> discord.Embed:
        """Create a Discord embed with proper formatting and length checks."""
        embed = discord.Embed(color=color)
        
        if title:
            embed.title = title[:256]  # Discord title limit
            
        if description:
            embed.description = description[:4096]  # Discord description limit
            
        if fields:
            for field in fields[:25]:  # Discord limits embeds to 25 fields
                name = field.get("name", "")[:256]  # Field name limit
                value = field.get("value", "")[:1024]  # Field value limit
                inline = field.get("inline", False)
                embed.add_field(name=name, value=value, inline=inline)
                
        if footer:
            embed.set_footer(text=footer[:2048])  # Footer text limit
            
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
            
        if image:
            embed.set_image(url=image)
            
        return embed

    def create_help_embed(self, title: str, commands: List[Dict[str, str]]) -> discord.Embed:
        """Create a help message embed."""
        fields = [
            {
                "name": f"📌 {cmd['name']}",
                "value": f"{cmd['description']}\nUsage: `{cmd['usage']}`",
                "inline": False
            }
            for cmd in commands
        ]
        
        embed = self.create_embed(
            title=title,
            color=0x2ecc71,  # Green
            fields=fields,
            footer="💡 Tip: Use !help <command> for more details about a specific command"
        )
        
        return embed

    # Main Response Formatting Method
    def format_response(self, response: str) -> Union[str, List[str]]:
        """Format a response for Discord, handling length limits and formatting."""
        # Handle length limits
        if len(response) > self.max_message_length:
            return self.split_message(response)
            
        return response

class PersonalityTransformer:
    """Transforms responses to match a specific personality."""
    
    def __init__(self, model: Any):
        """Initialize transformer with language model.
        
        Args:
            model: Language model for personality transformation
        """
        self.model = model
        
    async def transform(self, response: str, personality: str = "cat", question: str = "") -> str:
        """Transform a response to match the personality.
        
        Args:
            response: Original response to transform
            personality: Personality type to use
            question: Original question for context
            
        Returns:
            Transformed response with personality applied
        """
        if not response:
            return response
            
        # Preserve any code blocks or special formatting
        code_blocks = {}
        def save_code_block(match):
            key = f"__CODE_BLOCK_{len(code_blocks)}__"
            code_blocks[key] = match.group(0)
            return key
            
        # Save code blocks
        response_with_placeholders = re.sub(
            r"```[\s\S]*?```|`[^`]+`",
            save_code_block,
            response
        )
        
        # Transform the response using generate_response
        transformed = ""
        
        # Format the prompt messages directly
        system_message = """You are a sarcastic cat AI assistant. Transform the given response to match this personality:
        - Use subtle sarcasm and wit
        - Keep the original meaning and helpfulness
        - No physical actions or emotes
        - Follow Discord chat conventions
        - Use appropriate emojis sparingly
        - Keep formatting intact (code blocks, mentions, etc)
        
        Original question: {question}
        Response to transform: {response}"""
        
        formatted_system = system_message.format(
            question=question or "No context provided",
            response=response_with_placeholders
        )
        
        user_message = "Transform this response while keeping its meaning and any technical details intact."
        
        try:
            # Use generate_response with formatted messages
            async for chunk in self.model.generate_response(
                user_message,
                context=formatted_system
            ):
                transformed += chunk
            
            # Restore code blocks
            result = transformed
            for key, block in code_blocks.items():
                result = result.replace(key, block)
                
            return result
        except Exception as e:
            logger.warning(f"Personality transformation failed: {e}. Returning original response.")
            return response
