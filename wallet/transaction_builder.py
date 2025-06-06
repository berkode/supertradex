import os
import json
import asyncio
import httpx
from solders.pubkey import Pubkey
from solders.transaction import Transaction
from solders.instruction import Instruction, AccountMeta
from solana.rpc.async_api import AsyncClient
from solana.rpc.types import TxOpts  # Changed from solders
from dotenv import load_dotenv
import logging
from solders.system_program import ID as SYS_PROGRAM_ID
from solders.token import ID as TOKEN_PROGRAM_ID
from spl.token.instructions import get_associated_token_address, create_associated_token_account, close_account, sync_native
from solders.sysvar import RENT as SYSVAR_RENT_PUBKEY
import borsh_construct as borsh
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
from spl.token.constants import TOKEN_PROGRAM_ID, ASSOCIATED_TOKEN_PROGRAM_ID
from spl.token.instructions import get_associated_token_address
import math
from decimal import Decimal
from typing import Tuple, Dict, Any, Optional, List
from solders.system_program import transfer, TransferParams
import struct
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from solders.message import MessageV0
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
from spl.token.instructions import (
    create_associated_token_account,
    get_associated_token_address,
    sync_native,
    SyncNativeParams,
    close_account,
    CloseAccountParams
)
# from solders.rpc.types import TokenAccountOpts  # Keep commented
from solana.rpc.commitment import Processed  # Changed from solders
# from solders.rpc.commitment import Confirmed # Keep commented
import construct
from utils.helpers import *
from filters.bonding_curve import BondingCurveCalculator
from datetime import datetime
import base58
import time

# Load environment variables from .env
# load_dotenv(dotenv_path='../config/.env')

logger = logging.getLogger(__name__) # Use module-level logger

# --- Constants (Verify These!) ---
# Raydium Liquidity Pool V4 Program ID
RAYDIUM_LIQUIDITY_PROGRAM_ID_V4 = Pubkey.from_string("675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8")
# Serum Dex Program ID (check which version the pool uses)
# SERUM_DEX_PROGRAM_ID = Pubkey.from_string("9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin") # Example V3
# Open Orders Program ID (usually same as Token Program ID)
OPEN_ORDERS_PROGRAM_ID = TOKEN_PROGRAM_ID

# --- Add Pump.fun Constants (Verified) ---
PUMPFUN_PROGRAM_ID = Pubkey.from_string("6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P") # Correct Pump.fun Program ID
# You might need other Pump.fun related addresses (Global state, fee recipient?)
# Example Global Account (Verify if still needed/correct):
# PUMPFUN_GLOBAL_ACCOUNT = Pubkey.from_string("4wTV1YmiEkRvAtNtsSGPtUrqRYQMe5SKy2uB4Jjaxnjf")
# Example Fee Recipient (Verify if still needed/correct):
# PUMPFUN_FEE_RECIPIENT = Pubkey.from_string("CebN5WGQ4jvEPvsVU4EoHEpgzq1VV7AbicfhtW4xC9iM")

# --- Solana Mainnet SOL Mint ---
SOL_MINT_ADDRESS = "So11111111111111111111111111111111111111112"
SOL_MINT = Pubkey.from_string(SOL_MINT_ADDRESS) # Define SOL_MINT Pubkey
# --- Define WSOL_MINT (often same as SOL_MINT on mainnet) ---
WSOL_MINT = SOL_MINT # Explicitly define WSOL_MINT

# --- Add Pump.fun AMM Constants (From IDL) ---
PUMPFUN_AMM_PROGRAM_ID = Pubkey.from_string("pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA") # PumpSwap Program ID
# Calculate the Global Config PDA for PumpSwap
PUMPFUN_AMM_GLOBAL_CONFIG_PDA, _ = Pubkey.find_program_address(
    [b"global_config"], PUMPFUN_AMM_PROGRAM_ID
)
# Calculate the Event Authority PDA for PumpSwap
PUMPFUN_AMM_EVENT_AUTHORITY_PDA, _ = Pubkey.find_program_address(
    [b"__event_authority"], PUMPFUN_AMM_PROGRAM_ID
)

# --- System Program and Token Program IDs ---
# SYS_PROGRAM_ID = Pubkey.from_string("11111111111111111111111111111111") # Use solders.system_program.ID
# TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA") # Use spl.token.constants.TOKEN_PROGRAM_ID
TOKEN_2022_PROGRAM_ID = Pubkey.from_string("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb") # Needed for PumpSwap LP mints / potentially base/quote
# ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL") # Use spl.token.constants.ASSOCIATED_TOKEN_PROGRAM_ID

