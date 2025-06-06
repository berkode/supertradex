import pytest
import asyncio
from unittest.mock import Mock, patch
from main import run_trading_loop, initialize_components
from config.settings import Settings

@pytest.fixture
def settings():
    return Settings()

@pytest.fixture
def mock_components():
    return {
        "token_scanner": Mock(),
        "strategy_selector": Mock(),
        "order_manager": Mock(),
        "wallet_manager": Mock()
    }

@pytest.mark.asyncio
async def test_initialize_components(settings):
    """Test component initialization."""
    components = await initialize_components(settings)
    
    assert "token_scanner" in components
    assert "strategy_selector" in components
    assert "order_manager" in components
    assert "wallet_manager" in components

@pytest.mark.asyncio
async def test_initialize_components_error(settings):
    """Test component initialization with error."""
    with patch('main.TokenScanner', side_effect=Exception("Initialization error")):
        with pytest.raises(Exception) as exc_info:
            await initialize_components(settings)
        assert "Initialization error" in str(exc_info.value)

@pytest.mark.asyncio
async def test_run_trading_loop(mock_components):
    """Test trading loop execution."""
    # Mock token scanning results
    mock_components["token_scanner"].scan_tokens.return_value = [
        {
            "address": "0x123",
            "name": "Test Token",
            "symbol": "TEST",
            "price": 1.0,
            "volume24h": 1000000,
            "liquidity": 500000
        }
    ]
    
    # Mock strategy selection
    mock_components["strategy_selector"].select_strategy.return_value = {
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
    
    # Mock order placement
    mock_components["order_manager"].place_order.return_value = {
        "success": True,
        "tx_hash": "0xabc"
    }
    
    # Run trading loop for a short duration
    try:
        await asyncio.wait_for(
            run_trading_loop(mock_components),
            timeout=1.0
        )
    except asyncio.TimeoutError:
        pass
    
    # Verify component interactions
    mock_components["token_scanner"].scan_tokens.assert_called()
    mock_components["strategy_selector"].select_strategy.assert_called()
    mock_components["order_manager"].place_order.assert_called()

@pytest.mark.asyncio
async def test_run_trading_loop_no_tokens(mock_components):
    """Test trading loop with no tokens found."""
    # Mock empty token scan results
    mock_components["token_scanner"].scan_tokens.return_value = []
    
    # Run trading loop for a short duration
    try:
        await asyncio.wait_for(
            run_trading_loop(mock_components),
            timeout=1.0
        )
    except asyncio.TimeoutError:
        pass
    
    # Verify component interactions
    mock_components["token_scanner"].scan_tokens.assert_called()
    mock_components["strategy_selector"].select_strategy.assert_not_called()
    mock_components["order_manager"].place_order.assert_not_called()

@pytest.mark.asyncio
async def test_run_trading_loop_strategy_error(mock_components):
    """Test trading loop with strategy selection error."""
    # Mock token scanning results
    mock_components["token_scanner"].scan_tokens.return_value = [
        {
            "address": "0x123",
            "name": "Test Token",
            "symbol": "TEST",
            "price": 1.0,
            "volume24h": 1000000,
            "liquidity": 500000
        }
    ]
    
    # Mock strategy selection error
    mock_components["strategy_selector"].select_strategy.side_effect = Exception("Strategy error")
    
    # Run trading loop for a short duration
    try:
        await asyncio.wait_for(
            run_trading_loop(mock_components),
            timeout=1.0
        )
    except asyncio.TimeoutError:
        pass
    
    # Verify component interactions
    mock_components["token_scanner"].scan_tokens.assert_called()
    mock_components["strategy_selector"].select_strategy.assert_called()
    mock_components["order_manager"].place_order.assert_not_called()

@pytest.mark.asyncio
async def test_run_trading_loop_order_error(mock_components):
    """Test trading loop with order placement error."""
    # Mock token scanning results
    mock_components["token_scanner"].scan_tokens.return_value = [
        {
            "address": "0x123",
            "name": "Test Token",
            "symbol": "TEST",
            "price": 1.0,
            "volume24h": 1000000,
            "liquidity": 500000
        }
    ]
    
    # Mock strategy selection
    mock_components["strategy_selector"].select_strategy.return_value = {
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
    
    # Mock order placement error
    mock_components["order_manager"].place_order.side_effect = Exception("Order error")
    
    # Run trading loop for a short duration
    try:
        await asyncio.wait_for(
            run_trading_loop(mock_components),
            timeout=1.0
        )
    except asyncio.TimeoutError:
        pass
    
    # Verify component interactions
    mock_components["token_scanner"].scan_tokens.assert_called()
    mock_components["strategy_selector"].select_strategy.assert_called()
    mock_components["order_manager"].place_order.assert_called() 