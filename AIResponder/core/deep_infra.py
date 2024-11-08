from typing import AsyncGenerator, Optional, Dict, Any, List
import aiohttp
import json
import asyncio
from .base_model import BaseModel, ModelConfig
from ..utils.errors import ModelError, ModelInitializationError, ModelGenerationError

class DeepInfraModel(BaseModel):
    """Deep Infra API model implementation."""
    
    API_BASE = "https://api.deepinfra.com/v1/inference"
    DEFAULT_MODEL = "meta-llama/Llama-3.2-11B-Vision-Instruct"
    CHUNK_SIZE = 1024
    
    def __init__(
        self, 
        api_key: str, 
        model_name: str = DEFAULT_MODEL,
        config: Optional[ModelConfig] = None
    ):
        """Initialize Deep Infra model.
        
        Args:
            api_key: Deep Infra API key
            model_name: Model identifier
            config: Optional model configuration
        """
        super().__init__(config)
        self.api_key = api_key
        self._model_name = model_name
        self.session: Optional[aiohttp.ClientSession] = None
        self._api_endpoint = f"{self.API_BASE}/{model_name}"
        
    async def initialize(self) -> None:
        """Initialize API session."""
        try:
            self.session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
            )
            # Test connection
            async with self.session.get(f"{self.API_BASE}/health") as response:
                if response.status != 200:
                    raise ModelInitializationError(
                        f"API health check failed: {response.status}"
                    )
        except Exception as e:
            raise ModelInitializationError(f"Failed to initialize: {str(e)}")
    
    def _prepare_request_payload(
        self,
        prompt: str,
        context: Optional[str] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """Prepare the request payload."""
        payload = {
            "input": context + "\n" + prompt if context else prompt,
            "stream": True,
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
            "top_k": self.config.top_k,
            "repeat_penalty": self.config.repeat_penalty
        }
        
        if self.config.max_new_tokens:
            payload["max_new_tokens"] = self.config.max_new_tokens
            
        if self.config.stop_sequences:
            payload["stop"] = self.config.stop_sequences
            
        # Add any additional model-specific parameters
        payload.update({k: v for k, v in kwargs.items() if v is not None})
        
        return payload
    
    async def generate_response(
        self,
        prompt: str,
        context: Optional[str] = None,
        **kwargs: Any
    ) -> AsyncGenerator[str, None]:
        """Generate streaming response from the model."""
        if not self.session:
            await self.ensure_initialized()
            
        payload = self._prepare_request_payload(prompt, context, **kwargs)
        
        try:
            async with self.session.post(
                self._api_endpoint,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=300)  # 5 minute timeout
            ) as response:
                if response.status != 200:
                    error_body = await response.text()
                    raise ModelGenerationError(
                        f"API request failed: {response.status} - {error_body}"
                    )
                
                buffer = ""
                async for chunk in response.content.iter_chunked(self.CHUNK_SIZE):
                    chunk_text = chunk.decode('utf-8')
                    
                    # Handle SSE format
                    for line in chunk_text.split('\n'):
                        if line.startswith('data: '):
                            try:
                                data = json.loads(line[6:])
                                if 'token' in data:
                                    yield data['token']['text']
                                elif 'generated_text' in data:
                                    yield data['generated_text']
                            except json.JSONDecodeError:
                                # Handle partial JSON
                                buffer += line[6:]
                                try:
                                    data = json.loads(buffer)
                                    buffer = ""
                                    if 'token' in data:
                                        yield data['token']['text']
                                    elif 'generated_text' in data:
                                        yield data['generated_text']
                                except json.JSONDecodeError:
                                    continue
                            
        except asyncio.TimeoutError:
            raise ModelGenerationError("Request timed out")
        except Exception as e:
            raise ModelGenerationError(f"Generation failed: {str(e)}")
    
    async def cleanup(self) -> None:
        """Cleanup resources."""
        if self.session:
            try:
                await self.session.close()
            finally:
                self.session = None
    
    @property
    def model_name(self) -> str:
        """Get model name."""
        return self._model_name
    
    @property
    def max_tokens(self) -> int:
        """Get maximum token limit."""
        # Llama-3.2-11B-Vision-Instruct context window
        return 4096
