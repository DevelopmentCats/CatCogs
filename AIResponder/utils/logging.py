from colorama import Fore, Style, init
import logging

# Initialize colorama for cross-platform color support
init()

def setup_logger(name: str) -> logging.Logger:
    """Setup module logger with proper formatting and handlers."""
    logger = logging.getLogger(name)
    
    # Clear any existing handlers to prevent duplicates
    logger.handlers = []
    
    # Only add handler if none exist at root level
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '%(asctime)s %(levelname)-8s %(name)s %(message)s',
            datefmt='[%H:%M:%S]'
        )
        handler.setFormatter(formatter)
        root.addHandler(handler)
    
    return logger

def format_log(category: str, message: str, color: str = Fore.WHITE) -> str:
    """Format log message with consistent styling."""
    return f"{color}[{category}]{Style.RESET_ALL} {message}"

# Common color shortcuts
class LogColors:
    INFO = Fore.WHITE
    SUCCESS = Fore.GREEN
    WARNING = Fore.YELLOW
    ERROR = Fore.RED
    TOOL = Fore.CYAN
    ACTION = Fore.BLUE
    THOUGHT = Fore.MAGENTA
