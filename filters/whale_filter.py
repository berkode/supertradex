import logging
from typing import List, Dict, Optional


class WhaleFilter:
    """
    Identifies tokens with suspicious whale activity based on predefined thresholds.
    """

    def __init__(
        self, 
        whale_threshold: float, 
        suspicious_threshold: int, 
        logging_level: int = logging.INFO,
        save_flagged_tokens: Optional[str] = None
    ):
        """
        Initializes the WhaleFilter.
        
        :param whale_threshold: Percentage of token holdings considered as whale activity (e.g., 1.0 for 1%).
        :param suspicious_threshold: Minimum number of whale accounts for flagging as suspicious.
        :param logging_level: Logging level for the logger.
        :param save_flagged_tokens: Optional file path to save flagged tokens.
        """
        self.whale_threshold = whale_threshold
        self.suspicious_threshold = suspicious_threshold
        self.save_flagged_tokens = save_flagged_tokens

        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging_level)

        self.logger.info(
            "WhaleFilter initialized with whale threshold: %.2f%% and suspicious threshold: %d.",
            self.whale_threshold * 100,
            self.suspicious_threshold
        )

    def analyze_token(self, token: str, holder_data: Dict[str, float]) -> bool:
        """
        Analyzes whale activity for a given token.
        
        :param token: The token symbol or address to analyze.
        :param holder_data: A dictionary of holder addresses and their percentage holdings.
        :return: True if the token shows suspicious whale activity, False otherwise.
        """
        whale_accounts = [
            address for address, percentage in holder_data.items() 
            if percentage >= self.whale_threshold
        ]

        whale_count = len(whale_accounts)
        self.logger.debug(
            "Token '%s': Found %d whale accounts exceeding %.2f%% threshold.", 
            token, whale_count, self.whale_threshold * 100
        )

        if whale_count >= self.suspicious_threshold:
            self.logger.warning(
                "Token '%s' flagged for suspicious whale activity: %d accounts exceed %.2f%% holdings.",
                token, whale_count, self.whale_threshold * 100
            )
            return True
        return False

    def filter_tokens(self, tokens_data: Dict[str, Dict[str, float]]) -> List[str]:
        """
        Filters a list of tokens based on whale activity.
        
        :param tokens_data: A dictionary where keys are token symbols or addresses, and values are
                            dictionaries of holder data (address: percentage holdings).
        :return: A list of tokens flagged for suspicious whale activity.
        """
        flagged_tokens = []
        for token, holder_data in tokens_data.items():
            if self.analyze_token(token, holder_data):
                flagged_tokens.append(token)

        self.logger.info(
            "Whale filtering complete. %d tokens flagged for suspicious activity.", len(flagged_tokens)
        )

        if self.save_flagged_tokens:
            self._save_flagged_tokens(flagged_tokens)

        return flagged_tokens

    def _save_flagged_tokens(self, flagged_tokens: List[str]):
        """
        Saves flagged tokens to a specified file.
        
        :param flagged_tokens: List of tokens flagged for suspicious whale activity.
        """
        try:
            with open(self.save_flagged_tokens, "w") as file:
                for token in flagged_tokens:
                    file.write(f"{token}\n")
            self.logger.info(
                "Flagged tokens saved to file: %s", self.save_flagged_tokens
            )
        except Exception as e:
            self.logger.error(
                "Failed to save flagged tokens to file: %s. Error: %s",
                self.save_flagged_tokens, str(e)
            )