# --- Corrected PUBKEY Definition ---
# Use construct.Bytes for fixed-size byte arrays with borsh-construct 0.1.0
PUBKEY = construct.Bytes(32)
# --- End Correction ---

# --- !! VERIFY THESE DISCRIMINATORS !! ---
# Placeholder values - derive from sha256("global:buy")[:8] and sha256("global:sell")[:8]
# for the specific pAMMBay... program ID.
# Example derivation (replace with actual values):
# python -c 'import hashlib; print(hashlib.sha256(b"global:buy").digest()[:8].hex())'
# python -c 'import hashlib; print(hashlib.sha256(b"global:sell").digest()[:8].hex())'
# Common values might look like this, but VERIFY:
PUMP_BUY_DISCRIMINATOR = bytes.fromhex("f2360253234a70a1") # Example - VERIFY!
PUMP_SELL_DISCRIMINATOR = bytes.fromhex("51a01577c43575c1") # Example - VERIFY!
# --- !! END VERIFY !! ---

# Pool Account Structure
PUMPSWAP_POOL_SCHEMA = borsh.CStruct(
    # Discriminator is usually handled separately or prepended
    "pool_bump" / borsh.U8,
    "index" / borsh.U16,
    # Padding might exist here depending on Anchor alignment, check anchorpy or solana-py generated client if possible
    # Assuming standard alignment for now
    "creator" / PUBKEY, # Use the defined PUBKEY type
    "base_mint" / PUBKEY, # Use the defined PUBKEY type
    "quote_mint" / PUBKEY, # Use the defined PUBKEY type
    "lp_mint" / PUBKEY, # Use the defined PUBKEY type
    "pool_base_token_account" / PUBKEY, # Use the defined PUBKEY type
    "pool_quote_token_account" / PUBKEY, # Use the defined PUBKEY type
    "lp_supply" / borsh.U64,
    # Add any other fields from the IDL's Pool struct if necessary
)

# GlobalConfig Account Structure
PUMPSWAP_GLOBAL_CONFIG_SCHEMA = borsh.CStruct(
    # Discriminator is usually handled separately or prepended
    "admin" / PUBKEY, # Use the defined PUBKEY type
    "lp_fee_basis_points" / borsh.U64,
    "protocol_fee_basis_points" / borsh.U64,
    "disable_flags" / borsh.U8,
    # Padding might exist here
    "protocol_fee_recipients" / construct.Array(8, PUBKEY), # Use construct.Array and PUBKEY
    # Add any other fields from the IDL's GlobalConfig struct if necessary
)

# SPL Token Account Data Structure (Simplified)
SPL_ACCOUNT_LAYOUT = borsh.CStruct(
    "mint" / PUBKEY,
    "owner" / PUBKEY,
    "amount" / borsh.U64,
    "delegate_option" / borsh.U32,
    "delegate" / PUBKEY,
    "state" / borsh.U8,
    "is_native_option" / borsh.U32,
    "is_native" / borsh.U64,
    "delegated_amount" / borsh.U64,
    "close_authority_option" / borsh.U32,
    "close_authority" / PUBKEY,
)

# SPL Mint Layout (Standard)
SPL_MINT_LAYOUT = borsh.CStruct(
    "mint_authority_option" / borsh.U32,
    "mint_authority" / borsh.U8[32],
    "supply" / borsh.U64,
    "decimals" / borsh.U8,
    "is_initialized" / borsh.Bool,
    "freeze_authority_option" / borsh.U32,
    "freeze_authority" / borsh.U8[32],
)

# --- Add Buy/Sell Instruction Schemas ---
PUMPSWAP_BUY_SCHEMA = borsh.CStruct(
    "discriminator" / construct.Bytes(8), # 8-byte instruction discriminator
    "amount_in" / borsh.U64,              # Amount of quote token (usually SOL/WSOL lamports)
    "min_amount_out" / borsh.U64          # Minimum amount of base token expected
)

PUMPSWAP_SELL_SCHEMA = borsh.CStruct(
    "discriminator" / construct.Bytes(8), # 8-byte instruction discriminator
    "amount_in" / borsh.U64,              # Amount of base token
    "min_amount_out" / borsh.U64          # Minimum amount of quote token (usually SOL/WSOL lamports) expected
)
# --- End Buy/Sell Schemas ---

