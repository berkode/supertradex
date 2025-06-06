"""
Liquidity filter module for analyzing token liquidity metrics.
"""

import logging
import json
from typing import Dict, List, Any, Optional
from config.settings import Settings

logger = logging.getLogger(__name__)

class LiquidityFilter:
    """
    Ensures tokens have sufficient liquidity for safe trading.
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        logging_level: int = logging.INFO,
        save_results_to: str = None,
        save_format: str = "json",
    ):
        """
        Initializes the LiquidityFilter.

        :param settings: Settings instance to get configuration from.
        :param logging_level: Logging level for the logger.
        :param save_results_to: Optional file path to save flagged tokens for reporting.
        :param save_format: Format for saving flagged tokens ("json" or "txt").
        """
        if save_format not in {"json", "txt"}:
            raise ValueError("save_format must be either 'json' or 'txt'.")

        self.settings = settings or Settings()
        self.min_liquidity_threshold = self.settings.MIN_LIQUIDITY_THRESHOLD
        self.min_liquidity_ratio = self.settings.MIN_LIQUIDITY_RATIO
        self.save_results_to = save_results_to
        self.save_format = save_format

        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging_level)
        self.logger.info(
            "LiquidityFilter initialized with thresholds: Liquidity: %.2f, Liquidity Ratio: %.2f.",
            self.min_liquidity_threshold,
            self.min_liquidity_ratio,
        )

    async def analyze_token(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyzes a token for liquidity risks.
        NOTE: Made async to be callable directly from FilterManager.

        :param token_data: A dictionary containing token details:
                           - 'symbol': Token symbol or address.
                           - 'liquidity': Current liquidity value (e.g., in USD).
                           - 'market_cap': Market capitalization of the token.
        :return: A dictionary with the analysis result, including flagged status and detected risks.
        """
        symbol = token_data.get("symbol", "Unknown")
        liquidity_data = token_data.get("liquidity", {})
        # Extract the USD value safely
        liquidity = liquidity_data.get("usd", 0.0) if isinstance(liquidity_data, dict) else 0.0
        market_cap_data = token_data.get("marketCap", {}) # Assuming key might be marketCap
        market_cap = market_cap_data.get("usd", 0.0) if isinstance(market_cap_data, dict) else 0.0
        # Fallback if marketCap key is missing
        if market_cap == 0.0:
            market_cap = token_data.get("market_cap", 0.0) # Try 'market_cap'
            if isinstance(market_cap, dict):
                market_cap = market_cap.get("usd", 0.0) # Try getting usd from this dict too
            elif not isinstance(market_cap, (float, int)):
                 market_cap = 0.0 # Ensure it's a number

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

    async def analyze_and_annotate(self, tokens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Analyzes a list of tokens for liquidity risks and annotates them.

        Args:
            tokens: A list of token dictionaries. Expected keys: 'symbol', 'liquidity', 'market_cap'.
        
        Returns:
            The list of tokens, annotated with liquidity analysis results.
        """
        if not tokens:
            self.logger.warning("No token data provided for liquidity analysis.")
            return []

        annotated_tokens = []
        analysis_key = "liquidity_analysis"
        flagged_count = 0
        self.logger.info(f"Applying LiquidityFilter analysis to {len(tokens)} tokens.")

        for token_data in tokens:
            # analyze_token already handles missing keys safely and returns a dict
            analysis_result = await self.analyze_token(token_data) 
            # Add the result under the analysis key
            token_data[analysis_key] = analysis_result 
            
            if analysis_result.get("flagged", False):
                flagged_count += 1
                
            annotated_tokens.append(token_data)

        self.logger.info(
            "Liquidity analysis complete. %d tokens flagged out of %d analyzed.",
            flagged_count, len(annotated_tokens),
        )

        # Saving logic commented out
        # if self.save_results_to:
        #     # Potentially save only flagged tokens or all annotations?
        #     flagged_token_results = [t[analysis_key] for t in annotated_tokens if t[analysis_key]["flagged"]]
        #     self._save_results(flagged_token_results)

        return annotated_tokens

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

    async def filter_tokens(self, tokens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Filter tokens based on liquidity metrics.
        
        Args:
            tokens: List of tokens to filter
            
        Returns:
            List of tokens that passed the liquidity filter
        """
        filtered_tokens = []
        
        for token in tokens:
            try:
                # Get liquidity metrics
                liquidity = token.get("liquidity", 0)
                liquidity_ratio = token.get("liquidity_ratio", 0)
                
                # Check if liquidity meets minimum requirements
                if liquidity < self.settings.MIN_LIQUIDITY:
                    logger.info(f"Token {token['address']} failed liquidity filter: liquidity {liquidity} < {self.settings.MIN_LIQUIDITY}")
                    continue
                    
                if liquidity_ratio < self.settings.MIN_LIQUIDITY_RATIO:
                    logger.info(f"Token {token['address']} failed liquidity filter: liquidity ratio {liquidity_ratio} < {self.settings.MIN_LIQUIDITY_RATIO}")
                    continue
                    
                filtered_tokens.append(token)
                logger.info(f"Token {token['address']} passed liquidity filter with liquidity {liquidity} and ratio {liquidity_ratio}")
                
            except Exception as e:
                logger.error(f"Error filtering token {token['address']} with liquidity filter: {str(e)}")
                continue
                
        return filtered_tokens
