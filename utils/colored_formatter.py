"""
Custom formatter for adding colors to log messages.
"""
import logging

class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors and consistent width for log levels."""
    
    # ANSI color codes
    COLORS = {
        'CRITICAL': '\033[91m',  # Red
        'ERROR': '\033[93m',     # Orange/Yellow
        'WARNING': '\033[93m',   # Yellow
        'INFO': '\033[92m',      # Green
        'DEBUG': '\033[94m',     # Blue
        'RESET': '\033[0m'       # Reset
    }
    
    def format(self, record):
        # Get the original message
        message = super().format(record)
        
        # Add color based on log level
        levelname = record.levelname
        if levelname in self.COLORS:
            # Add color and reset code
            message = f"{self.COLORS[levelname]}{message}{self.COLORS['RESET']}"
        
        return message 