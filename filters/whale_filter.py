"""
Whale filter module for analyzing token whale metrics.
"""

import logging
from typing import Dict, Any, List, Optional
from config.settings import Settings

logger = logging.getLogger(__name__)

class WhaleFilter:
    """Filter for analyzing token whale metrics."""
    
    def __init__(self, settings: Settings):
        """
        Initialize the whale filter.
        
        Args:
            settings: Application settings
        """
        self.settings = settings
        logger.info("Whale filter initialized")
        
    async def analyze_token(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyzes a single token for whale metric requirements.

        Args:
            token_data: Dictionary containing token info (top_holder_percentage, whale_holdings).

        Returns:
            Dict with analysis results: {'flagged': bool, 'reason': str, ...metrics}
        """
        analysis_result = {'flagged': False, 'reason': 'passed'}
        try:
            mint = token_data.get('mint', 'UNKNOWN_MINT')
            top_holder_percentage = token_data.get("top_holder_percentage", 0)
            whale_holdings = token_data.get("whale_holdings", 0)
            analysis_result['top_holder_percentage'] = top_holder_percentage
            analysis_result['whale_holdings'] = whale_holdings

            max_top_holder = self.settings.MAX_TOP_HOLDER_PERCENTAGE
            max_whale = self.settings.MAX_WHALE_HOLDINGS

            if top_holder_percentage > max_top_holder:
                logger.debug(f"Token {mint} failed whale check: top holder % {top_holder_percentage} > {max_top_holder}")
                analysis_result['flagged'] = True
                analysis_result['reason'] = f'top_holder_percentage_too_high ({top_holder_percentage} > {max_top_holder})'
                return analysis_result # Exit early

            if whale_holdings > max_whale:
                logger.debug(f"Token {mint} failed whale check: whale holdings {whale_holdings} > {max_whale}")
                analysis_result['flagged'] = True
                analysis_result['reason'] = f'whale_holdings_too_high ({whale_holdings} > {max_whale})'
                return analysis_result # Exit early

            logger.debug(f"Token {mint} passed whale check.")
            return analysis_result

        except Exception as e:
            mint = token_data.get('mint', 'UNKNOWN_MINT') # Ensure mint is available for error log
            logger.error(f"Error analyzing whale metrics for token {mint}: {e}", exc_info=True)
            analysis_result['flagged'] = True # Flag on error
            analysis_result['reason'] = f'analysis_error: {e}'
            return analysis_result
            
    async def filter_tokens(self, tokens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Filter tokens based on whale metrics.
        
        Args:
            tokens: List of tokens to filter
            
        Returns:
            List of tokens that passed the whale filter
        """
        filtered_tokens = []
        
        for token in tokens:
            try:
                # Get whale metrics
                mint = token.get('mint', 'UNKNOWN_MINT')
                top_holder_percentage = token.get("top_holder_percentage", 0)
                whale_holdings = token.get("whale_holdings", 0)
                
                # Check if whale metrics meet requirements
                if top_holder_percentage > self.settings.MAX_TOP_HOLDER_PERCENTAGE:
                    logger.info(f"Token {mint} failed whale filter: top holder percentage {top_holder_percentage} > {self.settings.MAX_TOP_HOLDER_PERCENTAGE}")
                    continue
                    
                if whale_holdings > self.settings.MAX_WHALE_HOLDINGS:
                    logger.info(f"Token {mint} failed whale filter: whale holdings {whale_holdings} > {self.settings.MAX_WHALE_HOLDINGS}")
                    continue
                    
                filtered_tokens.append(token)
                logger.info(f"Token {mint} passed whale filter with top holder percentage {top_holder_percentage} and whale holdings {whale_holdings}")
                
            except Exception as e:
                mint = token.get('mint', 'UNKNOWN_MINT') # Ensure mint is available for error log
                logger.error(f"Error filtering token {mint} with whale filter: {str(e)}")
                continue
                
        return filtered_tokens
