import pytest
import pandas as pd
from datetime import datetime
from data.delta_calculator import DeltaCalculator
from data.token_database import TokenDatabase
from data.price_monitor import PriceMonitor

@pytest.fixture
def delta_calculator():
    """Create a DeltaCalculator instance for testing."""
    db = TokenDatabase()
    price_monitor = PriceMonitor()
    return DeltaCalculator(db, price_monitor)

@pytest.fixture
def sample_timeframe_data():
    """Create sample timeframe data for testing."""
    return {
        '1s': {
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
        },
        '5s': {
            'mint': 'test_mint',
            'timestamp': datetime.now().timestamp(),
            'price': 101.0,
            'volume': 1500.0,
            'liquidity': 10500.0,
            'mcap': 101000.0,
            'txn_buys': 15,
            'txn_sells': 8,
            'txn_total': 23,
            'txn_buy_volume': 1200.0,
            'txn_sell_volume': 300.0,
            'txn_total_volume': 1500.0
        }
    }

def test_validate_data(delta_calculator):
    """Test data validation."""
    # Test valid data
    valid_data = {
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
    assert delta_calculator._validate_data(valid_data) is True
    
    # Test invalid data (missing required fields)
    invalid_data = {
        'mint': 'test_mint',
        'timestamp': datetime.now().timestamp(),
        'price': 100.0
    }
    assert delta_calculator._validate_data(invalid_data) is False

def test_calculate_single_delta(delta_calculator, sample_timeframe_data):
    """Test single delta calculation."""
    short_data = sample_timeframe_data['1s']
    long_data = sample_timeframe_data['5s']
    
    # Test price delta
    delta = delta_calculator._calculate_single_delta(
        short_data, long_data, 'price', '1s_5s', 'test_mint'
    )
    assert delta is not None
    assert delta['metric_type'] == 'price'
    assert delta['short_value'] == 100.0
    assert delta['long_value'] == 101.0
    assert delta['absolute_change'] == -1.0
    assert delta['percentage_change'] == pytest.approx(-0.9901, rel=1e-4)
    
    # Test volume delta
    delta = delta_calculator._calculate_single_delta(
        short_data, long_data, 'volume', '1s_5s', 'test_mint'
    )
    assert delta is not None
    assert delta['metric_type'] == 'volume'
    assert delta['short_value'] == 1000.0
    assert delta['long_value'] == 1500.0
    assert delta['absolute_change'] == -500.0
    assert delta['percentage_change'] == pytest.approx(-33.3333, rel=1e-4)

def test_add_analytics(delta_calculator, sample_timeframe_data):
    """Test analytics addition to delta."""
    short_data = sample_timeframe_data['1s']
    long_data = sample_timeframe_data['5s']
    
    # Create a base delta
    delta = {
        'mint': 'test_mint',
        'timeframe': '1s_5s',
        'metric_type': 'price',
        'short_value': 100.0,
        'long_value': 101.0,
        'absolute_change': -1.0,
        'percentage_change': -0.9901
    }
    
    # Add analytics
    delta_with_analytics = delta_calculator._add_analytics(delta, short_data, long_data)
    
    # Check that analytics were added
    assert 'volatility' in delta_with_analytics
    assert 'volume_profile' in delta_with_analytics
    assert 'liquidity_metrics' in delta_with_analytics
    assert 'timestamp' in delta_with_analytics

@pytest.mark.asyncio
async def test_calculate_deltas(delta_calculator, sample_timeframe_data):
    """Test delta calculation for all metrics."""
    deltas = await delta_calculator.calculate_deltas('test_mint', sample_timeframe_data)
    
    # Check that deltas were calculated for each metric
    assert len(deltas) > 0
    metric_types = {delta['metric_type'] for delta in deltas}
    assert all(metric in metric_types for metric in delta_calculator.metric_types)
    
    # Check that each delta has the required fields
    for delta in deltas:
        assert 'mint' in delta
        assert 'timeframe' in delta
        assert 'metric_type' in delta
        assert 'short_value' in delta
        assert 'long_value' in delta
        assert 'absolute_change' in delta
        assert 'percentage_change' in delta
        assert 'short_timestamp' in delta
        assert 'long_timestamp' in delta
        assert 'volatility' in delta
        assert 'volume_profile' in delta
        assert 'liquidity_metrics' in delta
        assert 'timestamp' in delta 