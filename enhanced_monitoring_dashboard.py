from flask import Flask, render_template_string, jsonify, Markup
import json
import os
import glob
import re
from datetime import datetime
from pathlib import Path
import threading
import time
from typing import Dict, List, Optional

app = Flask(__name__)

def format_small_number(number: float, decimals: int = 8):
    """Format small numbers with zero count indicator"""
    if number == 0:
        return "0"
    
    # Convert to string with enough precision
    num_str = f"{number:.{decimals + 10}f}"
    
    # Find the position of the first non-zero digit after decimal
    decimal_part = num_str.split('.')[1] if '.' in num_str else ""
    
    # Count leading zeros after decimal point
    zero_count = 0
    for char in decimal_part:
        if char == '0':
            zero_count += 1
        else:
            break
    
    if zero_count > 3:  # If more than 3 zeros, show with count
        # Get the significant digits
        significant_part = decimal_part[zero_count:zero_count+4]
        return Markup(f"0.0<sub class='zero-count'>{zero_count}</sub>{significant_part}")
    else:
        # Normal formatting for numbers with few zeros
        return f"{number:.{decimals}f}".rstrip('0').rstrip('.')

def get_token_icon_letter(symbol: str) -> str:
    """Get the first letter of token symbol for icon"""
    return symbol[0].upper() if symbol else "?"

# ... existing code ... 