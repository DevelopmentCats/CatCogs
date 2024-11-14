from typing import Optional, List, Dict, Any
import asyncio
from langchain_community.tools import DuckDuckGoSearchRun
from . import AIResponderTool, ToolRegistry
from ..utils.errors import ToolError
from ..responses.rate_limiter import RateLimiter

@ToolRegistry.register
class WebSearch(AIResponderTool):
    """Web search tool using DuckDuckGo API."""
    
    name = "web_search"
    description = "Search the web for information using DuckDuckGo"
    
    # Constants
    MAX_RETRIES = 3
    TIMEOUT = 30
    MAX_QUERY_LENGTH = 500
    MAX_RESULTS = 5
    RATE_LIMIT_REQUESTS = 10  # Requests per minute
    RATE_LIMIT_BURST = 3
    
    def __init__(self, bot=None):
        super().__init__(bot)
        self.search_tool = DuckDuckGoSearchRun()
        self.rate_limiter = RateLimiter(
            requests_per_minute=self.RATE_LIMIT_REQUESTS,
            burst_limit=self.RATE_LIMIT_BURST
        )
        
    def _validate_query(self, query: str) -> None:
        if not query or not query.strip():
            raise ToolError(self.name, "Search query cannot be empty")
            
        if len(query) > self.MAX_QUERY_LENGTH:
            raise ToolError(
                self.name,
                f"Query too long (max {self.MAX_QUERY_LENGTH} characters)"
            )
            
        harmful_patterns = ['javascript:', 'data:', 'file:', 'vbscript:']
        if any(pattern in query.lower() for pattern in harmful_patterns):
            raise ToolError(self.name, "Query contains invalid patterns")
            
    def _format_results(self, results: str) -> str:
        """Format search results."""
        if not results or results.strip() == "":
            return "No relevant information found."
            
        # Split into paragraphs and limit length
        paragraphs = results.split('\n\n')[:self.MAX_RESULTS]
        formatted = []
        
        for i, para in enumerate(paragraphs, 1):
            if para.strip():
                formatted.append(f"{i}. {para.strip()}")
                
        if not formatted:
            return "No relevant information found."
            
        return "\n\n".join(formatted)
        
    def _run(self, query: str) -> str:
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
        await self.rate_limiter.check_rate_limit("search")
        
        for attempt in range(self.MAX_RETRIES):
            try:
                # Run search in thread pool to avoid blocking
                loop = asyncio.get_event_loop()
                results = await loop.run_in_executor(
                    None, 
                    self.search_tool.run,
                    query
                )
                
                return self._format_results(results)
                
            except Exception as e:
                if attempt == self.MAX_RETRIES - 1:
                    raise ToolError(self.name, f"Search failed: {str(e)}")
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
                continue
                
        raise ToolError(self.name, "Maximum retry attempts exceeded")

    @property
    def error_handling_hint(self) -> str:
        return ("Try rephrasing your search query or breaking it into smaller parts. "
                "If the issue persists, consider using alternative information sources.")

    async def cleanup(self) -> None:
        await self.rate_limiter.cleanup()
