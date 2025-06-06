import logging
from typing import Dict, List


class ScamFilter:
    """
    Scans smart contract data for known scam patterns such as mint functions, hidden fees,
    burnt liquidity, or suspicious developer wallets.
    """

    def __init__(self, logging_level: int = logging.INFO):
        """
        Initializes the ScamFilter.

        :param logging_level: Logging level for the logger.
        """
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging_level)
        self.scam_patterns = [
            "mint_function",      # Indicates presence of unrestricted mint functions
            "hidden_fees",        # Indicates contracts with undisclosed fees
            "burnt_liquidity",    # Indicates liquidity that cannot be recovered
            "dev_wallet_control", # Indicates excessive control by developer wallets
        ]
        self.logger.info("ScamFilter initialized with %d known patterns.", len(self.scam_patterns))

    async def analyze_contract(self, contract_data: Dict[str, any]) -> Dict[str, any]:
        """
        Analyzes a single smart contract for scam patterns.
        NOTE: Made async to be callable from async analyze_and_annotate without blocking.

        :param contract_data: A dictionary containing the contract data:
                              - 'address': Smart contract address
                              - 'code': Smart contract source code
                              - 'deployer_wallet': Deployer wallet address
                              - 'audit_reports': List of any external audit results
        :return: A dictionary with the analysis result, including a flagged status and detected patterns.
        """
        flagged = False
        detected_patterns = []

        # Check for unrestricted mint function
        if "mint" in contract_data.get("code", "").lower():
            detected_patterns.append("mint_function")
            flagged = True

        # Check for hidden fees
        if "fee" in contract_data.get("code", "").lower() and "hidden" in contract_data.get("code", "").lower():
            detected_patterns.append("hidden_fees")
            flagged = True

        # Check for burnt liquidity
        if "burn" in contract_data.get("code", "").lower() and "liquidity" in contract_data.get("code", "").lower():
            detected_patterns.append("burnt_liquidity")
            flagged = True

        # Check for excessive developer wallet control
        if "deployer" in contract_data.get("code", "").lower() and "control" in contract_data.get("code", "").lower():
            detected_patterns.append("dev_wallet_control")
            flagged = True

        # Include audit findings if available
        if contract_data.get("audit_reports"):
            for report in contract_data["audit_reports"]:
                if "scam" in report.lower() or "issue" in report.lower():
                    detected_patterns.append("audit_flagged")
                    flagged = True

        self.logger.info(
            "Contract '%s' analyzed: Flagged=%s, Patterns=%s",
            contract_data.get("address", "Unknown"),
            flagged,
            detected_patterns,
        )

        return {
            "address": contract_data.get("address", "Unknown"),
            "flagged": flagged,
            "detected_patterns": detected_patterns,
        }

    async def analyze_and_annotate(self, tokens: List[Dict[str, any]]) -> List[Dict[str, any]]:
        """
        Analyzes a list of tokens for potential scams based on contract data and annotates them.

        Args:
            tokens: A list of token dictionaries. Expects contract data under 'contract_data'.
        
        Returns:
            The list of tokens, annotated with scam analysis results.
        """
        if not tokens:
            self.logger.warning("No token data provided for scam analysis.")
            return []

        annotated_tokens = []
        analysis_key = "scam_analysis"
        flagged_count = 0
        self.logger.info(f"Applying ScamFilter analysis to {len(tokens)} tokens.")

        for token_data in tokens:
            mint = token_data.get('mint', 'Unknown')
            # Assume contract data is available in the token dictionary
            contract_data = token_data.get('contract_data') # Adjust key if necessary

            if isinstance(contract_data, dict):
                # Await the async analyze_contract call
                analysis_result = await self.analyze_contract(contract_data) 
                # Add the result under the analysis key
                token_data[analysis_key] = analysis_result
                if analysis_result.get("flagged", False):
                    flagged_count += 1
            else:
                self.logger.warning(f"Missing or invalid 'contract_data' for token {mint}. Skipping scam analysis.")
                token_data[analysis_key] = {"flagged": None, "status": "skipped_missing_data"}
                
            annotated_tokens.append(token_data)

        self.logger.info(
            "Scam analysis complete. %d tokens flagged out of %d analyzed.",
            flagged_count, len(annotated_tokens),
        )

        # No saving logic in the original filter
        return annotated_tokens
