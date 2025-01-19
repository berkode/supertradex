import logging
import json
from typing import List, Set, Optional


class Blacklist:
    """
    Manages a blacklist of tokens to avoid, with support for manual and automated updates.
    """

    def __init__(self, blacklist_file: Optional[str] = None, logging_level: int = logging.INFO):
        """
        Initializes the Blacklist.

        :param blacklist_file: Optional file path to save/load the blacklist.
        :param logging_level: Logging level for the logger.
        """
        self.blacklist: Set[str] = set()
        self.blacklist_file = blacklist_file
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging_level)

        if blacklist_file:
            self._load_blacklist()

        self.logger.info("Blacklist initialized with %d tokens.", len(self.blacklist))

    def _load_blacklist(self):
        """
        Loads the blacklist from a file. Supports JSON and TXT formats.
        """
        if not self.blacklist_file:
            self.logger.warning("Blacklist file not specified. Starting with an empty blacklist.")
            return

        try:
            if self.blacklist_file.endswith(".json"):
                with open(self.blacklist_file, "r") as file:
                    self.blacklist = set(json.load(file))
                self.logger.info("Blacklist loaded from JSON file: %s", self.blacklist_file)
            else:  # Assume plain text format
                with open(self.blacklist_file, "r") as file:
                    self.blacklist = set(line.strip() for line in file if line.strip())
                self.logger.info("Blacklist loaded from TXT file: %s", self.blacklist_file)
        except FileNotFoundError:
            self.logger.warning("Blacklist file not found: %s. Starting with an empty blacklist.", self.blacklist_file)
        except Exception as e:
            self.logger.error("Failed to load blacklist from file: %s. Error: %s", self.blacklist_file, str(e))

    def _save_blacklist(self):
        """
        Saves the current blacklist to a file. Supports JSON and TXT formats.
        """
        if not self.blacklist_file:
            return

        try:
            if self.blacklist_file.endswith(".json"):
                with open(self.blacklist_file, "w") as file:
                    json.dump(sorted(self.blacklist), file, indent=4)
                self.logger.info("Blacklist saved to JSON file: %s", self.blacklist_file)
            else:  # Save as plain text
                with open(self.blacklist_file, "w") as file:
                    for token in sorted(self.blacklist):
                        file.write(f"{token}\n")
                self.logger.info("Blacklist saved to TXT file: %s", self.blacklist_file)
        except Exception as e:
            self.logger.error("Failed to save blacklist to file: %s. Error: %s", self.blacklist_file, str(e))

    def add_token(self, token: str) -> bool:
        """
        Adds a token to the blacklist.

        :param token: The symbol or address of the token to blacklist.
        :return: True if the token was added, False if it was already blacklisted.
        """
        if token in self.blacklist:
            self.logger.warning("Token '%s' is already in the blacklist.", token)
            return False
        self.blacklist.add(token)
        self.logger.info("Token '%s' added to the blacklist.", token)
        self._save_blacklist()
        return True

    def remove_token(self, token: str) -> bool:
        """
        Removes a token from the blacklist.

        :param token: The symbol or address of the token to remove.
        :return: True if the token was removed, False if it was not in the blacklist.
        """
        if token not in self.blacklist:
            self.logger.warning("Token '%s' is not in the blacklist.", token)
            return False
        self.blacklist.remove(token)
        self.logger.info("Token '%s' removed from the blacklist.", token)
        self._save_blacklist()
        return True

    def is_blacklisted(self, token: str) -> bool:
        """
        Checks if a token is in the blacklist.

        :param token: The symbol or address of the token to check.
        :return: True if the token is blacklisted, False otherwise.
        """
        return token in self.blacklist

    def get_blacklist(self) -> List[str]:
        """
        Returns the current blacklist.

        :return: A sorted list of blacklisted tokens.
        """
        return sorted(self.blacklist)

    def update_blacklist_from_source(self, source: List[str]):
        """
        Updates the blacklist with tokens from an external source.

        :param source: A list of token symbols or addresses to add to the blacklist.
        """
        added_tokens = [token for token in source if token not in self.blacklist]
        self.blacklist.update(source)
        self.logger.info("Blacklist updated with %d tokens from external source.", len(added_tokens))
        self._save_blacklist()
        return added_tokens
