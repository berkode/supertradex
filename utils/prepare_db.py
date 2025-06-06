#!/usr/bin/env python3
"""
Database preparation script to ensure proper setup of the trading database.
This script:
1. Removes any existing database file (optional)
2. Creates a new database with the proper structure
3. Initializes it with default data
"""
import os
import sys
import sqlite3
import logging
import shutil
from pathlib import Path

# Add parent directory to path if needed for config import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import settings # Import the initialized settings instance

# Configure logging
logging.basicConfig(level=logging.DEBUG, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def prepare_database(force_reset=False):
    """
    Prepare the database with initial structure and data.
    Args:
        force_reset: If True, will delete and recreate the database
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Get database path string from settings
        # Settings initialization ensures DATABASE_URL is set and path is resolved
        db_path_str = settings.DATABASE_FILE_PATH
        if not db_path_str:
            # This case should ideally not be reached if settings initialized correctly
            logger.critical("DATABASE_FILE_PATH not found in settings. Cannot prepare database.")
            raise ValueError("Database path not configured in settings.")
        
        logger.info(f"Using database path from settings: {db_path_str}")

        # Handle force reset
        if force_reset and os.path.exists(db_path_str):
            logger.info(f"Force reset requested, deleting existing database at {db_path_str}")
            os.remove(db_path_str)
            
        # Create basic database structure
        logger.info(f"Creating new database at {db_path_str}")
        conn = sqlite3.connect(db_path_str)
        cursor = conn.cursor()

        # Create tables
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS strategy (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                parameters TEXT,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_id TEXT NOT NULL,
                strategy_id INTEGER,
                coin_id INTEGER,
                action TEXT NOT NULL,
                type TEXT NOT NULL,
                price REAL NOT NULL,
                amount REAL NOT NULL,
                total REAL NOT NULL,
                status TEXT DEFAULT 'PENDING',
                notes TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (strategy_id) REFERENCES strategy(id),
                FOREIGN KEY (coin_id) REFERENCES coins(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alert (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_id TEXT NOT NULL,
                strategy_id INTEGER,
                coin_id INTEGER,
                message TEXT NOT NULL,
                level TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1,
                last_triggered TIMESTAMP,
                FOREIGN KEY (strategy_id) REFERENCES strategy(id),
                FOREIGN KEY (coin_id) REFERENCES coins(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS coins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                pair TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                fiat_limit REAL,
                close_price REAL,
                is_in_position BOOLEAN DEFAULT 0,
                is_trending BOOLEAN DEFAULT 0,
                is_mooning BOOLEAN DEFAULT 0,
                is_dumping BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trade_strategy_id ON trades(strategy_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trade_coin_id ON trades(coin_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_alert_strategy_id ON alert(strategy_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_alert_coin_id ON alert(coin_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_coins_symbol ON coins(symbol)")

        # Insert initial data
        cursor.execute("""
            INSERT OR IGNORE INTO strategy (name, description, parameters, is_active)
            VALUES (?, ?, ?, ?)
        """, ("Default Strategy", "Default trading strategy", "{}", 1))

        conn.commit()
        conn.close()
        
        logger.info("Database preparation completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Error preparing database: {str(e)}")
        return False

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Prepare the trading database")
    parser.add_argument("--reset", action="store_true", help="Force reset the database")
    args = parser.parse_args()
    
    success = prepare_database(force_reset=args.reset)
    sys.exit(0 if success else 1) 