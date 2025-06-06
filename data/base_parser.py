"""
Base parser class for DEX-specific blockchain data parsing
Provides common interface for all DEX parsers
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import logging

class DexParser(ABC):
    """
    Abstract base class for DEX-specific parsers
    Defines the interface that all DEX parsers must implement
    """
    
    def __init__(self, settings, logger: Optional[logging.Logger] = None):
        """
        Initialize the parser with settings and logger
        
        Args:
            settings: Application settings object
            logger: Logger instance for this parser
        """
        self.settings = settings
        self.logger = logger or logging.getLogger(self.__class__.__name__)
        
    @abstractmethod
    def parse_swap_logs(self, logs: List[str], signature: str = None) -> Optional[Dict[str, Any]]:
        """
        Parse swap transaction logs to extract price and trading information
        
        Args:
            logs: List of log strings from the transaction
            signature: Transaction signature for context (optional)
            
        Returns:
            Optional[Dict]: Parsed swap information with price, amounts, etc., or None if no swap found
        """
        pass

    @abstractmethod 
    def parse_account_update(self, raw_data: Any, pool_address: str = None) -> Optional[Dict[str, Any]]:
        """
        Parse account state update data to extract current pool state
        
        Args:
            raw_data: Raw account data (base64 string or decoded bytes)
            pool_address: Pool address for context (optional)
            
        Returns:
            Optional[Dict]: Parsed account state with price, liquidity, etc., or None if parsing failed
        """
        pass
    
    def get_dex_id(self) -> str:
        """
        Get the DEX identifier for this parser
        
        Returns:
            str: DEX identifier (e.g., 'raydium_v4', 'pumpswap')
        """
        return getattr(self, 'DEX_ID', self.__class__.__name__.lower().replace('parser', ''))
        
    def validate_logs(self, logs: List[str]) -> bool:
        """
        Basic validation that logs are non-empty and contain strings
        
        Args:
            logs: List of log strings to validate
            
        Returns:
            bool: True if logs are valid for parsing
        """
        return bool(logs) and all(isinstance(log, str) for log in logs) 