# Derive the fee recipient ATA if not defined explicitly
try:
    RAYDIUM_POOL_LAYOUT_V4 = borsh.CStruct(
        "status" / borsh.U64,
        "nonce" / borsh.U64,
        "max_order" / borsh.U64,
        "depth" / borsh.U64,
        "base_decimal" / borsh.U64,
        "quote_decimal" / borsh.U64,
        "state" / borsh.U64,
        "reset_flag" / borsh.U64,
        "min_size" / borsh.U64,
        "vol_max_cut_ratio" / borsh.U64,
        "amount_wave_ratio" / borsh.U64,
        "base_lot_size" / borsh.U64,
        "quote_lot_size" / borsh.U64,
        "min_price_multiplier" / borsh.U64,
        "max_price_multiplier" / borsh.U64,
        "system_decimal_value" / borsh.U64,
        "min_separate_numerator" / borsh.U64,
        "min_separate_denominator" / borsh.U64,
        "trade_fee_numerator" / borsh.U64,
        "trade_fee_denominator" / borsh.U64,
        "pnl_numerator" / borsh.U64,
        "pnl_denominator" / borsh.U64,
        "swap_fee_numerator" / borsh.U64,
        "swap_fee_denominator" / borsh.U64,
        "base_need_take_pnl" / borsh.U64,
        "quote_need_take_pnl" / borsh.U64,
        "quote_total_pnl" / borsh.U64,
        "base_total_pnl" / borsh.U64,
        "pool_open_time" / borsh.U64, # u128 little endian
        "punish_pc_amount" / borsh.U64,
        "punish_coin_amount" / borsh.U64,
        "orderbook_to_init_time" / borsh.U64,
        "swap_base_in_amount" / borsh.U128,
        "swap_quote_out_amount" / borsh.U128,
        "swap_base_out_amount" / borsh.U128,
        "swap_quote_in_amount" / borsh.U128,
        "swap_base_to_quote_fee" / borsh.U64, # u128 little endian
        "swap_quote_to_base_fee" / borsh.U64,
        "pool_base_vault" / PUBKEY, # borsh.Bytes(32)
        "pool_quote_vault" / PUBKEY, # borsh.Bytes(32)
        "base_mint" / PUBKEY, # borsh.Bytes(32)
        "quote_mint" / PUBKEY, # borsh.Bytes(32)
        "lp_mint" / PUBKEY, # borsh.Bytes(32)
        "open_orders" / PUBKEY, # borsh.Bytes(32)
        "market_id" / PUBKEY, # borsh.Bytes(32)
        "market_program_id" / PUBKEY, # borsh.Bytes(32)
        "target_orders" / PUBKEY, # borsh.Bytes(32)
        "withdraw_queue" / PUBKEY, # borsh.Bytes(32)
        "lp_vault" / PUBKEY, # borsh.Bytes(32)
        "owner" / PUBKEY, # borsh.Bytes(32)
        "lp_reserve" / borsh.U64, # u128 little endian
        # --- Corrected line: Use construct.Array ---
        "protocol_fee_recipients" / construct.Array(8, PUBKEY), # Array of 8 Pubkeys
        "padding" / construct.Padding(64) # Adjust padding if necessary based on exact layout
    )
except ImportError as e:
    # Handle potential import errors for borsh_construct or construct
    logger.error(f"Import error during borsh layout definition: {e}. Ensure 'borsh-construct' and 'construct' are installed.")
    RAYDIUM_POOL_LAYOUT_V4 = None
except AttributeError as e:
    logger.error(f"Attribute error during borsh layout definition: {e}. Check borsh_construct/construct version/syntax.")
    RAYDIUM_POOL_LAYOUT_V4 = None
except Exception as e:
    logger.error(f"Unexpected error defining borsh layout: {e}")
    RAYDIUM_POOL_LAYOUT_V4 = None

# --- Helper Placeholder Functions (Implement These!) ---

