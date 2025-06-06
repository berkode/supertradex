#!/usr/bin/env python3
"""
Quick script to test SQLite database access with different methods.
"""
import os
import sys
import sqlite3
import logging
from pathlib import Path
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

# Configure logging
logging.basicConfig(level=logging.DEBUG, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_direct_sqlite():
    """Test direct SQLite connection."""
    db_path = Path('outputs/traders.db').resolve()
    logger.info(f"Testing direct SQLite connection to: {db_path}")
    
    try:
        # Get file permissions
        permissions = oct(os.stat(db_path).st_mode)[-3:]
        logger.info(f"File permissions: {permissions}")
        
        # Test connection
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT sqlite_version();")
        version = cursor.fetchone()
        logger.info(f"SQLite version: {version[0]}")
        
        # Test schema
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        logger.info(f"Tables in database: {[t[0] for t in tables]}")
        
        # Test data
        cursor.execute("SELECT * FROM user LIMIT 1;")
        user = cursor.fetchone()
        logger.info(f"First user: {user}")
        
        conn.close()
        logger.info("Direct SQLite connection successful")
        return True
    except Exception as e:
        logger.error(f"Direct SQLite connection failed: {e}", exc_info=True)
        return False

def test_sqlalchemy():
    """Test SQLAlchemy connection."""
    db_path = Path('outputs/traders.db').resolve()
    logger.info(f"Testing SQLAlchemy connection to: {db_path}")
    
    try:
        # Create Flask app with SQLAlchemy
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        
        # Initialize SQLAlchemy with the app
        db = SQLAlchemy(app)
        
        # Define a minimal User model for testing
        class User(db.Model):
            id = db.Column(db.Integer, primary_key=True)
            username = db.Column(db.String(50), nullable=False)
            email = db.Column(db.String(120), nullable=False)
        
        # Test connection within app context
        with app.app_context():
            user_count = User.query.count()
            logger.info(f"User count from SQLAlchemy: {user_count}")
            
            if user_count > 0:
                first_user = User.query.first()
                logger.info(f"First user from SQLAlchemy: {first_user.username}")
                
        logger.info("SQLAlchemy connection successful")
        return True
    except Exception as e:
        logger.error(f"SQLAlchemy connection failed: {e}", exc_info=True)
        return False

def main():
    """Main function."""
    # Make sure outputs directory exists
    os.makedirs('outputs', exist_ok=True)
    
    # Test direct SQLite connection
    sqlite_result = test_direct_sqlite()
    
    # Test SQLAlchemy connection
    sqlalchemy_result = test_sqlalchemy()
    
    # Print summary
    logger.info(f"Summary: Direct SQLite: {'✅' if sqlite_result else '❌'}, SQLAlchemy: {'✅' if sqlalchemy_result else '❌'}")
    
    return 0 if sqlite_result and sqlalchemy_result else 1

if __name__ == "__main__":
    sys.exit(main()) 