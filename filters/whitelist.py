import csv
import os
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Set, TYPE_CHECKING
from logging import getLogger

# Import DB and Settings for type hinting only
if TYPE_CHECKING:
    from data.token_database import TokenDatabase # Keep if db interaction needed
from config.settings import Settings

# Remove direct imports of Settings or get_settings

# Use module-level logger
logger = getLogger(__name__)

class Whitelist:
    """Manages the token whitelist, loading from and saving to a CSV file specified in settings."""

    def __init__(self, settings: 'Settings'): # Accept settings object
        """Initialize Whitelist, loading data based on settings."""
        self.logger = logger # Use module logger
        self.settings = settings # Store settings
        
        try:
            self.whitelist_file = Path(self.settings.WHITELIST_FILE)
            self.logger.info(f"Whitelist file path set to: {self.whitelist_file}")
        except AttributeError:
            self.logger.error("WHITELIST_FILE not found in settings. Cannot initialize Whitelist.")
            # Or set a default path, but raising is safer if it's required
            raise ValueError("WHITELIST_FILE setting is required for Whitelist functionality.")
        
        self.whitelist: Set[str] = self._load_whitelist() # Use corrected load method
        self.logger.info(f"Whitelist loaded with {len(self.whitelist)} entries.")

    def _load_whitelist(self) -> Set[str]:
        """Loads the whitelist mint addresses from the CSV file."""
        whitelist_set = set()
        if not self.whitelist_file.exists():
            self.logger.warning(f"Whitelist file not found: {self.whitelist_file}")
            # Ensure the directory exists
            try:
                self.whitelist_file.parent.mkdir(parents=True, exist_ok=True)
                # Create an empty file with header
                with open(self.whitelist_file, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(['mint'])
                self.logger.info(f"Created empty whitelist file: {self.whitelist_file}")
            except Exception as e:
                self.logger.error(f"Failed to create whitelist file {self.whitelist_file}: {e}")
            return whitelist_set # Return empty set

        try:
            with open(self.whitelist_file, 'r', newline='') as f:
                reader = csv.DictReader(f)
                # Verify header
                if 'mint' not in (reader.fieldnames or []):
                    self.logger.error(f"Whitelist file {self.whitelist_file} missing 'mint' header.")
                    return whitelist_set # Return empty set if header is wrong
                
                # Read addresses
                for i, row in enumerate(reader):
                    address = row.get('mint')
                    if address:
                        whitelist_set.add(address.strip())
                    else:
                        self.logger.warning(f"Found empty 'mint' value in {self.whitelist_file}, row index: {i}")
        except Exception as e:
            self.logger.error(f"Error loading whitelist from {self.whitelist_file}: {e}", exc_info=True)
            # Depending on desired behavior, could return empty set or raise error
        
        return whitelist_set

    def is_whitelisted(self, mint: str) -> bool:
        """Checks if a token mint is in the loaded whitelist set."""
        return mint in self.whitelist

    def add_to_whitelist(self, mint: str) -> bool:
        """Adds a token mint to the whitelist set and appends to the file."""
        if not isinstance(mint, str) or not mint:
            self.logger.warning(f"Attempted to add invalid token mint: {mint}")
            return False

        mint = mint.strip()
        if mint not in self.whitelist:
            self.whitelist.add(mint)
            try:
                # Append to file - ensure directory exists
                self.whitelist_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self.whitelist_file, 'a', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([mint])
                self.logger.info(f"Added {mint} to whitelist file.")
                return True
            except Exception as e:
                self.logger.error(f"Error adding {mint} to whitelist file {self.whitelist_file}: {e}")
                # Rollback the change in the set if file write failed
                self.whitelist.discard(mint)
                return False
        else:
            self.logger.debug(f"Token {mint} is already in the whitelist.")
            return False

    def remove_from_whitelist(self, mint: str) -> bool:
        """Removes a token mint from the whitelist set and rewrites the file."""
        if not isinstance(mint, str) or not mint:
            self.logger.warning(f"Attempted to remove invalid token mint: {mint}")
            return False
            
        mint = mint.strip()
        if mint in self.whitelist:
            self.whitelist.remove(mint)
            # Rewrite the file without the removed mint
            try:
                self.whitelist_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self.whitelist_file, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(['mint']) # Write header
                    for address in sorted(list(self.whitelist)):
                        writer.writerow([address])
                self.logger.info(f"Removed {mint} from whitelist and updated file.")
                return True
            except Exception as e:
                self.logger.error(f"Error rewriting whitelist file after removing {mint}: {e}")
                # Consider adding the mint back to the set if rewrite fails
                self.whitelist.add(mint) # Potential rollback
                return False
        else:
            self.logger.warning(f"Attempted to remove {mint} which is not in the whitelist.")
            return False

    def get_whitelist(self) -> Set[str]:
        """Returns the current set of whitelisted addresses."""
        return self.whitelist.copy() # Return a copy to prevent external modification

# --- WhitelistFilter Class ---
class WhitelistFilter:
    """Filter component using the Whitelist manager instance."""
    
    # Removed db dependency as it seems unused by Whitelist itself
    def __init__(self, settings: 'Settings'): # Accept settings object
        """Initializes the filter, creating a Whitelist instance."""
        self.logger = logger # Use module logger
        self.settings = settings
        
        # Initialize the Whitelist instance here, passing settings
        try:
            # Whitelist now manages its own file IO based on settings
            self.whitelist_manager = Whitelist(settings) 
            self.logger.info("WhitelistFilter initialized with Whitelist manager.")
        except Exception as e:
            self.logger.error(f"Failed to initialize Whitelist manager within WhitelistFilter: {e}", exc_info=True)
            self.whitelist_manager = None # Indicate failure

    # Renamed from analyze_and_annotate for clarity, matching base filter structure
    async def apply(self, tokens: list[dict]) -> list[dict]:
        """
        Checks each token against the whitelist and annotates it.
        Assumes token dicts have a 'mint' key.

        Args:
            tokens: A list of token dictionaries.

        Returns:
            The list of token dictionaries, annotated with whitelist status.
        """
        self.logger.info(f"Applying WhitelistFilter to {len(tokens)} tokens.")
        if not self.whitelist_manager:
             self.logger.error("Whitelist manager not available. Cannot apply filter.")
             # Annotate all tokens with error status
             for token in tokens:
                 token["whitelist_analysis"] = {"status": "error", "error": "Whitelist manager unavailable"}
             return tokens

        annotated_tokens = []
        whitelist_mints = self.whitelist_manager.get_whitelist() # Gets the set of mints
        self.logger.debug(f"Checking against {len(whitelist_mints)} whitelist mints.")

        for token_data in tokens:
            token_address = token_data.get('mint')
            analysis_key = "whitelist_analysis" # Standardized key
            if not token_address:
                token_data[analysis_key] = {"status": "error", "error": "Missing mint address"}
                annotated_tokens.append(token_data)
                continue

            try:
                # Use the is_whitelisted method from the Whitelist instance
                is_listed = self.whitelist_manager.is_whitelisted(token_address)
                if is_listed:
                    token_data[analysis_key] = {"status": "whitelisted", "flagged": True}
                    self.logger.debug(f"Token {token_address} IS whitelisted.")
                else:
                    token_data[analysis_key] = {"status": "not_whitelisted", "flagged": False}
                    self.logger.debug(f"Token {token_address} is NOT whitelisted.")
                annotated_tokens.append(token_data)
            except Exception as e:
                self.logger.error(f"Error checking whitelist for {token_address}: {e}", exc_info=False)
                token_data[analysis_key] = {"status": "error", "error": str(e)}
                annotated_tokens.append(token_data)
                
        return annotated_tokens

    async def close(self):
        """Clean up resources (if any). Currently does nothing."""
        self.logger.info("WhitelistFilter closed.")