from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional, Dict, Any, List
from dataclasses import dataclass
from ..utils.errors import ModelInitializationError, ModelGenerationError

@dataclass
class ModelConfig:
    """Configuration for model initialization."""
    temperature: float = 0.7
    top_p: float = 0.9
    top_k: int = 40
    repeat_penalty: float = 1.1
    max_new_tokens: Optional[int] = None
    stop_sequences: List[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary."""
        return {k: v for k, v in self.__dict__.items() if v is not None}

class BaseModel(ABC):
    """Base class for AI model implementations.
    
    This abstract class defines the interface for AI model implementations,
    providing common functionality and required methods for model operations.
    """
    
    def __init__(self, config: Optional[ModelConfig] = None):
        """Initialize the model with configuration.
        
        Args:
            config: Optional model configuration
        """
        self.config = config or ModelConfig()
        self._is_initialized = False
        
    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the model.
        
        This method should handle any necessary setup like loading model weights
        or establishing connections to model servers.
        
        Raises:
            ModelInitializationError: If initialization fails
        """
        pass
    
    @abstractmethod
    async def generate_response(
        self,
        prompt: str,
        context: Optional[str] = None,
        **kwargs: Any
    ) -> AsyncGenerator[str, None]:
        """Generate a streaming response from the model.
        
        Args:
            prompt: The input prompt to generate from
            context: Optional context to condition the generation
            **kwargs: Additional model-specific parameters
            
        Yields:
            Chunks of generated text
            
        Raises:
            ModelGenerationError: If generation fails
        """
        pass
    
    @abstractmethod
    async def cleanup(self) -> None:
        """Cleanup any resources.
        
        This method should handle proper cleanup of any resources
        like closing connections or freeing memory.
        """
        pass
    
    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the name of the model."""
        pass
    
    @property
    @abstractmethod
    def max_tokens(self) -> int:
        """Return the maximum tokens the model can handle."""
        pass
    
    async def ensure_initialized(self) -> None:
        """Ensure the model is initialized before use."""
        if not self._is_initialized:
            try:
                await self.initialize()
                self._is_initialized = True
            except Exception as e:
                raise ModelInitializationError(f"Failed to initialize model: {str(e)}")
    
    def update_config(self, **kwargs: Any) -> None:
        """Update model configuration parameters.
        
        Args:
            **kwargs: Configuration parameters to update
        """
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
    
    @property
    def is_initialized(self) -> bool:
        """Check if model is initialized."""
        return self._is_initialized
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.ensure_initialized()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.cleanup()
        self._is_initialized = False
