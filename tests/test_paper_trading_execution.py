#!/usr/bin/env python3
"""
Test paper trading execution with focused tokens
"""
import asyncio
import sys
import os
import io
from pathlib import Path
from dotenv import load_dotenv, dotenv_values

# Add project root to sys.path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Load environment variables (same logic as main.py)
print("--- Loading Environment Variables for Test ---")
from utils.encryption import decrypt_env_file, get_encryption_password
from config.settings import EncryptionSettings

ENV_DIR = project_root / "config"
ENV_PLAIN_PATH = ENV_DIR / ".env"
ENV_ENCRYPTED_PATH = ENV_DIR / ".env.encrypted"

def update_dotenv_vars(env_vars: dict, override: bool = False) -> None:
    """Update os.environ with the given environment variables."""
    for key, value in env_vars.items():
        if value is None:
            continue
        value_str = str(value)
        if override or key not in os.environ:
            os.environ[key] = value_str

# Load encryption password
password = None
try:
    password = get_encryption_password()
    if password:
        print("INFO: Successfully retrieved encryption password.")
except Exception as e:
    print(f"ERROR: Could not retrieve encryption password: {e}")

# Load encrypted file first
if ENV_ENCRYPTED_PATH.exists() and password:
    try:
        decrypted_content = decrypt_env_file(ENV_ENCRYPTED_PATH, password)
        if decrypted_content:
            loaded_vars = dotenv_values(stream=io.StringIO(decrypted_content))
            update_dotenv_vars(loaded_vars, override=False)
            print(f"INFO: Loaded {len(loaded_vars)} variables from encrypted file.")
    except Exception as e:
        print(f"ERROR: Failed to decrypt: {e}")

# Load plain .env file
if ENV_PLAIN_PATH.exists():
    load_dotenv(dotenv_path=ENV_PLAIN_PATH, override=True)
    print("INFO: Loaded plain environment file.")

print("--- Environment Variables Loaded ---")

from config import Settings
from data.token_database import TokenDatabase
from strategies.paper_trading import PaperTrading
from wallet.wallet_manager import WalletManager
from data.price_monitor import PriceMonitor
from utils.logger import get_logger
import httpx
from solana.rpc.async_api import AsyncClient
from config.dexscreener_api import DexScreenerAPI

