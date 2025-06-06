with open('data/market_data.py', 'r') as f:
    content = f.read()

# Find the problematic docstring
function_def = "async def _setup_price_monitor_for_token(self, mint: str, symbol: str = None, pool_address: str = None):"
wrong_docstring = """    """
    Set up price monitor polling for low-priority tokens
    
    Args:
        mint: The token's mint address
        symbol: The token's symbol
        pool_address: The pool/AMM address (optional)
        
    Returns:
        bool: Success status
    \"\"\""""

# Create the correct docstring with proper indentation
correct_docstring = '''    """
    Set up price monitor polling for low-priority tokens
    
    Args:
        mint: The token's mint address
        symbol: The token's symbol
        pool_address: The pool/AMM address (optional)
        
    Returns:
        bool: Success status
    """'''

# Find the position of the function definition
function_pos = content.find(function_def)
if function_pos != -1:
    # Find the start of the docstring after the function definition
    docstring_pos = content.find('"""', function_pos)
    if docstring_pos != -1:
        # Extract the end of the docstring
        docstring_end = content.find('"""', docstring_pos + 3) + 3
        if docstring_end > docstring_pos + 3:
            # Replace the docstring with the correctly indented version
            new_content = (
                content[:docstring_pos] + 
                correct_docstring + 
                content[docstring_end:]
            )
            
            # Write back to the file
            with open('data/market_data.py', 'w') as f:
                f.write(new_content)
            
            print("Fixed the docstring indentation in _setup_price_monitor_for_token method")
        else:
            print("Could not find the end of the docstring")
    else:
        print("Could not find the start of the docstring")
else:
    print("Could not find the function definition") 