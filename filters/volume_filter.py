import logging
from typing import Dict, List, Optional


class VolumeFilter:
    """
    Filters out tokens with low trading volume.
    """

    def __init__(
        self, 
        min_volume_threshold: float, 
        logging_level: int = logging.INFO, 
        save_filtered_tokens: Optional[str] = None
    ):
        """
        Initializes the VolumeFilter.
        
        :param min_volume_threshold: Minimum trading volume required to pass the filter.
        :param logging_level: Logging level for the logger.
        :param save_filtered_tokens: Optional file path to save the filtered tokens.
        """
        if min_volume_threshold <= 0:
            raise ValueError("min_volume_threshold must be a positive value.")

        self.min_volume_threshold = min_volume_threshold
        self.save_filtered_tokens = save_filtered_tokens

        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging_level)
        self.logger.info(
            "VolumeFilter initialized with minimum volume threshold: %.2f.",
            self.min_volume_threshold
        )

    def filter_tokens(self, tokens_volume: Dict[str, float]) -> List[str]:
        """
        Filters tokens based on their trading volume.
        
        :param tokens_volume: A dictionary where keys are token symbols or addresses,
                              and values are their trading volumes.
        :return: A list of tokens that meet or exceed the minimum volume threshold.
        """
        if not tokens_volume:
            self.logger.warning("No token volume data provided for filtering.")
            return []

        valid_tokens = []
        for token, volume in tokens_volume.items():
            if volume >= self.min_volume_threshold:
                valid_tokens.append(token)
                self.logger.debug(
                    "Token '%s' passed with volume %.2f (threshold: %.2f).",
                    token, volume, self.min_volume_threshold
                )
            else:
                self.logger.warning(
                    "Token '%s' excluded due to low volume %.2f (threshold: %.2f).",
                    token, volume, self.min_volume_threshold
                )

        self.logger.info(
            "Volume filtering complete. %d tokens passed the volume filter.",
            len(valid_tokens)
        )

        if self.save_filtered_tokens:
            self._save_filtered_tokens(valid_tokens)

        return valid_tokens

    def _save_filtered_tokens(self, filtered_tokens: List[str]):
        """
        Saves filtered tokens to a specified file.
        
        :param filtered_tokens: List of tokens that passed the volume filter.
        """
        try:
            with open(self.save_filtered_tokens, "w") as file:
                for token in filtered_tokens:
                    file.write(f"{token}\n")
            self.logger.info(
                "Filtered tokens saved to file: %s", self.save_filtered_tokens
            )
        except Exception as e:
            self.logger.error(
                "Failed to save filtered tokens to file: %s. Error: %s",
                self.save_filtered_tokens, str(e)
            )
