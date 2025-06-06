from web.app import create_app
import sys, os
sys.path.append(os.path.dirname(os.path.realpath(__file__)))

# Import the centralized configuration
from config.settings import Settings, initialize_settings

# Initialize settings first
initialize_settings()

# Try to load encrypted environment variables first
from utils.encryption import decrypt_env_file

encrypted_env_path = os.environ.get('ENCRYPTED_ENV_PATH', '.env.encrypted')
if os.path.exists(encrypted_env_path):
    print(f"Loading encrypted environment from {encrypted_env_path}")
    # Create a temporary decrypted file
    temp_file = '.env.temp'
    decrypt_env_file(os.environ.get('ENCRYPTION_PASSWORD', ''), encrypted_env_path, temp_file)
    # Load the decrypted environment variables
    from dotenv import load_dotenv
    load_dotenv(temp_file)
    # Clean up temporary file
    os.remove(temp_file)
else:
    print("Could not load encrypted environment, falling back to regular .env")
    from dotenv import load_dotenv
    load_dotenv()

import logging
from pathlib import Path
from data.token_database import TokenDatabase
from data.token_scanner import TokenScanner
from web.models import db
from web.tradingview import TradingViewManager

# Configure logging
logging.basicConfig(
    level=Settings.LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(Settings.LOG_FILE),
        logging.StreamHandler() if Settings.ENABLE_CONSOLE_LOGGING else None
    ]
)
logger = logging.getLogger(__name__)

# Ensure outputs directory exists
os.makedirs('outputs', exist_ok=True)

def init_app():
    """Initialize the application components."""
    try:
        logger.info("Initializing application...")
        settings = Settings() # Get settings instance
        
        # Initialize database (reads settings internally)
        db = TokenDatabase()
        logger.info(f"Database initialized using settings. Path: {settings.DATABASE_FILE_PATH}")
        
        # Initialize token scanner with database instance
        scanner = TokenScanner(db_instance=db)
        logger.info("Token scanner initialized")
        
        # Initialize TradingView manager
        tradingview = TradingViewManager()
        logger.info("TradingView manager initialized")
        
        return db, scanner, tradingview
        
    except Exception as e:
        logger.error(f"Error initializing application: {str(e)}")
        raise

def cleanup_app(db, scanner, tradingview):
    """Clean up application resources."""
    try:
        if scanner:
            scanner.close()
        if db:
            db.close()
        if tradingview:
            tradingview.close()
        logger.info("Application resources cleaned up")
    except Exception as e:
        logger.error(f"Error cleaning up application resources: {str(e)}")
        raise

if __name__ == "__main__":
    db = None
    scanner = None
    tradingview = None
    try:
        db, scanner, tradingview = init_app()
        # Create Flask application
        app = create_app()
        # Initialize database with app context
        with app.app_context():
            db.create_all()
        # Add your server initialization code here
        logger.info("Server started successfully")
    except Exception as e:
        logger.error(f"Error starting server: {str(e)}")
        raise
    finally:
        cleanup_app(db, scanner, tradingview)
else:
    gunicorn_app = create_app()
    # Initialize database with app context
    with gunicorn_app.app_context():
        db.create_all()
    # run with: 
    # gunicorn --bind $HOST:$PORT --workers 1 --threads 2 --timeout 0 appserver:gunicorn_app
    # gunicorn --bind 0.0.0.0:8080 --workers 1 --threads 2 --timeout 0 appserver:gunicorn_app