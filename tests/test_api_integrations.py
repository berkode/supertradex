import pytest
import aiohttp
from unittest.mock import Mock, patch
from config.settings import Settings
from api.dexscreener_api import DexScreenerAPI
from api.rugcheck_api import RugCheckAPI
from api.solsniffer_api import SolSnifferAPI
from api.twitter_api import TwitterAPI

@pytest.fixture
def settings():
    return Settings()

@pytest.fixture
def dexscreener_api(settings):
    return DexScreenerAPI(settings)

@pytest.fixture
def rugcheck_api(settings):
    return RugCheckAPI(settings)

@pytest.fixture
def solsniffer_api(settings):
    return SolSnifferAPI(settings)

@pytest.fixture
def twitter_api(settings):
    return TwitterAPI(settings)

@pytest.mark.asyncio
async def test_dexscreener_get_trending_tokens(dexscreener_api):
    """Test DexScreener trending tokens endpoint."""
    mock_response = {
        "pairs": [
            {
                "baseToken": {
                    "address": "0x123",
                    "name": "Test Token",
                    "symbol": "TEST"
                },
                "priceUsd": "1.0",
                "volume24h": "1000000",
                "liquidity": "500000"
            }
        ]
    }
    
    with patch('aiohttp.ClientSession.get') as mock_get:
        mock_get.return_value.__aenter__.return_value.json = Mock(
            return_value=mock_response
        )
        
        tokens = await dexscreener_api.get_trending_tokens()
        assert len(tokens) == 1
        assert tokens[0]["address"] == "0x123"
        assert tokens[0]["symbol"] == "TEST"

@pytest.mark.asyncio
async def test_dexscreener_get_token_details(dexscreener_api):
    """Test DexScreener token details endpoint."""
    token_address = "0x123"
    mock_response = {
        "pairs": [
            {
                "priceUsd": "1.0",
                "volume24h": "1000000",
                "liquidity": "500000",
                "priceChange24h": "10.0"
            }
        ]
    }
    
    with patch('aiohttp.ClientSession.get') as mock_get:
        mock_get.return_value.__aenter__.return_value.json = Mock(
            return_value=mock_response
        )
        
        details = await dexscreener_api.get_token_details(token_address)
        assert details["price"] == 1.0
        assert details["volume24h"] == 1000000
        assert details["liquidity"] == 500000

@pytest.mark.asyncio
async def test_rugcheck_validate_token(rugcheck_api):
    """Test RugCheck token validation endpoint."""
    token_address = "0x123"
    mock_response = {
        "score": 0.8,
        "risk_level": "low",
        "warnings": []
    }
    
    with patch('aiohttp.ClientSession.post') as mock_post:
        mock_post.return_value.__aenter__.return_value.json = Mock(
            return_value=mock_response
        )
        
        result = await rugcheck_api.validate_token(token_address)
        assert result["score"] == 0.8
        assert result["risk_level"] == "low"

@pytest.mark.asyncio
async def test_solsniffer_validate_token(solsniffer_api):
    """Test SolSniffer token validation endpoint."""
    token_address = "0x123"
    mock_response = {
        "score": 0.7,
        "holders": 1000,
        "transactions": 5000,
        "risk_factors": []
    }
    
    with patch('aiohttp.ClientSession.get') as mock_get:
        mock_get.return_value.__aenter__.return_value.json = Mock(
            return_value=mock_response
        )
        
        result = await solsniffer_api.validate_token(token_address)
        assert result["score"] == 0.7
        assert result["holders"] == 1000

@pytest.mark.asyncio
async def test_twitter_get_token_info(twitter_api):
    """Test Twitter token information endpoint."""
    token_symbol = "TEST"
    mock_response = {
        "followers_count": 1000,
        "tweet_count": 500,
        "sentiment_score": 0.6
    }
    
    with patch('tweepy.API') as mock_api:
        mock_api.return_value.get_user.return_value = Mock(
            followers_count=1000,
            statuses_count=500
        )
        
        result = await twitter_api.get_token_info(token_symbol)
        assert result["followers"] == 1000
        assert result["tweets"] == 500

@pytest.mark.asyncio
async def test_api_error_handling(dexscreener_api):
    """Test API error handling."""
    with patch('aiohttp.ClientSession.get') as mock_get:
        mock_get.return_value.__aenter__.return_value.raise_for_status = Mock(
            side_effect=aiohttp.ClientError("API Error")
        )
        
        with pytest.raises(Exception) as exc_info:
            await dexscreener_api.get_trending_tokens()
        assert "API Error" in str(exc_info.value)

@pytest.mark.asyncio
async def test_api_rate_limiting(dexscreener_api):
    """Test API rate limiting."""
    with patch('aiohttp.ClientSession.get') as mock_get:
        mock_get.return_value.__aenter__.return_value.status = 429
        mock_get.return_value.__aenter__.return_value.json = Mock(
            return_value={"error": "Rate limit exceeded"}
        )
        
        with pytest.raises(Exception) as exc_info:
            await dexscreener_api.get_trending_tokens()
        assert "Rate limit exceeded" in str(exc_info.value)

@pytest.mark.asyncio
async def test_api_timeout_handling(dexscreener_api):
    """Test API timeout handling."""
    with patch('aiohttp.ClientSession.get') as mock_get:
        mock_get.return_value.__aenter__.return_value.raise_for_status = Mock(
            side_effect=asyncio.TimeoutError("Request timed out")
        )
        
        with pytest.raises(Exception) as exc_info:
            await dexscreener_api.get_trending_tokens()
        assert "Request timed out" in str(exc_info.value)

@pytest.mark.asyncio
async def test_api_invalid_response(dexscreener_api):
    """Test API invalid response handling."""
    mock_response = {"invalid": "response"}
    
    with patch('aiohttp.ClientSession.get') as mock_get:
        mock_get.return_value.__aenter__.return_value.json = Mock(
            return_value=mock_response
        )
        
        with pytest.raises(Exception) as exc_info:
            await dexscreener_api.get_trending_tokens()
        assert "Invalid response format" in str(exc_info.value) 