"""
Raydium V4 DEX parser for swap logs and account updates
Consolidates parsing logic from blockchain_listener.py and market_data.py
"""

import re
import base64
import struct
import math
from typing import List, Dict, Any, Optional
from .base_parser import DexParser

class RaydiumV4Parser(DexParser):
    """Parser for Raydium V4 AMM pools"""
    
    DEX_ID = 'raydium_v4'
    
    def parse_swap_logs(self, logs: List[str], signature: str = None, target_mint: str = None) -> Optional[Dict[str, Any]]:
        """
        Parse Raydium V4 swap logs to extract price information.
        Uses sophisticated parsing logic from market_data.py with enhancements.
        """
        try:
            if not self.validate_logs(logs):
                return None
            
            # ✅ CRITICAL FIX: Extract all mints from logs first
            extracted_mints = self._extract_all_mints_from_logs(logs)
            
            # ✅ CRITICAL FIX: Only process if our target mint is involved in this transaction
            if target_mint and extracted_mints and target_mint not in extracted_mints:
                if self.logger:
                    self.logger.debug(f"🚫 Skipping Raydium V4 transaction {signature[:8]}... - target mint {target_mint[:8]}... not found in logs (found: {[m[:8]+'...' for m in extracted_mints[:3]]})")
                return None
                
            # Enhanced swap info structure
            swap_info = {
                "event_type": "swap",
                "found_swap": False,
                "swap_direction": None,
                "amount_in": None,
                "amount_out": None,
                "amount_in_decimals": None,
                "amount_out_decimals": None,
                "instruction_type": None,
                "token_in": None,
                "token_out": None,
                "price_ratio": None,
                "fee_amount": None,
                "raw_amounts": [],
                "transfers_detected": [],
                "parsing_confidence": 0.0,
                "liquidity_change": None,
                "slippage_estimate": None,
                "signature": signature,
                "source": "raydium_v4_log",
                "dex_id": self.DEX_ID,
                "target_mint": target_mint,
                "extracted_mints": extracted_mints  # Track all mints found
            }
            
            transfer_count = 0
            
            for log in logs:
                log_lower = log.lower()
                
                # Enhanced Raydium swap instruction detection
                if "instruction: swapbasein" in log_lower:
                    swap_info["found_swap"] = True
                    swap_info["instruction_type"] = "swapbasein"
                    swap_info["swap_direction"] = "base_to_quote"
                    swap_info["parsing_confidence"] += 0.4
                    if self.logger and log:
                        self.logger.debug(f"Found Raydium V4 SwapBaseIn: {log}")
                    
                elif "instruction: swapbaseout" in log_lower:
                    swap_info["found_swap"] = True
                    swap_info["instruction_type"] = "swapbaseout"
                    swap_info["swap_direction"] = "quote_to_base"
                    swap_info["parsing_confidence"] += 0.4
                    if self.logger and log:
                        self.logger.debug(f"Found Raydium V4 SwapBaseOut: {log}")
                    
                # Look for token transfers (indicates actual movement)
                elif "transfer" in log_lower:
                    transfer_count += 1
                    swap_info["parsing_confidence"] += 0.1
                    
                    # Extract transfer amounts
                    transfer_amounts = re.findall(r'transfer[:\s]+(\d+)', log, re.IGNORECASE)
                    for amount_str in transfer_amounts:
                        try:
                            amount = int(amount_str)
                            if 1000 <= amount <= 1000000000000:  # Filter realistic swap amounts (1K-1T tokens)
                                swap_info["transfers_detected"].append(amount)
                                swap_info["raw_amounts"].append(amount)
                        except ValueError:
                            continue
                            
                # Enhanced amount extraction
                amount_patterns = [
                    r'transfer[_\s]*amount[:\s]+(\d+)',
                    r'swap[_\s]*amount[:\s]+(\d+)',
                    r'in[_\s]*amount[:\s]+(\d+)', 
                    r'out[_\s]*amount[:\s]+(\d+)',
                    r'fee[_\s]*amount[:\s]+(\d+)'
                ]
                
                for pattern in amount_patterns:
                    amounts = re.findall(pattern, log, re.IGNORECASE)
                    for amount_str in amounts:
                        try:
                            amount = int(amount_str)
                            if 1000 <= amount <= 1000000000000:  # Filter realistic amounts (1K-1T)
                                swap_info["raw_amounts"].append(amount)
                                swap_info["parsing_confidence"] += 0.05
                        except ValueError:
                            continue
                
                # Extract token addresses (Base58 format)
                token_pattern = r'\b([1-9A-HJ-NP-Za-km-z]{32,44})\b'
                tokens = re.findall(token_pattern, log)
                if tokens:
                    for token in tokens:
                        if not swap_info["token_in"]:
                            swap_info["token_in"] = token
                        elif not swap_info["token_out"] and token != swap_info["token_in"]:
                            swap_info["token_out"] = token
                            break
                    swap_info["parsing_confidence"] += 0.1
                
                # Look for fee information
                fee_patterns = [r'fee[:\s]+(\d+)', r'commission[:\s]+(\d+)']
                for pattern in fee_patterns:
                    fees = re.findall(pattern, log_lower)
                    if fees:
                        try:
                            swap_info["fee_amount"] = int(fees[0])
                            swap_info["parsing_confidence"] += 0.1
                        except ValueError:
                            pass
                            
                # Look for pool initialization or liquidity changes
                if "initialize" in log_lower and ("pool" in log_lower or "amm" in log_lower):
                    swap_info["event_type"] = "pool_initialize"
                    swap_info["found_swap"] = True
                    swap_info["parsing_confidence"] += 0.3
                    
                if "liquidity" in log_lower:
                    liquidity_amounts = re.findall(r'liquidity[:\s]+(\d+)', log_lower)
                    if liquidity_amounts:
                        try:
                            swap_info["liquidity_change"] = int(liquidity_amounts[0])
                            swap_info["parsing_confidence"] += 0.1
                        except ValueError:
                            pass
            
            # Process and assign amounts intelligently
            if len(swap_info["raw_amounts"]) >= 2:
                # Remove duplicates and sort
                unique_amounts = list(set(swap_info["raw_amounts"]))
                unique_amounts.sort(reverse=True)
                
                # Assign amounts based on transfer patterns
                if len(swap_info["transfers_detected"]) >= 2:
                    # Use transfer amounts as they're more reliable
                    swap_info["amount_in"] = swap_info["transfers_detected"][0]
                    swap_info["amount_out"] = swap_info["transfers_detected"][1]
                else:
                    # Use largest amounts found
                    swap_info["amount_in"] = unique_amounts[0]
                    swap_info["amount_out"] = unique_amounts[1]
                    
                swap_info["parsing_confidence"] += 0.2
                
                # Calculate price ratio and slippage estimate with proper decimal handling
                if swap_info["amount_in"] and swap_info["amount_out"]:
                    try:
                        amount_in_raw = swap_info["amount_in"]
                        amount_out_raw = swap_info["amount_out"]
                        
                        # Initialize price variables to avoid NameError
                        price_sol = None
                        
                        # Apply proper decimal handling for Raydium V4
                        # Typically: SOL has 9 decimals, other tokens have 6-9 decimals
                        sol_decimals = 9
                        token_decimals = 6  # Common for meme tokens, 9 for established tokens
                        
                        # Determine swap direction and calculate price in SOL per token
                        if swap_info["swap_direction"] == "base_to_quote":
                            # Base (token) → Quote (SOL): selling token for SOL
                            token_amount = amount_in_raw / (10 ** token_decimals)
                            sol_amount = amount_out_raw / (10 ** sol_decimals)
                            if token_amount > 0:
                                price_sol = sol_amount / token_amount
                        elif swap_info["swap_direction"] == "quote_to_base":
                            # Quote (SOL) → Base (token): buying token with SOL
                            sol_amount = amount_in_raw / (10 ** sol_decimals)
                            token_amount = amount_out_raw / (10 ** token_decimals)
                            if token_amount > 0:
                                price_sol = sol_amount / token_amount
                        else:
                            # Unknown direction, use heuristic based on amount sizes
                            if amount_in_raw > amount_out_raw * 100:  # amount_in likely token (larger raw value)
                                token_amount = amount_in_raw / (10 ** token_decimals)
                                sol_amount = amount_out_raw / (10 ** sol_decimals)
                                if token_amount > 0:
                                    price_sol = sol_amount / token_amount
                            else:  # amount_in likely SOL
                                sol_amount = amount_in_raw / (10 ** sol_decimals)
                                token_amount = amount_out_raw / (10 ** token_decimals)
                                if token_amount > 0:
                                    price_sol = sol_amount / token_amount
                        
                        # Sanity check: reasonable SOL price range
                        if 0.000000001 <= price_sol <= 1.0:
                            swap_info["price"] = price_sol  # Store SOL price
                            swap_info["price_ratio"] = price_sol  # Keep for backwards compatibility
                            if self.logger and price_sol is not None:
                                self.logger.debug(f"Raydium V4 calculated price: {price_sol:.12f} SOL per token")
                            
                            # Simple slippage estimate
                            try:
                                if price_sol < 0.95 * (amount_out_raw / amount_in_raw) or price_sol > 1.05 * (amount_out_raw / amount_in_raw):
                                    slippage = abs(1 - (price_sol / (amount_out_raw / amount_in_raw))) * 100
                                    if slippage is not None and not math.isnan(slippage):
                                        swap_info["slippage_estimate"] = f"{slippage:.2f}%"
                            except (ZeroDivisionError, TypeError):
                                pass
                            
                            swap_info["parsing_confidence"] += 0.15
                        else:
                            if self.logger and price_sol is not None:
                                self.logger.warning(f"Raydium V4 calculated price {price_sol:.12f} SOL outside reasonable range")
                            
                    except (ZeroDivisionError, TypeError, NameError):
                        # Fallback to old calculation if decimal handling fails
                        try:
                            # Initialize fallback price variable
                            price_adjusted = None
                            
                            raw_price_ratio = amount_out_raw / amount_in_raw
                            # Apply a conservative decimal adjustment
                            price_adjusted = raw_price_ratio / (10 ** 3)  # Assume ~3 decimal difference
                            if 0.000000001 <= price_adjusted <= 1.0:
                                swap_info["price"] = price_adjusted
                                swap_info["price_ratio"] = price_adjusted
                                if self.logger and price_adjusted is not None:
                                    self.logger.debug(f"Raydium V4 fallback price: {price_adjusted:.12f} SOL per token")
                                swap_info["parsing_confidence"] += 0.1
                        except (ZeroDivisionError, TypeError):
                            pass
            
            # Enhance confidence based on transfer detection
            if transfer_count >= 2:
                swap_info["parsing_confidence"] += 0.2
                
            # Only return if we have reasonable confidence and found a swap
            if swap_info["found_swap"] and swap_info["parsing_confidence"] >= 0.3:
                return swap_info
            else:
                return None
                
        except Exception as e:
            if self.logger and e is not None:
                self.logger.error(f"Error parsing Raydium V4 swap log: {e}", exc_info=True)
            return None

    def parse_account_update(self, raw_data: Any, pool_address: str = None) -> Optional[Dict[str, Any]]:
        """
        Parse Raydium V4 pool account update data
        Extracts current pool state including prices and liquidity
        """
        try:
            if not raw_data:
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
                
            if len(decoded_data) < 752:  # Raydium V4 pool state is 752 bytes
                if self.logger and pool_address:
                    self.logger.warning(f"Raydium V4 pool {pool_address} account data too short: {len(decoded_data)} bytes")
                return None
                
            try:
                # Extract decimals from known offsets
                base_decimal = struct.unpack('<Q', decoded_data[32:40])[0]  # offset 32 for base_decimal
                quote_decimal = struct.unpack('<Q', decoded_data[40:48])[0]  # offset 40 for quote_decimal
                
                # Extract vault addresses from known offsets
                base_vault_offset = 296  # offset for pool_base_vault in the complete layout
                quote_vault_offset = 328  # offset for pool_quote_vault in the complete layout
                
                if len(decoded_data) >= base_vault_offset + 32 and len(decoded_data) >= quote_vault_offset + 32:
                    base_vault = decoded_data[base_vault_offset:base_vault_offset + 32]
                    quote_vault = decoded_data[quote_vault_offset:quote_vault_offset + 32]
                    
                    return {
                        "event_type": "account_update",
                        "pool_address": pool_address,
                        "base_decimal": base_decimal,
                        "quote_decimal": quote_decimal,
                        "pool_base_vault": base_vault.hex(),
                        "pool_quote_vault": quote_vault.hex(),
                        "source": "raydium_v4_account",
                        "dex_id": self.DEX_ID,
                        "requires_vault_fetch": True  # Indicates need to fetch vault balances for price
                    }
                else:
                    if self.logger and pool_address:
                        self.logger.warning(f"Insufficient data to extract vault addresses for Raydium V4 pool {pool_address}")
                    return None
                    
            except struct.error as e:
                if self.logger and e is not None and pool_address:
                    self.logger.warning(f"Error parsing Raydium V4 pool structure for {pool_address}: {e}")
                return None
                
        except Exception as e:
            if self.logger and e is not None and pool_address:
                self.logger.error(f"Error parsing Raydium V4 account update for {pool_address}: {e}", exc_info=True)
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