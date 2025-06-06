import pytest
from data.data_fetcher import DataFetcher
from config import DexScreenerAPI
from config.raydium_api import RaydiumAPI

def test_data_fetcher_initialization():
    """Test the initialization of the DataFetcher class."""
    data_fetcher = DataFetcher()
    assert isinstance(data_fetcher, DataFetcher)
    assert isinstance(data_fetcher.dex_screener_api, DexScreenerAPI)
    assert isinstance(data_fetcher.raydium_api, RaydiumAPI)

def test_fetch_dexscreener_data():
    """Test fetching data from Dexscreener."""
    data_fetcher = DataFetcher()
    latest_data = data_fetcher.fetch_dexscreener_data()
    assert isinstance(latest_data, dict)

def test_fetch_raydium_data():
    """Test fetching data from Raydium."""
    data_fetcher = DataFetcher()
    latest_data = data_fetcher.fetch_raydium_data()
    assert isinstance(latest_data, dict)
