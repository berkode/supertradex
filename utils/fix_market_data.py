#!/usr/bin/env python3

"""
Fix indentation issues in market_data.py
"""

import os

def fix_market_data():
    # Read the file
    file_path = 'data/market_data.py'
    with open(file_path, 'r') as f:
        lines = f.readlines()
    
    # Find the problematic function
    start_index = None
    end_index = None
    
    for i, line in enumerate(lines):
        if 'async def _setup_price_monitor_for_token(' in line:
            start_index = i
            break
    
    if start_index is None:
        print("Could not find the _setup_price_monitor_for_token function")
        return
    
    # Find the end of the function
    for i in range(start_index + 1, len(lines)):
        if line.startswith('    async def') or line.startswith('    def'):
            end_index = i - 1
            break
    
    if end_index is None:
        end_index = len(lines) - 1
    
    # Create the fixed function
    fixed_function = """    async def _setup_price_monitor_for_token(self, mint: str, symbol: str = None, pool_address: str = None):
        \"\"\"
        Set up price monitor polling for low-priority tokens
        
        Args:
            mint: The token's mint address
            symbol: The token's symbol
            pool_address: The pool/AMM address (optional)
            
        Returns:
            bool: Success status
        \"\"\"
        if mint not in self._monitored_tokens:
            # Initialize token info if not already present
            self._monitored_tokens[mint] = {
                'address': mint,
                'symbol': symbol or mint[:8],
                'pool_address': pool_address,
                'monitoring_started': int(time.time()),
                'last_price': None,
                'last_price_updated': None,
                'hourly_volume': 0,
                'priority': 'low',  # Always low priority for price monitor
                'monitoring_method': 'price_monitor'
            }
        else:
            # Update existing record
            self._monitored_tokens[mint]['monitoring_method'] = 'price_monitor'
            
        self.logger.info(f"Setting up LOW PRIORITY price monitor polling for {mint}")
        
        # Register with price monitor for polling updates
        if hasattr(self, 'price_monitor') and self.price_monitor:
            try:
                # Just pass the mint to add_token since it only accepts one parameter
                self.price_monitor.add_token(mint)
                self.logger.info(f"Added {mint} to price monitor polling")
                return True
            except Exception as e:
                self.logger.error(f"Error adding token to price monitor: {e}")
                return False
        else:
            self.logger.error("Cannot set up price monitor: price_monitor not initialized")
            return False
"""
    
    # Replace the function in the file
    new_lines = lines[:start_index] + [fixed_function] + lines[end_index+1:]
    
    # Write the file
    with open(file_path, 'w') as f:
        f.writelines(new_lines)
    
    print("Fixed the _setup_price_monitor_for_token function in market_data.py")

if __name__ == "__main__":
    fix_market_data() 