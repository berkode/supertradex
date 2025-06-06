import pytest
import os
import sqlite3
from unittest.mock import Mock, patch
from data.token_database import TokenDatabase
from config.settings import Settings
from pathlib import Path

@pytest.fixture
def settings():
    # Ensure settings are loaded for the test session
    return Settings()

@pytest.fixture
def db_path(tmp_path):
    # Provides the temporary path string
    return str(tmp_path / "test.db")

@pytest.fixture
def token_db(settings, db_path):
    # Temporarily override settings for the test database path
    original_file_path = settings.DATABASE_FILE_PATH
    original_url = settings.DATABASE_URL
    temp_db_path_obj = Path(db_path)
    
    # Ensure parent directory exists for the temp DB
    temp_db_path_obj.parent.mkdir(parents=True, exist_ok=True)
    
    # Set settings to use the temporary path
    settings.DATABASE_FILE_PATH = str(temp_db_path_obj)
    settings.DATABASE_URL = f"sqlite+aiosqlite:///{settings.DATABASE_FILE_PATH}"
    
    print(f"[Fixture] Using temporary DB URL: {settings.DATABASE_URL}") # Debug print

    # Instantiate TokenDatabase - it will now use the overridden settings
    db_instance = TokenDatabase(db_path=settings.DATABASE_FILE_PATH, settings=settings) # Pass settings and correct db_path
    
    # Need to manually initialize since it's not done in __init__ anymore for async
    # Assuming tests run within an event loop (e.g., using pytest-asyncio)
    # asyncio.run(db_instance.initialize()) # Avoid running loop here, tests should handle it

    yield db_instance # Provide the instance to the test
    
    # Cleanup: Restore original settings
    print("[Fixture] Restoring original DB settings...") # Debug print
    settings.DATABASE_FILE_PATH = original_file_path
    settings.DATABASE_URL = original_url
    # Optional: Clean up the temp db file if not handled by tmp_path
    # if temp_db_path_obj.exists():
    #     temp_db_path_obj.unlink()

def test_init_database(token_db, db_path):
    """Test database initialization."""
    assert os.path.exists(db_path)
    
    # Verify tables are created
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check tokens table
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tokens'")
    assert cursor.fetchone() is not None
    
    # Check trades table
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='trades'")
    assert cursor.fetchone() is not None
    
    conn.close()

def test_add_token(token_db):
    """Test adding a token to the database."""
    token = {
        "address": "0x123",
        "name": "Test Token",
        "symbol": "TEST",
        "price": 1.0,
        "volume24h": 1000000,
        "liquidity": 500000,
        "rugcheck_score": 0.8,
        "solsniffer_score": 0.7,
        "twitter_followers": 1000
    }
    
    token_db.add_token(token)
    
    # Verify token was added
    saved_token = token_db.get_token("0x123")
    assert saved_token is not None
    assert saved_token["symbol"] == "TEST"
    assert saved_token["price"] == 1.0

def test_update_token(token_db):
    """Test updating a token in the database."""
    # Add initial token
    token = {
        "address": "0x123",
        "name": "Test Token",
        "symbol": "TEST",
        "price": 1.0,
        "volume24h": 1000000,
        "liquidity": 500000
    }
    token_db.add_token(token)
    
    # Update token
    updated_token = {
        "address": "0x123",
        "name": "Test Token",
        "symbol": "TEST",
        "price": 1.5,
        "volume24h": 2000000,
        "liquidity": 1000000
    }
    token_db.update_token(updated_token)
    
    # Verify token was updated
    saved_token = token_db.get_token("0x123")
    assert saved_token["price"] == 1.5
    assert saved_token["volume24h"] == 2000000

def test_get_tokens(token_db):
    """Test retrieving tokens from the database."""
    # Add multiple tokens
    tokens = [
        {
            "address": "0x123",
            "name": "Token 1",
            "symbol": "T1",
            "price": 1.0,
            "volume24h": 1000000,
            "liquidity": 500000
        },
        {
            "address": "0x456",
            "name": "Token 2",
            "symbol": "T2",
            "price": 2.0,
            "volume24h": 2000000,
            "liquidity": 1000000
        }
    ]
    
    for token in tokens:
        token_db.add_token(token)
    
    # Retrieve all tokens
    saved_tokens = token_db.get_tokens()
    assert len(saved_tokens) == 2
    assert any(t["symbol"] == "T1" for t in saved_tokens)
    assert any(t["symbol"] == "T2" for t in saved_tokens)

def test_add_trade(token_db):
    """Test adding a trade to the database."""
    trade = {
        "token_address": "0x123",
        "type": "buy",
        "price": 1.0,
        "amount": 0.1,
        "timestamp": "2024-01-01T00:00:00"
    }
    
    token_db.add_trade(trade)
    
    # Verify trade was added
    trades = token_db.get_trades("0x123")
    assert len(trades) == 1
    assert trades[0]["type"] == "buy"
    assert trades[0]["price"] == 1.0

def test_get_trades(token_db):
    """Test retrieving trades from the database."""
    # Add multiple trades
    trades = [
        {
            "token_address": "0x123",
            "type": "buy",
            "price": 1.0,
            "amount": 0.1,
            "timestamp": "2024-01-01T00:00:00"
        },
        {
            "token_address": "0x123",
            "type": "sell",
            "price": 1.5,
            "amount": 0.1,
            "timestamp": "2024-01-02T00:00:00"
        }
    ]
    
    for trade in trades:
        token_db.add_trade(trade)
    
    # Retrieve trades
    saved_trades = token_db.get_trades("0x123")
    assert len(saved_trades) == 2
    assert saved_trades[0]["type"] == "buy"
    assert saved_trades[1]["type"] == "sell"

def test_cleanup_old_tokens(token_db):
    """Test cleaning up old tokens from the database."""
    # Add tokens with different timestamps
    tokens = [
        {
            "address": "0x123",
            "name": "Token 1",
            "symbol": "T1",
            "price": 1.0,
            "volume24h": 1000000,
            "liquidity": 500000,
            "last_updated": "2024-01-01T00:00:00"
        },
        {
            "address": "0x456",
            "name": "Token 2",
            "symbol": "T2",
            "price": 2.0,
            "volume24h": 2000000,
            "liquidity": 1000000,
            "last_updated": "2024-01-02T00:00:00"
        }
    ]
    
    for token in tokens:
        token_db.add_token(token)
    
    # Clean up old tokens
    token_db.cleanup_old_tokens(days=1)
    
    # Verify only recent token remains
    saved_tokens = token_db.get_tokens()
    assert len(saved_tokens) == 1
    assert saved_tokens[0]["symbol"] == "T2"

def test_get_token_statistics(token_db):
    """Test retrieving token statistics."""
    # Add trades for a token
    trades = [
        {
            "token_address": "0x123",
            "type": "buy",
            "price": 1.0,
            "amount": 0.1,
            "timestamp": "2024-01-01T00:00:00"
        },
        {
            "token_address": "0x123",
            "type": "sell",
            "price": 1.5,
            "amount": 0.1,
            "timestamp": "2024-01-02T00:00:00"
        }
    ]
    
    for trade in trades:
        token_db.add_trade(trade)
    
    # Get statistics
    stats = token_db.get_token_statistics("0x123")
    assert "total_trades" in stats
    assert "total_volume" in stats
    assert "average_price" in stats
    assert stats["total_trades"] == 2
    assert stats["total_volume"] == 0.2
    assert stats["average_price"] == 1.25 