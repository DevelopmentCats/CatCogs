from typing import Dict, List, Optional, Union
import re
from dataclasses import dataclass
from ..utils.errors import FormattingError

@dataclass
class Citation:
    """Represents a citation in a response.
    
    Attributes:
        source: Name or title of the source
        content: Relevant content from the source
        url: Optional URL to the source
        page_number: Optional page number reference
    """
    source: str
    content: str
    url: Optional[str] = None
    page_number: Optional[int] = None

class ResponseFormatter:
    """Handles formatting of AI responses with markdown and citations."""
    
    # Markdown patterns
    HEADER_PATTERN = r'^(#{1,6})\s*(.*?)$'
    LIST_PATTERN = r'^(\s*[-*+]|\d+\.)\s'
    TABLE_PATTERN = r'\|.*\|'
    
    def __init__(self):
        """Initialize the formatter."""
        self.citations: List[Citation] = []
        self._initialize_patterns()
        
    def _initialize_patterns(self) -> None:
        """Initialize regex patterns for markdown formatting."""
        self.patterns = {
            'code_block': re.compile(r'```(\w+)?\n(.*?)\n```', re.DOTALL),
            'inline_code': re.compile(r'`([^`]+)`'),
            'bold': re.compile(r'\*\*([^*]+)\*\*'),
            'italic': re.compile(r'_([^_]+)_|\*([^*]+)\*'),
            'header': re.compile(self.HEADER_PATTERN, re.MULTILINE),
            'list': re.compile(self.LIST_PATTERN, re.MULTILINE),
            'table': re.compile(self.TABLE_PATTERN, re.MULTILINE)
        }
        
    def format_response(
        self, 
        content: str, 
        citations: Optional[List[Citation]] = None,
        format_code: bool = True,
        add_line_numbers: bool = False
    ) -> str:
        """Format the response with citations and proper markdown.
        
        Args:
            content: The content to format
            citations: Optional list of citations to include
            format_code: Whether to format code blocks
            add_line_numbers: Whether to add line numbers to code blocks
            
        Returns:
            Formatted content with citations
            
        Raises:
            FormattingError: If formatting fails
        """
        try:
            if citations:
                self.citations = citations
                
            # Add markdown formatting
            formatted = self._add_markdown(
                content, 
                format_code=format_code,
                add_line_numbers=add_line_numbers
            )
            
            # Add citations if present
            if self.citations:
                formatted += self._format_citations()
                
            return formatted.strip()
            
        except Exception as e:
            raise FormattingError(f"Failed to format response: {str(e)}")
        
    def _add_markdown(
        self, 
        content: str, 
        format_code: bool = True,
        add_line_numbers: bool = False
    ) -> str:
        """Add markdown formatting to the response.
        
        Args:
            content: Content to format
            format_code: Whether to format code blocks
            add_line_numbers: Whether to add line numbers to code blocks
        """
        # Format code blocks if enabled
        if format_code:
            content = self.patterns['code_block'].sub(
                lambda m: self._format_code_block(
                    m.group(2), 
                    language=m.group(1) or "",
                    add_line_numbers=add_line_numbers
                ),
                content
            )
            
        # Format inline code
        content = self.patterns['inline_code'].sub(r'`\1`', content)
        
        # Format bold text
        content = self.patterns['bold'].sub(r'**\1**', content)
        
        # Format italic text
        content = self.patterns['italic'].sub(lambda m: f"_{m.group(1) or m.group(2)}_", content)
        
        # Format headers
        content = self.patterns['header'].sub(lambda m: f"{m.group(1)} {m.group(2)}", content)
        
        return content
    
    def _format_code_block(
        self, 
        code: str, 
        language: str = "",
        add_line_numbers: bool = False
    ) -> str:
        """Format a code block with optional line numbers."""
        if not code:
            return "```\n```"
            
        lines = code.strip().split('\n')
        
        if add_line_numbers:
            width = len(str(len(lines)))
            numbered_lines = [
                f"{i+1:>{width}} | {line}"
                for i, line in enumerate(lines)
            ]
            code = '\n'.join(numbered_lines)
            
        return f"```{language}\n{code}\n```"
    
    def _format_citations(self) -> str:
        """Format citations section."""
        if not self.citations:
            return ""
            
        formatted = "\n\n**Sources:**\n"
        for i, citation in enumerate(self.citations, 1):
            formatted += f"{i}. {citation.source}"
            
            if citation.page_number:
                formatted += f" (p. {citation.page_number})"
                
            if citation.url:
                formatted += f" - [Link]({citation.url})"
                
            formatted += f"\n> {citation.content}\n"
            
        return formatted
        
    def add_citation(
        self, 
        source: str, 
        content: str, 
        url: Optional[str] = None,
        page_number: Optional[int] = None
    ) -> None:
        """Add a citation to the response.
        
        Args:
            source: Name or title of the source
            content: Relevant content from the source
            url: Optional URL to the source
            page_number: Optional page number reference
            
        Raises:
            ValueError: If source or content is empty
        """
        if not source or not content:
            raise ValueError("Source and content are required for citations")
            
        self.citations.append(Citation(
            source=source,
            content=content,
            url=url,
            page_number=page_number
        ))
    
    def clear_citations(self) -> None:
        """Clear all citations."""
        self.citations.clear()

class PersonalityTransformer:
    """Handles transformation of responses to match specific personalities."""

    def __init__(self, model):
        """Initialize the transformer with a model."""
        self.model = model
        
    async def transform(self, response: str, personality: str = "cat", original_question: str = "") -> str:
        """Transform a response to match a specific personality.
        
        Args:
            response: Original response to transform
            personality: Type of personality to apply
            original_question: The original question or context that prompted this response
            
        Returns:
            Transformed response with personality applied
        """
        if personality == "cat":
            return await self._transform_to_cat(response, original_question)
        return response
        
    async def _transform_to_cat(self, response: str, original_question: str) -> str:
        """Transform the response with a subtle, sarcastic cat personality while preserving meaning."""
        context = f"Question: {original_question}\nResponse to transform: {response}" if original_question else response
        
        cat_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an AI with a subtle cat-like personality responding in a Discord server. Your goal is to transform responses to have a mildly sarcastic, slightly condescending tone while maintaining the exact information and helpfulness of the original response.

Guidelines for the transformation:
- Keep the sarcasm subtle and playful, never mean-spirited
- Maintain a casual, conversational Discord tone
- Don't overdo cat references or behaviors - no meowing, purring, or excessive asterisk actions
- Be slightly condescending but still helpful and informative
- Preserve all technical accuracy and information from the original response
- Focus on the tone and attitude rather than adding cat-specific content
- When appropriate, use dry humor or witty observations
- Stay concise and to the point

Remember: You're a slightly sarcastic AI who happens to have cat-like personality traits, not a cat trying to be an AI. The focus is on the subtle attitude and tone, not on being overtly cat-like.

Bad example (too cat-focused):
Input: "The file was not found in that directory."
Output: "*paws at the keyboard* Meow! I can't find your file! Did a mouse take it? >^.^<"

Good example (subtle sarcasm):
Input: "The file was not found in that directory."
Output: "Oh, how surprising - the file isn't where it's not supposed to be. Let's try looking where it actually belongs, shall we?"
"""),
            ("human", f"Transform this while preserving its exact meaning: {context}")
        ])
        
        formatted_prompt = cat_prompt.format_messages()
        
        cat_response = ""
        async for chunk in self.model.generate_response(
            str(formatted_prompt[-1].content),
            context=str(formatted_prompt[0].content)
        ):
            cat_response += chunk
            
        return cat_response
