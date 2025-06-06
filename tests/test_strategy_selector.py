import pytest
from unittest.mock import Mock, patch
from strategies.strategy_selector import StrategySelector
from config.settings import Settings

@pytest.fixture
def settings():
    return Settings()

@pytest.fixture
def strategy_selector(settings):
    return StrategySelector(settings)

def test_select_strategy(strategy_selector):
    """Test strategy selection based on token metrics."""
    token = {
        "address": "0x123",
        "name": "Test Token",
        "symbol": "TEST",
        "price": 1.0,
        "volume24h": 1000000,
        "liquidity": 500000,
        "priceChange24h": 10.0,
        "rugcheck_score": 0.8,
        "solsniffer_score": 0.7,
        "twitter_followers": 1000
    }
    
    strategy = strategy_selector.select_strategy(token)
    assert strategy is not None
    assert "entry_conditions" in strategy
    assert "exit_conditions" in strategy
    assert "position_size" in strategy

def test_select_strategy_low_metrics(strategy_selector):
    """Test strategy selection for tokens with low metrics."""
    token = {
        "address": "0x123",
        "name": "Test Token",
        "symbol": "TEST",
        "price": 1.0,
        "volume24h": 1000,
        "liquidity": 500,
        "priceChange24h": 1.0,
        "rugcheck_score": 0.3,
        "solsniffer_score": 0.2,
        "twitter_followers": 100
    }
    
    strategy = strategy_selector.select_strategy(token)
    assert strategy is None

@pytest.mark.asyncio
async def test_evaluate_entry_conditions(strategy_selector):
    """Test evaluation of entry conditions."""
    token = {
        "address": "0x123",
        "name": "Test Token",
        "symbol": "TEST",
        "price": 1.0,
        "volume24h": 1000000,
        "liquidity": 500000,
        "priceChange24h": 10.0,
        "rugcheck_score": 0.8,
        "solsniffer_score": 0.7,
        "twitter_followers": 1000
    }
    
    strategy = strategy_selector.select_strategy(token)
    should_enter = await strategy_selector.evaluate_entry_conditions(token, strategy)
    assert isinstance(should_enter, bool)

@pytest.mark.asyncio
async def test_evaluate_exit_conditions(strategy_selector):
    """Test evaluation of exit conditions."""
    token = {
        "address": "0x123",
        "name": "Test Token",
        "symbol": "TEST",
        "price": 1.0,
        "volume24h": 1000000,
        "liquidity": 500000,
        "priceChange24h": 10.0,
        "rugcheck_score": 0.8,
        "solsniffer_score": 0.7,
        "twitter_followers": 1000
    }
    
    strategy = strategy_selector.select_strategy(token)
    should_exit = await strategy_selector.evaluate_exit_conditions(token, strategy)
    assert isinstance(should_exit, bool)

def test_calculate_position_size(strategy_selector):
    """Test position size calculation."""
    token = {
        "address": "0x123",
        "name": "Test Token",
        "symbol": "TEST",
        "price": 1.0,
        "volume24h": 1000000,
        "liquidity": 500000,
        "priceChange24h": 10.0,
        "rugcheck_score": 0.8,
        "solsniffer_score": 0.7,
        "twitter_followers": 1000
    }
    
    strategy = strategy_selector.select_strategy(token)
    position_size = strategy_selector.calculate_position_size(token, strategy)
    assert isinstance(position_size, float)
    assert position_size > 0

def test_validate_strategy_parameters(strategy_selector):
    """Test strategy parameter validation."""
    strategy = {
        "entry_conditions": {
            "min_volume": 1000000,
            "min_liquidity": 500000,
            "min_price_change": 5.0
        },
        "exit_conditions": {
            "take_profit": 20.0,
            "stop_loss": 10.0
        },
        "position_size": 0.1
    }
    
    is_valid = strategy_selector.validate_strategy_parameters(strategy)
    assert is_valid is True

def test_validate_strategy_parameters_invalid(strategy_selector):
    """Test strategy parameter validation with invalid parameters."""
    strategy = {
        "entry_conditions": {
            "min_volume": -1000000,
            "min_liquidity": -500000,
            "min_price_change": -5.0
        },
        "exit_conditions": {
            "take_profit": -20.0,
            "stop_loss": -10.0
        },
        "position_size": 1.5
    }
    
    is_valid = strategy_selector.validate_strategy_parameters(strategy)
    assert is_valid is False 