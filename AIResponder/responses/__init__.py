"""
AI Responder Cog for Red Discord Bot

A powerful AI assistant cog that provides conversational AI capabilities,
tool integration, and memory management.
"""

from redbot.core.bot import Red
from redbot.core.utils import get_end_user_data_statement
from .airesponder import AIResponder

__red_end_user_data_statement__ = get_end_user_data_statement(__file__)

async def setup(bot: Red) -> None:
    """Initialize the AIResponder cog.
    
    Args:
        bot: Red Discord bot instance
    """
    cog = AIResponder(bot)
    await cog.initialize()
    await bot.add_cog(cog)
