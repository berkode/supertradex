import pytest
import asyncio
from datetime import datetime
from unittest.mock import MagicMock
from data.monitoring import Monitoring
from data.token_database import TokenDatabase
from data.price_monitor import PriceMonitor
from data.delta_calculator import DeltaCalculator
from data.blockchain_listener import BlockchainListener
from data.data_fetcher import DataFetcher
from config.settings import Settings

# Dummy callback for BlockchainListener
async def dummy_callback(data):
    pass

@pytest.fixture
def monitoring():
    """Create a Monitoring instance for testing."""
    db = TokenDatabase()
    price_monitor = PriceMonitor()
    delta_calculator = DeltaCalculator(db, price_monitor)
    
    # Provide necessary args to BlockchainListener or mock it
    # Option 1: Mock Settings and provide dummy callback
    mock_settings = MagicMock(spec=Settings)
    # Set necessary attributes on mock_settings if listener uses them in init
    mock_settings.HELIUS_WSS_URL = "wss://test-endpoint.com"
    mock_settings.HELIUS_API_KEY = "test-key"
    mock_settings.MONITORED_PROGRAMS = "" # Empty for test if not needed
    
    blockchain_listener = BlockchainListener(settings=mock_settings, callback=dummy_callback)
    
    # Option 2: Mock the entire listener if its functionality isn't tested here
    # blockchain_listener = MagicMock(spec=BlockchainListener)
    
    data_fetcher = DataFetcher()
    return Monitoring(db, price_monitor, delta_calculator, blockchain_listener, data_fetcher)

@pytest.fixture
def sample_token_data():
    """Create sample token data for testing."""
    return {
        'mint': 'test_mint',
        'timestamp': datetime.now().timestamp(),
        'price': 100.0,
        'volume': 1000.0,
        'liquidity': 10000.0,
        'mcap': 100000.0,
        'txn_buys': 10,
        'txn_sells': 5,
        'txn_total': 15,
        'txn_buy_volume': 800.0,
        'txn_sell_volume': 200.0,
        'txn_total_volume': 1000.0
    }

@pytest.mark.asyncio
async def test_collect_timeframe_data(monitoring, sample_token_data):
    """Test data collection for a single timeframe."""
    # Mock the data sources to return sample data
    monitoring.blockchain_listener.get_token_data = lambda mint, timeframe: sample_token_data
    monitoring.data_fetcher.get_token_data = lambda mint, timeframe: sample_token_data
    
    # Test data collection for 1s timeframe
    data = await monitoring.collect_timeframe_data('test_mint', '1s')
    assert data is not None
    assert data['mint'] == 'test_mint'
    assert data['price'] == 100.0
    assert data['volume'] == 1000.0
    
    # Test data collection for 5s timeframe
    data = await monitoring.collect_timeframe_data('test_mint', '5s')
    assert data is not None
    assert data['mint'] == 'test_mint'
    assert data['price'] == 100.0
    assert data['volume'] == 1000.0

@pytest.mark.asyncio
async def test_monitor_token(monitoring, sample_token_data):
    """Test monitoring a single token."""
    # Mock the data sources to return sample data
    monitoring.blockchain_listener.get_token_data = lambda mint, timeframe: sample_token_data
    monitoring.data_fetcher.get_token_data = lambda mint, timeframe: sample_token_data
    
    # Create a callback to store deltas
    deltas = []
    async def delta_callback(delta):
        deltas.append(delta)
    
    # Monitor token for a short duration
    monitor_task = asyncio.create_task(
        monitoring.monitor_token('test_mint', delta_callback, interval=0.1)
    )
    
    # Wait for a few iterations
    await asyncio.sleep(0.5)
    
    # Cancel the monitoring task
    monitor_task.cancel()
    
    try:
        await monitor_task
    except asyncio.CancelledError:
        pass
    
    # Check that deltas were calculated
    assert len(deltas) > 0
    
    # Check delta structure
    for delta in deltas:
        assert 'mint' in delta
        assert 'timeframe' in delta
        assert 'metric_type' in delta
        assert 'short_value' in delta
        assert 'long_value' in delta
        assert 'absolute_change' in delta
        assert 'percentage_change' in delta

@pytest.mark.asyncio
async def test_monitor_tokens(monitoring, sample_token_data):
    """Test monitoring multiple tokens."""
    # Mock the data sources to return sample data
    monitoring.blockchain_listener.get_token_data = lambda mint, timeframe: sample_token_data
    monitoring.data_fetcher.get_token_data = lambda mint, timeframe: sample_token_data
    
    # Create a callback to store deltas
    deltas = []
    async def delta_callback(delta):
        deltas.append(delta)
    
    # Monitor multiple tokens
    tokens = ['test_mint1', 'test_mint2', 'test_mint3']
    monitor_task = asyncio.create_task(
        monitoring.monitor_tokens(tokens, delta_callback, interval=0.1)
    )
    
    # Wait for a few iterations
    await asyncio.sleep(0.5)
    
    # Cancel the monitoring task
    monitor_task.cancel()
    
    try:
        await monitor_task
    except asyncio.CancelledError:
        pass
    
    # Check that deltas were calculated for all tokens
    assert len(deltas) > 0
    
    # Check that we have deltas for each token
    token_deltas = {delta['mint'] for delta in deltas}
    assert all(token in token_deltas for token in tokens) 