#!/usr/bin/env python3
"""
Debug script to identify database creation issues
"""
import os
import sys
import logging
import sqlite3
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.DEBUG, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Add parent directory to path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def debug_db_creation():
    """Test basic database creation to debug permission issues."""
    try:
        # Import settings to get the DATABASE_FILE_PATH and DATABASE_URL
        from config.settings import settings
        
        db_file_path_str = settings.DATABASE_FILE_PATH
        db_url = settings.DATABASE_URL # Used for connection
        db_file_path = Path(db_file_path_str)
        db_parent_dir = db_file_path.parent

        logger.info(f"Using Database File Path from settings: {db_file_path}")
        logger.info(f"Database parent directory: {db_parent_dir}")
        logger.info(f"Database parent directory exists: {db_parent_dir.exists()}")
        
        # Ensure the parent directory exists (Settings should handle this, but double-check)
        if not db_parent_dir.exists():
            logger.warning(f"Database parent directory {db_parent_dir} does not exist. Attempting creation...")
            try:
                db_parent_dir.mkdir(exist_ok=True, parents=True)
                logger.info(f"Created database parent directory: {db_parent_dir}")
            except Exception as e:
                logger.error(f"Failed to create database parent directory {db_parent_dir}: {e}")
                return False # Cannot proceed without directory
        
        # Get permissions of the directory
        try:
            dir_perms = os.stat(db_parent_dir).st_mode & 0o777
            logger.info(f"Database parent directory permissions: {oct(dir_perms)}")
        except FileNotFoundError:
             logger.error(f"Parent directory {db_parent_dir} not found after creation attempt.")
             return False
        
        # Try to make the directory writable (adjust permissions if needed)
        try:
            os.chmod(db_parent_dir, 0o755) # Ensure reasonable permissions
            logger.info(f"Set permissions for {db_parent_dir} to 755")
        except Exception as e:
            logger.warning(f"Could not change permissions for {db_parent_dir}: {e}")
        
        # Database path (already have db_file_path from settings)
        logger.info(f"Attempting connection to Database path: {db_file_path}")
        
        # Try to create/connect to the SQLite database using the file path
        logger.info(f"Connecting to SQLite database at {db_file_path}...")
        # Use the file path string for sqlite3.connect
        conn = sqlite3.connect(str(db_file_path))
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS test (id INTEGER PRIMARY KEY, name TEXT)")
        cursor.execute("INSERT INTO test (name) VALUES ('test')")
        conn.commit()
        
        # Verify the table was created
        cursor.execute("SELECT * FROM test")
        rows = cursor.fetchall()
        logger.info(f"Test query results: {rows}")
        
        conn.close()
        logger.info("Database created and tested successfully")
        
        # Check the DB file permissions
        if db_file_path.exists():
            file_perms = os.stat(db_file_path).st_mode & 0o777
            logger.info(f"Database file permissions: {oct(file_perms)}")
            # Try to make the file readable/writable
            try:
                os.chmod(db_file_path, 0o644)
                logger.info("Changed DB file permissions to 644")
            except Exception as e:
                logger.error(f"Error changing file permissions: {e}")
        else:
            logger.error("Database file does not exist after creation attempt")
        
        return True
    except Exception as e:
        logger.error(f"Error during database debug: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    if debug_db_creation():
        logger.info("Database debugging completed successfully")
        sys.exit(0)
    else:
        logger.error("Database debugging failed")
        sys.exit(1) 