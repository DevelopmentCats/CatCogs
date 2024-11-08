from typing import Optional, List, Dict, Any
import aiohttp
import json
import asyncio
from datetime import datetime, timedelta
from . import AIResponderTool, ToolRegistry
from ..utils.errors import ToolError, ToolExecutionError
from ..responses.rate_limiter import RateLimiter

@ToolRegistry.register
class WebSearch(AIResponderTool):
    """Web search tool using DuckDuckGo API."""
    
    name = "web_search"
    description = "Search the web for information using DuckDuckGo"
    
    # Constants
    API_URL = "https://api.duckduckgo.com/"
    MAX_RETRIES = 3
    TIMEOUT = 30
    MAX_QUERY_LENGTH = 500
    MAX_RESULTS = 5
    RATE_LIMIT_REQUESTS = 10  # Requests per minute
    RATE_LIMIT_BURST = 3
    
    def __init__(self, bot=None, api_key: Optional[str] = None):
        """Initialize web search tool.
        
        Args:
            bot: Discord bot instance
            api_key: Optional API key for enhanced search
        """
        super().__init__(bot)
        self.api_key = api_key
        self.session: Optional[aiohttp.ClientSession] = None
        self.rate_limiter = RateLimiter(
            requests_per_minute=self.RATE_LIMIT_REQUESTS,
            burst_limit=self.RATE_LIMIT_BURST
        )
        
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
        await self.rate_limiter.cleanup()
            
    def _validate_query(self, query: str) -> None:
        """Validate search query."""
        if not query or not query.strip():
            raise ToolError(self.name, "Search query cannot be empty")
            
        if len(query) > self.MAX_QUERY_LENGTH:
            raise ToolError(
                self.name,
                f"Query too long (max {self.MAX_QUERY_LENGTH} characters)"
            )
            
        # Check for potentially harmful queries
        harmful_patterns = ['javascript:', 'data:', 'file:', 'vbscript:']
        if any(pattern in query.lower() for pattern in harmful_patterns):
            raise ToolError(self.name, "Query contains invalid patterns")
            
    async def _process_response_text(self, response_text: str) -> Dict[str, Any]:
        """Process DuckDuckGo response text into usable data."""
        try:
            # Remove any JSONP wrapper if present
            text = response_text.strip()
            if text.startswith('ddg('):
                text = text[4:-2]  # Remove ddg( and );
                
            # Parse the JSON data
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise ToolError(self.name, f"Failed to parse search results: {str(e)}")
            
    def _process_results(self, data: Dict[str, Any]) -> List[str]:
        """Process and format search results.
        
        Args:
            data: Raw API response data
            
        Returns:
            List of formatted result strings
        """
        results = []
        
        # Add instant answer if available
        if abstract := data.get("AbstractText"):
            source = data.get("AbstractSource", "")
            url = data.get("AbstractURL", "")
            results.append(f"📚 Summary ({source}): {abstract}")
            if url:
                results.append(f"Source: {url}")
                
        # Add definition if available
        if definition := data.get("Definition"):
            source = data.get("DefinitionSource", "")
            results.append(f"📖 Definition ({source}): {definition}")
            
        # Process related topics
        if related := data.get("RelatedTopics"):
            topics = []
            for topic in related[:self.MAX_RESULTS]:
                if text := topic.get("Text"):
                    url = topic.get("FirstURL", "")
                    topics.append(f"• {text}")
                    if url:
                        topics.append(f"  Link: {url}")
            if topics:
                results.append("\n🔍 Related Information:")
                results.extend(topics)
                
        return results
        
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
        
        # Check rate limits
        await self.rate_limiter.check_rate_limit("search")
        
        if not self.session:
            await self.initialize()
            
        for attempt in range(self.MAX_RETRIES):
            try:
                async with self.session.get(
                    self.API_URL,
                    params={
                        "q": query,
                        "format": "json",
                        "no_redirect": 1,
                        "no_html": 1,
                        "skip_disambig": 1,
                        "t": "AIResponderBot",  # User agent identifier
                        **({"appid": self.api_key} if self.api_key else {})
                    },
                    headers={
                        "Accept": "application/json, application/javascript",
                        "User-Agent": "AIResponderBot/1.0"
                    }
                ) as response:
                    if response.status == 429:  # Rate limited
                        if attempt < self.MAX_RETRIES - 1:
                            await asyncio.sleep(2 ** attempt)  # Exponential backoff
                            continue
                        raise ToolError(self.name, "Rate limited by search API")
                        
                    if response.status != 200:
                        raise ToolError(
                            self.name,
                            f"API request failed: {response.status}"
                        )
                        
                    # Get response text and process it
                    response_text = await response.text()
                    data = await self._process_response_text(response_text)
                    
                    # Process results
                    results = self._process_results(data)
                    
                    if not results:
                        return "No relevant information found."
                        
                    return "\n\n".join(results)
                    
            except asyncio.TimeoutError:
                if attempt == self.MAX_RETRIES - 1:
                    raise ToolError(self.name, "Search request timed out")
                continue
                
            except aiohttp.ClientError as e:
                if attempt == self.MAX_RETRIES - 1:
                    raise ToolError(self.name, f"Network error: {str(e)}")
                continue
                
            except Exception as e:
                raise ToolError(self.name, f"Search failed: {str(e)}")
                
        raise ToolError(self.name, "Maximum retry attempts exceeded")

    @property
    def error_handling_hint(self) -> str:
        """Provide error handling hint for the agent."""
        return ("Try rephrasing your search query or breaking it into smaller parts. "
                "If the issue persists, consider using alternative information sources.")
