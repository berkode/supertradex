import os
import logging
from logging.handlers import RotatingFileHandler, QueueHandler, QueueListener
from queue import Queue
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class LoggingConfig:
    """Class to set up centralized logging for the trading system."""

    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
    LOG_FILE = os.getenv("LOG_FILE", "trading_system.log")
    MAX_LOG_FILE_SIZE = int(os.getenv("MAX_LOG_FILE_SIZE", 10 * 1024 * 1024))  # 10 MB
    BACKUP_COUNT = int(os.getenv("BACKUP_COUNT", 5))  # Number of backup log files
    ENABLE_CONSOLE_LOGGING = os.getenv("ENABLE_CONSOLE_LOGGING", "True").lower() == "true"

    @classmethod
    def setup_logging(cls):
        """Configures the logging system."""
        try:
            # Create a log queue for asynchronous logging
            log_queue = Queue()

            # Initialize the root logger
            root_logger = logging.getLogger()
            root_logger.setLevel(getattr(logging, cls.LOG_LEVEL, logging.INFO))

            # Define the log format
            log_format = logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )

            # File handler with rotation
            file_handler = RotatingFileHandler(
                cls.LOG_FILE,
                maxBytes=cls.MAX_LOG_FILE_SIZE,
                backupCount=cls.BACKUP_COUNT,
            )
            file_handler.setFormatter(log_format)
            file_handler.setLevel(getattr(logging, cls.LOG_LEVEL, logging.INFO))

            # Console handler (optional)
            console_handler = None
            if cls.ENABLE_CONSOLE_LOGGING:
                console_handler = logging.StreamHandler()
                console_handler.setFormatter(log_format)
                console_handler.setLevel(getattr(logging, cls.LOG_LEVEL, logging.INFO))

            # Queue handler for asynchronous logging
            queue_handler = QueueHandler(log_queue)
            root_logger.addHandler(queue_handler)

            # Add console and file handlers to queue listener
            handlers = [file_handler]
            if console_handler:
                handlers.append(console_handler)

            queue_listener = QueueListener(log_queue, *handlers)
            queue_listener.start()

            # Suppress overly verbose logs from external libraries
            logging.getLogger("urllib3").setLevel(logging.WARNING)
            logging.getLogger("requests").setLevel(logging.WARNING)

            root_logger.info("Logging system configured successfully.")

        except PermissionError as e:
            print(f"Error initializing logging: {e}")
            raise