async def calculate_min_amount_out(pool_or_curve_info: dict, input_amount: int, slippage_bps: int, platform: str) -> int:
    """
    Placeholder: Calculate minimum output amount based on pool/curve state and slippage.
    Requires fetching real-time reserves/curve state.
    """
    logger.warning(f"Slippage calculation for {platform} is using a placeholder. Implement actual logic!")
    # --- !!! IMPLEMENT ACTUAL CALCULATION HERE !!! ---
    expected_output = 0
    if not pool_or_curve_info:
         logger.error("Cannot calculate min_amount_out without pool/curve info.")
         return 0 # Or raise error

    try:
        if platform == 'raydium_v4':
            # Example: Needs actual reserve keys from your fetched pool_info
            # reserve_in = float(pool_or_curve_info['inputTokenReserve'])
            # reserve_out = float(pool_or_curve_info['outputTokenReserve'])
            # fee = 0.0025 # Example fee
            # if reserve_in == 0 or reserve_out == 0: return 0
            # amount_in_after_fee = input_amount * (1 - fee)
            # expected_output = (reserve_out * amount_in_after_fee) / (reserve_in + amount_in_after_fee)
            logger.info("Raydium slippage calculation needs implementation.")
            pass # Replace with actual AMM calculation using pool_info keys
        elif platform == 'pump_fun':
            # Example: Needs actual curve keys from your fetched curve_info
            # virtual_sol = float(pool_or_curve_info['virtualSolReserves'])
            # virtual_token = float(pool_or_curve_info['virtualTokenReserves'])
            # Use bonding curve formula to calculate expected output for 'input_amount'
            logger.info("Pump.fun slippage calculation needs implementation.")
            pass # Replace with actual bonding curve calculation
        elif platform == 'pump_fun_amm':
             # Needs implementation based on Pump.fun AMM formula and pool_info keys
             logger.info("Pump.fun AMM slippage calculation needs implementation.")
             pass
        else:
            logger.error(f"Unsupported platform for slippage calculation: {platform}")
            return 0

        if expected_output > 0:
            min_out = int(expected_output * (1 - slippage_bps / 10000))
            logger.info(f"Calculated expected_output: {expected_output}, min_amount_out: {min_out}")
            return min_out
        else:
            # If expected output couldn't be calculated, return 0 (or handle error)
            # For safety, we might return 0 to prevent swaps with no minimum guarantee
            logger.warning("Could not calculate expected output, returning 0 for min_amount_out.")
            return 0
    except KeyError as e:
         logger.error(f"Missing key in pool/curve info for slippage calculation: {e}")
         return 0
    except Exception as e:
         logger.error(f"Error calculating slippage: {e}", exc_info=True)
         return 0

# Assume get_associated_token_address is available (e.g., from spl-token library)
# from spl.token.instructions import get_associated_token_address

