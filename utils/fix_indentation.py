#!/usr/bin/env python3
import re

def fix_indentation():
    file_path = 'data/market_data.py'
    
    with open(file_path, 'r') as file:
        content = file.read()
    
    # Look for the problematic area
    pattern = r'(            elif data_type == "volume":\n                # Update volume if available\n                volume = event_data.get\(\'volume\'\)\n                event_type = event_data.get\(\'event_type\'\)\n\s+)(\s+if volume is not None and event_type == "swap":\n)(\s+self\.logger\.info.*\n\s+await self\.update_token_volume.*\n)'
    
    # Replace it with correctly indented code
    fixed_content = re.sub(
        pattern,
        r'\1                if volume is not None and event_type == "swap":\n\3',
        content
    )
    
    # Write back to the file
    with open(file_path, 'w') as file:
        file.write(fixed_content)
    
    print(f"Fixed indentation in {file_path}")

if __name__ == "__main__":
    fix_indentation() 