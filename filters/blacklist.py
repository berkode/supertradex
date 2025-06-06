import logging
from data.token_database import TokenDatabase
import json # For direct query fallback display
import pandas as pd # For direct query fallback display

logger = logging.getLogger(__name__)

class Blacklist:
    """Manages the token blacklist using the database."""

    def __init__(self, db: TokenDatabase):
        """
        Initializes the Blacklist manager.

        Args:
            db: An instance of TokenDatabase.
        """
        self.db = db
        logger.info("Blacklist manager initialized.")

    async def add_token(self, token_address: str, reason: str = "Manual blacklist") -> bool:
        """
        Adds a token to the blacklist by setting its status to 'blacklisted' in the database.

        Args:
            token_address: The address of the token to blacklist.
            reason: An optional reason for blacklisting (will be added to filter_details).

        Returns:
            True if the token was successfully blacklisted, False otherwise.
        """
        if not token_address:
            logger.error("Cannot add token to blacklist: 'address' not provided.")
            return False

        success = await self.db.add_to_blacklist(token_address, reason)
        # Logging is handled within the db method
        return success

    async def remove_token(self, token_address: str) -> bool:
        """Removes token from blacklist by setting status to 'scanned'."""
        if not token_address:
            logger.error("Cannot remove token from blacklist: 'address' not provided.")
            return False
        return await self.db.remove_from_blacklist(token_address)


    async def is_blacklisted(self, token_address: str) -> bool:
        """
        Checks if a token is currently blacklisted in the database.

        Args:
            token_address: The address of the token to check.

        Returns:
            True if the token is blacklisted, False otherwise.
        """
        if not token_address:
            return False
        # Logging is handled within the db method
        return await self.db.is_blacklisted(token_address)

    # Optional: Method to get all blacklisted tokens for viewing
    async def get_tokens(self) -> list[dict]:
        """Retrieves all blacklisted tokens from the database."""
        conn = await self.db._get_connection() # Access internal connection for direct query
        sql = "SELECT * FROM tokens WHERE status = 'blacklisted'"
        tokens = []
        try:
            async with conn.cursor() as cursor:
                await cursor.execute(sql)
                rows = await cursor.fetchall()
                tokens = [dict(row) for row in rows]
            logger.info(f"Retrieved {len(tokens)} blacklisted tokens from DB.")
            return tokens
        except Exception as e: # Use generic Exception as aiosqlite.Error might not be caught if conn fails
            logger.error(f"Error retrieving blacklist tokens: {e}", exc_info=True)
            return []

    # Helper for CLI display (used in main.py)
    async def display_tokens(self):
        """Displays blacklist content formatted for the console."""
        print("\n--- Blacklist ---")
        tokens = await self.get_tokens()
        if not tokens:
            print("Blacklist is empty.")
        else:
            try:
                df = pd.DataFrame(tokens)
                # Select and reorder columns for display
                cols_to_show = ['address', 'symbol', 'name', 'status', 'filter_details']
                df_display = df[[col for col in cols_to_show if col in df.columns]]
                # Attempt to parse JSON in filter_details for better display
                def format_details(details_str):
                    try:
                        details_dict = json.loads(details_str or '{}')
                        reason = details_dict.get('blacklist_reason', 'N/A')
                        ts = details_dict.get('blacklisted_at', '')
                        return f"Reason: {reason} ({ts})"
                    except:
                        return details_str[:100] # Fallback
                if 'filter_details' in df_display.columns:
                     df_display['filter_details'] = df_display['filter_details'].apply(format_details)
                     df_display.rename(columns={'filter_details': 'Blacklist Info'}, inplace=True)

                print(df_display.to_string(index=False, max_colwidth=50))
            except ImportError:
                # Fallback to simple print if pandas not installed
                for token in tokens:
                    print(f"  Address: {token.get('address')}, Symbol: {token.get('symbol')}, Status: {token.get('status')}")
                    details = token.get('filter_details')
                    if details: print(f"    Details: {details[:100]}...") # Print snippet
        print("-----------------\n")

    async def close(self):
        """Clean up resources."""
        try:
            # No need to commit since TokenDatabase handles its own connections
            logger.info("Blacklist manager closed successfully")
        except Exception as e:
            logger.error(f"Error closing Blacklist manager: {e}")

# --- Blacklist Filter Class ---

class BlacklistFilter:
    """Applies blacklist check as an analysis step."""
    
    def __init__(self, db: TokenDatabase, settings=None): # Accept settings even if not used now
        """Initializes the filter, creating a Blacklist instance."""
        self.logger = logging.getLogger(__name__) # Initialize logger
        self.blacklist = Blacklist(db)
        self.settings = settings # Store settings if provided
        self.logger.info("BlacklistFilter initialized.")

    async def analyze_and_annotate(self, tokens: list[dict]) -> list[dict]:
        """
        Checks each token against the blacklist and annotates it.

        Args:
            tokens: A list of token dictionaries.

        Returns:
            The list of token dictionaries, annotated with blacklist status.
        """
        self.logger.info(f"Applying BlacklistFilter to {len(tokens)} tokens.")
        annotated_tokens = []
        for token in tokens:
            token_address = token.get('mint')
            analysis_key = "blacklist_analysis"
            if not token_address:
                token[analysis_key] = {"status": "error", "error": "Missing mint address"}
                annotated_tokens.append(token)
                continue

            try:
                is_listed = await self.blacklist.is_blacklisted(token_address)
                if is_listed:
                    token[analysis_key] = {"status": "blacklisted", "flagged": True}
                    self.logger.debug(f"Token {token_address} is blacklisted.")
                else:
                    token[analysis_key] = {"status": "not_blacklisted", "flagged": False}
                annotated_tokens.append(token)
            except Exception as e:
                self.logger.error(f"Error checking blacklist for {token_address}: {e}", exc_info=False)
                token[analysis_key] = {"status": "error", "error": str(e)}
                annotated_tokens.append(token)
                
        return annotated_tokens

    async def close(self):
        """Clean up resources, including the internal Blacklist instance."""
        await self.blacklist.close()
        logger.info("BlacklistFilter closed.")
