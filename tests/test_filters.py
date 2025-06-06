import pytest
from filters.whitelist import Whitelist
from filters.blacklist import Blacklist
from config import FiltersConfig

def test_whitelist_initialization():
    """Test the initialization of the Whitelist class."""
    whitelist = Whitelist()
    assert isinstance(whitelist, Whitelist)
    assert isinstance(whitelist.criteria, dict)
    assert isinstance(whitelist.filtered_tokens, list)

def test_blacklist_initialization():
    """Test the initialization of the Blacklist class."""
    blacklist = Blacklist()
    assert isinstance(blacklist, Blacklist)
    assert isinstance(blacklist.criteria, dict)
    assert isinstance(blacklist.filtered_tokens, list)

def test_whitelist_build_from_filters():
    """Test building the whitelist from filters."""
    whitelist = Whitelist()
    whitelist.build_from_filters()
    assert len(whitelist.filtered_tokens) > 0

def test_blacklist_build_from_filters():
    """Test building the blacklist from filters."""
    blacklist = Blacklist()
    blacklist.build_from_filters()
    assert len(blacklist.filtered_tokens) > 0

def test_filters_config_initialization():
    """Test the initialization of the FiltersConfig class."""
    filters_config = FiltersConfig()
    assert isinstance(filters_config, FiltersConfig)
    assert isinstance(filters_config.criteria, dict)

def test_filters_config_criteria_content():
    """Test the content of the criteria in FiltersConfig."""
    filters_config = FiltersConfig()
    assert "min_market_cap" in filters_config.criteria
    assert "max_market_cap" in filters_config.criteria
    assert "min_liquidity" in filters_config.criteria
    assert "max_liquidity" in filters_config.criteria
    assert "min_volume" in filters_config.criteria
    assert "max_volume" in filters_config.criteria
    assert "min_age" in filters_config.criteria
    assert "max_age" in filters_config.criteria
    assert "min_txns" in filters_config.criteria
    assert "max_txns" in filters_config.criteria
    assert "min_buys" in filters_config.criteria
