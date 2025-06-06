import logging
from solders.pubkey import Pubkey
from solana.rpc.async_api import AsyncClient
from solana.rpc.core import RPCException
from typing import Dict, Optional, Any
import httpx
import asyncio

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("balance_checker.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class BalanceChecker:
    def __init__(self, 
                 solana_client: AsyncClient, 
                 wallet_pubkey: Pubkey, 
                 http_client: httpx.AsyncClient,
                 settings: Optional[Any] = None
                 ):
        if not solana_client or not wallet_pubkey or not http_client:
             raise ValueError("solana_client, wallet_pubkey, and http_client are required.")
             
        self.solana_client = solana_client
        self.wallet_pubkey = wallet_pubkey
        self.http_client = http_client
        self.settings = settings

        # Use settings for API endpoints
        self.dex_screener_api = getattr(settings, 'DEXSCREENER_API_URL')
        self.sol_price_api = getattr(settings, 'SOL_PRICE_API')

        logger.info(f"BalanceChecker initialized for wallet: {self.wallet_pubkey}")

    async def fetch_sol_price(self) -> float:
        retries = 3
        delay = 1
        for attempt in range(retries):
            try:
                response = await self.http_client.get(self.sol_price_api, timeout=10.0)
                response.raise_for_status()
                data = response.json()
                sol_price = data["solana"]["usd"]
                logger.info(f"Fetched SOL price: ${sol_price}")
                return float(sol_price)
            except (httpx.HTTPStatusError, httpx.RequestError, httpx.TimeoutException) as e:
                logger.warning(f"Attempt {attempt + 1}/{retries} failed fetching SOL price: {e}")
                if attempt == retries - 1:
                    logger.critical(f"Final attempt failed fetching SOL price after {retries} retries: {e}", exc_info=False)
                    return 0.0
                await asyncio.sleep(delay * (2 ** attempt))
            except Exception as e:
                logger.error(f"Unexpected error fetching SOL price: {e}", exc_info=True)
                return 0.0
        return 0.0

    async def fetch_token_metadata_from_dexscreener(self, token_address: str) -> Dict[str, Any]:
        default_meta = {"priceUsd": 0.0, "symbol": "UNKNOWN", "name": "Unknown Token"}
        retries = 3
        delay = 1
        for attempt in range(retries):
            try:
                url = f"{self.dex_screener_api}/latest/dex/tokens/{token_address}"
                logger.debug(f"Fetching DexScreener metadata from: {url} (Attempt {attempt+1})")
                response = await self.http_client.get(url, timeout=15.0)
                response.raise_for_status()
                data = response.json()

                pairs = data.get("pairs", [])
                if not pairs:
                    logger.warning(f"No DexScreener pair data found for token: {token_address}")
                    return default_meta

                pair_data = pairs[0]
                metadata = {
                    "priceUsd": float(pair_data.get("priceUsd", 0.0)),
                    "symbol": pair_data.get("baseToken", {}).get("symbol", "UNKNOWN"),
                    "name": pair_data.get("baseToken", {}).get("name", "Unknown Token")
                }
                logger.info(f"Fetched metadata for token {token_address}: {metadata}")
                return metadata
            except (httpx.HTTPStatusError, httpx.RequestError, httpx.TimeoutException) as e:
                logger.warning(f"Attempt {attempt + 1}/{retries} failed fetching metadata for {token_address}: {e}")
                if attempt == retries - 1:
                    logger.critical(f"Final attempt failed fetching metadata for {token_address} after {retries} retries: {e}", exc_info=False)
                    return default_meta
                await asyncio.sleep(delay * (2 ** attempt))
            except Exception as e:
                logger.error(f"Unexpected error fetching metadata for token {token_address}: {e}", exc_info=True)
                return default_meta
        return default_meta

    async def get_sol_balance(self) -> float:
        retries = 3
        delay = 1
        for attempt in range(retries):
            try:
                response = await self.solana_client.get_balance(self.wallet_pubkey)
                if response.value is not None:
                    balance_lamports = response.value
                    balance_sol = balance_lamports / 1e9
                    logger.debug(f"Fetched SOL balance for {self.wallet_pubkey}: {balance_sol} SOL")
                    return balance_sol
                logger.warning(f"Received null value for SOL balance request for {self.wallet_pubkey} (Attempt {attempt+1})")
                return 0.0
            except (RPCException, asyncio.TimeoutError) as e:
                logger.warning(f"Attempt {attempt + 1}/{retries} failed fetching SOL balance for {self.wallet_pubkey}: {e}")
                if attempt == retries - 1:
                    logger.critical(f"Final attempt failed fetching SOL balance for {self.wallet_pubkey} after {retries} retries: {e}", exc_info=False)
                    return 0.0
                await asyncio.sleep(delay * (2 ** attempt))
            except Exception as e:
                logger.error(f"Unexpected error fetching SOL balance for {self.wallet_pubkey}: {e}", exc_info=True)
                return 0.0
        return 0.0

    async def get_token_balance(self, token_mint_address: str) -> Optional[float]:
        retries = 3
        delay = 1
        for attempt in range(retries):
            try:
                mint_pubkey = Pubkey.from_string(token_mint_address)
                ata_response = await self.solana_client.get_token_accounts_by_owner(self.wallet_pubkey, mint=mint_pubkey)
                if ata_response.value:
                    account_data = ata_response.value[0].account.data
                    if isinstance(account_data, bytes):
                        balance_response = await self.solana_client.get_token_account_balance(ata_response.value[0].pubkey)
                        if balance_response.value:
                            return float(balance_response.value.ui_amount_string)
                        logger.warning(f"get_token_account_balance returned null for {token_mint_address} (Attempt {attempt+1})")
                        return None
                    elif hasattr(account_data, 'parsed'):
                        ui_amount = account_data.parsed.get('info', {}).get('tokenAmount', {}).get('uiAmountString')
                        if ui_amount is not None:
                            return float(ui_amount)
                        else:
                            logger.warning(f"Could not find uiAmountString in parsed data for {token_mint_address}")
                            return None
                    else:
                        logger.warning(f"Unexpected account data format for {token_mint_address}")
                        return None
                else:
                    logger.debug(f"No token account found for mint {token_mint_address} (Attempt {attempt+1})")
                    return 0.0
            except ValueError as e:
                logger.error(f"Invalid token mint address format: {token_mint_address} - {e}")
                return None
            except (RPCException, asyncio.TimeoutError) as e:
                logger.warning(f"Attempt {attempt + 1}/{retries} failed fetching balance for {token_mint_address}: {e}")
                if attempt == retries - 1:
                    logger.critical(f"Final attempt failed fetching balance for {token_mint_address} after {retries} retries: {e}", exc_info=False)
                    return None
                await asyncio.sleep(delay * (2 ** attempt))
            except Exception as e:
                logger.error(f"Unexpected error fetching balance for token {token_mint_address}: {e}", exc_info=True)
                return None
        return None

    async def close(self):
        logger.info("BalanceChecker closed (no owned resources).")
