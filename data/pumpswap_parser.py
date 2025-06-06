"""
PumpSwap DEX parser for swap logs and account updates
Consolidates parsing logic from blockchain_listener.py and market_data.py
"""

import re
import base64
import borsh_construct as bc
import asyncio
import json
import time
import websockets
from websockets.exceptions import WebSocketException, ConnectionClosed
from typing import List, Dict, Any, Optional, Callable
from .base_parser import DexParser

class PumpSwapParser(DexParser):
    """Parser for PumpSwap AMM pools"""
    
    DEX_ID = 'pumpswap'
    
    def __init__(self, settings, logger=None):
        super().__init__(settings, logger)
        
        # **ADDED: Decimal caching and Helius API integration**
        self._decimal_cache = {}  # mint_address -> decimals
        self._helius_base_url = getattr(settings, 'SOLANA_RPC_URL', 'https://mainnet.helius-rpc.com')
        if not self._helius_base_url.startswith('http'):
            self._helius_base_url = f"https://{self._helius_base_url}"
        
        # **ADDED: Helius Pump AMM WebSocket Stream Support**
        self._stream_callback = None
        self._ws_connection = None
        self._stream_running = False
        self._stream_task = None
        self._subscription_id = None
        
        # Extract API key for WebSocket connection - FIX SecretStr handling
        api_key = ""
        if hasattr(settings, 'HELIUS_API_KEY') and settings.HELIUS_API_KEY:
            # Handle both SecretStr and regular string
            if hasattr(settings.HELIUS_API_KEY, 'get_secret_value'):
                api_key = settings.HELIUS_API_KEY.get_secret_value()
            else:
                api_key = str(settings.HELIUS_API_KEY)
            # Skip if it's a placeholder
            if api_key in ['placeholder_key', 'your_actual_helius_api_key_here', '']:
                api_key = ""
        elif hasattr(settings, 'SOLANA_RPC_URL') and settings.SOLANA_RPC_URL:
            rpc_url = settings.SOLANA_RPC_URL
            if 'api-key=' in rpc_url:
                api_key = rpc_url.split('api-key=')[1].split('&')[0]
        
        # Use the proper Helius WebSocket URL from settings
        if api_key and hasattr(settings, 'HELIUS_WSS_URL'):
            base_wss = settings.HELIUS_WSS_URL
            if '?api-key=' not in base_wss:
                self._websocket_url = f"{base_wss}?api-key={api_key}"
            else:
                self._websocket_url = base_wss
        else:
            # Fallback to Solana public WebSocket (no API key needed)
            self._websocket_url = getattr(settings, 'SOLANA_MAINNET_WSS', 'wss://api.mainnet-beta.solana.com/')
            if self.logger:
                self.logger.info(f"🔧 Using public Solana WebSocket (no Helius API key available): {self._websocket_url}")
            
        self._pump_program_id = getattr(settings, 'PUMPSWAP_PROGRAM_ID', 'pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA')
        
        # Initialize PumpSwap AMM layout for account parsing
        try:
            self._pumpswap_amm_layout = bc.CStruct(
                "version" / bc.U8,
                "status" / bc.U8,
                "bump" / bc.U8,
                "decimals" / bc.U8,
                "minimum_sol_amount" / bc.U64,
                "minimum_token_amount" / bc.U64,
                "total_trade_volume_sol" / bc.U64,
                "total_trade_volume_token" / bc.U64,
                "sol_balance" / bc.U64,
                "token_balance" / bc.U64,
                "last_swap_timestamp" / bc.I64,
                "owner" / bc.Bytes[32],
                "token_mint" / bc.Bytes[32],
                "token_vault" / bc.Bytes[32],
                "sol_vault" / bc.Bytes[32],
                "quote_token_mint" / bc.Bytes[32],
                "fee_percentage" / bc.U16,
                "fee_owner" / bc.Bytes[32],
                "config" / bc.Bytes[32]
            )
            if self.logger:
                self.logger.info("PumpSwap AMM layout initialized successfully")
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error defining PumpSwap AMM layout: {e}", exc_info=True)
            self._pumpswap_amm_layout = None
    
    async def parse_swap_logs_async(self, logs: List[str], signature: str = None) -> Optional[Dict[str, Any]]:
        """
        Async version of parse_swap_logs that can fetch actual token decimals from Helius.
        """
        try:
            if not self.validate_logs(logs):
                return None
                
            # **ADDED: Extract token mint address for accurate decimal fetching**
            token_mint = self._extract_token_mint_from_logs(logs, signature)
            
            # Enhanced swap info structure
            swap_info = {
                "event_type": "swap",
                "found_swap": False,
                "instruction_type": None,
                "amount_in": None,
                "amount_out": None,
                "buy_amount": None,
                "sell_amount": None,
                "price": None,
                "program_interactions": [],
                "signature": signature,
                "source": "pumpswap_log",
                "dex_id": self.DEX_ID,
                "token_mint": token_mint  # **ADDED: Store extracted mint**
            }
            
            # **ADDED: Fetch actual decimals from Helius if we have a mint**
            actual_token_decimals = None
            if token_mint:
                try:
                    actual_token_decimals = await self._get_token_decimals_from_helius(token_mint)
                    if self.logger:
                        self.logger.info(f"🎯 Fetched actual decimals for {token_mint[:8]}...: {actual_token_decimals}")
                except Exception as e:
                    if self.logger:
                        self.logger.warning(f"Failed to fetch decimals for {token_mint[:8]}...: {e}")
            
            # Process logs for swap detection...
            # ✅ ENHANCED: Add comprehensive log pattern debugging
            if self.logger and signature:
                self.logger.info(f"🔍 PUMPSWAP LOG ANALYSIS for {signature[:8]}...")
                for i, log in enumerate(logs):
                    if "pAMM" in log or "pump" in log.lower() or "swap" in log.lower():
                        self.logger.info(f"  📄 Log {i}: {log}")

            for log in logs:
                log_lower = log.lower()
                
                # ✅ ENHANCED: Look for more PumpSwap patterns
                # Standard instruction patterns
                if any(pattern in log_lower for pattern in ["instruction: buy", "instruction: sell", "instruction: swap"]):
                    swap_info["found_swap"] = True
                    if "buy" in log_lower:
                        swap_info["instruction_type"] = "buy"
                    elif "sell" in log_lower:
                        swap_info["instruction_type"] = "sell"
                    else:
                        swap_info["instruction_type"] = "swap"
                    if self.logger:
                        self.logger.info(f"✅ Found PumpSwap {swap_info['instruction_type']} instruction: {log}")
                
                # ✅ ENHANCED: Look for PumpSwap AMM specific patterns
                # Pattern 1: "Pump B: X, S: Y" (balance updates)
                pump_balance_match = re.search(r'pump\s+b:\s*(\d+),?\s*s:\s*(\d+)', log_lower)
                if pump_balance_match:
                    swap_info["found_swap"] = True
                    swap_info["instruction_type"] = "balance_update"
                    buy_amount_raw = int(pump_balance_match.group(1))
                    sell_amount_raw = int(pump_balance_match.group(2))
                    swap_info["buy_amount"] = buy_amount_raw
                    swap_info["sell_amount"] = sell_amount_raw
                    
                    if self.logger:
                        self.logger.info(f"✅ Found PumpSwap balance update: B={buy_amount_raw}, S={sell_amount_raw}")
                    
                    # Calculate price immediately
                    if buy_amount_raw > 0 and sell_amount_raw > 0:
                        price_sol, token_decimals_used, calc_method = self._calculate_price_with_actual_decimals(
                            sol_lamports=buy_amount_raw,
                            token_raw_amount=sell_amount_raw,
                            actual_token_decimals=actual_token_decimals,
                            token_mint=token_mint
                        )
                        
                        if price_sol is not None:
                            swap_info["price"] = price_sol
                            swap_info["price_ratio"] = price_sol
                            swap_info["calculation_method"] = calc_method
                            swap_info["token_decimals_used"] = token_decimals_used
                            if self.logger:
                                method_desc = "🎯 HELIUS API" if actual_token_decimals is not None else "📊 FALLBACK"
                                self.logger.info(f"{method_desc} PumpSwap price: {price_sol:.8f} SOL (decimals: {token_decimals_used})")
                
                # ✅ ENHANCED: Pattern 2: Look for reserve/liquidity updates
                reserve_match = re.search(r'reserve[s]?\s*[:\-]?\s*(\d+)', log_lower)
                if reserve_match and not swap_info.get("buy_amount"):
                    reserve_amount = int(reserve_match.group(1))
                    if reserve_amount > 1000000:  # Likely SOL in lamports
                        swap_info["buy_amount"] = reserve_amount
                        if self.logger:
                            self.logger.info(f"✅ Found reserve amount: {reserve_amount}")
                
                # ✅ ENHANCED: Pattern 3: Look for token amounts
                token_amount_match = re.search(r'token[s]?\s*[:\-]?\s*(\d+)', log_lower)
                if token_amount_match and not swap_info.get("sell_amount"):
                    token_amount = int(token_amount_match.group(1))
                    if token_amount > 1000:  # Reasonable token amount
                        swap_info["sell_amount"] = token_amount
                        if self.logger:
                            self.logger.info(f"✅ Found token amount: {token_amount}")
                
                # ✅ ENHANCED: Pattern 4: Look for any numeric patterns that might be amounts
                if "amount" in log_lower:
                    amount_matches = re.findall(r'amount[_\w]*[:\s]+(\d+)', log, re.IGNORECASE)
                    for amount_str in amount_matches:
                        amount = int(amount_str)
                        if amount > 1000:  # Filter out small numbers
                            if swap_info["amount_in"] is None:
                                swap_info["amount_in"] = amount
                                if self.logger:
                                    self.logger.info(f"✅ Found amount_in: {amount}")
                            elif swap_info["amount_out"] is None:
                                swap_info["amount_out"] = amount
                                if self.logger:
                                    self.logger.info(f"✅ Found amount_out: {amount}")
                
                # ✅ ENHANCED: Pattern 5: Look for program invocations
                if "program" in log_lower and ("invoke" in log_lower or "success" in log_lower):
                    swap_info["program_interactions"].append(log.strip())
                    if "pAMM" in log or "pump" in log_lower:
                        swap_info["found_swap"] = True
                        if self.logger:
                            self.logger.info(f"✅ Found PumpSwap program interaction: {log}")
                
                # ✅ ENHANCED: Pattern 6: Look for explicit price mentions
                price_pattern = r'price[:\s]*(\d+(?:\.\d+)?)'
                price_match = re.search(price_pattern, log, re.IGNORECASE)
                if price_match:
                    try:
                        explicit_price = float(price_match.group(1))
                        swap_info["price"] = explicit_price
                        swap_info["found_swap"] = True
                        if self.logger:
                            self.logger.info(f"✅ Found explicit price: {explicit_price}")
                    except ValueError:
                        pass
                
                # Try to extract amounts from generic patterns
                if "amount" in log_lower:
                    try:
                        amount_matches = re.findall(r'amount[_\w]*[:\s]+(\d+)', log, re.IGNORECASE)
                        for amount_str in amount_matches:
                            amount = int(amount_str)
                            if amount > 1000:  # Filter out small numbers
                                if swap_info["amount_in"] is None:
                                    swap_info["amount_in"] = amount
                                elif swap_info["amount_out"] is None:
                                    swap_info["amount_out"] = amount
                    except Exception:
                        pass
                        
                # Look for explicit price patterns
                price_pattern = r'price[:\s]*(\d+(?:\.\d+)?)'
                price_match = re.search(price_pattern, log, re.IGNORECASE)
                if price_match:
                    try:
                        swap_info["price"] = float(price_match.group(1))
                        swap_info["found_swap"] = True
                    except ValueError:
                        pass
            
            # Calculate price from amounts if not already found
            if not swap_info["price"] and swap_info["amount_in"] and swap_info["amount_out"]:
                try:
                    # **IMPROVED: Use actual decimals from Helius**
                    amount_in_raw = swap_info["amount_in"]   # Likely SOL in lamports
                    amount_out_raw = swap_info["amount_out"] # Likely tokens in raw amount
                    
                    price_sol, token_decimals_used, calc_method = self._calculate_price_with_actual_decimals(
                        sol_lamports=amount_in_raw,
                        token_raw_amount=amount_out_raw,
                        actual_token_decimals=actual_token_decimals,
                        token_mint=token_mint
                    )
                    
                    if price_sol is not None:
                        swap_info["price"] = price_sol
                        swap_info["price_ratio"] = price_sol
                        swap_info["calculation_method"] = calc_method
                        swap_info["token_decimals_used"] = token_decimals_used
                        swap_info["helius_decimals_used"] = actual_token_decimals is not None
                        if self.logger:
                            method_desc = "🎯 HELIUS API" if actual_token_decimals is not None else "📊 FALLBACK"
                            self.logger.info(f"{method_desc} PumpSwap generic price: {price_sol:.8f} SOL (decimals: {token_decimals_used})")
                    else:
                        if self.logger:
                            sol_converted = amount_in_raw / 1_000_000_000
                            self.logger.warning(f"Failed to calculate reasonable generic price: {amount_in_raw} lamports ({sol_converted:.9f} SOL) / {amount_out_raw} raw tokens")
                            
                except Exception as e:
                    if self.logger and e is not None:
                        self.logger.error(f"Error in generic price calculation: {e}")
                    pass
            
            # Return swap info if we found any relevant events
            if swap_info["found_swap"]:
                return swap_info
            else:
                return None
                
        except Exception as e:
            if self.logger and e is not None:
                self.logger.error(f"Error parsing PumpSwap log: {e}", exc_info=True)
            return None

    def parse_swap_logs(self, logs: List[str], signature: str = None, target_mint: str = None) -> Optional[Dict[str, Any]]:
        """
        Sync wrapper for parse_swap_logs that falls back to basic decimal detection.
        For full Helius API support, use parse_swap_logs_async().
        """
        try:
            # Extract mint for debugging or use provided target_mint
            token_mint = target_mint or self._extract_token_mint_from_logs(logs, signature)
            if self.logger and token_mint:
                self.logger.debug(f"🔍 Target mint: {token_mint}")
            
            # For now, fall back to the old sync method but with improved logging
            return self._parse_swap_logs_sync(logs, signature, token_mint)
        except Exception as e:
            if self.logger and e is not None:
                self.logger.error(f"Error in sync parse_swap_logs: {e}", exc_info=True)
            return None
    
    def _parse_swap_logs_sync(self, logs: List[str], signature: str = None, token_mint: str = None) -> Optional[Dict[str, Any]]:
        """
        Synchronous version with improved decimal handling and target mint filtering.
        """
        try:
            if not self.validate_logs(logs):
                return None
            
            # ✅ CRITICAL FIX: Extract all mints from logs first
            extracted_mints = self._extract_all_mints_from_logs(logs)
            
            # ✅ CRITICAL FIX: Only process if our target mint is involved in this transaction
            if token_mint and extracted_mints and token_mint not in extracted_mints:
                if self.logger:
                    sig_display = signature[:8] + "..." if signature else "unknown"
                    mint_display = token_mint[:8] + "..." if token_mint else "unknown"
                    found_display = [m[:8]+'...' for m in extracted_mints[:3]] if extracted_mints else []
                    self.logger.debug(f"🚫 Skipping transaction {sig_display} - target mint {mint_display} not found in logs (found: {found_display})")
                return None
                
            # Enhanced swap info structure
            swap_info = {
                "event_type": "swap",
                "found_swap": False,
                "instruction_type": None,
                "amount_in": None,
                "amount_out": None,
                "buy_amount": None,
                "sell_amount": None,
                "price": None,
                "program_interactions": [],
                "signature": signature,
                "source": "pumpswap_log",
                "dex_id": self.DEX_ID,
                "token_mint": token_mint,
                "extracted_mints": extracted_mints  # Track all mints found
            }
            
            # ✅ ENHANCED: Add comprehensive log pattern debugging for sync version
            if self.logger and signature:
                self.logger.info(f"🔍 PUMPSWAP SYNC LOG ANALYSIS for {signature[:8]}...")
                for i, log in enumerate(logs):
                    if "pAMM" in log or "pump" in log.lower() or "swap" in log.lower():
                        self.logger.info(f"  📄 Log {i}: {log}")

            for log in logs:
                log_lower = log.lower()
                
                # ✅ ENHANCED: Look for more PumpSwap patterns (sync version)
                # Standard instruction patterns
                if any(pattern in log_lower for pattern in ["instruction: buy", "instruction: sell", "instruction: swap"]):
                    swap_info["found_swap"] = True
                    if "buy" in log_lower:
                        swap_info["instruction_type"] = "buy"
                    elif "sell" in log_lower:
                        swap_info["instruction_type"] = "sell"
                    else:
                        swap_info["instruction_type"] = "swap"
                    if self.logger:
                        self.logger.info(f"✅ Found PumpSwap {swap_info['instruction_type']} instruction: {log}")
                
                # ✅ ENHANCED: Look for PumpSwap AMM specific patterns
                # Pattern 1: "Pump B: X, S: Y" (balance updates)
                pump_balance_match = re.search(r'pump\s+b:\s*(\d+),?\s*s:\s*(\d+)', log_lower)
                if pump_balance_match:
                    swap_info["found_swap"] = True
                    swap_info["instruction_type"] = "balance_update"
                    buy_amount_raw = int(pump_balance_match.group(1))
                    sell_amount_raw = int(pump_balance_match.group(2))
                    swap_info["buy_amount"] = buy_amount_raw
                    swap_info["sell_amount"] = sell_amount_raw
                    
                    if self.logger:
                        self.logger.info(f"✅ Found PumpSwap balance update: B={buy_amount_raw}, S={sell_amount_raw}")
                    
                    # Calculate price immediately with sync decimals
                    if buy_amount_raw > 0 and sell_amount_raw > 0:
                        # Get cached decimals if available
                        cached_decimals = self._get_token_decimals_sync(token_mint) if token_mint else None
                        
                        price_sol, token_decimals_used, calc_method = self._calculate_price_with_actual_decimals(
                            sol_lamports=buy_amount_raw,
                            token_raw_amount=sell_amount_raw,
                            actual_token_decimals=cached_decimals,
                            token_mint=token_mint
                        )
                        
                        if price_sol is not None:
                            swap_info["price"] = price_sol
                            swap_info["price_ratio"] = price_sol
                            swap_info["calculation_method"] = calc_method
                            swap_info["token_decimals_used"] = token_decimals_used
                            if self.logger:
                                method_desc = "💾 CACHED" if cached_decimals is not None else "📊 TESTED"
                                self.logger.info(f"{method_desc} PumpSwap price: {price_sol:.8f} SOL (decimals: {token_decimals_used})")
                
                # ✅ ENHANCED: Pattern 2: Look for reserve/liquidity updates
                reserve_match = re.search(r'reserve[s]?\s*[:\-]?\s*(\d+)', log_lower)
                if reserve_match and not swap_info.get("buy_amount"):
                    reserve_amount = int(reserve_match.group(1))
                    if reserve_amount > 1000000:  # Likely SOL in lamports
                        swap_info["buy_amount"] = reserve_amount
                        if self.logger:
                            self.logger.info(f"✅ Found reserve amount: {reserve_amount}")
                
                # ✅ ENHANCED: Pattern 3: Look for token amounts
                token_amount_match = re.search(r'token[s]?\s*[:\-]?\s*(\d+)', log_lower)
                if token_amount_match and not swap_info.get("sell_amount"):
                    token_amount = int(token_amount_match.group(1))
                    if token_amount > 1000:  # Reasonable token amount
                        swap_info["sell_amount"] = token_amount
                        if self.logger:
                            self.logger.info(f"✅ Found token amount: {token_amount}")
                
                # ✅ ENHANCED: Pattern 4: Look for any numeric patterns that might be amounts
                if "amount" in log_lower:
                    amount_matches = re.findall(r'amount[_\w]*[:\s]+(\d+)', log, re.IGNORECASE)
                    for amount_str in amount_matches:
                        amount = int(amount_str)
                        if amount > 1000:  # Filter out small numbers
                            if swap_info["amount_in"] is None:
                                swap_info["amount_in"] = amount
                                if self.logger:
                                    self.logger.info(f"✅ Found amount_in: {amount}")
                            elif swap_info["amount_out"] is None:
                                swap_info["amount_out"] = amount
                                if self.logger:
                                    self.logger.info(f"✅ Found amount_out: {amount}")
                
                # ✅ ENHANCED: Pattern 5: Look for program invocations
                if "program" in log_lower and ("invoke" in log_lower or "success" in log_lower):
                    swap_info["program_interactions"].append(log.strip())
                    if "pAMM" in log or "pump" in log_lower:
                        swap_info["found_swap"] = True
                        if self.logger:
                            self.logger.info(f"✅ Found PumpSwap program interaction: {log}")
                
                # ✅ ENHANCED: Pattern 6: Look for explicit price mentions
                price_pattern = r'price[:\s]*(\d+(?:\.\d+)?)'
                price_match = re.search(price_pattern, log, re.IGNORECASE)
                if price_match:
                    try:
                        explicit_price = float(price_match.group(1))
                        swap_info["price"] = explicit_price
                        swap_info["found_swap"] = True
                        if self.logger:
                            self.logger.info(f"✅ Found explicit price: {explicit_price}")
                    except ValueError:
                        pass
            
            # Return swap info if we found any relevant events
            if swap_info["found_swap"]:
                return swap_info
            else:
                return None
                
        except Exception as e:
            if self.logger and e is not None:
                self.logger.error(f"Error parsing PumpSwap log sync: {e}", exc_info=True)
            return None

    def parse_account_update(self, raw_data: Any, pool_address: str = None) -> Optional[Dict[str, Any]]:
        """
        Parse PumpSwap account update data using borsh layout
        Extracts current pool state with price and liquidity
        """
        try:
            if not raw_data or not self._pumpswap_amm_layout:
                return None
                
            # Handle both base64 string and bytes
            if isinstance(raw_data, str):
                try:
                    decoded_data = base64.b64decode(raw_data)
                except Exception as e:
                    if self.logger and e is not None:
                        self.logger.error(f"Error decoding base64 data: {e}")
                    return None
            elif isinstance(raw_data, (bytes, bytearray)):
                decoded_data = bytes(raw_data)
            else:
                if self.logger:
                    raw_data_type = type(raw_data).__name__ if raw_data is not None else 'None'
                    self.logger.warning(f"Unsupported raw_data type: {raw_data_type}")
                return None
                
            try:
                parsed_state = self._pumpswap_amm_layout.parse(decoded_data)
                
                token_decimals = parsed_state.decimals
                sol_decimals = 9
                token_balance_raw = parsed_state.token_balance
                sol_balance_raw = parsed_state.sol_balance

                if token_balance_raw > 0 and sol_balance_raw > 0 and token_decimals is not None:
                    price = (sol_balance_raw / (10**sol_decimals)) / (token_balance_raw / (10**token_decimals))
                    
                    return {
                        "event_type": "account_update",
                        "pool_address": pool_address,
                        "price": price,
                        "liquidity_sol": sol_balance_raw / (10**sol_decimals),
                        "token_reserve_raw": token_balance_raw,
                        "sol_reserve_raw": sol_balance_raw,
                        "token_decimals": token_decimals,
                        "source": "pumpswap_account",
                        "dex_id": self.DEX_ID,
                        "total_trade_volume_sol": parsed_state.total_trade_volume_sol,
                        "total_trade_volume_token": parsed_state.total_trade_volume_token,
                        "last_swap_timestamp": parsed_state.last_swap_timestamp
                    }
                else:
                    if self.logger and pool_address:
                        self.logger.warning(f"Insufficient data in PumpSwap account state for {pool_address} to calculate price")
                    return None
                    
            except Exception as e:
                if self.logger and e is not None and pool_address:
                    self.logger.error(f"Error parsing PumpSwap account data for {pool_address}: {e}", exc_info=True)
                return None
                
        except Exception as e:
            if self.logger and e is not None and pool_address:
                self.logger.error(f"Error parsing PumpSwap account update for {pool_address}: {e}", exc_info=True)
            return None 

    def _calculate_price_with_actual_decimals(self, sol_lamports: int, token_raw_amount: int, actual_token_decimals: int = None, token_mint: str = None, expected_price_range=(0.0000001, 100.0)):
        """
        Calculate price using actual token decimals from Helius API when available.
        
        Args:
            sol_lamports: Raw SOL amount in lamports (always needs ÷ 10^9)
            token_raw_amount: Raw token amount (needs ÷ 10^token_decimals)
            actual_token_decimals: Actual decimals fetched from Helius API
            token_mint: Token mint address for logging
            expected_price_range: Tuple of (min_price, max_price) in SOL
        
        Returns:
            tuple: (calculated_price_sol, token_decimals_used, calculation_method)
        """
        if not sol_lamports or not token_raw_amount:
            return None, None, "insufficient_data"
            
        try:
            # SOL is ALWAYS 9 decimals (1 SOL = 1,000,000,000 lamports)
            sol_amount = sol_lamports / 1_000_000_000  # Convert lamports to SOL
            
            # If we have actual decimals from Helius, use them first
            if actual_token_decimals is not None:
                try:
                    token_amount = token_raw_amount / (10 ** actual_token_decimals)
                    if token_amount > 0:
                        price_sol = sol_amount / token_amount
                        
                        # Check if price is in reasonable range
                        if expected_price_range[0] <= price_sol <= expected_price_range[1]:
                            if self.logger:
                                mint_display = token_mint[:8] + "..." if token_mint else "unknown"
                                self.logger.debug(f"🎯 HELIUS: {sol_lamports} lamports ({sol_amount:.9f} SOL) ÷ {token_raw_amount} raw ({token_amount:.6f} tokens) = {price_sol:.8f} SOL/token (mint: {mint_display}, decimals: {actual_token_decimals})")
                            return price_sol, actual_token_decimals, "helius_api"
                        else:
                            if self.logger:
                                self.logger.warning(f"🎯 HELIUS decimals ({actual_token_decimals}) gave unreasonable price {price_sol:.12f} SOL, trying fallbacks")
                except (ZeroDivisionError, TypeError, ValueError):
                    if self.logger:
                        self.logger.warning(f"🎯 HELIUS decimals ({actual_token_decimals}) calculation failed, trying fallbacks")
            
            # Fallback to testing common decimal values - prioritize 6 and 9 decimals
            test_decimals = [6, 9, 4, 8, 3, 2]  # Common token decimal values, 6 and 9 most common
            
            for decimals in test_decimals:
                try:
                    # Convert token raw amount to actual amount
                    token_amount = token_raw_amount / (10 ** decimals)
                    
                    if token_amount > 0:
                        # Price = SOL per token
                        price_sol = sol_amount / token_amount
                        
                        # Check if price is in reasonable range
                        if expected_price_range[0] <= price_sol <= expected_price_range[1]:
                            method = f"tested_decimals_{decimals}"
                            if self.logger:
                                mint_display = token_mint[:8] + "..." if token_mint else "unknown"
                                self.logger.debug(f"📊 FALLBACK: {sol_lamports} lamports ({sol_amount:.9f} SOL) ÷ {token_raw_amount} raw ({token_amount:.6f} tokens) = {price_sol:.8f} SOL/token (mint: {mint_display}, decimals: {decimals})")
                            return price_sol, decimals, method
                            
                except (ZeroDivisionError, TypeError, ValueError):
                    continue
            
            # If no reasonable price found, log the issue
            if self.logger:
                sol_amount = sol_lamports / 1_000_000_000
                mint_display = token_mint[:8] + "..." if token_mint else "unknown"
                tested_list = [actual_token_decimals] + test_decimals if actual_token_decimals else test_decimals
                self.logger.warning(f"Could not calculate reasonable price for {sol_lamports} lamports ({sol_amount:.9f} SOL) / {token_raw_amount} raw tokens (mint: {mint_display}, tried decimals: {tested_list})")
            return None, None, "no_reasonable_price"
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error calculating price from amounts {sol_lamports}/{token_raw_amount}: {e}")
            return None, None, "calculation_error"

    def _detect_token_decimals(self, buy_amount_raw, sell_amount_raw, expected_price_range=(0.0000001, 100.0)):
        """
        Auto-detect token decimals by testing different decimal combinations
        to find reasonable price ranges.
        
        Args:
            buy_amount_raw: Raw buy amount (usually SOL)
            sell_amount_raw: Raw sell amount (usually tokens)  
            expected_price_range: Tuple of (min_price, max_price) in SOL
        
        Returns:
            tuple: (sol_decimals, token_decimals, calculated_price)
        """
        if not buy_amount_raw or not sell_amount_raw:
            return 9, 6, None
            
        # Test different decimal combinations
        test_combinations = [
            (9, 6),   # Common: SOL=9, meme token=6
            (9, 9),   # SOL=9, established token=9
            (9, 8),   # SOL=9, token=8
            (9, 4),   # SOL=9, very small token=4
            (9, 3),   # SOL=9, micro token=3
        ]
        
        for sol_dec, token_dec in test_combinations:
            try:
                # Calculate price with this decimal combination
                sol_adjusted = buy_amount_raw / (10 ** sol_dec)
                token_adjusted = sell_amount_raw / (10 ** token_dec)
                
                if token_adjusted > 0:
                    price_sol = sol_adjusted / token_adjusted
                    
                    # Check if price is in reasonable range
                    if expected_price_range[0] <= price_sol <= expected_price_range[1]:
                        if self.logger:
                            self.logger.debug(f"Auto-detected decimals: SOL={sol_dec}, Token={token_dec}, Price={price_sol:.8f} SOL")
                        return sol_dec, token_dec, price_sol
                        
            except (ZeroDivisionError, TypeError, ValueError):
                continue
                
        # Fallback to default if no reasonable price found
        if self.logger:
            self.logger.warning(f"Could not auto-detect decimals for amounts {buy_amount_raw}/{sell_amount_raw}, using defaults")
        return 9, 6, None 

    async def _get_token_decimals_from_helius(self, mint_address: str) -> int:
        """
        Fetch actual token decimals from Helius API using getAccountInfo.
        Caches results to avoid repeated API calls.
        
        Args:
            mint_address: The token mint address
            
        Returns:
            int: Token decimals (6 for most meme tokens, 9 for established tokens)
        """
        # Check cache first
        if mint_address in self._decimal_cache:
            return self._decimal_cache[mint_address]
        
        try:
            import httpx
            
            # Skip API call if using placeholder key
            if 'placeholder' in self._helius_base_url.lower() or not self._helius_base_url.startswith('http'):
                if self.logger:
                    self.logger.debug(f"Skipping Helius API call (invalid endpoint): {self._helius_base_url}")
                raise Exception("Invalid Helius endpoint")
            
            # Prepare Helius getAccountInfo request for token mint
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getAccountInfo",
                "params": [
                    mint_address,
                    {
                        "encoding": "jsonParsed"
                    }
                ]
            }
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(self._helius_base_url, json=payload)
                response.raise_for_status()
                
                data = response.json()
                
                if "result" in data and data["result"] and "value" in data["result"]:
                    account_info = data["result"]["value"]
                    if account_info and "data" in account_info:
                        parsed_data = account_info["data"]
                        if "parsed" in parsed_data and "info" in parsed_data["parsed"]:
                            decimals = parsed_data["parsed"]["info"].get("decimals")
                            if decimals is not None:
                                self._decimal_cache[mint_address] = decimals
                                if self.logger:
                                    self.logger.debug(f"✅ Fetched {mint_address[:8]}... decimals from Helius: {decimals}")
                                return decimals
                
                # If we couldn't parse, log and fall back
                if self.logger:
                    self.logger.warning(f"❌ Could not parse token decimals from Helius for {mint_address[:8]}...")
                    
        except Exception as e:
            if self.logger:
                self.logger.debug(f"🔧 Helius API unavailable for {mint_address[:8]}..., using fallback: {e}")
        
        # Fallback to common values
        fallback_decimals = 6  # Most meme tokens use 6 decimals
        self._decimal_cache[mint_address] = fallback_decimals
        if self.logger:
            self.logger.debug(f"Using fallback decimals for {mint_address[:8]}...: {fallback_decimals}")
        return fallback_decimals
    
    def _get_token_decimals_sync(self, mint_address: str) -> int:
        """
        Synchronous version that returns cached decimals or reasonable fallback.
        Use this when async call is not possible.
        """
        # Check cache first
        if mint_address in self._decimal_cache:
            return self._decimal_cache[mint_address]
        
        # Return fallback without API call
        fallback_decimals = 6  # Most meme tokens
        self._decimal_cache[mint_address] = fallback_decimals
        if self.logger:
            self.logger.debug(f"Sync fallback decimals for {mint_address[:8]}...: {fallback_decimals}")
        return fallback_decimals 

    def _extract_token_mint_from_logs(self, logs: List[str], signature: str = None) -> str:
        """
        Try to extract token mint address from logs or use the signature to fetch transaction details.
        
        Args:
            logs: Transaction logs to search for mint addresses
            signature: Transaction signature for Helius lookup
            
        Returns:
            str: Token mint address if found, None otherwise
        """
        # Try to extract mint from logs first (faster)
        for log in logs:
            # Look for Solana addresses (base58, 32-44 chars, alphanumeric)
            import re
            addresses = re.findall(r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b', log)
            for addr in addresses:
                # Skip known program IDs and SOL mint
                if addr in ['11111111111111111111111111111112', 'So11111111111111111111111111111111112']:
                    continue
                # First non-program address is likely the token mint
                if len(addr) >= 32:
                    if self.logger:
                        self.logger.debug(f"Extracted potential mint from logs: {addr[:8]}...")
                    return addr
        
        # If signature provided, we could fetch transaction details from Helius here
        # For now, return None to use fallback decimals
        return None
    
    def _extract_all_mints_from_logs(self, logs: List[str]) -> List[str]:
        """
        Extract all possible token mint addresses from logs.
        Used to verify that our target mint is involved in the transaction.
        
        Args:
            logs: Transaction logs to search for mint addresses
            
        Returns:
            List[str]: All unique mint addresses found in logs
        """
        extracted_mints = set()
        
        # Known program IDs to skip
        known_programs = {
            '11111111111111111111111111111112',  # System Program
            'So11111111111111111111111111111111112',  # SOL mint
            '675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8',  # Raydium V4
            'CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK',  # Raydium CLMM
            '6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P',   # PumpFun
            'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA',   # Token Program
            'ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL'    # Associated Token Program
        }
        
        try:
            import re
            for log in logs:
                # Look for Solana addresses (base58, 32-44 chars, alphanumeric)
                addresses = re.findall(r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b', log)
                for addr in addresses:
                    if addr not in known_programs and len(addr) >= 32:
                        extracted_mints.add(addr)
                        
            return list(extracted_mints)
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error extracting mints from logs: {e}")
            return []
    
    # **ADDED: Helius Pump AMM WebSocket Stream Methods**
    
    async def start_helius_pump_stream(self, callback: Optional[Callable] = None):
        """
        Start the Helius Pump AMM WebSocket stream for real-time price updates
        
        Args:
            callback: Optional callback function to handle price updates
        """
        if self._stream_running:
            if self.logger:
                self.logger.warning("Helius Pump AMM stream is already running")
            return
        
        self._stream_callback = callback
        self._stream_running = True
        
        if self.logger:
            masked_url = self._mask_websocket_url(self._websocket_url)
            self.logger.info(f"🚀 Starting Helius Pump AMM stream: {masked_url}")
        
        # Start the stream in a background task
        self._stream_task = asyncio.create_task(self._run_pump_stream())
    
    async def stop_helius_pump_stream(self):
        """Stop the Helius Pump AMM WebSocket stream"""
        self._stream_running = False
        
        if self._ws_connection:
            await self._ws_connection.close()
        
        if self._stream_task:
            self._stream_task.cancel()
            try:
                await self._stream_task
            except asyncio.CancelledError:
                pass
        
        if self.logger:
            self.logger.info("🛑 Helius Pump AMM stream stopped")
    
    def _mask_websocket_url(self, url: str) -> str:
        """Mask API key in WebSocket URL for logging"""
        if 'api-key=' in url:
            parts = url.split('api-key=')
            if len(parts) > 1:
                key_part = parts[1].split('&')[0]
                masked_key = key_part[:8] + '...' if len(key_part) > 8 else '***'
                return url.replace(key_part, masked_key)
        return url
    
    async def _run_pump_stream(self):
        """Main stream loop with reconnection logic"""
        max_retries = 5
        retry_delay = 1.0
        retry_count = 0
        
        while self._stream_running and retry_count < max_retries:
            try:
                await self._connect_and_listen()
                retry_count = 0  # Reset on successful connection
            except Exception as e:
                retry_count += 1
                if retry_count < max_retries and self._stream_running:
                    if self.logger:
                        self.logger.warning(f"🔄 Helius stream connection failed, retrying in {retry_delay}s (attempt {retry_count}/{max_retries}): {e}")
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 60)  # Exponential backoff, max 60s
                else:
                    if self.logger:
                        self.logger.error(f"❌ Max retries reached for Helius stream: {e}")
                    break
    
    async def _connect_and_listen(self):
        """Connect to Helius WebSocket and listen for Pump AMM data"""
        if self.logger:
            self.logger.info("🔌 Connecting to Helius Pump AMM stream...")
        
        async with websockets.connect(self._websocket_url) as websocket:
            self._ws_connection = websocket
            if self.logger:
                self.logger.info("✅ Connected to Helius Pump AMM stream")
            
            # Subscribe to Pump AMM logs
            await self._subscribe_to_pump_amm(websocket)
            
            # Start ping task to keep connection alive
            ping_task = asyncio.create_task(self._ping_loop(websocket))
            
            try:
                # Listen for messages
                async for message in websocket:
                    if not self._stream_running:
                        break
                    await self._handle_stream_message(message)
            finally:
                ping_task.cancel()
                try:
                    await ping_task
                except asyncio.CancelledError:
                    pass
    
    async def _subscribe_to_pump_amm(self, websocket):
        """Subscribe to Pump AMM program logs"""
        subscription_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "logsSubscribe",
            "params": [
                {
                    "mentions": [self._pump_program_id]
                },
                {
                    "commitment": "confirmed"
                }
            ]
        }
        
        if self.logger:
            self.logger.info(f"📡 Subscribing to Pump AMM logs for program: {self._pump_program_id}")
        await websocket.send(json.dumps(subscription_request))
    
    async def _ping_loop(self, websocket):
        """Send periodic pings to keep connection alive"""
        while self._stream_running:
            try:
                await asyncio.sleep(30)  # Ping every 30 seconds
                if websocket.open:
                    await websocket.ping()
                    if self.logger:
                        self.logger.debug("💓 Ping sent to Helius")
            except asyncio.CancelledError:
                break
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"⚠️ Ping failed: {e}")
                break
    
    async def _handle_stream_message(self, message: str):
        """Handle incoming WebSocket messages"""
        try:
            data = json.loads(message)
            
            # Handle subscription confirmation
            if 'result' in data and isinstance(data['result'], int):
                self._subscription_id = data['result']
                if self.logger:
                    self.logger.info(f"✅ Subscribed to Pump AMM with ID: {self._subscription_id}")
                return
            
            # Handle log notifications
            if 'method' in data and data['method'] == 'logsNotification':
                await self._process_stream_log_notification(data)
                
        except json.JSONDecodeError as e:
            if self.logger:
                self.logger.error(f"❌ Failed to parse JSON message: {e}")
        except Exception as e:
            if self.logger:
                self.logger.error(f"❌ Error handling stream message: {e}")
    
    async def _process_stream_log_notification(self, data: Dict[str, Any]):
        """Process Pump AMM log notifications from the stream"""
        try:
            params = data.get('params', {})
            result = params.get('result', {})
            value = result.get('value', {})
            
            signature = value.get('signature')
            logs = value.get('logs', [])
            
            if not signature or not logs:
                return
            
            if self.logger:
                self.logger.info(f"🔥 Helius Pump AMM stream event: {signature[:8]}... ({len(logs)} logs)")
            
            # Use the existing async parsing logic with actual Helius decimal fetching
            price_data = await self.parse_swap_logs_async(logs, signature)
            
            if price_data and price_data.get('price') and self._stream_callback:
                # Enhance the data with stream-specific information
                enhanced_data = {
                    **price_data,
                    'signature': signature,
                    'timestamp': time.time(),
                    'source': 'helius_pump_stream',
                    'dex_id': self.DEX_ID,
                    'stream_source': True
                }
                
                if self.logger:
                    price = price_data['price']
                    decimals_info = f"(decimals: {price_data.get('token_decimals_used', 'unknown')})"
                    method_info = price_data.get('calculation_method', 'unknown')
                    self.logger.info(f"🎯 Helius stream extracted price: {price:.8f} SOL {decimals_info} [{method_info}]")
                
                # Call the callback with the enhanced price data
                if asyncio.iscoroutinefunction(self._stream_callback):
                    await self._stream_callback(enhanced_data)
                else:
                    self._stream_callback(enhanced_data)
                
        except Exception as e:
            if self.logger:
                self.logger.error(f"❌ Error processing stream log notification: {e}")
    
    def is_stream_running(self) -> bool:
        """Check if the Helius Pump AMM stream is currently running"""
        return self._stream_running
    
    def get_stream_status(self) -> Dict[str, Any]:
        """Get status information about the Helius Pump AMM stream"""
        return {
            'running': self._stream_running,
            'connected': self._ws_connection is not None and not self._ws_connection.closed if self._ws_connection else False,
            'subscription_id': self._subscription_id,
            'websocket_url_masked': self._mask_websocket_url(self._websocket_url),
            'program_id': self._pump_program_id
        }