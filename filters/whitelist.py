import logging
import json
from typing import List, Set

class Whitelist:
    """
    Manages a list of safe tokens for immediate trading.
    """

    def __init__(self, initial_tokens: List[str] = None, whitelist_file: str = None):
        """
        Initializes the whitelist with an optional initial set of tokens or loads from a file.
        
        :param initial_tokens: A list of token symbols or addresses to preload in the whitelist.
        :param whitelist_file: Path to a file for persisting the whitelist.
        """
        self.tokens: Set[str] = set(initial_tokens or [])
        self.whitelist_file = whitelist_file
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        
        if whitelist_file:
            self._load_from_file()
        
        self.logger.info("Whitelist initialized with %d tokens.", len(self.tokens))

    def _load_from_file(self):
        """
        Loads the whitelist from a file if specified.
        """
        try:
            with open(self.whitelist_file, 'r') as file:
                data = json.load(file)
                self.tokens = set(data)
                self.logger.info("Whitelist loaded from file: %s", self.whitelist_file)
        except FileNotFoundError:
            self.logger.warning("Whitelist file not found. Starting with an empty list.")
        except json.JSONDecodeError as e:
            self.logger.error("Failed to load whitelist file: %s. Error: %s", self.whitelist_file, str(e))

    def _save_to_file(self):
        """
        Saves the current whitelist to a file if specified.
        """
        if not self.whitelist_file:
            return
        
        try:
            with open(self.whitelist_file, 'w') as file:
                json.dump(list(self.tokens), file)
                self.logger.info("Whitelist saved to file: %s", self.whitelist_file)
        except Exception as e:
            self.logger.error("Failed to save whitelist to file: %s. Error: %s", self.whitelist_file, str(e))

    def add_token(self, token: str) -> bool:
        """
        Adds a token to the whitelist.
        
        :param token: The symbol or address of the token to add.
        :return: True if the token was added, False if it was already in the whitelist.
        """
        if token in self.tokens:
            self.logger.warning("Token '%s' is already in the whitelist.", token)
            return False
        self.tokens.add(token)
        self.logger.info("Token '%s' added to the whitelist.", token)
        self._save_to_file()
        return True

    def remove_token(self, token: str) -> bool:
        """
        Removes a token from the whitelist.
        
        :param token: The symbol or address of the token to remove.
        :return: True if the token was removed, False if it was not in the whitelist.
        """
        if token not in self.tokens:
            self.logger.warning("Token '%s' is not in the whitelist.", token)
            return False
        self.tokens.remove(token)
        self.logger.info("Token '%s' removed from the whitelist.", token)
        self._save_to_file()
        return True

    def is_whitelisted(self, token: str) -> bool:
        """
        Checks if a token is in the whitelist.
        
        :param token: The symbol or address of the token to check.
        :return: True if the token is in the whitelist, False otherwise.
        """
        return token in self.tokens

    def get_all_tokens(self) -> List[str]:
        """
        Returns a list of all tokens in the whitelist.
        
        :return: A list of token symbols or addresses.
        """
        return sorted(self.tokens)

    def clear_whitelist(self):
        """
        Clears all tokens from the whitelist.
        """
        self.tokens.clear()
        self.logger.info("Whitelist cleared.")
        self._save_to_file()
