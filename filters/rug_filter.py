import logging
from typing import Dict, List, Any


class RugPullFilter:
    """
    Detects rug-pull risks in tokens using a combination of key risk indicators and the rug pull score.
    """

    def __init__(
        self,
        rug_pull_score_threshold: float,
        dev_wallet_activity_threshold: float = 50.0,
        logging_level: int = logging.INFO,
        save_results_to: str = None,
    ):
        """
        Initializes the RugPullFilter.

        :param rug_pull_score_threshold: Minimum acceptable rug pull score. Tokens with scores below this
                                         are flagged as high risk.
        :param dev_wallet_activity_threshold: Maximum allowed developer wallet activity score (0-100).
        :param logging_level: Logging level for the logger.
        :param save_results_to: Optional file path to save flagged tokens for reporting.
        """
        if not (0 <= rug_pull_score_threshold <= 100):
            raise ValueError("rug_pull_score_threshold must be between 0 and 100.")
        if not (0 <= dev_wallet_activity_threshold <= 100):
            raise ValueError("dev_wallet_activity_threshold must be between 0 and 100.")

        self.rug_pull_score_threshold = rug_pull_score_threshold
        self.dev_wallet_activity_threshold = dev_wallet_activity_threshold
        self.save_results_to = save_results_to

        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging_level)
        self.logger.info(
            "RugPullFilter initialized with thresholds: Rug Pull Score: %.2f, Dev Wallet Activity: %.2f.",
            self.rug_pull_score_threshold, self.dev_wallet_activity_threshold
        )

    def analyze_token(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyzes a token for rug-pull risks based on its rug pull score and key risk indicators.

        :param token_data: A dictionary containing token details:
                           - 'symbol': Token symbol or address.
                           - 'rug_pull_score': A pre-calculated score (0-100) indicating risk level.
                           - 'liquidity_lock': Boolean indicating if liquidity is locked.
                           - 'ownership_renounced': Boolean indicating if ownership is renounced.
                           - 'dev_wallet_activity': A risk score (0-100) for developer wallet activity.
        :return: A dictionary with the analysis result, including flagged status and detected risks.
        """
        symbol = token_data.get("symbol", "Unknown")
        rug_pull_score = token_data.get("rug_pull_score", 0.0)
        liquidity_lock = token_data.get("liquidity_lock", False)
        ownership_renounced = token_data.get("ownership_renounced", False)
        dev_wallet_activity = token_data.get("dev_wallet_activity", 0.0)

        flagged = False
        detected_risks = []

        # Check rug pull score
        if rug_pull_score < self.rug_pull_score_threshold:
            detected_risks.append("low_rug_pull_score")
            flagged = True

        # Check liquidity lock
        if not liquidity_lock:
            detected_risks.append("no_liquidity_lock")
            flagged = True

        # Check ownership renouncement
        if not ownership_renounced:
            detected_risks.append("non_renounced_ownership")
            flagged = True

        # Check developer wallet activity
        if dev_wallet_activity > self.dev_wallet_activity_threshold:
            detected_risks.append("high_dev_wallet_activity")
            flagged = True

        self.logger.info(
            "Token '%s' analyzed: Flagged=%s, Risks=%s",
            symbol,
            flagged,
            detected_risks,
        )

        return {
            "symbol": symbol,
            "flagged": flagged,
            "detected_risks": detected_risks,
        }

    def filter_tokens(self, tokens_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Filters a list of tokens for rug-pull risks.

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
            "Rug-pull filtering complete. %d tokens flagged out of %d analyzed.",
            len(flagged_tokens), len(tokens_data)
        )

        if self.save_results_to:
            self._save_results(flagged_tokens)

        return flagged_tokens

    def _save_results(self, flagged_tokens: List[Dict[str, Any]]):
        """
        Saves flagged tokens to a specified file for reporting.

        :param flagged_tokens: List of flagged tokens.
        """
        try:
            with open(self.save_results_to, "w") as file:
                for token in flagged_tokens:
                    file.write(f"{token['symbol']}: {token}\n")
            self.logger.info("Flagged tokens saved to file: %s", self.save_results_to)
        except Exception as e:
            self.logger.error(
                "Failed to save flagged tokens to file: %s. Error: %s",
                self.save_results_to, str(e)
            )
