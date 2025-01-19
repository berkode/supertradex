import logging
import os
from logging.handlers import RotatingFileHandler, SMTPHandler
from typing import Optional

# Default logging configuration (loaded from environment variables or defaults)
LOG_FILE = os.getenv("LOG_FILE", "synthron.log")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
MAX_LOG_FILE_SIZE = int(os.getenv("MAX_LOG_FILE_SIZE", 10 * 1024 * 1024))  # 10 MB
BACKUP_COUNT = int(os.getenv("BACKUP_COUNT", 5))  # Keep 5 backup log files
ENABLE_CONSOLE_LOGGING = os.getenv("ENABLE_CONSOLE_LOGGING", "True").lower() == "true"
ENABLE_EMAIL_LOGGING = os.getenv("ENABLE_EMAIL_LOGGING", "False").lower() == "true"

# Email configuration for critical error reporting
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", 587))
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "True").lower() == "true"
EMAIL_USERNAME = os.getenv("EMAIL_USERNAME", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_RECIPIENTS = os.getenv("EMAIL_RECIPIENTS", "").split(",")

def get_logger(module_name: str, log_file: Optional[str] = None) -> logging.Logger:
    """
    Configure and return a logger for the specified module.

    Args:
        module_name (str): Name of the module using the logger.
        log_file (Optional[str]): Path to the log file. Defaults to the global log file.
    
    Returns:
        logging.Logger: Configured logger instance.
    """
    log_file = log_file or LOG_FILE
    logger = logging.getLogger(module_name)
    if logger.hasHandlers():  # Prevent duplicate handlers
        return logger

    logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    # Formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - [%(name)s] - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    # File handler with rotation
    file_handler = RotatingFileHandler(log_file, maxBytes=MAX_LOG_FILE_SIZE, backupCount=BACKUP_COUNT)
    file_handler.setFormatter(formatter)
    file_handler.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    logger.addHandler(file_handler)

    # Console handler (optional)
    if ENABLE_CONSOLE_LOGGING:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
        logger.addHandler(console_handler)

    # Email handler for critical errors (optional)
    if ENABLE_EMAIL_LOGGING and EMAIL_HOST and EMAIL_USERNAME and EMAIL_PASSWORD and EMAIL_RECIPIENTS:
        email_handler = SMTPHandler(
            mailhost=(EMAIL_HOST, EMAIL_PORT),
            fromaddr=EMAIL_USERNAME,
            toaddrs=EMAIL_RECIPIENTS,
            subject="Synthron Critical Alert",
            credentials=(EMAIL_USERNAME, EMAIL_PASSWORD),
            secure=() if EMAIL_USE_TLS else None,
        )
        email_handler.setFormatter(formatter)
        email_handler.setLevel(logging.CRITICAL)
        logger.addHandler(email_handler)

    logger.info(f"Logger initialized for {module_name} with level {LOG_LEVEL}")
    return logger
