import os
import time
import random
import logging
from typing import Optional, Dict, List
from datetime import datetime, timezone
from dotenv import load_dotenv
from utils.logger import get_logger

# Get logger for this module
logger = get_logger(__name__)

class ProxyManager:
    def __init__(self):
        self.logger = logger
        load_dotenv("config/.env")
        
        self.proxy_list_file = os.getenv('PROXY_LIST_FILE', 'config/proxies.txt')
        self.rotation_interval = int(os.getenv('PROXY_ROTATION_INTERVAL', '300'))
        self.max_failures = int(os.getenv('MAX_PROXY_FAILURES', '3'))
        self.timeout = int(os.getenv('PROXY_TIMEOUT', '30'))
        
        self.proxies: List[Dict] = []
        self.current_proxy: Optional[Dict] = None
        self.last_rotation: Optional[datetime] = None
        self.proxy_failures: Dict[str, int] = {}
        
    async def initialize(self) -> bool:
        """
        Initialize the proxy manager.
        
        Returns:
            bool: True if initialization was successful, False otherwise
        """
        try:
            self.logger.info("Initializing ProxyManager")
            self._load_proxies()
            self.logger.info(f"ProxyManager initialized with {len(self.proxies)} proxies")
            return True
        except Exception as e:
            self.logger.error(f"Error initializing ProxyManager: {e}")
            # Still return True to allow application to continue
            return True
    
    def _load_proxies(self) -> None:
        """Load proxies from the proxy list file."""
        try:
            if not os.path.exists(self.proxy_list_file):
                self.logger.warning(f"Proxy list file not found: {self.proxy_list_file}")
                return
                
            with open(self.proxy_list_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        try:
                            # Expected format: protocol://username:password@host:port
                            protocol, rest = line.split('://')
                            auth, host_port = rest.split('@')
                            username, password = auth.split(':')
                            host, port = host_port.split(':')
                            
                            proxy = {
                                'protocol': protocol,
                                'username': username,
                                'password': password,
                                'host': host,
                                'port': port,
                                'url': line,
                                'failures': 0
                            }
                            self.proxies.append(proxy)
                        except Exception as e:
                            self.logger.error(f"Error parsing proxy line: {line}, Error: {e}")
                            
            self.logger.info(f"Loaded {len(self.proxies)} proxies from {self.proxy_list_file}")
            
        except Exception as e:
            self.logger.error(f"Error loading proxies: {e}")
    
    def get_proxy(self) -> Optional[Dict]:
        """Get a working proxy, rotating if necessary."""
        current_time = datetime.now(timezone.utc)
        
        # Check if we need to rotate
        if (self.last_rotation is None or 
            (current_time - self.last_rotation).total_seconds() >= self.rotation_interval):
            self._rotate_proxy()
        
        # If current proxy has too many failures, rotate
        if self.current_proxy and self.current_proxy['failures'] >= self.max_failures:
            self._rotate_proxy()
        
        return self.current_proxy
    
    def _rotate_proxy(self) -> None:
        """Rotate to a new proxy from the pool."""
        if not self.proxies:
            self.logger.warning("No proxies available")
            return
            
        # Filter out failed proxies
        available_proxies = [p for p in self.proxies if p['failures'] < self.max_failures]
        
        if not available_proxies:
            self.logger.warning("No working proxies available")
            return
            
        # Select a random proxy from available ones
        self.current_proxy = random.choice(available_proxies)
        self.last_rotation = datetime.now(timezone.utc)
        self.logger.info(f"Rotated to new proxy: {self.current_proxy['host']}")
    
    def mark_proxy_failure(self, proxy: Dict) -> None:
        """Mark a proxy as failed and increment its failure count."""
        if proxy in self.proxies:
            proxy['failures'] += 1
            self.logger.warning(f"Proxy {proxy['host']} failed {proxy['failures']} times")
            
            if proxy['failures'] >= self.max_failures:
                self.logger.error(f"Proxy {proxy['host']} has reached max failures")
                self._rotate_proxy()
    
    def get_proxy_url(self) -> Optional[str]:
        """Get the current proxy URL."""
        proxy = self.get_proxy()
        return proxy['url'] if proxy else None
    
    def get_proxy_dict(self) -> Optional[Dict]:
        """Get the current proxy as a dictionary for requests/aiohttp."""
        proxy = self.get_proxy()
        if not proxy:
            return None
            
        return {
            'http': proxy['url'],
            'https': proxy['url']
        }
        
    async def close(self):
        """
        Close the proxy manager and clean up resources.
        """
        try:
            # Nothing to close, but keeping the pattern consistent
            self.logger.info("ProxyManager resources closed")
        except Exception as e:
            self.logger.error(f"Error closing ProxyManager: {e}")