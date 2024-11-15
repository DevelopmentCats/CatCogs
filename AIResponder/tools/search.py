from typing import Optional, List, Dict, Any, Tuple
import asyncio
import json
import re
from datetime import datetime
from nltk.tokenize import word_tokenize
from nltk.tag import pos_tag
from nltk.chunk import ne_chunk
from langchain_community.tools import DuckDuckGoSearchRun
from . import AIResponderTool, ToolRegistry
from ..utils.errors import ToolError
from ..responses.rate_limiter import RateLimiter

@ToolRegistry.register
class WebSearch(AIResponderTool):
    """Advanced web search tool with semantic understanding and context-aware processing."""
    
    name = "web_search"
    description = "Advanced web search with semantic processing and context awareness"
    
    # Constants
    MAX_RETRIES = 3
    TIMEOUT = 30
    MAX_QUERY_LENGTH = 500
    MAX_RESULTS = 10
    RATE_LIMIT_REQUESTS = 10
    RATE_LIMIT_BURST = 3
    
    # Query classification patterns
    QUERY_PATTERNS = {
        'factual': ['what is', 'who is', 'where is', 'when', 'why', 'how'],
        'event': ['happening', 'events', 'schedule', 'shows', 'concerts'],
        'news': ['news', 'latest', 'update', 'recent', 'announced'],
        'location': ['in', 'at', 'near', 'around', 'within'],
        'time': ['today', 'now', 'current', 'tonight', 'this week', 'tomorrow'],
        'comparison': ['vs', 'versus', 'compared to', 'difference between'],
        'recommendation': ['best', 'top', 'recommended', 'should i', 'how to'],
        'definition': ['meaning of', 'define', 'what does', 'explanation of'],
        'price': ['cost', 'price', 'how much', 'expensive', 'cheap'],
        'review': ['review', 'rating', 'opinion', 'worth it', 'good or bad']
    }
    
    def __init__(self, bot=None):
        super().__init__(bot)
        self.search_tool = None
        self.rate_limiter = None
        
    async def initialize(self) -> None:
        """Initialize web search tool and NLP components."""
        self.search_tool = DuckDuckGoSearchRun()
        self.rate_limiter = RateLimiter(
            requests_per_minute=self.RATE_LIMIT_REQUESTS,
            burst_limit=self.RATE_LIMIT_BURST
        )
        
    def _extract_entities(self, query: str) -> Dict[str, List[str]]:
        """Extract named entities and key phrases from query."""
        tokens = word_tokenize(query)
        tagged = pos_tag(tokens)
        entities = ne_chunk(tagged)
        
        extracted = {
            'organizations': [],
            'persons': [],
            'locations': [],
            'dates': [],
            'key_phrases': []
        }
        
        current_chunk = []
        for chunk in entities:
            if hasattr(chunk, 'label'):
                if chunk.label() == 'ORGANIZATION':
                    extracted['organizations'].append(' '.join([c[0] for c in chunk]))
                elif chunk.label() == 'PERSON':
                    extracted['persons'].append(' '.join([c[0] for c in chunk]))
                elif chunk.label() == 'GPE':
                    extracted['locations'].append(' '.join([c[0] for c in chunk]))
            elif chunk[1].startswith('NN'):  # Noun phrases
                current_chunk.append(chunk[0])
            else:
                if current_chunk:
                    extracted['key_phrases'].append(' '.join(current_chunk))
                    current_chunk = []
                    
        return extracted
        
    def _analyze_query_intent(self, query: str) -> Tuple[List[str], Dict[str, Any]]:
        """Analyze query to determine intent and extract relevant information."""
        query_lower = query.lower()
        intents = []
        metadata = {
            'entities': self._extract_entities(query),
            'temporal_context': None,
            'spatial_context': None,
            'comparison_items': [],
            'attributes': []
        }
        
        # Detect query types
        for intent, patterns in self.QUERY_PATTERNS.items():
            if any(pattern in query_lower for pattern in patterns):
                intents.append(intent)
                
        # Extract temporal context
        temporal_patterns = {
            'specific_date': r'\b\d{1,2}/\d{1,2}/\d{2,4}\b',
            'relative_date': r'\b(?:today|tomorrow|yesterday|next|last)\s+(?:week|month|year|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b',
            'time_period': r'\b(?:morning|afternoon|evening|night)\b'
        }
        
        for context, pattern in temporal_patterns.items():
            if re.search(pattern, query_lower):
                metadata['temporal_context'] = context
                
        # Extract comparison items
        if 'comparison' in intents:
            comparison_pattern = r'\b([\w\s]+)\s+(?:vs|versus|compared to|or)\s+([\w\s]+)\b'
            matches = re.findall(comparison_pattern, query_lower)
            if matches:
                metadata['comparison_items'] = [item.strip() for item in matches[0]]
                
        return intents, metadata
        
    def _enhance_query(self, query: str) -> str:
        """Enhance search query based on intent and context analysis."""
        intents, metadata = self._analyze_query_intent(query)
        enhanced_query = query
        
        # Add contextual keywords based on intent
        intent_keywords = {
            'factual': 'facts about',
            'event': 'events schedule',
            'news': 'latest news',
            'recommendation': 'top rated',
            'definition': 'definition meaning',
            'price': 'current price',
            'review': 'reviews ratings'
        }
        
        # Add relevant keywords based on detected intents
        for intent in intents:
            if intent in intent_keywords and intent_keywords[intent] not in query.lower():
                enhanced_query = f"{intent_keywords[intent]} {enhanced_query}"
                
        # Add temporal context if missing
        if 'time' in intents and not metadata['temporal_context']:
            current_date = datetime.now().strftime("%B %d %Y")
            enhanced_query = f"{enhanced_query} {current_date}"
            
        # Add location context for location-specific queries
        if metadata['entities']['locations']:
            location = metadata['entities']['locations'][0]
            if location.lower() not in enhanced_query.lower():
                enhanced_query = f"{enhanced_query} in {location}"
                
        return enhanced_query
        
    def _validate_query(self, query: str) -> None:
        """Validate and sanitize search query."""
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
            
    def _parse_result(self, result: str, query_intents: List[str]) -> Dict[str, Any]:
        """Parse and enrich search result based on query intent."""
        parsed = {
            'content': result,
            'source': None,
            'date': None,
            'type': 'general',
            'relevance_score': 0,
            'metadata': {}
        }
        
        # Extract source and clean content
        if ' - ' in result:
            parts = result.split(' - ')
            if len(parts) >= 2:
                parsed['source'] = parts[0].strip()
                parsed['content'] = ' - '.join(parts[1:]).strip()
                
        # Extract and parse dates
        date_patterns = [
            (r'\b\d{1,2}/\d{1,2}/\d{2,4}\b', 'date'),
            (r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2}(?:st|nd|rd|th)?,? \d{4}\b', 'date'),
            (r'\btoday\b', 'relative'),
            (r'\btonight\b', 'relative')
        ]
        
        for pattern, date_type in date_patterns:
            match = re.search(pattern, parsed['content'])
            if match:
                parsed['date'] = {
                    'value': match.group(),
                    'type': date_type
                }
                
        # Categorize result type
        content_lower = parsed['content'].lower()
        
        # Dynamic categorization based on content and query intent
        if any(word in content_lower for word in ['event', 'show', 'concert', 'performance']):
            parsed['type'] = 'event'
        elif any(word in content_lower for word in ['news', 'announced', 'reported']):
            parsed['type'] = 'news'
        elif any(word in content_lower for word in ['review', 'rating', 'stars']):
            parsed['type'] = 'review'
        elif any(word in content_lower for word in ['price', 'cost', '$']):
            parsed['type'] = 'price'
        elif any(intent in query_intents for intent in ['factual', 'definition']):
            parsed['type'] = 'information'
            
        # Calculate relevance score
        parsed['relevance_score'] = self._calculate_relevance(parsed, query_intents)
        
        return parsed
        
    def _calculate_relevance(self, parsed_result: Dict[str, Any], query_intents: List[str]) -> float:
        """Calculate result relevance score based on multiple factors."""
        score = 1.0
        
        # Boost score based on result type matching query intent
        if parsed_result['type'] in query_intents:
            score *= 1.5
            
        # Boost score for results with sources
        if parsed_result['source']:
            score *= 1.2
            
        # Boost score for results with dates for time-sensitive queries
        if parsed_result['date'] and 'time' in query_intents:
            score *= 1.3
            
        # Penalize very short or very long results
        content_length = len(parsed_result['content'])
        if content_length < 50:
            score *= 0.8
        elif content_length > 500:
            score *= 0.9
            
        return round(score, 2)
        
    def _format_results(self, results: str, query_intents: List[str]) -> str:
        """Format search results with enhanced structure and relevance-based ordering."""
        if not results or results.strip() == "":
            return "No relevant information found."
            
        # Parse and process all results
        paragraphs = results.split('\n\n')[:self.MAX_RESULTS]
        parsed_results = []
        
        for para in paragraphs:
            if para.strip():
                parsed = self._parse_result(para.strip(), query_intents)
                parsed_results.append(parsed)
                
        # Sort results by relevance score
        parsed_results.sort(key=lambda x: x['relevance_score'], reverse=True)
        
        # Format results with appropriate icons and structure
        formatted_results = []
        for result in parsed_results:
            # Select icon based on result type
            icons = {
                'event': '🎉',
                'news': '📰',
                'review': '⭐',
                'price': '💰',
                'information': 'ℹ️',
                'general': '📌'
            }
            prefix = icons.get(result['type'], '📌')
            
            # Format result string
            result_str = f"{prefix} {result['content']}"
            
            # Add metadata if available
            if result['source']:
                result_str += f"\nSource: {result['source']}"
            if result['date']:
                result_str += f"\nDate: {result['date']['value']}"
                
            formatted_results.append(result_str)
            
        if not formatted_results:
            return "No relevant information found."
            
        return "\n\n".join(formatted_results)
        
    def _run(self, query: str) -> str:
        raise NotImplementedError("This tool only supports async operation")
        
    async def _arun(self, query: str) -> str:
        """Perform advanced web search with semantic processing."""
        self._validate_query(query)
        await self.rate_limiter.check_rate_limit("search")
        
        # Analyze query and enhance it
        intents, metadata = self._analyze_query_intent(query)
        enhanced_query = self._enhance_query(query)
        
        for attempt in range(self.MAX_RETRIES):
            try:
                loop = asyncio.get_event_loop()
                results = await loop.run_in_executor(
                    None, 
                    self.search_tool.run,
                    enhanced_query
                )
                
                return self._format_results(results, intents)
                
            except Exception as e:
                if attempt == self.MAX_RETRIES - 1:
                    raise ToolError(self.name, f"Search failed: {str(e)}")
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
                
    @property
    def error_handling_hint(self) -> str:
        return ("Try rephrasing your search query or breaking it into smaller parts. "
                "If the issue persists, consider using alternative information sources.")
