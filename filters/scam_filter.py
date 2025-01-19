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

    def analyze_contract(self, contract_data: Dict[str, any]) -> Dict[str, any]:
        """
        Analyzes a single smart contract for scam patterns.

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

    def filter_contracts(self, contracts_data: List[Dict[str, any]]) -> List[Dict[str, any]]:
        """
        Filters a list of smart contracts for potential scams.

        :param contracts_data: A list of dictionaries where each dictionary represents a contract.
        :return: A list of flagged contracts with their analysis results.
        """
        if not contracts_data:
            self.logger.warning("No contract data provided for filtering.")
            return []

        flagged_contracts = []
        for contract_data in contracts_data:
            analysis_result = self.analyze_contract(contract_data)
            if analysis_result["flagged"]:
                flagged_contracts.append(analysis_result)

        self.logger.info(
            "Scam filtering complete. %d contracts flagged out of %d analyzed.",
            len(flagged_contracts), len(contracts_data)
        )

        return flagged_contracts
