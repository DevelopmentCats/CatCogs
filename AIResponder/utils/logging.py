from colorama import Fore, Style, init
import logging

# Initialize colorama for cross-platform color support
init()

def setup_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """Configure and return a logger with consistent formatting."""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    if not logger.handlers:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s [%(name)s] %(message)s',
            '[%H:%M:%S]'
        ))
        logger.addHandler(console_handler)
    
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
