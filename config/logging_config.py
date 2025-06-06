import logging
import os
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from config.settings import Settings, outputs_dir
from utils.colored_formatter import ColoredFormatter

# Set a basic formatter for early logging before setup_logging is called
basic_formatter = logging.Formatter(
    '%(levelname).1s %(asctime)s %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)

# Configure root logger with basic formatter
root_logger = logging.getLogger()
if not root_logger.handlers:
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(basic_formatter)
    root_logger.addHandler(console_handler)
    root_logger.setLevel(logging.INFO)

class LoggingConfig:
    """Configuration for logging in the trading system."""
    
    @staticmethod
    def setup_logging(settings=None):
        """Set up logging configuration with organized log separation."""
        if settings is None:
            settings = Settings()
            
        # Use outputs directory from settings
        log_dir = Path('outputs')
        log_dir.mkdir(exist_ok=True)
        
        # Configure root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)  # Allow all levels, filter at handler level
        
        # Remove existing handlers
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        # Create formatters
        console_formatter = ColoredFormatter(
            '%(levelname).1s %(asctime)s %(name)s: %(message)s',
            datefmt='%H:%M:%S'
        )
        file_formatter = logging.Formatter(
            '%(levelname).1s %(asctime)s %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Console handler - show INFO and above
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(console_formatter)
        console_handler.setLevel(logging.INFO)
        root_logger.addHandler(console_handler)
        
        # Main supertradex.log file handler - ONLY Critical, Error, Warning and Important Info
        # Create a custom filter for main log to reduce flooding
        class MainLogFilter(logging.Filter):
            def filter(self, record):
                # Allow all CRITICAL, ERROR, WARNING
                if record.levelno >= logging.WARNING:
                    return True
                
                # For INFO level, only allow important events (exclude blockchain flood)
                if record.levelno == logging.INFO:
                    # Exclude blockchain-related logs
                    excluded_loggers = [
                        'data.blockchain_listener',
                        'data.websocket_connection_manager', 
                        'data.message_dispatcher',
                        'data',
                        'FocusedMonitoring',
                        'BlockchainListener',
                        'HybridMonitoring'
                    ]
                    
                    # Exclude logs from blockchain-related loggers
                    for excluded in excluded_loggers:
                        if record.name.startswith(excluded):
                            return False
                    
                    # Exclude messages containing blockchain noise keywords
                    noise_keywords = [
                        'WebSocket message',
                        'Processing logs for signature',
                        'Pool Events:',
                        'Account Events:',
                        'BLOCKCHAIN PRICE:',
                        'Blockchain USD vs PriceMonitor',
                        'subscription confirmed',
                        'WebSocket connection',
                        'DEX program activity',
                        'Swap detected'
                    ]
                    
                    message = record.getMessage()
                    for keyword in noise_keywords:
                        if keyword.lower() in message.lower():
                            return False
                    
                    # Allow important INFO messages
                    important_keywords = [
                        'initialized',
                        'starting',
                        'shutting down', 
                        'error',
                        'failed',
                        'Paper trading',
                        'Trade executed',
                        'Strategy',
                        'Alert',
                        'Balance',
                        'Position'
                    ]
                    
                    for keyword in important_keywords:
                        if keyword.lower() in message.lower():
                            return True
                    
                    # Allow INFO from main application modules
                    important_modules = [
                        '__main__',
                        'strategies',
                        'execution',
                        'wallet',
                        'data.token_scanner',
                        'data.market_data'
                    ]
                    
                    for module in important_modules:
                        if record.name.startswith(module):
                            return True
                    
                    return False  # Block other INFO
                
                # Block DEBUG level from main log
                return False
        
        main_file_handler = RotatingFileHandler(
            log_dir / 'supertradex.log',
            maxBytes=50*1024*1024,  # 50MB
            backupCount=3,
            encoding='utf-8'
        )
        main_file_handler.setFormatter(file_formatter)
        main_file_handler.setLevel(logging.INFO)
        main_file_handler.addFilter(MainLogFilter())
        root_logger.addHandler(main_file_handler)
        
        # Set specific loggers to appropriate levels
        # Reduce noise from websockets and asyncio
        logging.getLogger('websockets').setLevel(logging.ERROR)
        logging.getLogger('asyncio').setLevel(logging.WARNING)
        
        # Important modules that should log to main file
        logging.getLogger('data.market_data').setLevel(logging.INFO)
        logging.getLogger('data.token_scanner').setLevel(logging.INFO)
        logging.getLogger('strategies').setLevel(logging.INFO)
        logging.getLogger('execution').setLevel(logging.INFO)
        logging.getLogger('wallet').setLevel(logging.INFO)
        
        # Blockchain-related loggers get their own dedicated loggers (setup separately)
        logging.getLogger('data.blockchain_listener').setLevel(logging.DEBUG)
        logging.getLogger('data.websocket_connection_manager').setLevel(logging.DEBUG)
        logging.getLogger('data.message_dispatcher').setLevel(logging.DEBUG)
        
        logging.info("Organized logging configuration initialized")
        logging.info("🔶 Main log: C/E/W + Important Info only")
        logging.info("🔶 Blockchain events: Separate blockchain_listener.log")
        logging.info("🔶 Price updates: Dedicated price_updates.log every 60s")