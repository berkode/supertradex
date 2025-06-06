"""
Centralized Configuration Manager
Enforces environment variable flow: .env → Configuration files → Application code
"""

import os
import time
import logging
from typing import Dict, Any, Optional, List, Union
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum

from utils.logger import get_logger

class ConfigCategory(str, Enum):
    """Configuration categories for organized access"""
    # Core system configuration
    SYSTEM = "system"
    LOGGING = "logging"
    DATABASE = "database"
    
    # API and network configuration  
    API = "api"
    SOLANA = "solana"
    WEBSOCKET = "websocket"
    
    # Trading and strategy configuration
    TRADING = "trading"
    THRESHOLDS = "thresholds"
    FILTERS = "filters"
    RISK_MANAGEMENT = "risk_management"
    
    # Blockchain and DEX configuration
    BLOCKCHAIN = "blockchain"
    DEX = "dex"
    
    # Security and authentication
    SECURITY = "security"
    ENCRYPTION = "encryption"
    
    # Performance and monitoring
    PERFORMANCE = "performance"
    MONITORING = "monitoring"

@dataclass
class ConfigMetadata:
    """Metadata for configuration values"""
    category: ConfigCategory
    description: str
    data_type: type
    required: bool = True
    default_value: Any = None
    validation_fn: Optional[callable] = None
    sensitive: bool = False  # For masking in logs

