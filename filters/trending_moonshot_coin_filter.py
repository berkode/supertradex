import logging
import json
from typing import Dict, List, Optional


class TrendingMoonshotCoinFilter:
    """
    Filters coins based on trending criteria, identifying those with potential for moonshots.
    """

    def __init__(
        self,
        min_volume_threshold: float,
        min_trending_score: float,
        min_price_change_percent: float,
        logging_level: int = logging.INFO,
        save_filtered_coins: Optional[str] = None,
        save_format: str = "json",
    ):
        """
        Initializes the TrendingMoonshotCoinFilter.

        :param min_volume_threshold: Minimum trading volume required for a coin to be considered.
        :param min_trending_score: Minimum trending score required for a coin to qualify.
        :param min_price_change_percent: Minimum percentage price change required.
        :param logging_level: Logging level for the logger.
        :param save_filtered_coins: Optional file path to save the filtered coins.
        :param save_format: File format for saving filtered coins ("json" or "txt").
        """
        if min_volume_threshold <= 0 or min_trending_score <= 0 or min_price_change_percent <= 0:
            raise ValueError("All thresholds must be positive values.")
        if save_format not in {"json", "txt"}:
            raise ValueError("save_format must be either 'json' or 'txt'.")

        self.min_volume_threshold = min_volume_threshold
        self.min_trending_score = min_trending_score
        self.min_price_change_percent = min_price_change_percent
        self.save_filtered_coins = save_filtered_coins
        self.save_format = save_format

        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging_level)
        self.logger.info(
            "TrendingMoonshotCoinFilter initialized with thresholds - "
            "Volume: %.2f, Trending Score: %.2f, Price Change: %.2f%%.",
            self.min_volume_threshold, self.min_trending_score, self.min_price_change_percent
        )

    def filter_coins(self, coins_data: List[Dict]) -> List[Dict]:
        """
        Filters coins based on trending moonshot criteria.

        :param coins_data: A list of dictionaries where each dictionary represents a coin with keys:
                           - 'symbol': Coin symbol or address.
                           - 'volume': Trading volume of the coin.
                           - 'trending_score': A calculated trending score for the coin.
                           - 'price_change_percent': Price change percentage over a given period.
        :return: A list of dictionaries for coins that meet all criteria.
        """
        if not coins_data:
            self.logger.warning("No coin data provided for filtering.")
            return []

        filtered_coins = []
        for coin in coins_data:
            symbol = coin.get("symbol", "Unknown")
            volume = coin.get("volume", 0.0)
            trending_score = coin.get("trending_score", 0.0)
            price_change_percent = coin.get("price_change_percent", 0.0)

            if (
                volume >= self.min_volume_threshold
                and trending_score >= self.min_trending_score
                and price_change_percent >= self.min_price_change_percent
            ):
                filtered_coins.append(coin)
                self.logger.debug(
                    "Coin '%s' passed all filters (Volume: %.2f, Trending Score: %.2f, Price Change: %.2f%%).",
                    symbol, volume, trending_score, price_change_percent
                )
            else:
                self.logger.warning(
                    "Coin '%s' excluded (Volume: %.2f, Trending Score: %.2f, Price Change: %.2f%%).",
                    symbol, volume, trending_score, price_change_percent
                )

        self.logger.info(
            "Trending coin filtering complete. %d coins passed the filter.", len(filtered_coins)
        )

        if self.save_filtered_coins:
            self._save_filtered_coins(filtered_coins)

        return filtered_coins

    def _save_filtered_coins(self, filtered_coins: List[Dict]):
        """
        Saves filtered coins to a specified file.

        :param filtered_coins: List of coins that passed the filters.
        """
        if not self.save_filtered_coins:
            return

        try:
            if self.save_format == "json":
                with open(self.save_filtered_coins, "w") as file:
                    json.dump(filtered_coins, file, indent=4)
                self.logger.info(
                    "Filtered coins saved to JSON file: %s", self.save_filtered_coins
                )
            elif self.save_format == "txt":
                with open(self.save_filtered_coins, "w") as file:
                    for coin in filtered_coins:
                        file.write(f"{coin['symbol']}: {coin}\n")
                self.logger.info(
                    "Filtered coins saved to TXT file: %s", self.save_filtered_coins
                )
        except Exception as e:
            self.logger.error(
                "Failed to save filtered coins to file: %s. Error: %s",
                self.save_filtered_coins, str(e)
            )
