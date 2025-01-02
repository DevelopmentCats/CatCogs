"""Utils package for ServerSage's PURRFECT functionality 😺"""

from .gemini_client import GeminiClient
from .server_analyzer import ServerAnalyzer
from .suggestion_manager import SuggestionManager

__all__ = [
    'GeminiClient',
    'ServerAnalyzer',
    'SuggestionManager'
]

# Version info
__version__ = '1.0.0'
__author__ = 'DevelopmentCats'
