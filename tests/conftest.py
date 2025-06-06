import pytest
import os
from dotenv import load_dotenv

# Load test environment variables
load_dotenv("config/.env.test")

@pytest.fixture(autouse=True)
def setup_test_environment():
    """Setup test environment before each test."""
    # Set test-specific environment variables
    os.environ["SOLSNIFFER_API_KEY"] = "test_api_key"
    os.environ["SOLSNIFFER_API_URL"] = "https://test.api.solsniffer.com"
    os.environ["MIN_SOLSNIFFER_SCORE"] = "50"
    
    os.environ["SOLANATRACKER_API_KEY"] = "test_api_key"
    os.environ["SOLANATRACKER_URL"] = "https://test.api.solanatracker.com"
    
    os.environ["RUGCHECK_API_KEY"] = "test_api_key"
    os.environ["RUGCHECK_URL"] = "https://test.api.rugcheck.com"
    
    os.environ["OUTPUT_DIR"] = "tests/outputs"
    
    # Create output directory if it doesn't exist
    os.makedirs(os.environ["OUTPUT_DIR"], exist_ok=True)
    
    yield
    
    # Cleanup after each test
    # Remove test output files
    for file in os.listdir(os.environ["OUTPUT_DIR"]):
        os.remove(os.path.join(os.environ["OUTPUT_DIR"], file))

@pytest.fixture
def mock_async_client():
    """Create a mock async HTTP client."""
    class MockAsyncClient:
        async def aclose(self):
            pass
            
        async def get(self, *args, **kwargs):
            return MockResponse()
            
    class MockResponse:
        def __init__(self):
            self.status_code = 200
            
        async def json(self):
            return {"data": "test"}
            
    return MockAsyncClient()

@pytest.fixture
def mock_token_database():
    """Create a mock token database."""
    class MockTokenDatabase:
        async def add_or_update_token(self, token_data):
            pass
            
        async def get_token(self, token_mint):
            return None
            
        async def get_all_tokens(self):
            return []
            
    return MockTokenDatabase()

@pytest.fixture
def mock_settings():
    """Create mock settings."""
    class MockSettings:
        def __init__(self):
            self.api_timeout = 30
            self.max_retries = 3
            self.retry_delay = 1
            
    return MockSettings()

@pytest.fixture
def mock_thresholds():
    """Create mock thresholds."""
    class MockThresholds:
        def __init__(self):
            self.min_score = 50
            self.min_liquidity = 1000
            self.max_price_impact = 5
            
    return MockThresholds() 