from typing import Optional, Dict, Any

class AIResponderError(Exception):
    """Base exception class for AIResponder errors."""
    pass

class ToolError(AIResponderError):
    """Base class for tool-related errors."""
    def __init__(self, tool_name: str, message: str):
        self.tool_name = tool_name
        super().__init__(f"Tool '{tool_name}': {message}")

class ToolExecutionError(ToolError):
    """Raised when a tool execution fails."""
    def __init__(self, tool_name: str, message: str, original_error: Optional[Exception] = None):
        self.original_error = original_error
        super().__init__(tool_name, message)

class ToolInitializationError(ToolError):
    """Raised when tool initialization fails."""
    pass

class ModelError(AIResponderError):
    """Base class for model-related errors."""
    pass

class ModelInitializationError(ModelError):
    """Raised when model initialization fails."""
    pass

class ModelGenerationError(ModelError):
    """Raised when model generation fails."""
    pass

class ModelResponseError(ModelError):
    """Raised when model response processing fails."""
    pass

class ResponseError(AIResponderError):
    """Base class for response-related errors."""
    pass

class ResponseParsingError(ResponseError):
    """Raised when response parsing fails."""
    pass

class ValidationError(ResponseError):
    """Raised when input validation fails."""
    pass

class FormattingError(ResponseError):
    """Raised when response formatting fails."""
    pass

class ChunkingError(ResponseError):
    """Raised when response chunking fails."""
    pass

class RateLimitError(ResponseError):
    """Raised when rate limits are exceeded."""
    def __init__(self, message: str, retry_after: Optional[float] = None):
        self.retry_after = retry_after
        super().__init__(message)

class ConfigError(AIResponderError):
    """Raised when configuration operations fail."""
    pass

class ConversationError(AIResponderError):
    """Raised when conversation operations fail."""
    pass

class AgentError(AIResponderError):
    """Base class for agent-related errors."""
    pass

class AgentInitializationError(AgentError):
    """Raised when agent initialization fails."""
    pass

class AgentExecutionError(AgentError):
    """Raised when agent execution fails."""
    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        self.context = context or {}
        super().__init__(message)
