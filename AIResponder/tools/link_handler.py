"""Link handling tool for the AI responder."""

from typing import Dict, Any, Optional
from . import AIResponderTool, ToolRegistry
from redbot.core.bot import Red
import re
import validators
from urllib.parse import urlparse, quote

@ToolRegistry.register
class LinkHandler(AIResponderTool):
    """Tool for handling and formatting links in responses."""
    
    name = "link_handler"
    description = "Formats and validates links for Discord messages"
    required_args = ["url"]
    optional_args = {
        "title": "",
        "description": "",
        "embed": False
    }
    example_uses = [
        'Format a simple URL: {"url": "https://example.com"}',
        'Format with title: {"url": "https://example.com", "title": "Example Site"}',
        'Create embed: {"url": "https://example.com", "title": "Example", "description": "An example site", "embed": true}'
    ]

    def __init__(self, bot: Optional[Red] = None):
        super().__init__(bot)
        self.url_pattern = None
        
    async def initialize(self) -> None:
        """Initialize link handler tool."""
        self.url_pattern = re.compile(
            r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
        )

    def _validate_url(self, url: str) -> bool:
        """Validate URL format and accessibility."""
        return bool(validators.url(url))

    def _format_url(self, url: str) -> str:
        """Format URL for Discord message."""
        # Ensure URL is properly encoded
        parsed = urlparse(url)
        path = quote(parsed.path)
        return f"{parsed.scheme}://{parsed.netloc}{path}"

    def _create_embed(self, url: str, title: str = "", description: str = "") -> Dict[str, Any]:
        """Create Discord embed for URL."""
        embed = {
            "type": "rich",
            "url": url,
            "title": title or url,
        }
        if description:
            embed["description"] = description
        return embed

    def _run(self, **kwargs) -> str:
        """Synchronous execution is not supported."""
        raise NotImplementedError("LinkHandler only supports async execution")

    async def _arun(self, **kwargs) -> str:
        """Format and validate URL for Discord message.
        
        Args:
            url: The URL to format
            title: Optional title for the link
            description: Optional description for embed
            embed: Whether to create a Discord embed
            
        Returns:
            Formatted link or embed data
        """
        url = kwargs.get("url")
        title = kwargs.get("title", "")
        description = kwargs.get("description", "")
        use_embed = kwargs.get("embed", False)

        if not url:
            raise ValueError("URL is required")

        # Validate URL
        if not self._validate_url(url):
            raise ValueError(f"Invalid URL: {url}")

        # Format URL
        formatted_url = self._format_url(url)

        # Create response based on parameters
        if use_embed:
            embed_data = self._create_embed(formatted_url, title, description)
            return f"__EMBED__{str(embed_data)}"
        elif title:
            return f"[{title}]({formatted_url})"
        else:
            return formatted_url

    async def cleanup(self) -> None:
        """No cleanup needed."""
        pass
