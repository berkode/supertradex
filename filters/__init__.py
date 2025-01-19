"""
Filters Package

This package provides various filters for analyzing tokens, including whitelist, blacklist,
rug pull detection, liquidity checks, scam detection, whale activity, volume thresholds,
and trending coin analysis.

Exports:
    - Whitelist: Manages a list of safe tokens for immediate trading.
    - Blacklist: Manages a list of tokens to avoid.
    - RugPullFilter: Detects rug-pull risks in tokens.
    - LiquidityFilter: Ensures tokens have sufficient liquidity for safe trading.
    - ScamFilter: Scans contract code for known scams.
    - WhaleFilter: Flags tokens with suspicious whale activity.
    - VolumeFilter: Excludes tokens with low trading volume.
    - TrendingMoonshotCoinFilter: Identifies coins with potential for significant upward movement.
"""

import logging
from .whitelist import Whitelist
from .blacklist import Blacklist
from .rug_filter import RugPullFilter
from .liquidity_filter import LiquidityFilter
from .scam_filter import ScamFilter
from .whale_filter import WhaleFilter
from .volume_filter import VolumeFilter
from .trending_moonshot_coin_filter import TrendingMoonshotCoinFilter

# Configure logging for the filters package
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)

# Log the initialization of the filters package
logger = logging.getLogger(__name__)
logger.info("Filters package initialized successfully.")

__all__ = [
    "Whitelist",
    "Blacklist",
    "RugPullFilter",
    "LiquidityFilter",
    "ScamFilter",
    "WhaleFilter",
    "VolumeFilter",
    "TrendingMoonshotCoinFilter",
]