class ConfigurationManager:
    """
    Centralized configuration management system
    
    Enforces the rule: .env files → Configuration files → Application code
    - Provides single source of truth for all configuration access
    - Handles configuration validation and type conversion
    - Manages configuration metadata and documentation
    - Provides category-based configuration access
    """
    
    def __init__(self, settings=None, logger: Optional[logging.Logger] = None):
        self.logger = logger or get_logger(__name__)
        self.settings = settings
        
        # Configuration registry
        self._config_registry: Dict[str, ConfigMetadata] = {}
        self._config_cache: Dict[str, Any] = {}
        self._last_reload_time = 0
        self._cache_ttl = 300  # 5 minutes cache TTL
        
        # Initialize configuration registry
        self._initialize_config_registry()
        
        # Load initial configuration
        self._load_configuration()
        
        self.logger.info("ConfigurationManager initialized")
    
    def _initialize_config_registry(self):
        """Initialize the configuration registry with metadata"""
        
        # System Configuration
        self._register_config("LOG_LEVEL", ConfigCategory.SYSTEM, 
                            "Logging level for the application", str, True)
        self._register_config("LOG_FILE", ConfigCategory.SYSTEM,
                            "Path to the main log file", str, True)
        self._register_config("ENABLE_CONSOLE_LOGGING", ConfigCategory.SYSTEM,
                            "Enable console logging output", bool, True, True)
        
        # Database Configuration
        self._register_config("DATABASE_URL", ConfigCategory.DATABASE,
                            "Database connection URL", str, True, sensitive=True)
        
        # Solana/Blockchain Configuration
        self._register_config("SOLANA_MAINNET_RPC", ConfigCategory.SOLANA,
                            "Solana mainnet RPC endpoint", str, True)
        self._register_config("SOLANA_MAINNET_WSS", ConfigCategory.SOLANA,
                            "Solana mainnet WebSocket endpoint", str, True)
        self._register_config("HELIUS_RPC_URL", ConfigCategory.SOLANA,
                            "Helius RPC URL for enhanced performance", str, True, sensitive=True)
        self._register_config("HELIUS_WSS_URL", ConfigCategory.SOLANA,
                            "Helius WebSocket URL", str, True, sensitive=True)
        
        # WebSocket Configuration
        self._register_config("WEBSOCKET_DEFAULT_RECONNECT_DELAY", ConfigCategory.WEBSOCKET,
                            "Default reconnection delay in seconds", int, True, 5)
        self._register_config("WEBSOCKET_MAX_RECONNECT_DELAY", ConfigCategory.WEBSOCKET,
                            "Maximum reconnection delay in seconds", int, True, 60)
        self._register_config("WEBSOCKET_PING_INTERVAL", ConfigCategory.WEBSOCKET,
                            "WebSocket ping interval in seconds", int, True, 20)
        self._register_config("WEBSOCKET_PING_TIMEOUT", ConfigCategory.WEBSOCKET,
                            "WebSocket ping timeout in seconds", int, True, 20)
        self._register_config("WEBSOCKET_CONNECT_TIMEOUT", ConfigCategory.WEBSOCKET,
                            "WebSocket connection timeout in seconds", int, True, 10)
        self._register_config("WEBSOCKET_SUBSCRIPTION_TIMEOUT", ConfigCategory.WEBSOCKET,
                            "WebSocket subscription confirmation timeout", int, True, 60)
        self._register_config("WEBSOCKET_MAX_RETRIES_PER_ENDPOINT", ConfigCategory.WEBSOCKET,
                            "Maximum retries per WebSocket endpoint", int, True, 3)
        self._register_config("WEBSOCKET_MAX_MESSAGE_SIZE", ConfigCategory.WEBSOCKET,
                            "Maximum WebSocket message size in bytes", int, False, 10*1024*1024)
        
        # API Configuration
        self._register_config("DEXSCREENER_API_URL", ConfigCategory.API,
                            "DexScreener API base URL", str, True)
        self._register_config("RAYDIUM_API_URL", ConfigCategory.API,
                            "Raydium API base URL", str, True)
        self._register_config("JUPITER_API_ENDPOINT", ConfigCategory.API,
                            "Jupiter API endpoint for swaps", str, True)
        self._register_config("HTTP_TIMEOUT", ConfigCategory.API,
                            "HTTP request timeout in seconds", int, True, 30)
        self._register_config("API_CONCURRENCY_LIMIT", ConfigCategory.API,
                            "Maximum concurrent API requests", int, True, 10)
        
        # Trading Configuration
        self._register_config("TRADE_SIZE", ConfigCategory.TRADING,
                            "Default trade size", float, True)
        self._register_config("MAX_SLIPPAGE_PCT", ConfigCategory.TRADING,
                            "Maximum slippage percentage", float, True)
        self._register_config("STOP_LOSS_PCT", ConfigCategory.TRADING,
                            "Stop loss percentage", float, True)
        self._register_config("TAKE_PROFIT_PCT", ConfigCategory.TRADING,
                            "Take profit percentage", float, True)
        self._register_config("MIN_POSITION_SIZE_USD", ConfigCategory.TRADING,
                            "Minimum position size in USD", float, True)
        self._register_config("MAX_POSITION_SIZE_USD", ConfigCategory.TRADING,
                            "Maximum position size in USD", float, True)
        
        # Risk Management
        self._register_config("RISK_PER_TRADE", ConfigCategory.RISK_MANAGEMENT,
                            "Risk per trade as percentage", float, True)
        self._register_config("MAX_POSITION_SIZE_PCT", ConfigCategory.RISK_MANAGEMENT,
                            "Maximum position size as percentage", float, True)
        self._register_config("DAILY_LOSS_LIMIT", ConfigCategory.RISK_MANAGEMENT,
                            "Daily loss limit", float, False)
        
        # Performance and Monitoring
        self._register_config("MARKETDATA_INTERVAL", ConfigCategory.PERFORMANCE,
                            "Market data update interval in seconds", int, True)
        self._register_config("PRICEMONITOR_INTERVAL", ConfigCategory.PERFORMANCE,
                            "Price monitoring interval in seconds", int, True)
        self._register_config("TOKEN_SCAN_INTERVAL", ConfigCategory.PERFORMANCE,
                            "Token scanning interval in seconds", int, True)
        self._register_config("MONITORING_INTERVAL_SECONDS", ConfigCategory.MONITORING,
                            "General monitoring interval in seconds", int, True)
        
        # Blockchain Listener Configuration
        self._register_config("WS_RECONNECT_DELAY", ConfigCategory.BLOCKCHAIN,
                            "WebSocket reconnection delay for blockchain listener", int, True, 5)
        self._register_config("MAX_LISTEN_RETRIES", ConfigCategory.BLOCKCHAIN,
                            "Maximum retries for blockchain listener", int, True, 10)
        
        # Security Configuration
        self._register_config("ENCRYPTION_KEY_PATH", ConfigCategory.SECURITY,
                            "Path to encryption key file", str, True, sensitive=True)
        self._register_config("USE_PROXIES", ConfigCategory.SECURITY,
                            "Enable proxy usage", bool, False, False)
        self._register_config("PROXY_FILE_PATH", ConfigCategory.SECURITY,
                            "Path to proxy configuration file", str, False)
        
        # Filter Configuration
        self._register_config("FILTER_SCAM_ENABLED", ConfigCategory.FILTERS,
                            "Enable scam token filtering", bool, False, False)
        self._register_config("FILTER_DUMP_ENABLED", ConfigCategory.FILTERS,
                            "Enable dump detection filtering", bool, False, False)
        self._register_config("FILTER_WHALE_ENABLED", ConfigCategory.FILTERS,
                            "Enable whale transaction filtering", bool, False, False)
        self._register_config("FILTER_BLACKLIST_ENABLED", ConfigCategory.FILTERS,
                            "Enable blacklist filtering", bool, False, False)
        self._register_config("FILTER_WHITELIST_ENABLED", ConfigCategory.FILTERS,
                            "Enable whitelist filtering", bool, False, False)
        
        self.logger.info(f"Registered {len(self._config_registry)} configuration parameters")
    
    def _register_config(self, key: str, category: ConfigCategory, description: str, 
                        data_type: type, required: bool = True, default_value: Any = None,
                        validation_fn: callable = None, sensitive: bool = False):
        """Register a configuration parameter with metadata"""
        self._config_registry[key] = ConfigMetadata(
            category=category,
            description=description,
            data_type=data_type,
            required=required,
            default_value=default_value,
            validation_fn=validation_fn,
            sensitive=sensitive
        )
    
    def _load_configuration(self):
        """Load configuration from settings object"""
        if not self.settings:
            self.logger.warning("No settings object provided, cannot load configuration")
            return
        
        loaded_count = 0
        missing_required = []
        
        for key, metadata in self._config_registry.items():
            try:
                # Get value from settings object
                if hasattr(self.settings, key):
                    value = getattr(self.settings, key)
                    
                    # Type conversion and validation
                    if value is not None:
                        converted_value = self._convert_type(value, metadata.data_type, key)
                        
                        # Apply validation if provided
                        if metadata.validation_fn:
                            if not metadata.validation_fn(converted_value):
                                self.logger.error(f"Validation failed for {key}: {converted_value}")
                                continue
                        
                        self._config_cache[key] = converted_value
                        loaded_count += 1
                        
                        # Log loading (mask sensitive values)
                        display_value = "***MASKED***" if metadata.sensitive else converted_value
                        self.logger.debug(f"Loaded config {key} = {display_value}")
                    
                    elif metadata.default_value is not None:
                        self._config_cache[key] = metadata.default_value
                        loaded_count += 1
                        self.logger.debug(f"Using default for {key} = {metadata.default_value}")
                    
                    elif metadata.required:
                        missing_required.append(key)
                        
                elif metadata.default_value is not None:
                    self._config_cache[key] = metadata.default_value
                    loaded_count += 1
                    self.logger.debug(f"Using default for {key} = {metadata.default_value}")
                
                elif metadata.required:
                    missing_required.append(key)
                    
            except Exception as e:
                self.logger.error(f"Error loading configuration {key}: {e}")
                if metadata.required:
                    missing_required.append(key)
        
        # Log results
        if missing_required:
            self.logger.error(f"Missing required configuration parameters: {missing_required}")
        
        self.logger.info(f"Loaded {loaded_count} configuration parameters")
        self._last_reload_time = time.time()
    
    def _convert_type(self, value: Any, target_type: type, key: str) -> Any:
        """Convert value to target type with error handling"""
        try:
            if target_type == bool:
                if isinstance(value, str):
                    return value.lower() in ('true', '1', 'yes', 'on')
                return bool(value)
            elif target_type == int:
                return int(value)
            elif target_type == float:
                return float(value)
            elif target_type == str:
                return str(value)
            else:
                return value
        except (ValueError, TypeError) as e:
            self.logger.error(f"Type conversion failed for {key}: {value} -> {target_type}: {e}")
            raise
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value by key"""
        if key in self._config_cache:
            return self._config_cache[key]
        
        if key in self._config_registry:
            metadata = self._config_registry[key]
            if metadata.default_value is not None:
                return metadata.default_value
        
        if default is not None:
            return default
        
        if key in self._config_registry and self._config_registry[key].required:
            raise ValueError(f"Required configuration parameter '{key}' not found")
        
        return None
    
    def get_by_category(self, category: ConfigCategory) -> Dict[str, Any]:
        """Get all configuration values for a specific category"""
        result = {}
        for key, metadata in self._config_registry.items():
            if metadata.category == category:
                try:
                    result[key] = self.get(key)
                except ValueError:
                    # Skip required parameters that aren't available without settings
                    continue
        return result
    
    def get_websocket_config(self) -> Dict[str, Any]:
        """Get WebSocket-specific configuration"""
        return self.get_by_category(ConfigCategory.WEBSOCKET)
    
    def get_solana_config(self) -> Dict[str, Any]:
        """Get Solana-specific configuration"""
        return self.get_by_category(ConfigCategory.SOLANA)
    
    def get_trading_config(self) -> Dict[str, Any]:
        """Get trading-specific configuration"""
        result = {}
        for key, metadata in self._config_registry.items():
            if metadata.category == ConfigCategory.TRADING:
                try:
                    result[key] = self.get(key)
                except ValueError:
                    # Skip required parameters that aren't available without settings
                    continue
        return result
    
    def get_api_config(self) -> Dict[str, Any]:
        """Get API-specific configuration"""
        return self.get_by_category(ConfigCategory.API)
    
    def get_risk_management_config(self) -> Dict[str, Any]:
        """Get risk management configuration"""
        return self.get_by_category(ConfigCategory.RISK_MANAGEMENT)
    
    def get_monitoring_config(self) -> Dict[str, Any]:
        """Get monitoring and performance configuration"""
        monitoring = self.get_by_category(ConfigCategory.MONITORING)
        performance = self.get_by_category(ConfigCategory.PERFORMANCE)
        return {**monitoring, **performance}
    
    def get_blockchain_config(self) -> Dict[str, Any]:
        """Get blockchain listener configuration"""
        return self.get_by_category(ConfigCategory.BLOCKCHAIN)
    
    def reload_configuration(self) -> bool:
        """Reload configuration from settings"""
        try:
            old_cache = self._config_cache.copy()
            self._config_cache.clear()
            self._load_configuration()
            
            # Check for changes
            changes = []
            for key in set(old_cache.keys()) | set(self._config_cache.keys()):
                old_val = old_cache.get(key)
                new_val = self._config_cache.get(key)
                if old_val != new_val:
                    changes.append(key)
            
            if changes:
                self.logger.info(f"Configuration reloaded with {len(changes)} changes: {changes}")
            else:
                self.logger.debug("Configuration reloaded with no changes")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to reload configuration: {e}")
            return False
    
    def validate_configuration(self) -> Dict[str, List[str]]:
        """Validate all configuration values and return validation results"""
        results = {
            'valid': [],
            'invalid': [],
            'missing_required': [],
            'warnings': []
        }
        
        for key, metadata in self._config_registry.items():
            if key not in self._config_cache:
                if metadata.required:
                    results['missing_required'].append(key)
                else:
                    results['warnings'].append(f"Optional parameter {key} not set")
                continue
            
            value = self._config_cache[key]
            
            try:
                # Type validation
                expected_type = metadata.data_type
                if not isinstance(value, expected_type):
                    results['invalid'].append(f"{key}: Expected {expected_type.__name__}, got {type(value).__name__}")
                    continue
                
                # Custom validation
                if metadata.validation_fn and not metadata.validation_fn(value):
                    results['invalid'].append(f"{key}: Custom validation failed")
                    continue
                
                results['valid'].append(key)
                
            except Exception as e:
                results['invalid'].append(f"{key}: Validation error - {e}")
        
        return results
    
    def get_configuration_summary(self) -> Dict[str, Any]:
        """Get summary of configuration status"""
        validation_results = self.validate_configuration()
        
        return {
            'total_parameters': len(self._config_registry),
            'loaded_parameters': len(self._config_cache),
            'valid_parameters': len(validation_results['valid']),
            'invalid_parameters': len(validation_results['invalid']),
            'missing_required': len(validation_results['missing_required']),
            'warnings': len(validation_results['warnings']),
            'categories': list(set(meta.category for meta in self._config_registry.values())),
            'last_reload': self._last_reload_time,
            'cache_ttl': self._cache_ttl
        }
    
    def get_parameter_info(self, key: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a configuration parameter"""
        if key not in self._config_registry:
            return None
        
        metadata = self._config_registry[key]
        current_value = self._config_cache.get(key)
        
        return {
            'key': key,
            'category': metadata.category.value,
            'description': metadata.description,
            'data_type': metadata.data_type.__name__,
            'required': metadata.required,
            'default_value': metadata.default_value,
            'current_value': "***MASKED***" if metadata.sensitive else current_value,
            'has_validation': metadata.validation_fn is not None,
            'sensitive': metadata.sensitive
        }
    
    def list_parameters_by_category(self) -> Dict[str, List[str]]:
        """List all parameters organized by category"""
        result = {}
        for key, metadata in self._config_registry.items():
            category = metadata.category.value
            if category not in result:
                result[category] = []
            result[category].append(key)
        return result
    
    def export_configuration_docs(self) -> str:
        """Export configuration documentation"""
        docs = ["# Configuration Parameters Documentation", ""]
        
        for category in ConfigCategory:
            category_params = [
                (key, meta) for key, meta in self._config_registry.items() 
                if meta.category == category
            ]
            
            if category_params:
                docs.append(f"## {category.value.upper()}")
                docs.append("")
                
                for key, metadata in category_params:
                    docs.append(f"### {key}")
                    docs.append(f"**Description:** {metadata.description}")
                    docs.append(f"**Type:** {metadata.data_type.__name__}")
                    docs.append(f"**Required:** {'Yes' if metadata.required else 'No'}")
                    if metadata.default_value is not None:
                        docs.append(f"**Default:** {metadata.default_value}")
                    if metadata.sensitive:
                        docs.append("**Sensitive:** Yes (value will be masked in logs)")
                    docs.append("")
        
        return "\n".join(docs)

# Global configuration manager instance
_config_manager: Optional[ConfigurationManager] = None

def get_config_manager(settings=None) -> ConfigurationManager:
    """Get or create the global configuration manager instance"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigurationManager(settings)
    return _config_manager

def initialize_config_manager(settings) -> ConfigurationManager:
    """Initialize the global configuration manager with settings"""
    global _config_manager
    _config_manager = ConfigurationManager(settings)
    return _config_manager

# Convenience functions for common configuration access
def get_websocket_config() -> Dict[str, Any]:
    """Get WebSocket configuration"""
    return get_config_manager().get_websocket_config()

def get_solana_config() -> Dict[str, Any]:
    """Get Solana configuration"""
    return get_config_manager().get_solana_config()

def get_trading_config() -> Dict[str, Any]:
    """Get trading configuration"""
    return get_config_manager().get_trading_config()

def get_api_config() -> Dict[str, Any]:
    """Get API configuration"""
    return get_config_manager().get_api_config()

def get_config(key: str, default: Any = None) -> Any:
    """Get a configuration value by key"""
    return get_config_manager().get(key, default) 