import logging
import json
from typing import Dict, List, Any


class LiquidityFilter:
    """
    Ensures tokens have sufficient liquidity for safe trading.
    """

    def __init__(
        self,
        min_liquidity_threshold: float,
        min_liquidity_ratio: float,
        logging_level: int = logging.INFO,
        save_results_to: str = None,
        save_format: str = "json",
    ):
        """
        Initializes the LiquidityFilter.

        :param min_liquidity_threshold: Minimum absolute liquidity required (e.g., in USD).
        :param min_liquidity_ratio: Minimum liquidity-to-market-cap ratio required.
        :param logging_level: Logging level for the logger.
        :param save_results_to: Optional file path to save flagged tokens for reporting.
        :param save_format: Format for saving flagged tokens ("json" or "txt").
        """
        if min_liquidity_threshold <= 0:
            raise ValueError("min_liquidity_threshold must be greater than 0.")
        if not (0 <= min_liquidity_ratio <= 1):
            raise ValueError("min_liquidity_ratio must be between 0 and 1.")
        if save_format not in {"json", "txt"}:
            raise ValueError("save_format must be either 'json' or 'txt'.")

        self.min_liquidity_threshold = min_liquidity_threshold
        self.min_liquidity_ratio = min_liquidity_ratio
        self.save_results_to = save_results_to
        self.save_format = save_format

        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging_level)
        self.logger.info(
            "LiquidityFilter initialized with thresholds: Liquidity: %.2f, Liquidity Ratio: %.2f.",
            self.min_liquidity_threshold,
            self.min_liquidity_ratio,
        )

    def analyze_token(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyzes a token for liquidity risks.

        :param token_data: A dictionary containing token details:
                           - 'symbol': Token symbol or address.
                           - 'liquidity': Current liquidity value (e.g., in USD).
                           - 'market_cap': Market capitalization of the token.
        :return: A dictionary with the analysis result, including flagged status and detected risks.
        """
        symbol = token_data.get("symbol", "Unknown")
        liquidity = token_data.get("liquidity", 0.0)
        market_cap = token_data.get("market_cap", 0.0)

        flagged = False
        detected_risks = []

        # Check minimum liquidity threshold
        if liquidity < self.min_liquidity_threshold:
            detected_risks.append("low_liquidity")
            flagged = True

        # Check liquidity-to-market-cap ratio
        if market_cap > 0 and (liquidity / market_cap) < self.min_liquidity_ratio:
            detected_risks.append("low_liquidity_ratio")
            flagged = True

        self.logger.debug(
            "Token '%s' analyzed: Flagged=%s, Liquidity=%.2f, Market Cap=%.2f, Risks=%s",
            symbol,
            flagged,
            liquidity,
            market_cap,
            detected_risks,
        )

        return {
            "symbol": symbol,
            "liquidity": liquidity,
            "market_cap": market_cap,
            "flagged": flagged,
            "detected_risks": detected_risks,
        }

    def filter_tokens(self, tokens_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Filters a list of tokens for liquidity risks.

        :param tokens_data: A list of dictionaries where each dictionary represents a token.
        :return: A list of flagged tokens with their analysis results.
        """
        if not tokens_data:
            self.logger.warning("No token data provided for filtering.")
            return []

        flagged_tokens = []
        for token_data in tokens_data:
            analysis_result = self.analyze_token(token_data)
            if analysis_result["flagged"]:
                flagged_tokens.append(analysis_result)

        self.logger.info(
            "Liquidity filtering complete. %d tokens flagged out of %d analyzed.",
            len(flagged_tokens), len(tokens_data),
        )

        if self.save_results_to:
            self._save_results(flagged_tokens)

        return flagged_tokens

    def _save_results(self, flagged_tokens: List[Dict[str, Any]]):
        """
        Saves flagged tokens to a specified file for reporting.

        :param flagged_tokens: List of flagged tokens.
        """
        if not self.save_results_to:
            return

        try:
            if self.save_format == "json":
                with open(self.save_results_to, "w") as file:
                    json.dump(flagged_tokens, file, indent=4)
                self.logger.info("Flagged tokens saved to JSON file: %s", self.save_results_to)
            elif self.save_format == "txt":
                with open(self.save_results_to, "w") as file:
                    for token in flagged_tokens:
                        file.write(f"{token['symbol']}: {token}\n")
                self.logger.info("Flagged tokens saved to TXT file: %s", self.save_results_to)
        except Exception as e:
            self.logger.error(
                "Failed to save flagged tokens to file: %s. Error: %s",
                self.save_results_to,
                str(e),
            )
