import logging
from typing import Dict, List, Any
from config.settings import Settings


class DumpFilter:
    """
    Detects dump risks in tokens using a combination of key risk indicators and the dump score.
    """

    def __init__(
        self,
        settings: Settings,
        logging_level: int = logging.INFO
    ):
        """
        Initializes the DumpFilter.

        :param settings: Application settings containing threshold values
        :param logging_level: Logging level for the logger
        """
        self.settings = settings
        self.dump_score_threshold = settings.DUMP_SCORE_THRESHOLD
        self.dev_wallet_activity_threshold = settings.DEV_WALLET_ACTIVITY_THRESHOLD

        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging_level)
        self.logger.info(
            "DumpFilter initialized with thresholds: Dump Score: %.2f, Dev Wallet Activity: %.2f.",
            self.dump_score_threshold, self.dev_wallet_activity_threshold
        )

    async def analyze_token(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyzes a token for dump risks based on its dump score and key risk indicators.
        NOTE: Made async to be callable directly from FilterManager.

        :param token_data: A dictionary containing token details:
                           - 'symbol': Token symbol or address.
                           - 'dump_score': A pre-calculated score (0-100) indicating risk level.
                           - 'liquidity_lock': Boolean indicating if liquidity is locked.
                           - 'ownership_renounced': Boolean indicating if ownership is renounced.
                           - 'dev_wallet_activity': A risk score (0-100) for developer wallet activity.
        :return: A dictionary with the analysis result, including flagged status and detected risks.
        """
        mint = token_data.get("mint", "UNKNOWN_MINT")
        dump_score = token_data.get("dump_score", 0.0)
        liquidity_lock = token_data.get("liquidity_lock", False)
        ownership_renounced = token_data.get("ownership_renounced", False)
        dev_wallet_activity = token_data.get("dev_wallet_activity", 0.0)

        flagged = False
        detected_risks = []

        # Check dump score
        if dump_score < self.dump_score_threshold:
            detected_risks.append("low_dump_score")
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
            "Token %s analyzed: Flagged=%s, Risks=%s",
            mint,
            flagged,
            detected_risks,
        )

        return {
            "mint": mint,
            "flagged": flagged,
            "detected_risks": detected_risks,
        }

    async def filter_tokens(self, tokens_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Filters a list of tokens for dump risks.

        :param tokens_data: A list of dictionaries where each dictionary represents a token.
        :return: A list of tokens that passed the filter (not flagged for dump risk).
        """
        if not tokens_data:
            self.logger.warning("No token data provided for filtering.")
            return []

        filtered_tokens = []
        for token_data in tokens_data:
            # Await the async analyze_token call
            analysis_result = await self.analyze_token(token_data)
            # Add the analysis to the token data
            token_data["dump_analysis"] = analysis_result
            
            # Only keep tokens that aren't flagged as risky
            if not analysis_result["flagged"]:
                filtered_tokens.append(token_data)

        self.logger.info(
            "Dump filtering complete. %d tokens passed out of %d analyzed.",
            len(filtered_tokens), len(tokens_data)
        )

        return filtered_tokens

    async def analyze_and_annotate(self, tokens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Analyzes a list of tokens for dump risks and annotates them with risk information.
        Does not filter out tokens, only adds risk analysis data.

        :param tokens: A list of dictionaries where each dictionary represents a token.
        :return: The same list of tokens with added dump risk analysis data.
        """
        if not tokens:
            self.logger.warning("No token data provided for analysis.")
            return []

        for token in tokens:
            # Await the async analyze_token call
            analysis_result = await self.analyze_token(token)
            token["dump_analysis"] = analysis_result

        self.logger.info("Dump risk analysis complete for %d tokens.", len(tokens))
        return tokens