"""
Moonshot filter module for analyzing token moonshot potential.
"""

import logging
from typing import Dict, Any, List, Optional
from config.settings import Settings

logger = logging.getLogger(__name__)

class MoonshotFilter:
    """Filter for analyzing token moonshot potential."""
    
    def __init__(self, settings: Settings):
        """
        Initialize the moonshot filter.
        
        Args:
            settings: Application settings
        """
        self.settings = settings
        logger.info("Moonshot filter initialized")
        
    async def analyze_token(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyzes a single token for moonshot potential requirements.

        Args:
            token_data: Dictionary containing token info (price_change_24h, volume_change_24h, market_cap).

        Returns:
            Dict with analysis results: {'flagged': bool, 'reason': str, ...metrics}
        """
        analysis_result = {'flagged': False, 'reason': 'passed'}
        try:
            address = token_data.get('address', 'UNKNOWN')
            price_change_24h = token_data.get("price_change_24h", 0)
            volume_change_24h = token_data.get("volume_change_24h", 0)
            market_cap = token_data.get("market_cap", 0)
            analysis_result['price_change_24h'] = price_change_24h
            analysis_result['volume_change_24h'] = volume_change_24h
            analysis_result['market_cap'] = market_cap

            min_price_chg = self.settings.MIN_PRICE_CHANGE_24H
            min_vol_chg = self.settings.MIN_VOLUME_CHANGE_24H
            max_mc = self.settings.MAX_MARKET_CAP

            if price_change_24h < min_price_chg:
                logger.debug(f"Token {address} failed moonshot check: price change {price_change_24h} < {min_price_chg}")
                analysis_result['flagged'] = True
                analysis_result['reason'] = f'price_change_too_low ({price_change_24h} < {min_price_chg})'
                return analysis_result # Exit early

            if volume_change_24h < min_vol_chg:
                logger.debug(f"Token {address} failed moonshot check: volume change {volume_change_24h} < {min_vol_chg}")
                analysis_result['flagged'] = True
                analysis_result['reason'] = f'volume_change_too_low ({volume_change_24h} < {min_vol_chg})'
                return analysis_result # Exit early

            if market_cap > max_mc:
                logger.debug(f"Token {address} failed moonshot check: market cap {market_cap} > {max_mc}")
                analysis_result['flagged'] = True
                analysis_result['reason'] = f'market_cap_too_high ({market_cap} > {max_mc})'
                return analysis_result # Exit early

            logger.debug(f"Token {address} passed moonshot check.")
            return analysis_result

        except Exception as e:
            logger.error(f"Error analyzing moonshot metrics for token {token_data.get('address', 'UNKNOWN')}: {e}", exc_info=True)
            analysis_result['flagged'] = True # Flag on error
            analysis_result['reason'] = f'analysis_error: {e}'
            return analysis_result
        
    async def filter_tokens(self, tokens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Filter tokens based on moonshot potential.
        
        Args:
            tokens: List of tokens to filter
            
        Returns:
            List of tokens that passed the moonshot filter
        """
        filtered_tokens = []
        
        for token in tokens:
            try:
                # Get moonshot metrics
                price_change_24h = token.get("price_change_24h", 0)
                volume_change_24h = token.get("volume_change_24h", 0)
                market_cap = token.get("market_cap", 0)
                
                # Check if moonshot metrics meet requirements
                if price_change_24h < self.settings.MIN_PRICE_CHANGE_24H:
                    logger.info(f"Token {token['address']} failed moonshot filter: price change {price_change_24h} < {self.settings.MIN_PRICE_CHANGE_24H}")
                    continue
                    
                if volume_change_24h < self.settings.MIN_VOLUME_CHANGE_24H:
                    logger.info(f"Token {token['address']} failed moonshot filter: volume change {volume_change_24h} < {self.settings.MIN_VOLUME_CHANGE_24H}")
                    continue
                    
                if market_cap > self.settings.MAX_MARKET_CAP:
                    logger.info(f"Token {token['address']} failed moonshot filter: market cap {market_cap} > {self.settings.MAX_MARKET_CAP}")
                    continue
                    
                filtered_tokens.append(token)
                logger.info(f"Token {token['address']} passed moonshot filter with price change {price_change_24h}, volume change {volume_change_24h}, and market cap {market_cap}")
                
            except Exception as e:
                logger.error(f"Error filtering token {token['address']} with moonshot filter: {str(e)}")
                continue
                
        return filtered_tokens
