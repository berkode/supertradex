import pytest
from unittest.mock import Mock, patch
from execution.order_manager import OrderManager
from config.settings import Settings

@pytest.fixture
def settings():
    return Settings()

@pytest.fixture
def order_manager(settings):
    return OrderManager(settings)

@pytest.mark.asyncio
async def test_place_order(order_manager):
    """Test order placement."""
    token = {
        "address": "0x123",
        "name": "Test Token",
        "symbol": "TEST",
        "price": 1.0,
        "volume24h": 1000000,
        "liquidity": 500000
    }
    
    strategy = {
        "position_size": 0.1,
        "entry_conditions": {
            "min_volume": 1000000,
            "min_liquidity": 500000
        }
    }
    
    with patch('execution.order_manager.OrderManager._sign_transaction', 
              return_value="signed_tx"), \
         patch('execution.order_manager.OrderManager._send_transaction', 
              return_value={"success": True, "tx_hash": "0xabc"}):
        
        result = await order_manager.place_order(token, strategy)
        assert result["success"] is True
        assert "tx_hash" in result

@pytest.mark.asyncio
async def test_place_order_insufficient_balance(order_manager):
    """Test order placement with insufficient balance."""
    token = {
        "address": "0x123",
        "name": "Test Token",
        "symbol": "TEST",
        "price": 1.0,
        "volume24h": 1000000,
        "liquidity": 500000
    }
    
    strategy = {
        "position_size": 1.0,  # 100% of balance
        "entry_conditions": {
            "min_volume": 1000000,
            "min_liquidity": 500000
        }
    }
    
    with patch('execution.order_manager.OrderManager._get_balance', 
              return_value=0.5):
        
        with pytest.raises(Exception) as exc_info:
            await order_manager.place_order(token, strategy)
        assert "Insufficient balance" in str(exc_info.value)

@pytest.mark.asyncio
async def test_cancel_order(order_manager):
    """Test order cancellation."""
    order_id = "0x123"
    
    with patch('execution.order_manager.OrderManager._sign_transaction', 
              return_value="signed_tx"), \
         patch('execution.order_manager.OrderManager._send_transaction', 
              return_value={"success": True, "tx_hash": "0xabc"}):
        
        result = await order_manager.cancel_order(order_id)
        assert result["success"] is True
        assert "tx_hash" in result

@pytest.mark.asyncio
async def test_modify_order(order_manager):
    """Test order modification."""
    order_id = "0x123"
    new_price = 1.1
    new_size = 0.2
    
    with patch('execution.order_manager.OrderManager._sign_transaction', 
              return_value="signed_tx"), \
         patch('execution.order_manager.OrderManager._send_transaction', 
              return_value={"success": True, "tx_hash": "0xabc"}):
        
        result = await order_manager.modify_order(order_id, new_price, new_size)
        assert result["success"] is True
        assert "tx_hash" in result

@pytest.mark.asyncio
async def test_get_order_status(order_manager):
    """Test getting order status."""
    order_id = "0x123"
    
    with patch('execution.order_manager.OrderManager._get_order_info', 
              return_value={"status": "filled", "filled_size": 0.1}):
        
        status = await order_manager.get_order_status(order_id)
        assert status["status"] == "filled"
        assert status["filled_size"] == 0.1

def test_calculate_slippage(order_manager):
    """Test slippage calculation."""
    price = 1.0
    size = 0.1
    liquidity = 500000
    
    slippage = order_manager.calculate_slippage(price, size, liquidity)
    assert isinstance(slippage, float)
    assert slippage >= 0

def test_validate_order_parameters(order_manager):
    """Test order parameter validation."""
    token = {
        "address": "0x123",
        "name": "Test Token",
        "symbol": "TEST",
        "price": 1.0,
        "volume24h": 1000000,
        "liquidity": 500000
    }
    
    strategy = {
        "position_size": 0.1,
        "entry_conditions": {
            "min_volume": 1000000,
            "min_liquidity": 500000
        }
    }
    
    is_valid = order_manager.validate_order_parameters(token, strategy)
    assert is_valid is True

def test_validate_order_parameters_invalid(order_manager):
    """Test order parameter validation with invalid parameters."""
    token = {
        "address": "0x123",
        "name": "Test Token",
        "symbol": "TEST",
        "price": 1.0,
        "volume24h": 1000,
        "liquidity": 500
    }
    
    strategy = {
        "position_size": 1.5,  # Invalid position size
        "entry_conditions": {
            "min_volume": 1000000,
            "min_liquidity": 500000
        }
    }
    
    is_valid = order_manager.validate_order_parameters(token, strategy)
    assert is_valid is False 