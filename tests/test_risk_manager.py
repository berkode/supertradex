import pytest
from unittest.mock import Mock, patch
from risk.risk_manager import RiskManager
from config.settings import Settings

@pytest.fixture
def settings():
    return Settings()

@pytest.fixture
def risk_manager(settings):
    return RiskManager(settings)

def test_calculate_position_size(risk_manager):
    """Test position size calculation."""
    token = {
        "address": "0x123",
        "name": "Test Token",
        "symbol": "TEST",
        "price": 1.0,
        "volume24h": 1000000,
        "liquidity": 500000
    }
    
    strategy = {
        "position_size": 0.1,  # 10% of portfolio
        "risk_per_trade": 0.02  # 2% risk per trade
    }
    
    position_size = risk_manager.calculate_position_size(token, strategy)
    assert isinstance(position_size, float)
    assert position_size > 0
    assert position_size <= 1.0  # Should not exceed 100% of portfolio

def test_calculate_position_size_high_risk(risk_manager):
    """Test position size calculation with high risk parameters."""
    token = {
        "address": "0x123",
        "name": "Test Token",
        "symbol": "TEST",
        "price": 1.0,
        "volume24h": 1000000,
        "liquidity": 500000
    }
    
    strategy = {
        "position_size": 0.5,  # 50% of portfolio
        "risk_per_trade": 0.1  # 10% risk per trade
    }
    
    with pytest.raises(Exception) as exc_info:
        risk_manager.calculate_position_size(token, strategy)
    assert "Risk parameters exceed limits" in str(exc_info.value)

def test_calculate_stop_loss(risk_manager):
    """Test stop loss calculation."""
    token = {
        "address": "0x123",
        "name": "Test Token",
        "symbol": "TEST",
        "price": 1.0,
        "volume24h": 1000000,
        "liquidity": 500000
    }
    
    strategy = {
        "stop_loss_percentage": 0.1  # 10% stop loss
    }
    
    stop_loss = risk_manager.calculate_stop_loss(token, strategy)
    assert isinstance(stop_loss, float)
    assert stop_loss < token["price"]  # Stop loss should be below current price

def test_calculate_take_profit(risk_manager):
    """Test take profit calculation."""
    token = {
        "address": "0x123",
        "name": "Test Token",
        "symbol": "TEST",
        "price": 1.0,
        "volume24h": 1000000,
        "liquidity": 500000
    }
    
    strategy = {
        "take_profit_percentage": 0.2  # 20% take profit
    }
    
    take_profit = risk_manager.calculate_take_profit(token, strategy)
    assert isinstance(take_profit, float)
    assert take_profit > token["price"]  # Take profit should be above current price

def test_check_daily_loss_limit(risk_manager):
    """Test daily loss limit check."""
    # Mock trade history
    trades = [
        {
            "token": "TEST",
            "type": "buy",
            "price": 1.0,
            "amount": 0.1,
            "timestamp": "2024-01-01T00:00:00"
        },
        {
            "token": "TEST",
            "type": "sell",
            "price": 0.9,
            "amount": 0.1,
            "timestamp": "2024-01-01T01:00:00"
        }
    ]
    
    with patch('risk.risk_manager.RiskManager._get_daily_trades', 
              return_value=trades):
        
        can_trade = risk_manager.check_daily_loss_limit()
        assert isinstance(can_trade, bool)

def test_check_daily_loss_limit_exceeded(risk_manager):
    """Test daily loss limit check when limit is exceeded."""
    # Mock trade history with large losses
    trades = [
        {
            "token": "TEST",
            "type": "buy",
            "price": 1.0,
            "amount": 1.0,
            "timestamp": "2024-01-01T00:00:00"
        },
        {
            "token": "TEST",
            "type": "sell",
            "price": 0.5,
            "amount": 1.0,
            "timestamp": "2024-01-01T01:00:00"
        }
    ]
    
    with patch('risk.risk_manager.RiskManager._get_daily_trades', 
              return_value=trades):
        
        can_trade = risk_manager.check_daily_loss_limit()
        assert can_trade is False

def test_check_portfolio_risk(risk_manager):
    """Test portfolio risk check."""
    # Mock portfolio positions
    positions = [
        {
            "token": "TEST1",
            "size": 0.1,
            "unrealized_pnl": 0.1
        },
        {
            "token": "TEST2",
            "size": 0.2,
            "unrealized_pnl": -0.1
        }
    ]
    
    with patch('risk.risk_manager.RiskManager._get_positions', 
              return_value=positions):
        
        risk_level = risk_manager.check_portfolio_risk()
        assert isinstance(risk_level, float)
        assert 0 <= risk_level <= 1

def test_check_portfolio_risk_high(risk_manager):
    """Test portfolio risk check with high risk."""
    # Mock portfolio positions with high risk
    positions = [
        {
            "token": "TEST1",
            "size": 0.4,
            "unrealized_pnl": 0.1
        },
        {
            "token": "TEST2",
            "size": 0.4,
            "unrealized_pnl": -0.1
        }
    ]
    
    with patch('risk.risk_manager.RiskManager._get_positions', 
              return_value=positions):
        
        risk_level = risk_manager.check_portfolio_risk()
        assert risk_level > 0.7  # High risk level

def test_validate_risk_parameters(risk_manager):
    """Test risk parameter validation."""
    strategy = {
        "position_size": 0.1,
        "risk_per_trade": 0.02,
        "stop_loss_percentage": 0.1,
        "take_profit_percentage": 0.2
    }
    
    is_valid = risk_manager.validate_risk_parameters(strategy)
    assert is_valid is True

def test_validate_risk_parameters_invalid(risk_manager):
    """Test risk parameter validation with invalid parameters."""
    strategy = {
        "position_size": 1.5,  # Invalid position size
        "risk_per_trade": 0.5,  # Invalid risk per trade
        "stop_loss_percentage": 0.1,
        "take_profit_percentage": 0.2
    }
    
    is_valid = risk_manager.validate_risk_parameters(strategy)
    assert is_valid is False 