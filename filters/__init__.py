"""
Filters package for token filtering and verification.
"""

import logging
from typing import Optional, List, Dict, Any
from config.settings import Settings
from data.token_database import TokenDatabase
from config.rugcheck_api import RugcheckAPI
from .solsniffer_api import SolsnifferAPI
from .twitter_api import TwitterAPI
from .twitter_check import TwitterCheck
from .volume_filter import VolumeFilter
from .liquidity_filter import LiquidityFilter
from .whale_filter import WhaleFilter
from .moonshot_filter import MoonshotFilter
from .dump_filter import DumpFilter
from .scam_filter import ScamFilter
from .whitelist import Whitelist, WhitelistFilter
from .blacklist import Blacklist
from .bonding_curve import BondingCurveCalculator
from .social_filter import SocialFilter
from .rugcheck_filter import RugcheckFilter
from .filter_manager import FilterManager

logger = logging.getLogger(__name__)

class FiltersPackage:
    """Main class for managing all filter-related components."""
    
    def __init__(self, settings: Settings, data_package: Any):
        """
        Initialize the filters package.
        Args:
            settings: Application settings
            data_package: Data package instance containing token database and other components
        """
        self.settings = settings
        self.data_package = data_package
        
        # Initialize API clients
        self.rugcheck_api = RugcheckAPI(settings=settings)
        self.solsniffer_api = SolsnifferAPI(settings=settings)
        self.twitter_api = TwitterAPI()  # TwitterAPI gets settings internally
        self.twitter_check = TwitterCheck()  # TwitterCheck gets settings internally
        
        # Initialize filters
        self.scam_filter = ScamFilter()  # Only needs optional logging_level
        self.volume_filter = VolumeFilter(settings=settings)
        self.social_filter = SocialFilter(
            twitter_api=self.twitter_api,
            twitter_check=self.twitter_check
        )
        self.rugcheck_filter = RugcheckFilter(
            rugcheck_api=self.rugcheck_api,
            settings=settings
        )
        
    async def apply_filters(self, tokens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Apply all filters to the given tokens.
        
        Args:
            tokens: List of tokens to filter
            
        Returns:
            List of tokens that passed all filters
        """
        # Apply scam filter
        tokens = await self.scam_filter.analyze_and_annotate(tokens)
        
        # Apply volume filter
        tokens = await self.volume_filter.filter_tokens(tokens)
        
        # Apply social filter
        tokens = await self.social_filter.filter_tokens(tokens)
        
        # Apply rugcheck filter
        tokens = await self.rugcheck_filter.filter_tokens(tokens)
        
        return tokens

#__all__ = ['FiltersPackage'] # Keep this commented or remove if FiltersPackage is unused

# Add FilterManager, TwitterCheck, WhitelistFilter, RugcheckFilter to __all__
__all__ = ['FiltersPackage', 'FilterManager', 'TwitterCheck', 'WhitelistFilter', 'RugcheckFilter']
