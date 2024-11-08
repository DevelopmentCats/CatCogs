from typing import Optional, List, Dict, Any
import aiohttp
import json
from . import AIResponderTool, ToolRegistry
from ..utils.errors import ToolError

@ToolRegistry.register
class WebSearch(AIResponderTool):
    """Web search tool using DuckDuckGo API."""
    
    name = "web_search"
    description = "Search the web for information using DuckDuckGo"
    
    @classmethod
    def __init_subclass__(cls, **kwargs):
        """Prevent duplicate registration of web search tools."""
        super().__init_subclass__(**kwargs)
        if any(tool.__name__ == "WebSearch" for tool in ToolRegistry._tools.values()):
            return
            
    # Constants
    API_URL = "https://api.duckduckgo.com/"
    MAX_RETRIES = 3
    TIMEOUT = 30
    MAX_QUERY_LENGTH = 500
    
    def __init__(self, bot=None, api_key: Optional[str] = None):
        """Initialize web search tool.
        
        Args:
            bot: Discord bot instance
            api_key: Optional API key for enhanced search
        """
        super().__init__(bot)
        self.api_key = api_key
        self.session: Optional[aiohttp.ClientSession] = None
        
    async def initialize(self) -> None:
        """Initialize the search tool with session."""
        if not self.session:
            timeout = aiohttp.ClientTimeout(total=self.TIMEOUT)
            self.session = aiohttp.ClientSession(timeout=timeout)
    
    async def cleanup(self) -> None:
        """Cleanup resources."""
        if self.session:
            await self.session.close()
            self.session = None
            
    def _validate_query(self, query: str) -> None:
        """Validate search query.
        
        Args:
            query: Search query to validate
            
        Raises:
            ToolError: If query is invalid
        """
        if not query or not query.strip():
            raise ToolError(self.name, "Search query cannot be empty")
            
        if len(query) > self.MAX_QUERY_LENGTH:
            raise ToolError(
                self.name,
                f"Query too long (max {self.MAX_QUERY_LENGTH} characters)"
            )
    
    def _run(self, query: str) -> str:
        """Synchronous operation not supported."""
        raise NotImplementedError("This tool only supports async operation")
    
    async def _arun(self, query: str) -> str:
        """Perform web search.
        
        Args:
            query: Search query
            
        Returns:
            Search results
            
        Raises:
            ToolError: If search fails
        """
        self._validate_query(query)
        
        if not self.session:
            await self.initialize()
            
        for attempt in range(self.MAX_RETRIES):
            try:
                async with self.session.get(
                    self.API_URL,
                    params={
                        "q": query,
                        "format": "json",
                        "no_html": 1,
                        "skip_disambig": 1,
                        **({"appid": self.api_key} if self.api_key else {})
                    }
                ) as response:
                    if response.status != 200:
                        raise ToolError(
                            self.name,
                            f"API request failed: {response.status}"
                        )
                        
                    data = await response.json()
                    
                    # Process search results
                    results = []
                    
                    # Add abstract if available
                    if abstract := data.get("AbstractText"):
                        results.append(f"Summary: {abstract}")
                        
                    # Add definition if available
                    if definition := data.get("Definition"):
                        results.append(f"Definition: {definition}")
                        
                    # Add related topics
                    if related := data.get("RelatedTopics"):
                        topics = [topic.get("Text") for topic in related[:3] if topic.get("Text")]
                        if topics:
                            results.append("\nRelated Information:")
                            results.extend(f"- {topic}" for topic in topics)
                    
                    if not results:
                        return "No relevant information found."
                        
                    return "\n\n".join(results)
                    
            except aiohttp.ClientError as e:
                if attempt == self.MAX_RETRIES - 1:
                    raise ToolError(self.name, f"Network error: {str(e)}")
                continue
                
            except json.JSONDecodeError:
                raise ToolError(self.name, "Invalid response from search API")
                
            except Exception as e:
                raise ToolError(self.name, f"Search failed: {str(e)}")
