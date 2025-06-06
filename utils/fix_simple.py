with open('data/market_data.py', 'r') as f:
    content = f.read()

# Replace the problematic section
start_marker = "            elif data_type == \"volume\":"
end_marker = "            else:"

fixed_section = """            elif data_type == "volume":
                # Update volume if available
                volume = event_data.get('volume')
                event_type = event_data.get('event_type')
                
                if volume is not None and event_type == "swap":
                    self.logger.info(f"Blockchain update: {mint} swap volume: {volume} USD")
                    await self.update_token_volume(mint, volume)
            else:"""

# Find the start and end positions
start_pos = content.find(start_marker)
end_pos = content.find(end_marker, start_pos)

if start_pos != -1 and end_pos != -1:
    # Replace the section
    new_content = content[:start_pos] + fixed_section + content[end_pos + len(end_marker):]
    
    # Write back to the file
    with open('data/market_data.py', 'w') as f:
        f.write(new_content)
    
    print("Fixed the indentation issue in market_data.py")
else:
    print("Could not find the problematic section") 