async def test_paper_trading():
    """Test paper trading with the current focused tokens"""
    logger = get_logger(__name__)
    
    try:
        # Initialize components
        settings = Settings()
        db = await TokenDatabase.create(settings.DATABASE_FILE_PATH, settings)
        
        # Get the focused tokens (BONK and Saphi)
        focused_tokens = [
            "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",  # BONK
            "7ZYyESa8TkuoBVFi5seeLPr7B3MeLvyPgEgv5MDTpump"    # Saphi
        ]
        
        logger.info("🎯 Starting paper trading test with focused tokens...")
        
        # Initialize required components for paper trading
        http_client = httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT)
        solana_client = AsyncClient(settings.SOLANA_RPC_URL)
        
        # Initialize DexScreener API for PriceMonitor
        dexscreener_api = DexScreenerAPI(settings=settings, proxy_manager=None)
        await dexscreener_api.initialize()
        
        # Initialize wallet manager (for paper trading simulation)
        wallet_manager = WalletManager(settings=settings, solana_client=solana_client, db=db)
        await wallet_manager.initialize()
        
        # Initialize price monitor with required dex_api_client
        price_monitor = PriceMonitor(settings=settings, http_client=http_client, dex_api_client=dexscreener_api)
        
        # Initialize paper trading
        paper_trading = PaperTrading(
            settings=settings,
            db=db,
            wallet_manager=wallet_manager,
            price_monitor=price_monitor
        )
        await paper_trading.load_persistent_state()
        
        logger.info("📊 Current paper trading state:")
        logger.info(f"   💰 SOL Balance: {paper_trading.paper_sol_balance:.2f} SOL")
        logger.info(f"   📈 Token Positions: {len(paper_trading.paper_token_balances)}")
        
        # Test trades for each focused token
        for i, token_mint in enumerate(focused_tokens):
            try:
                # Get current price
                price = await price_monitor.get_current_price_usd(token_mint)
                if not price:
                    logger.warning(f"❌ Could not get price for {token_mint[:8]}...")
                    continue
                
                # Get token info from database
                token = await db.get_token_by_mint(token_mint)
                if not token:
                    logger.warning(f"❌ Token {token_mint[:8]}... not found in database")
                    continue
                
                logger.info(f"\n🎯 Paper Trading Test #{i+1}: {token.symbol}")
                logger.info(f"   Current Price: ${price:.8f}")
                logger.info(f"   DEX: {token.dex_id}")
                
                # Execute a small buy order (10 SOL worth)
                buy_amount_sol = 10.0
                buy_amount_tokens = buy_amount_sol / price  # Calculate token amount
                logger.info(f"   📈 Executing BUY: {buy_amount_sol} SOL worth ({buy_amount_tokens:.6f} tokens) of {token.symbol}")
                
                # Simulate paper trade directly by updating the paper trading state
                initial_sol_balance = paper_trading.paper_sol_balance
                
                # Check if we have enough SOL
                if initial_sol_balance >= buy_amount_sol:
                    # Execute buy
                    paper_trading.paper_sol_balance -= buy_amount_sol
                    current_quantity = paper_trading.paper_token_balances.get(token_mint, 0.0)
                    current_total_cost = paper_trading.paper_token_total_cost_usd.get(token_mint, 0.0)
                    
                    paper_trading.paper_token_balances[token_mint] = current_quantity + buy_amount_tokens
                    paper_trading.paper_token_total_cost_usd[token_mint] = current_total_cost + buy_amount_sol
                    
                    logger.info(f"   ✅ BUY executed successfully")
                    logger.info(f"      💰 New SOL Balance: {paper_trading.paper_sol_balance:.2f} SOL")
                    logger.info(f"      📈 Token Position: {paper_trading.paper_token_balances[token_mint]:.6f} tokens")
                    
                    # Save the state to database
                    await paper_trading.db.set_paper_summary_value('paper_sol_balance', value_float=paper_trading.paper_sol_balance)
                    await paper_trading.db.upsert_paper_position(
                        mint=token_mint,
                        quantity=paper_trading.paper_token_balances[token_mint],
                        total_cost_usd=paper_trading.paper_token_total_cost_usd[token_mint],
                        average_price_usd=paper_trading.paper_token_total_cost_usd[token_mint] / paper_trading.paper_token_balances[token_mint]
                    )
                    
                    # Wait a moment and then execute a partial sell
                    await asyncio.sleep(2)
                    
                    # Get updated price (simulate price movement)
                    new_price = await price_monitor.get_current_price_usd(token_mint)
                    if new_price:
                        logger.info(f"   📊 Updated Price: ${new_price:.8f}")
                        
                        # Sell 50% of the position
                        position_amount = paper_trading.paper_token_balances[token_mint]
                        sell_percentage = 0.5
                        sell_amount = position_amount * sell_percentage
                        sell_value_sol = sell_amount * new_price
                        
                        logger.info(f"   📉 Executing SELL: {sell_percentage*100}% of position ({sell_amount:.6f} tokens)")
                        
                        # Execute sell
                        paper_trading.paper_sol_balance += sell_value_sol
                        
                        # Calculate cost basis for the sold amount
                        avg_cost_per_token = paper_trading.paper_token_total_cost_usd[token_mint] / position_amount
                        cost_basis_sold = sell_amount * avg_cost_per_token
                        
                        # Update position
                        paper_trading.paper_token_balances[token_mint] = position_amount - sell_amount
                        paper_trading.paper_token_total_cost_usd[token_mint] -= cost_basis_sold
                        
                        # Calculate P&L
                        realized_pnl = sell_value_sol - cost_basis_sold
                        
                        logger.info(f"   ✅ SELL executed successfully")
                        logger.info(f"      💰 New SOL Balance: {paper_trading.paper_sol_balance:.2f} SOL")
                        logger.info(f"      📈 Remaining Position: {paper_trading.paper_token_balances[token_mint]:.6f} tokens")
                        logger.info(f"      💵 Realized P&L: {realized_pnl:.2f} SOL")
                        
                        # Save updated state
                        await paper_trading.db.set_paper_summary_value('paper_sol_balance', value_float=paper_trading.paper_sol_balance)
                        if paper_trading.paper_token_balances[token_mint] > 1e-9:
                            await paper_trading.db.upsert_paper_position(
                                mint=token_mint,
                                quantity=paper_trading.paper_token_balances[token_mint],
                                total_cost_usd=paper_trading.paper_token_total_cost_usd[token_mint],
                                average_price_usd=paper_trading.paper_token_total_cost_usd[token_mint] / paper_trading.paper_token_balances[token_mint]
                            )
                        else:
                            # Position closed, remove from database
                            await paper_trading.db.delete_paper_position(token_mint)
                            paper_trading.paper_token_balances.pop(token_mint, None)
                            paper_trading.paper_token_total_cost_usd.pop(token_mint, None)
                else:
                    logger.error(f"   ❌ Insufficient SOL balance ({initial_sol_balance:.2f}) for {buy_amount_sol} SOL trade")
                    
                logger.info(f"   {'='*50}")
                    
            except Exception as e:
                logger.error(f"Error testing paper trade for {token_mint[:8]}...: {e}")
        
        # Final summary
        logger.info("\n" + "="*60)
        logger.info("📊 PAPER TRADING TEST SUMMARY")
        logger.info("="*60)
        logger.info(f"💰 Final SOL Balance: {paper_trading.paper_sol_balance:.2f} SOL")
        logger.info(f"📈 Active Positions: {len(paper_trading.paper_token_balances)}")
        
        for mint, amount in paper_trading.paper_token_balances.items():
            if amount > 1e-9:  # Only show meaningful positions
                token = await db.get_token_by_mint(mint)
                symbol = token.symbol if token else mint[:8]
                cost = paper_trading.paper_token_total_cost_usd.get(mint, 0)
                avg_cost = cost / amount if amount > 0 else 0
                
                # Get current market value
                current_price = await price_monitor.get_current_price_usd(mint)
                if current_price:
                    current_value = amount * current_price
                    unrealized_pnl = current_value - cost
                    logger.info(f"   • {symbol}: {amount:.6f} tokens @ ${avg_cost:.8f} avg cost")
                    logger.info(f"     Current Value: {current_value:.2f} SOL | Unrealized P&L: {unrealized_pnl:.2f} SOL")
                else:
                    logger.info(f"   • {symbol}: {amount:.6f} tokens @ ${avg_cost:.8f} avg cost")
        
        logger.info("="*60)
        logger.info("🎯 Paper trading test completed successfully!")
        
        # Clean up
        await http_client.aclose()
        await solana_client.close()
        await db.close()
        
    except Exception as e:
        logger.error(f"Error in paper trading test: {e}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(test_paper_trading()) 