"""
Volume filter module for analyzing token volume metrics.
"""

import logging
from typing import Dict, Any, List, Optional
from config.settings import Settings

logger = logging.getLogger(__name__)

class VolumeFilter:
    """Filter for analyzing token volume metrics."""
    
    def __init__(self, settings: Settings):
        """
        Initialize the volume filter.
        
        Args:
            settings: Application settings
        """
        self.settings = settings
        logger.info("Volume filter initialized")
        
    async def analyze_token(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyzes a single token for volume requirements.

        Args:
            token_data: Dictionary containing token info (volume_24h, volume_5m).

        Returns:
            Dict with analysis results: {'flagged': bool, 'reason': str, 'volume_24h': float, 'volume_5m': float}
        """
        analysis_result = {'flagged': False, 'reason': 'passed'}
        try:
            address = token_data.get('address', 'UNKNOWN')
            volume_24h = token_data.get("volume_24h", 0)
            volume_5m = token_data.get("volume_5m", 0)
            analysis_result['volume_24h'] = volume_24h
            analysis_result['volume_5m'] = volume_5m

            min_vol_24h = self.settings.MIN_VOLUME_24H
            min_vol_5m = self.settings.MIN_VOLUME_5M

            if volume_24h < min_vol_24h:
                logger.debug(f"Token {address} failed volume check: 24h volume {volume_24h} < {min_vol_24h}")
                analysis_result['flagged'] = True
                analysis_result['reason'] = f'volume_24h_too_low ({volume_24h} < {min_vol_24h})'
                return analysis_result # Exit early on first failure

            if volume_5m < min_vol_5m:
                logger.debug(f"Token {address} failed volume check: 5m volume {volume_5m} < {min_vol_5m}")
                analysis_result['flagged'] = True
                analysis_result['reason'] = f'volume_5m_too_low ({volume_5m} < {min_vol_5m})'
                return analysis_result # Exit early on first failure

            logger.debug(f"Token {address} passed volume check.")
            return analysis_result

        except Exception as e:
            logger.error(f"Error analyzing volume for token {token_data.get('address', 'UNKNOWN')}: {e}", exc_info=True)
            analysis_result['flagged'] = True # Flag on error
            analysis_result['reason'] = f'analysis_error: {e}'
            return analysis_result
        
    async def filter_tokens(self, tokens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Filter tokens based on volume metrics.
        
        Args:
            tokens: List of tokens to filter
            
        Returns:
            List of tokens that passed the volume filter
        """
        filtered_tokens = []
        
        for token in tokens:
            try:
                # Get volume metrics
                volume_24h = token.get("volume_24h", 0)
                volume_5m = token.get("volume_5m", 0)
                
                # Check if volume meets minimum requirements
                if volume_24h < self.settings.MIN_VOLUME_24H:
                    logger.info(f"Token {token['address']} failed volume filter: 24h volume {volume_24h} < {self.settings.MIN_VOLUME_24H}")
                    continue
                    
                if volume_5m < self.settings.MIN_VOLUME_5M:
                    logger.info(f"Token {token['address']} failed volume filter: 5m volume {volume_5m} < {self.settings.MIN_VOLUME_5M}")
                    continue
                    
                filtered_tokens.append(token)
                logger.info(f"Token {token['address']} passed volume filter with 24h volume {volume_24h} and 5m volume {volume_5m}")
                
            except Exception as e:
                logger.error(f"Error filtering token {token['address']} with volume filter: {str(e)}")
                continue
                
        return filtered_tokens
