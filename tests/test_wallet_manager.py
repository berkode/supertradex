import pytest
from unittest.mock import Mock, patch
from wallet.wallet_manager import WalletManager
from config.settings import Settings

@pytest.fixture
def settings():
    return Settings()

@pytest.fixture
def wallet_manager(settings):
    return WalletManager(settings)

def test_verify_wallet_setup(wallet_manager):
    """Test wallet setup verification."""
    with patch('wallet.wallet_manager.WalletManager._check_solana_cli', 
              return_value=True), \
         patch('wallet.wallet_manager.WalletManager._verify_wallet_address', 
              return_value=True):
        
        is_valid = wallet_manager.verify_wallet_setup()
        assert is_valid is True

def test_verify_wallet_setup_missing_cli(wallet_manager):
    """Test wallet setup verification with missing Solana CLI."""
    with patch('wallet.wallet_manager.WalletManager._check_solana_cli', 
              return_value=False):
        
        with pytest.raises(Exception) as exc_info:
            wallet_manager.verify_wallet_setup()
        assert "Solana CLI not found" in str(exc_info.value)

def test_verify_wallet_setup_invalid_address(wallet_manager):
    """Test wallet setup verification with invalid wallet address."""
    with patch('wallet.wallet_manager.WalletManager._check_solana_cli', 
              return_value=True), \
         patch('wallet.wallet_manager.WalletManager._verify_wallet_address', 
              return_value=False):
        
        with pytest.raises(Exception) as exc_info:
            wallet_manager.verify_wallet_setup()
        assert "Invalid wallet address" in str(exc_info.value)

@pytest.mark.asyncio
async def test_get_balance(wallet_manager):
    """Test getting wallet balance."""
    with patch('wallet.wallet_manager.WalletManager._execute_solana_command', 
              return_value="1.5"):
        
        balance = await wallet_manager.get_balance()
        assert isinstance(balance, float)
        assert balance == 1.5

@pytest.mark.asyncio
async def test_get_token_balance(wallet_manager):
    """Test getting token balance."""
    token_address = "0x123"
    
    with patch('wallet.wallet_manager.WalletManager._execute_solana_command', 
              return_value="100.0"):
        
        balance = await wallet_manager.get_token_balance(token_address)
        assert isinstance(balance, float)
        assert balance == 100.0

@pytest.mark.asyncio
async def test_sign_transaction(wallet_manager):
    """Test transaction signing."""
    transaction = "raw_transaction"
    
    with patch('wallet.wallet_manager.WalletManager._execute_solana_command', 
              return_value="signed_transaction"):
        
        signed_tx = await wallet_manager.sign_transaction(transaction)
        assert signed_tx == "signed_transaction"

@pytest.mark.asyncio
async def test_send_transaction(wallet_manager):
    """Test transaction sending."""
    signed_tx = "signed_transaction"
    
    with patch('wallet.wallet_manager.WalletManager._execute_solana_command', 
              return_value="0xabc"):
        
        tx_hash = await wallet_manager.send_transaction(signed_tx)
        assert tx_hash == "0xabc"

def test_validate_transaction(wallet_manager):
    """Test transaction validation."""
    transaction = {
        "to": "0x123",
        "value": 1.0,
        "data": "0x"
    }
    
    is_valid = wallet_manager.validate_transaction(transaction)
    assert is_valid is True

def test_validate_transaction_invalid(wallet_manager):
    """Test transaction validation with invalid transaction."""
    transaction = {
        "to": "0x123",
        "value": -1.0,  # Invalid value
        "data": "0x"
    }
    
    is_valid = wallet_manager.validate_transaction(transaction)
    assert is_valid is False

@pytest.mark.asyncio
async def test_get_transaction_history(wallet_manager):
    """Test getting transaction history."""
    with patch('wallet.wallet_manager.WalletManager._execute_solana_command', 
              return_value='[{"signature": "0x123", "status": "success"}]'):
        
        history = await wallet_manager.get_transaction_history()
        assert isinstance(history, list)
        assert len(history) == 1
        assert history[0]["signature"] == "0x123"
        assert history[0]["status"] == "success"
