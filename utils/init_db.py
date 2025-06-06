#!/usr/bin/env python3
"""
Database initialization script that runs the init_db function from data.__init__.py
"""
import sys
import logging
import os
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.DEBUG, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Add parent directory to path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the data package
try:
    from data import DataPackage
    logger.info("Successfully imported DataPackage")
except Exception as e:
    logger.error(f"Error importing DataPackage: {e}", exc_info=True)
    sys.exit(1)

def main():
    """Initialize the database manually."""
    try:
        # Create data package object
        data_pkg = DataPackage()
        logger.info("Created DataPackage instance")
        
        # Run init_db method
        logger.info("Initializing database...")
        result = data_pkg.init_db()
        
        if result:
            logger.info("Database initialized successfully")
            return 0
        else:
            logger.error("Database initialization failed")
            return 1
    except Exception as e:
        logger.error(f"Unexpected error during database initialization: {e}", exc_info=True)
        return 1

if __name__ == "__main__":
    sys.exit(main()) 