class TransactionBuilder:
    """
    Provides utility functions for building and sending basic Solana transactions.
    NOTE: Complex swap transaction construction has been removed in favor of using
    an aggregator like Jupiter via OrderManager.
    This class primarily handles transaction sending and potentially simple
    instruction building (e.g., transfers, ATA management) if needed.
    """
    def __init__(self, solana_client: AsyncClient, http_client: Optional[httpx.AsyncClient] = None):
        """
        Initializes the TransactionBuilder.

        Args:
            solana_client: An initialized solana.rpc.async_api.AsyncClient instance.
            http_client: An optional initialized httpx.AsyncClient for external API calls (if any remain).
        """
        self.client = solana_client # Use the passed Solana client
        self.http_client = http_client # Store the passed http client, if still needed
        logger.info("TransactionBuilder initialized.")

    async def _get_mint_info(self, mint_pubkey: Pubkey) -> Tuple[int, Pubkey]:
        """Fetches mint decimals and token program owner."""
        if mint_pubkey == SOL_MINT:
            return 9, TOKEN_PROGRAM_ID # Treat WSOL as standard Token Program owned

        logger.debug(f"Fetching mint info for {mint_pubkey}...") # Changed level to debug
        try:
            acc_info = await self.client.get_account_info(mint_pubkey)
            if not acc_info or not acc_info.value:
                raise ValueError(f"Mint account not found or empty: {mint_pubkey}")

            owner = acc_info.value.owner
            data = acc_info.value.data

            if owner == TOKEN_2022_PROGRAM_ID:
                logger.warning(f"Mint {mint_pubkey} is owned by Token-2022 ({TOKEN_2022_PROGRAM_ID}). "
                               f"Parsing basic decimals only.")
                # Basic parsing attempt (adjust offset/layout if known)
                try:
                     # Standard SPL Mint layout offset for decimals is 44
                     decimals = int.from_bytes(data[44:45], 'little')
                     logger.debug(f"Parsed decimals for Token-2022 {mint_pubkey}: {decimals}")
                     return decimals, owner
                except IndexError:
                     logger.warning(f"Could not parse decimals for Token-2022 {mint_pubkey} at standard offset, data length {len(data)}. Defaulting to 6.")
                     return 6, owner # Default assumption
                except Exception as e:
                     logger.warning(f"Error parsing decimals for Token-2022 {mint_pubkey}, defaulting to 6: {e}")
                     return 6, owner # Default assumption

            elif owner == TOKEN_PROGRAM_ID:
                 # Standard SPL Token mint parsing
                 try:
                     # Using offset 44 for decimals based on standard layout
                     decimals = int.from_bytes(data[44:45], 'little')
                     logger.debug(f"Parsed decimals for SPL Token {mint_pubkey}: {decimals}")
                     return decimals, owner
                 except IndexError:
                     logger.warning(f"Could not parse decimals for SPL Token {mint_pubkey} at standard offset, data length {len(data)}. Defaulting to 6.")
                     return 6, owner # Default assumption
                 except Exception as e:
                     logger.warning(f"Error parsing decimals for SPL Token {mint_pubkey}, defaulting to 6: {e}")
                     return 6, owner # Default assumption
            else:
                raise ValueError(f"Unknown mint owner program: {owner} for mint {mint_pubkey}")

        except Exception as e:
            logger.error(f"Failed to get mint info for {mint_pubkey}: {e}", exc_info=True)
            raise ValueError(f"Failed to get mint info: {e}")

    async def _ensure_ata_exists(self, owner: Pubkey, mint: Pubkey, instructions_list: List[Instruction], payer: Pubkey) -> Pubkey:
        """Checks if an ATA exists, adds creation instruction if not. Returns ATA address."""
        ata = get_associated_token_address(owner, mint)
        logger.debug(f"Checking ATA {ata} for owner {owner} and mint {mint}...") # Changed level to debug
        try:
            # Use get_account_info which returns None if not found (less prone to exceptions than get_balance)
            acc_info = await self.client.get_account_info(ata, commitment=Confirmed) # Use commitment
            if acc_info and acc_info.value:
                 logger.debug(f"ATA {ata} already exists.")
            else:
                logger.info(f"ATA {ata} not found. Adding creation instruction...")
                instructions_list.append(
                    create_associated_token_account(
                         payer=payer, owner=owner, mint=mint
                    )
                )
        except Exception as e:
            # Catch broader errors during check, though get_account_info should be safer
            logger.warning(f"Error checking ATA {ata}, assuming it needs creation: {e}")
            instructions_list.append(
                create_associated_token_account(
                    payer=payer, owner=owner, mint=mint
                )
            )
        return ata

    async def send_transaction(
        self,
        transaction: Transaction, # Can be Transaction or VersionedTransaction
        signers: List[Keypair],
        opts: TxOpts = TxOpts(skip_confirmation=False, preflight_commitment=Processed) # Default opts
    ) -> str:
        """
        Sends a prepared transaction to the Solana blockchain asynchronously.

        Args:
            transaction: The Solana Transaction or VersionedTransaction object.
            signers: A list of Keypair objects required to sign the transaction.
                            Typically includes the fee_payer.
            opts: Transaction sending options.

        Returns:
            str: Transaction signature upon successful sending.

        Raises:
            ValueError: If signers list is empty or invalid.
            RuntimeError: If sending the transaction fails.
        """
        if not signers:
            logger.error("send_transaction called without any signers (Keypair objects).")
            raise ValueError("Cannot send transaction: At least one signer (Keypair) is required.")

        logger.debug(f"Sending transaction with {len(signers)} signers...")
        try:
            # Solana-py client's send_transaction handles both Transaction and VersionedTransaction
            # It also handles signing internally if Keypairs are provided.
            response = await self.client.send_transaction(transaction, *signers, opts=opts)

            if not response or not hasattr(response, 'value') or not response.value:
                 # Improved error checking for response structure
                 logger.error(f"Failed to send transaction. Invalid or empty response from RPC: {response}")
                 raise RuntimeError(f"Failed to send transaction. Invalid RPC response: {response}")

            signature = response.value
            signature_str = str(signature)
            logger.info(f"Transaction sent successfully. Signature: {signature_str}")
            return signature_str

        except Exception as e:
            # Log the full error for debugging
            logger.error(f"Failed to send transaction: {e}", exc_info=True)
            # Consider wrapping specific RPC exceptions if needed
            raise RuntimeError(f"Failed to send transaction: {e}")

    # Removed fetch_pumpfun_amm_pool_info
    # async def fetch_pumpfun_amm_pool_info(...): ...

    # Removed _fetch_pumpfun_amm_global_config
    # async def _fetch_pumpfun_amm_global_config(...): ...

    # Removed _fetch_token_account_balance (if only used for pump amm)
    # async def _fetch_token_account_balance(...): ...

    # Keep close method if explicit cleanup is needed for the http_client
    async def close(self):
        """Closes the underlying HTTP client if it was provided."""
        if self.http_client:
            await self.http_client.aclose()
            logger.info("TransactionBuilder's HTTP client closed.")

