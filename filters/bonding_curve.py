"""
Bonding Curve Utility Module for Pump.fun Tokens

This module provides utilities to calculate bonding curve progress percentage and other 
metrics related to pump.fun token bonding curves.
"""
import os
import json
import base64
import logging
import struct  # Added for deserialization
from typing import Dict, Optional, Tuple, TYPE_CHECKING # Add TYPE_CHECKING
import base58
from solders.pubkey import Pubkey
from solana.rpc.async_api import AsyncClient
from decimal import Decimal, getcontext
from utils.logger import get_logger
import borsh_construct as bc # Attempting to use borsh-construct

# Import Settings for type hinting
if TYPE_CHECKING:
    from config.settings import Settings

# Set Decimal precision
getcontext().prec = 18 # Set precision for Decimal calculations

# Get logger for this module
logger = get_logger(__name__)

class BondingCurveCalculator:
    """Utilities for pump.fun bonding curve calculations"""
    
    # Constants
    PUMP_FUN_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"  # Pump.fun program ID
    # Calculated as the first 8 bytes of: `sha256("account:BondingCurve")`.
    PUMP_CURVE_ACCOUNT_DISCRIMINATOR = bytes([0x17, 0xb7, 0xf8, 0x37, 0x60, 0xd8, 0xac, 0x60])
    # Define layout using borsh_construct
    BONDING_CURVE_LAYOUT = bc.CStruct(
        "virtualTokenReserves" / bc.U64,
        "virtualSolReserves" / bc.U64,
        "realTokenReserves" / bc.U64,
        "realSolReserves" / bc.U64,
        "tokenTotalSupply" / bc.U64, # Note: Interpretation might vary based on source
        "complete" / bc.Bool
    )
    # From gist comment, seems to be a reference value, potentially fetched from another account
    # 4wTV1YmiEkRvAtNtsSGPtUrqRYQMe5SKy2uB4Jjaxnjf - this might store the initial reserve value
    # For now, hardcoding based on gist, but ideally fetched. Using Decimal for precision.
    # REMOVED Hardcoded constants - now loaded from settings in __init__
    # INITIAL_REAL_TOKEN_RESERVES_FOR_PROGRESS = Decimal("793100000000000")
    # TOTAL_VIRTUAL_TOKEN_RESERVES_START = Decimal("1073000000000000")
    
    def __init__(self, solana_client: AsyncClient, settings: 'Settings'): # Add settings object
        """
        Initialize BondingCurveCalculator with Solana client and settings.
        
        Args:
            solana_client: Solana RPC client instance
            settings: Application settings object
        """
        self.client = solana_client
        self.settings = settings # Store settings
        self.logger = get_logger("BondingCurveCalculator")

        # Pump.fun protocol constants - calculated dynamically from protocol parameters
        # These are NOT configurable - they are protocol constants for pump.fun bonding curves
        self.INITIAL_REAL_TOKEN_RESERVES_FOR_PROGRESS = Decimal("793100000000000")  # 793.1M tokens (for 1B total supply)
        self.TOTAL_VIRTUAL_TOKEN_RESERVES_START = Decimal("1073000000000000")       # 1.073B virtual tokens at start
        self.logger.info("Pump.fun bonding curve protocol constants initialized.")
    
    @staticmethod
    def derive_bonding_curve_address(mint_address: str) -> str:
        """
        Derive bonding curve account address from mint address.
        
        Args:
            mint_address: Token mint address
            
        Returns:
            str: Bonding curve account address
        """
        try:
            mint_pubkey = Pubkey.from_string(mint_address)
            seeds = [b"bonding-curve", bytes(mint_pubkey)]
            program_id = Pubkey.from_string(BondingCurveCalculator.PUMP_FUN_PROGRAM_ID)
            
            bonding_curve_pubkey, _ = Pubkey.find_program_address(seeds, program_id)
            return str(bonding_curve_pubkey)
        except Exception as e:
            logger.error(f"Error deriving bonding curve address for {mint_address}: {e}")
            return ""
    
    async def fetch_bonding_curve_data(self, mint_address: str) -> Optional[Dict]:
        """
        Fetch and deserialize bonding curve data from the Solana blockchain.
        
        Args:
            mint_address: Token mint address
            
        Returns:
            Optional[Dict]: Deserialized bonding curve data or None if error/not found.
        """
        try:
            # Convert string address to Pubkey
            mint_pubkey = Pubkey.from_string(mint_address)
        except ValueError:
            self.logger.error(f"Invalid mint address format: {mint_address}")
            return None
            
        # Derive bonding curve address AFTER validating mint address format
        bonding_curve_address = self.derive_bonding_curve_address(mint_address)
        if not bonding_curve_address:
            self.logger.error(f"Could not derive bonding curve address for mint: {mint_address}")
            return None
            
        try:
            # Convert bonding curve string address to Pubkey for the RPC call
            bonding_curve_pubkey = Pubkey.from_string(bonding_curve_address) 
                
            # Fetch account data
            response = await self.client.get_account_info(bonding_curve_pubkey) # Use Pubkey object
            
            # Check if account exists and has data
            if response is None or response.value is None:
                self.logger.debug(f"No account info found for bonding curve PDA {bonding_curve_address} (mint: {mint_address}). Likely not on pump.fun or migrated.")
                return None
                
            account_info = response.value # Access the Account object
            raw_data = account_info.data
            
            if not raw_data:
                 self.logger.error(f"Account data is empty for bonding curve {bonding_curve_address} (mint: {mint_address})")
                 return None

            # Check discriminator
            discriminator = raw_data[:8]
            if discriminator != self.PUMP_CURVE_ACCOUNT_DISCRIMINATOR:
                 self.logger.error(f"Account {bonding_curve_address} (mint: {mint_address}) is not a valid pump.fun BondingCurve account. Discriminator mismatch.")
                 self.logger.debug(f"Expected: {self.PUMP_CURVE_ACCOUNT_DISCRIMINATOR.hex()}, Got: {discriminator.hex()}")
                 return None

            # Check data length (handled by borsh-construct parsing)

            # Deserialize using borsh-construct
            parsed_data = self.BONDING_CURVE_LAYOUT.parse(raw_data[8:])

            deserialized_data = {
                "mint": mint_address,
                "bonding_curve": bonding_curve_address,
                # Assign parsed values - convert u64 to Decimal
                "virtualTokenReserves": Decimal(parsed_data.virtualTokenReserves),
                "virtualSolReserves": Decimal(parsed_data.virtualSolReserves),
                "realTokenReserves": Decimal(parsed_data.realTokenReserves),
                "realSolReserves": Decimal(parsed_data.realSolReserves),
                "tokenTotalSupply": Decimal(parsed_data.tokenTotalSupply),
                "complete": parsed_data.complete,
                # Fetch token decimals separately if needed, pump.fun often uses 6
                "tokenDecimals": 6 # Assume 6 decimals for pump.fun tokens
            }
            self.logger.debug(f"Successfully deserialized bonding curve data for {mint_address} using borsh-construct: {deserialized_data}")
            return deserialized_data
            
        except bc.BorshError as e:
             self.logger.error(f"Borsh-construct parsing error for bonding curve {bonding_curve_address} (mint: {mint_address}): {e}", exc_info=True)
             return None
        except Exception as e:
            self.logger.error(f"Error fetching/deserializing bonding curve data for {mint_address}: {e}", exc_info=True)
            return None
    
    def calculate_bonding_curve_progress(self, curve_data: Dict) -> float:
        """
        Calculate bonding curve progress percentage using deserialized data.
        
        Formula approach based on reserves (adapted from gist/stackexchange):
        Progress = 100 * (Total tokens to sell - Current Real tokens remaining) / Total tokens to sell
        Total tokens to sell = Initial Real Token Reserves (e.g., 793.1M for 1B total supply)
        Current Real tokens remaining = curve_data['realTokenReserves']

        Alternative (from gist):
        Progress = (Total Virtual Start - Current Virtual) / (Total Virtual Start - Virtual End)
                 = (1.073B - current_virtual_tokens) / (1.073B - 206.9M) approx
                 = (1.073B - current_virtual_tokens) / 793.1M

        Let's use the virtual token reserves method based on the StackExchange explanation:
        Progress = (Total Virtual Start - Current Virtual Tokens) / Amount Sold during curve * 100
        Progress = (1.073B - virtualTokenReserves) / 793.1M * 100
        
        Args:
            curve_data: Deserialized bonding curve data from fetch_bonding_curve_data
            
        Returns:
            float: Bonding curve progress percentage (0-100)
        """
        try:
            if not curve_data or curve_data.get("complete") is None: # Check if data is valid
                self.logger.warning("Invalid or missing curve data for progress calculation.")
                return 0.0
                
            # Use Decimal for calculations
            virtual_token_reserves = curve_data.get("virtualTokenReserves", Decimal(0))

            # Constants defined above - now loaded from self
            total_virtual_start = self.TOTAL_VIRTUAL_TOKEN_RESERVES_START
            tokens_sold_on_curve = self.INITIAL_REAL_TOKEN_RESERVES_FOR_PROGRESS # 793.1M

            if tokens_sold_on_curve <= 0:
                 self.logger.warning("INITIAL_REAL_TOKEN_RESERVES_FOR_PROGRESS is zero or negative, cannot calculate progress.")
                 return 100.0 if curve_data.get("complete") else 0.0 # Assume 100% if marked complete, else 0

            tokens_bought = total_virtual_start - virtual_token_reserves

            # Handle edge case where reserves might exceed start due to oddities
            if tokens_bought < 0:
                 tokens_bought = Decimal(0)
                 self.logger.warning(f"Calculated negative tokens_bought for {curve_data.get('mint')}, capping at 0. Virtual Reserves: {virtual_token_reserves}")

            progress_decimal = (tokens_bought / tokens_sold_on_curve) * 100
            
            # Ensure progress is between 0 and 100
            progress = max(Decimal(0), min(Decimal(100), progress_decimal))

            self.logger.debug(f"Calculated progress for {curve_data.get('mint')}: {progress:.4f}% (Virtual Reserves: {virtual_token_reserves})")
            
            # Return as float
            return float(progress)
            
        except (TypeError, ValueError, KeyError) as e:
            self.logger.error(f"Error calculating bonding curve progress: {e}. Curve data: {curve_data}", exc_info=True)
            return 0.0
        except Exception as e:
            self.logger.error(f"Unexpected error calculating bonding curve progress: {e}", exc_info=True)
            return 0.0
    
    def calculate_market_cap_from_progress(self, curve_data: Dict, sol_price_usd: float) -> Tuple[float, float]:
        """
        Calculate market cap based on bonding curve progress and SOL price.
        NOTE: This uses a simplified market cap estimation based on progress.
              A more accurate calculation would involve the current price derived from reserves.
        
        Args:
            curve_data: Deserialized bonding curve data from the blockchain
            sol_price_usd: Current SOL price in USD
            
        Returns:
            Tuple[float, float]: (market_cap_usd, bonding_curve_percent)
        """
        try:
            # Calculate bonding curve progress percentage using the updated method
            progress_percent_decimal = Decimal(self.calculate_bonding_curve_progress(curve_data))
            progress_percent = float(progress_percent_decimal) # Convert for comparison logic
            
            # Get liquidity in SOL from curve data (use virtual reserves for pump.fun price mechanism)
            # Convert lamports (u64) to SOL (Decimal)
            virtual_sol_reserves = curve_data.get("virtualSolReserves", Decimal(0))
            liquidity_sol = virtual_sol_reserves / Decimal(10**9) # 1 SOL = 10^9 lamports
            
            # Calculate liquidity in USD
            liquidity_usd = float(liquidity_sol * Decimal(sol_price_usd))
            
            # --- Market Cap Estimation Logic (Simplified) ---
            # This is a heuristic. Real MCAP = price * circulating_supply. Price changes along the curve.
            # We estimate based on liquidity and progress stage.
            if progress_percent >= 99:
                market_cap = liquidity_usd * (5 + (progress_percent - 99) * 5)
            elif progress_percent >= 90:
                market_cap = liquidity_usd * (3 + (progress_percent - 90) / 10 * 2)
            elif progress_percent >= 50:
                market_cap = liquidity_usd * (2 + (progress_percent - 50) / 40)
            else:
                market_cap = liquidity_usd * (1 + progress_percent / 50)
            
            # Safety check for non-finite values
            if not isinstance(market_cap, (int, float)) or not isinstance(progress_percent, (int, float)):
                 self.logger.error(f"Non-numeric result in market cap calculation. MCAP: {market_cap}, Progress: {progress_percent}")
                 return (0.0, 0.0)
                 
            # Cap negative market cap which might occur with very low/negative liquidity_usd
            market_cap = max(0.0, market_cap)

            self.logger.debug(f"Calculated MCAP for {curve_data.get('mint')}: ${market_cap:.2f} USD (Progress: {progress_percent:.2f}%)")
            return (market_cap, progress_percent)
            
        except Exception as e:
            self.logger.error(f"Error calculating market cap from progress for {curve_data.get('mint')}: {e}", exc_info=True)
            return (0.0, 0.0)
    
    async def get_bonding_curve_metrics(self, mint_address: str, sol_price_usd: float) -> Dict:
        """
        Get comprehensive bonding curve metrics for a token using deserialized data.
        
        Args:
            mint_address: Token mint address
            sol_price_usd: Current SOL price in USD
            
        Returns:
            Dict: Dictionary containing bonding curve metrics
        """
        metrics = {
            "status": "error",
            "message": "Initialization error",
            "mint": mint_address,
            "bonding_curve_address": "",
            "progress_percent": 0.0,
            "market_cap": 0.0,
            "migration_likelihood": "UNKNOWN",
            "time_to_migration": "UNKNOWN",
            "raw_curve_data": {}
        }
        try:
            # Fetch and deserialize bonding curve data
            curve_data = await self.fetch_bonding_curve_data(mint_address)
            if not curve_data:
                self.logger.warning(f"Could not fetch/deserialize bonding curve data for {mint_address}.")
                metrics["message"] = "Could not fetch or deserialize bonding curve data (token might not be on pump.fun or account invalid)"
                metrics["status"] = "not_found_or_invalid"
                return metrics

            metrics["bonding_curve_address"] = curve_data.get("bonding_curve", "")
            metrics["raw_curve_data"] = { # Store raw deserialized numbers
                "virtualTokenReserves": str(curve_data.get("virtualTokenReserves")),
                "virtualSolReserves": str(curve_data.get("virtualSolReserves")),
                "realTokenReserves": str(curve_data.get("realTokenReserves")),
                "realSolReserves": str(curve_data.get("realSolReserves")),
                "tokenTotalSupply": str(curve_data.get("tokenTotalSupply")),
                "complete": curve_data.get("complete"),
                "tokenDecimals": curve_data.get("tokenDecimals")
            }
            
            # Calculate market cap and progress percentage
            market_cap, progress_percent = self.calculate_market_cap_from_progress(curve_data, sol_price_usd)
            
            metrics["progress_percent"] = progress_percent
            metrics["market_cap"] = market_cap

            # Predict migration likelihood based on progress
            if progress_percent >= 95:
                metrics["migration_likelihood"] = "VERY HIGH"
                metrics["time_to_migration"] = "IMMINENT (< 24 hours)"
            elif progress_percent >= 90:
                 metrics["migration_likelihood"] = "HIGH"
                 metrics["time_to_migration"] = "VERY SOON (1-3 days)"
            elif progress_percent >= 75:
                 metrics["migration_likelihood"] = "MEDIUM"
                 metrics["time_to_migration"] = "SOON (3-7 days)"
            elif progress_percent >= 50:
                 metrics["migration_likelihood"] = "LOW"
                 metrics["time_to_migration"] = "MEDIUM (1-2 weeks)"
            else:
                metrics["migration_likelihood"] = "VERY LOW"
                metrics["time_to_migration"] = "LONG (> 2 weeks)"
            
            # Handle case where curve is marked complete
            if curve_data.get("complete"):
                 # Note: complete=True means the pump.fun bonding curve finished.
                 # Migration to Raydium is the expected next step, but not guaranteed by this flag alone.
                 metrics["progress_percent"] = 100.0 # Override progress if complete flag is set
                 metrics["migration_likelihood"] = "COMPLETED" # Accurate based on the flag
                 metrics["time_to_migration"] = "MIGRATED/COMPLETED" # Reflects the likely outcome
                 
            metrics["status"] = "success"
            metrics.pop("message", None) # Remove initial error message on success

            return metrics
            
        except Exception as e:
            self.logger.error(f"Error getting bonding curve metrics for {mint_address}: {e}", exc_info=True)
            metrics["status"] = "error"
            metrics["message"] = str(e)
            return metrics 