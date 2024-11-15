from typing import Optional, Union, Dict
import numexpr
import math
from decimal import Decimal, InvalidOperation
from ..utils.errors import ToolError
from . import AIResponderTool, ToolRegistry

@ToolRegistry.register
class Calculator(AIResponderTool):
    """Calculator tool for mathematical expressions."""
    
    name = "calculator"
    description = "Perform mathematical calculations including basic arithmetic, trigonometry, and more"
    
    # Constants for validation
    MAX_EXPRESSION_LENGTH = 1000
    ALLOWED_FUNCTIONS = {
        'sin', 'cos', 'tan', 'sqrt', 'abs', 
        'exp', 'log', 'log10', 'pow', 'round'
    }
    
    @classmethod
    def __init_subclass__(cls, **kwargs):
        """Prevent duplicate registration of calculator tools."""
        super().__init_subclass__(**kwargs)
        if any(tool.__name__ == "Calculator" for tool in ToolRegistry._tools.values()):
            return
    
    def __init__(self, bot=None):
        """Initialize calculator with math functions."""
        super().__init__(bot)
        
    async def initialize(self) -> None:
        """Initialize calculator tool."""
        self._setup_math_functions()
        
    def _setup_math_functions(self) -> None:
        """Setup additional math functions for numexpr."""
        self.math_functions = {
            'sin': math.sin,
            'cos': math.cos,
            'tan': math.tan,
            'sqrt': math.sqrt,
            'abs': abs,
            'exp': math.exp,
            'log': math.log,
            'log10': math.log10,
            'pow': pow,
            'round': round
        }
        
    def _validate_expression(self, expression: str) -> None:
        """Validate the mathematical expression.
        
        Args:
            expression: Expression to validate
            
        Raises:
            ToolError: If expression is invalid
        """
        if not expression or not expression.strip():
            raise ToolError(self.name, "Expression cannot be empty")
            
        if len(expression) > self.MAX_EXPRESSION_LENGTH:
            raise ToolError(
                self.name, 
                f"Expression too long (max {self.MAX_EXPRESSION_LENGTH} characters)"
            )
            
        # Check for potentially harmful expressions
        if any(keyword in expression.lower() for keyword in ['import', 'eval', 'exec']):
            raise ToolError(self.name, "Invalid expression: contains forbidden keywords")
            
        # Validate parentheses matching
        if expression.count('(') != expression.count(')'):
            raise ToolError(self.name, "Invalid expression: unmatched parentheses")
    
    def _format_result(self, result: Union[float, int, Decimal]) -> str:
        """Format the calculation result.
        
        Args:
            result: Result to format
            
        Returns:
            Formatted result string
        """
        try:
            # Handle special cases
            if isinstance(result, (float, Decimal)):
                if math.isnan(float(result)):
                    return "The result is: Not a Number (NaN)"
                if math.isinf(float(result)):
                    return "The result is: Infinity"
                    
            # Format regular numbers
            if isinstance(result, (int, Decimal)):
                return f"The result is: {result}"
            return f"The result is: {result:.10g}"
            
        except Exception:
            return f"The result is: {result}"
    
    def _run(self, expression: str) -> str:
        """Execute the calculation.
        
        Args:
            expression: Mathematical expression to evaluate
            
        Returns:
            Formatted result string
            
        Raises:
            ToolError: If calculation fails
        """
        try:
            # Validate expression
            self._validate_expression(expression)
            
            # Clean up expression
            expression = expression.strip()
            
            # Add math functions to local dict
            local_dict = {name: func for name, func in self.math_functions.items()}
            
            # Evaluate expression
            result = numexpr.evaluate(expression, local_dict=local_dict).item()
            
            return self._format_result(result)
            
        except (SyntaxError, TypeError) as e:
            raise ToolError(self.name, f"Invalid expression syntax: {str(e)}")
        except (ValueError, ZeroDivisionError) as e:
            raise ToolError(self.name, f"Math error: {str(e)}")
        except Exception as e:
            raise ToolError(self.name, f"Error evaluating expression: {str(e)}")
    
    async def _arun(self, expression: str) -> str:
        """Async wrapper for _run.
        
        Args:
            expression: Mathematical expression to evaluate
            
        Returns:
            Formatted result string
        """
        return self._run(expression)
