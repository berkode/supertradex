import pytest
import os
import logging
from unittest.mock import Mock, patch
from utils.logging_manager import LoggingManager
from config.settings import Settings

@pytest.fixture
def settings():
    return Settings()

@pytest.fixture
def log_dir(tmp_path):
    return str(tmp_path / "logs")

@pytest.fixture
def logging_manager(settings, log_dir):
    return LoggingManager(settings, log_dir)

def test_init_logging(logging_manager, log_dir):
    """Test logging initialization."""
    assert os.path.exists(log_dir)
    assert os.path.exists(os.path.join(log_dir, "trader.log"))
    
    # Verify logger configuration
    logger = logging.getLogger("trader")
    assert logger.level == logging.INFO
    assert len(logger.handlers) > 0

def test_log_trade(logging_manager):
    """Test trade logging."""
    trade = {
        "token": "TEST",
        "type": "buy",
        "price": 1.0,
        "amount": 0.1,
        "timestamp": "2024-01-01T00:00:00"
    }
    
    logging_manager.log_trade(trade)
    
    # Verify log file contains trade information
    with open(logging_manager.trade_log_file, "r") as f:
        log_content = f.read()
        assert "TEST" in log_content
        assert "buy" in log_content
        assert "1.0" in log_content

def test_log_error(logging_manager):
    """Test error logging."""
    error_msg = "Test error message"
    logging_manager.log_error(error_msg)
    
    # Verify log file contains error information
    with open(logging_manager.error_log_file, "r") as f:
        log_content = f.read()
        assert error_msg in log_content
        assert "ERROR" in log_content

def test_log_token_scan(logging_manager):
    """Test token scan logging."""
    tokens = [
        {
            "address": "0x123",
            "name": "Test Token",
            "symbol": "TEST",
            "price": 1.0,
            "volume24h": 1000000,
            "liquidity": 500000
        }
    ]
    
    logging_manager.log_token_scan(tokens)
    
    # Verify log file contains token scan information
    with open(logging_manager.scan_log_file, "r") as f:
        log_content = f.read()
        assert "TEST" in log_content
        assert "1000000" in log_content
        assert "500000" in log_content

def test_log_strategy_selection(logging_manager):
    """Test strategy selection logging."""
    token = {
        "address": "0x123",
        "name": "Test Token",
        "symbol": "TEST",
        "price": 1.0,
        "volume24h": 1000000,
        "liquidity": 500000
    }
    
    strategy = {
        "entry_conditions": {
            "min_volume": 1000000,
            "min_liquidity": 500000
        },
        "exit_conditions": {
            "take_profit": 20.0,
            "stop_loss": 10.0
        },
        "position_size": 0.1
    }
    
    logging_manager.log_strategy_selection(token, strategy)
    
    # Verify log file contains strategy selection information
    with open(logging_manager.strategy_log_file, "r") as f:
        log_content = f.read()
        assert "TEST" in log_content
        assert "entry_conditions" in log_content
        assert "exit_conditions" in log_content

def test_log_portfolio_update(logging_manager):
    """Test portfolio update logging."""
    portfolio = {
        "total_value": 10000.0,
        "positions": [
            {
                "token": "TEST1",
                "size": 0.1,
                "value": 1000.0
            },
            {
                "token": "TEST2",
                "size": 0.2,
                "value": 2000.0
            }
        ]
    }
    
    logging_manager.log_portfolio_update(portfolio)
    
    # Verify log file contains portfolio information
    with open(logging_manager.portfolio_log_file, "r") as f:
        log_content = f.read()
        assert "10000.0" in log_content
        assert "TEST1" in log_content
        assert "TEST2" in log_content

def test_log_performance(logging_manager):
    """Test performance logging."""
    performance = {
        "total_trades": 10,
        "winning_trades": 6,
        "losing_trades": 4,
        "total_profit": 1000.0,
        "win_rate": 0.6
    }
    
    logging_manager.log_performance(performance)
    
    # Verify log file contains performance information
    with open(logging_manager.performance_log_file, "r") as f:
        log_content = f.read()
        assert "10" in log_content
        assert "6" in log_content
        assert "4" in log_content
        assert "1000.0" in log_content
        assert "0.6" in log_content

def test_rotate_logs(logging_manager):
    """Test log rotation."""
    # Create some log content
    for i in range(1000):
        logging_manager.log_trade({
            "token": f"TEST{i}",
            "type": "buy",
            "price": 1.0,
            "amount": 0.1,
            "timestamp": "2024-01-01T00:00:00"
        })
    
    # Trigger log rotation
    logging_manager.rotate_logs()
    
    # Verify old log file was archived
    assert os.path.exists(logging_manager.trade_log_file)
    assert os.path.exists(logging_manager.trade_log_file + ".1")

def test_cleanup_old_logs(logging_manager):
    """Test cleanup of old log files."""
    # Create some old log files
    old_log = logging_manager.trade_log_file + ".10"
    with open(old_log, "w") as f:
        f.write("old log content")
    
    # Clean up old logs
    logging_manager.cleanup_old_logs(days=7)
    
    # Verify old log file was removed
    assert not os.path.exists(old_log)
    assert os.path.exists(logging_manager.trade_log_file) 