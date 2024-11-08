from redbot.core import Config
from typing import Dict, Any, List, Optional
from ..utils.errors import ConfigError

defaults = {
    "api_key": None,
    "model_name": "meta-llama/Llama-3.2-11B-Vision-Instruct",
    "max_history": 10,
    "history_expiry_hours": 24,
    "disabled_channels": [],
    "disabled_servers": [],
    "rate_limit_requests": 5,
    "rate_limit_burst": 2,
    "rate_limit_cooldown": 30,
    "max_response_chunks": 5,
    "tool_configs": {}
}

class ConfigManager:
    """Manages configuration for AI Responder."""
    
    def __init__(self, bot_config: Config):
        """Initialize config manager."""
        self.config = bot_config
        self._defaults = defaults
        
    async def initialize(self) -> None:
        """Initialize configuration with defaults."""
        try:
            await self.config.register_global(**self._defaults)
        except Exception as e:
            raise ConfigError(f"Failed to initialize config: {str(e)}")
    
    async def get_api_key(self) -> Optional[str]:
        """Get API key."""
        return await self.config.api_key()
    
    async def set_api_key(self, api_key: str) -> None:
        """Set API key."""
        try:
            await self.config.api_key.set(api_key)
        except Exception as e:
            raise ConfigError(f"Failed to set API key: {str(e)}")
    
    async def get_model_name(self) -> str:
        """Get model name."""
        return await self.config.model_name()
    
    async def set_model_name(self, model_name: str) -> None:
        """Set model name."""
        try:
            await self.config.model_name.set(model_name)
        except Exception as e:
            raise ConfigError(f"Failed to set model name: {str(e)}")
    
    async def is_channel_disabled(self, channel_id: int) -> bool:
        """Check if channel is disabled."""
        try:
            disabled = await self.config.disabled_channels()
            return channel_id in disabled
        except Exception as e:
            raise ConfigError(f"Failed to check channel status: {str(e)}")
    
    async def toggle_channel(self, channel_id: int) -> bool:
        """Toggle channel enabled/disabled state.
        
        Returns:
            bool: True if channel is now disabled, False if enabled
        """
        try:
            disabled = await self.config.disabled_channels()
            if channel_id in disabled:
                disabled.remove(channel_id)
                is_disabled = False
            else:
                disabled.append(channel_id)
                is_disabled = True
            await self.config.disabled_channels.set(disabled)
            return is_disabled
        except Exception as e:
            raise ConfigError(f"Failed to toggle channel: {str(e)}")
    
    async def is_server_disabled(self, server_id: int) -> bool:
        """Check if server is disabled."""
        try:
            disabled = await self.config.disabled_servers()
            return server_id in disabled
        except Exception as e:
            raise ConfigError(f"Failed to check server status: {str(e)}")
    
    async def toggle_server(self, server_id: int) -> bool:
        """Toggle server enabled/disabled state.
        
        Returns:
            bool: True if server is now disabled, False if enabled
        """
        try:
            disabled = await self.config.disabled_servers()
            if server_id in disabled:
                disabled.remove(server_id)
                is_disabled = False
            else:
                disabled.append(server_id)
                is_disabled = True
            await self.config.disabled_servers.set(disabled)
            return is_disabled
        except Exception as e:
            raise ConfigError(f"Failed to toggle server: {str(e)}")
    
    async def get_max_history(self) -> int:
        """Get maximum history size."""
        return await self.config.max_history()
    
    async def set_max_history(self, max_history: int) -> None:
        """Set maximum history size."""
        if max_history < 1:
            raise ConfigError("Max history must be at least 1")
        try:
            await self.config.max_history.set(max_history)
        except Exception as e:
            raise ConfigError(f"Failed to set max history: {str(e)}")
    
    async def get_history_expiry_hours(self) -> int:
        """Get history expiry hours."""
        return await self.config.history_expiry_hours()
    
    async def set_history_expiry_hours(self, hours: int) -> None:
        """Set history expiry hours."""
        if hours < 1:
            raise ConfigError("Expiry hours must be at least 1")
        try:
            await self.config.history_expiry_hours.set(hours)
        except Exception as e:
            raise ConfigError(f"Failed to set expiry hours: {str(e)}")
    
    async def get_rate_limit_config(self) -> Dict[str, int]:
        """Get rate limit configuration."""
        try:
            return {
                "requests": await self.config.rate_limit_requests(),
                "burst": await self.config.rate_limit_burst(),
                "cooldown": await self.config.rate_limit_cooldown()
            }
        except Exception as e:
            raise ConfigError(f"Failed to get rate limit config: {str(e)}")
    
    async def get_tool_config(self, tool_name: str) -> Dict[str, Any]:
        """Get tool-specific configuration."""
        try:
            tool_configs = await self.config.tool_configs()
            return tool_configs.get(tool_name, {})
        except Exception as e:
            raise ConfigError(f"Failed to get tool config: {str(e)}")
