"""
Core Module for AI Responder

This module provides the core model implementations and interfaces
for interacting with various AI models.
"""

from .base_model import BaseModel, ModelConfig
from .deep_infra import DeepInfraModel
from .ollama import OllamaModel

__all__ = [
    "BaseModel",
    "ModelConfig",
    "DeepInfraModel",
    "OllamaModel"
]

# Version information
__version__ = "1.0.0"

# Module metadata
__author__ = "DevelopmentCats"
__description__ = "Core AI Model Implementations"
__status__ = "Production"
