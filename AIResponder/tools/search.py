from typing import Optional, List, Dict, Any, Union
import aiohttp
import json
from . import AIResponderTool, ToolRegistry
from ..utils.errors import ToolError
from datetime import datetime, timedelta

@ToolRegistry.register
class WebSearch(AIResponderTool):
    """Advanced web search tool using DuckDuckGo API."""
    
    name = "web_search"
    description = "Search the web for current information using DuckDuckGo. Supports time-based, region-based, and safe search options."
    
    # Constants
    API_URL = "https://api.duckduckgo.com/"
    MAX_RETRIES = 3
    TIMEOUT = 30
    MAX_QUERY_LENGTH = 500
    MAX_RESULTS = 10
    
    # Search Parameters
    TIME_FILTERS = {
        "recent": "d",  # Past day
        "week": "w",    # Past week
        "month": "m",   # Past month
        "year": "y"     # Past year
    }
    
    def __init__(self, bot=None, api_key: Optional[str] = None):
        super().__init__(bot)
        self.api_key = api_key
        self.session: Optional[aiohttp.ClientSession] = None
        
    def parse_input(self, query: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Parse and validate search input."""
        if isinstance(query, str):
            return {"query": query}
            
        if not isinstance(query, dict):
            raise ToolError(self.name, "Invalid input format")
            
        return {
            "query": query.get("query", ""),
            "time_filter": query.get("time_filter", ""),
            "region": query.get("region", "wt-wt"),  # Default to worldwide
            "safe_search": query.get("safe_search", True)
        }

    async def _arun(self, query: Union[str, Dict[str, Any]]) -> str:
        """Perform advanced web search.
        
        Args:
            query: Search query string or dict with advanced parameters
            
        Returns:
            Formatted search results
        """
        params = self.parse_input(query)
        self._validate_query(params["query"])
        
        if not self.session:
            await self.initialize()
            
        search_params = {
            "q": params["query"],
            "format": "json",
            "no_html": 1,
            "skip_disambig": 1,
            "t": "AIResponderBot",
            "kl": params["region"],
            "safe": "1" if params["safe_search"] else "-1",
            **({"appid": self.api_key} if self.api_key else {})
        }
        
        # Add time filter if specified
        if params.get("time_filter") in self.TIME_FILTERS:
            search_params["df"] = self.TIME_FILTERS[params["time_filter"]]

        for attempt in range(self.MAX_RETRIES):
            try:
                async with self.session.get(
                    self.API_URL,
                    params=search_params
                ) as response:
                    if response.status != 200:
                        raise ToolError(
                            self.name,
                            f"API request failed: {response.status}"
                        )
                        
                    data = await response.json()
                    return self._process_results(data)
                    
            except aiohttp.ClientError as e:
                if attempt == self.MAX_RETRIES - 1:
                    raise ToolError(self.name, f"Network error: {str(e)}")
                continue
                
    def _process_results(self, data: Dict[str, Any]) -> str:
        """Process and format search results."""
        results = []
        
        # Add instant answer if available
        if abstract := data.get("AbstractText"):
            source = data.get("AbstractSource", "")
            url = data.get("AbstractURL", "")
            results.append(f"Summary from {source}:\n{abstract}")
            if url:
                results.append(f"Source: {url}\n")
                
        # Add definition if available
        if definition := data.get("Definition"):
            source = data.get("DefinitionSource", "")
            results.append(f"Definition from {source}:\n{definition}\n")
            
        # Add related topics
        if related := data.get("RelatedTopics"):
            topics = []
            for topic in related[:self.MAX_RESULTS]:
                if text := topic.get("Text"):
                    url = topic.get("FirstURL", "")
                    topics.append(f"• {text}")
                    if url:
                        topics.append(f"  Source: {url}")
            
            if topics:
                results.append("Related Information:")
                results.extend(topics)
                
        # Handle no results
        if not results:
            return "No relevant information found."
            
        return "\n\n".join(results)
