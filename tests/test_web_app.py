import pytest
from unittest.mock import Mock, patch
from web.app import app
from config.settings import Settings

@pytest.fixture
def settings():
    return Settings()

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_index_route(client):
    """Test the index route."""
    response = client.get('/')
    assert response.status_code == 200
    assert b'SuperTradeX' in response.data

def test_scan_tokens_route(client):
    """Test the token scanning route."""
    with patch('web.app.TokenScanner') as mock_scanner:
        mock_scanner.return_value.scan_tokens.return_value = [
            {
                "address": "0x123",
                "name": "Test Token",
                "symbol": "TEST",
                "price": 1.0,
                "volume24h": 1000000,
                "liquidity": 500000
            }
        ]
        
        response = client.post('/scan_tokens')
        assert response.status_code == 200
        data = response.get_json()
        assert len(data['tokens']) == 1
        assert data['tokens'][0]['symbol'] == 'TEST'

def test_scan_tokens_route_error(client):
    """Test the token scanning route with error."""
    with patch('web.app.TokenScanner') as mock_scanner:
        mock_scanner.return_value.scan_tokens.side_effect = Exception("Scan error")
        
        response = client.post('/scan_tokens')
        assert response.status_code == 500
        data = response.get_json()
        assert 'error' in data

def test_start_trading_route(client):
    """Test the start trading route."""
    with patch('web.app.run_trading_loop') as mock_trading:
        response = client.post('/start_trading')
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'started'
        mock_trading.assert_called_once()

def test_stop_trading_route(client):
    """Test the stop trading route."""
    with patch('web.app.stop_trading_loop') as mock_stop:
        response = client.post('/stop_trading')
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'stopped'
        mock_stop.assert_called_once()

def test_get_trading_status_route(client):
    """Test the trading status route."""
    with patch('web.app.get_trading_status') as mock_status:
        mock_status.return_value = {
            'is_running': True,
            'last_scan': '2024-01-01T00:00:00',
            'tokens_found': 5
        }
        
        response = client.get('/trading_status')
        assert response.status_code == 200
        data = response.get_json()
        assert data['is_running'] is True
        assert 'last_scan' in data
        assert data['tokens_found'] == 5

def test_get_token_list_route(client):
    """Test the token list route."""
    with patch('web.app.TokenDatabase') as mock_db:
        mock_db.return_value.get_tokens.return_value = [
            {
                "address": "0x123",
                "name": "Test Token",
                "symbol": "TEST",
                "price": 1.0,
                "volume24h": 1000000,
                "liquidity": 500000
            }
        ]
        
        response = client.get('/tokens')
        assert response.status_code == 200
        data = response.get_json()
        assert len(data['tokens']) == 1
        assert data['tokens'][0]['symbol'] == 'TEST'

def test_get_trade_history_route(client):
    """Test the trade history route."""
    with patch('web.app.OrderManager') as mock_orders:
        mock_orders.return_value.get_trade_history.return_value = [
            {
                "token": "TEST",
                "type": "buy",
                "price": 1.0,
                "amount": 0.1,
                "timestamp": "2024-01-01T00:00:00"
            }
        ]
        
        response = client.get('/trade_history')
        assert response.status_code == 200
        data = response.get_json()
        assert len(data['trades']) == 1
        assert data['trades'][0]['token'] == 'TEST'

def test_update_settings_route(client):
    """Test the settings update route."""
    new_settings = {
        "min_volume": 2000000,
        "min_liquidity": 1000000,
        "position_size": 0.2
    }
    
    with patch('web.app.update_settings') as mock_update:
        response = client.post('/settings', json=new_settings)
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'updated'
        mock_update.assert_called_once_with(new_settings)

def test_get_settings_route(client):
    """Test the settings retrieval route."""
    with patch('web.app.get_settings') as mock_get:
        mock_get.return_value = {
            "min_volume": 1000000,
            "min_liquidity": 500000,
            "position_size": 0.1
        }
        
        response = client.get('/settings')
        assert response.status_code == 200
        data = response.get_json()
        assert data['min_volume'] == 1000000
        assert data['min_liquidity'] == 500000
        assert data['position_size'] == 0.1 