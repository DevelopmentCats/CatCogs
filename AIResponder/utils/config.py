from redbot.core import Config
from typing import Dict, Any, List, Optional
from ..utils.errors import ConfigError

class ConfigManager:
    """Manages configuration for AI Responder."""
    
    def __init__(self, bot_config: Config):
        """Initialize config manager.
        
        Args:
            bot_config: Red bot Config instance
        """
        if not isinstance(bot_config, Config):
            raise ConfigError("Invalid config object provided")
        self.config = bot_config
        
    async def initialize(self) -> None:
        """Initialize configuration."""
        # Config is already initialized in AIResponder.__init__
        pass
    
    async def get_api_key(self) -> Optional[str]:
        """Get API key."""
        return await self.config.api_key()
    
    async def set_api_key(self, api_key: str) -> None:
        """Set API key.
        
        Args:
            api_key: API key to set, or 'clear' to remove
        """
        try:
            if api_key.lower() == 'clear':
                await self.config.api_key.set(None)
            else:
                # Validate API key format
                if not api_key.strip():
                    raise ConfigError("API key cannot be empty")
                await self.config.api_key.set(api_key.strip())
        except Exception as e:
            raise ConfigError(f"Failed to set API key: {str(e)}")
    
    async def get_model_name(self) -> str:
        """Get model name."""
        return await self.config.get_raw("model_name")
    
    async def set_model_name(self, model_name: str) -> None:
        """Set model name."""
        try:
            await self.config.set_raw("model_name", value=model_name)
        except Exception as e:
            raise ConfigError(f"Failed to set model name: {str(e)}")
    
    async def is_channel_disabled(self, channel_id: int) -> bool:
        """Check if channel is disabled."""
        try:
            disabled = await self.config.get_raw("disabled_channels")
            return channel_id in disabled
        except Exception as e:
            raise ConfigError(f"Failed to check channel status: {str(e)}")
    
    async def toggle_channel(self, channel_id: int) -> bool:
        """Toggle channel enabled/disabled state."""
        try:
            disabled = await self.config.get_raw("disabled_channels")
            if channel_id in disabled:
                disabled.remove(channel_id)
                is_disabled = False
            else:
                disabled.append(channel_id)
                is_disabled = True
            await self.config.set_raw("disabled_channels", value=disabled)
            return is_disabled
        except Exception as e:
            raise ConfigError(f"Failed to toggle channel: {str(e)}")
    
    async def get_max_history(self) -> int:
        """Get maximum history size."""
        return await self.config.get_raw("max_history")
    
    async def get_rate_limit_config(self) -> Dict[str, int]:
        """Get rate limit configuration."""
        try:
            return {
                "requests": await self.config.get_raw("rate_limit_requests"),
                "burst": await self.config.get_raw("rate_limit_burst")
            }
        except Exception as e:
            raise ConfigError(f"Failed to get rate limit config: {str(e)}")
