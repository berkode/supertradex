with open('data/market_data.py', 'r') as f:
    lines = f.readlines()

# Find the function definition line
for i, line in enumerate(lines):
    if 'async def _setup_price_monitor_for_token(' in line:
        function_line = i
        break
else:
    print("Function not found")
    exit(1)

# Check if the next line is properly indented
if lines[function_line + 1].strip() == '"""':
    # Fix the indentation
    lines[function_line + 1] = '    """\n'
    
    # Write back to file
    with open('data/market_data.py', 'w') as f:
        f.writelines(lines)
    print("Fixed the docstring indentation")
else:
    print("Unexpected line after function definition") 