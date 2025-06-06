"""
Raydium CLMM (Concentrated Liquidity Market Maker) parser
Consolidates parsing logic from blockchain_listener.py and market_data.py
"""

import re
from typing import List, Dict, Any, Optional
from .base_parser import DexParser

class RaydiumClmmParser(DexParser):
    """Parser for Raydium CLMM (Concentrated Liquidity) pools"""
    
    DEX_ID = 'raydium_clmm'
    
    def parse_swap_logs(self, logs: List[str], signature: str = None, target_mint: str = None) -> Optional[Dict[str, Any]]:
        """
        Parse Raydium CLMM swap logs to extract price information.
        Enhanced with concentrated liquidity position tracking and price impact analysis.
        """
        try:
            if not self.validate_logs(logs):
                return None
            
            # ✅ CRITICAL FIX: Extract all mints from logs first
            extracted_mints = self._extract_all_mints_from_logs(logs)
            
            # ✅ CRITICAL FIX: Only process if our target mint is involved in this transaction
            if target_mint and extracted_mints and target_mint not in extracted_mints:
                if self.logger:
                    self.logger.debug(f"🚫 Skipping Raydium CLMM transaction {signature[:8]}... - target mint {target_mint[:8]}... not found in logs (found: {[m[:8]+'...' for m in extracted_mints[:3]]})")
                return None
                
            # Enhanced CLMM-specific swap info
            swap_info = {
                "event_type": "swap",
                "found_swap": False,
                "amount_in": None,
                "amount_out": None,
                "amount_a": None,
                "amount_b": None,
                "is_exact_in": None,
                "tick_current": None,
                "sqrt_price": None,
                "sqrt_price_raw": None,
                "sqrt_price_type": None,
                "liquidity": None,
                "fee_amount": None,
                "price_impact": None,
                "raw_amounts": [],
                "transfers_detected": [],
                "parsing_confidence": 0.0,
                "pool_position_changes": [],
                "signature": signature,
                "source": "raydium_clmm_log",
                "dex_id": self.DEX_ID,
                "target_mint": target_mint,
                "extracted_mints": extracted_mints  # Track all mints found
            }
            
            transfer_count = 0
            
            for log in logs:
                log_lower = log.lower()
                
                # Enhanced CLMM swap detection
                if "instruction: swap" in log_lower:
                    swap_info["found_swap"] = True
                    swap_info["parsing_confidence"] += 0.4
                    if self.logger and log:
                        self.logger.debug(f"Found CLMM swap instruction: {log}")
                    
                    # Enhanced swap direction detection
                    if "exactin" in log_lower or "exact_in" in log_lower:
                        swap_info["is_exact_in"] = True
                        swap_info["parsing_confidence"] += 0.1
                    elif "exactout" in log_lower or "exact_out" in log_lower:
                        swap_info["is_exact_in"] = False
                        swap_info["parsing_confidence"] += 0.1
                
                # Look for CLMM-specific position changes
                elif "position" in log_lower and ("increase" in log_lower or "decrease" in log_lower):
                    swap_info["pool_position_changes"].append(log)
                    swap_info["parsing_confidence"] += 0.1
                    
                # Enhanced transfer detection
                elif "transfer" in log_lower:
                    transfer_count += 1
                    swap_info["parsing_confidence"] += 0.1
                    
                    # Extract transfer amounts
                    transfer_amounts = re.findall(r'transfer[:\s]+(\d+)', log, re.IGNORECASE)
                    for amount_str in transfer_amounts:
                        try:
                            amount = int(amount_str)
                            if 100 <= amount <= 1000000000000:  # CLMM realistic amounts (100-1T)
                                swap_info["transfers_detected"].append(amount)
                                swap_info["raw_amounts"].append(amount)
                        except ValueError:
                            continue
                
                # Extract CLMM-specific parameters
                # Tick information (for price calculation)
                tick_matches = re.findall(r'tick[_\s]*current[:\s]+(-?\d+)', log_lower)
                if not tick_matches:
                    tick_matches = re.findall(r'tick[:\s]+(-?\d+)', log_lower)
                if tick_matches:
                    try:
                        swap_info["tick_current"] = int(tick_matches[0])
                        swap_info["parsing_confidence"] += 0.15
                    except ValueError:
                        pass
                
                # Square root price (concentrated liquidity specific)
                sqrt_price_matches = re.findall(r'sqrt[_\s]*price[_\s]*x64[:\s]+(\d+)', log_lower)
                if not sqrt_price_matches:
                    sqrt_price_matches = re.findall(r'sqrt[_\s]*price[:\s]+(\d+)', log_lower)
                if sqrt_price_matches:
                    try:
                        sqrt_price_raw = int(sqrt_price_matches[0])
                        swap_info["sqrt_price_raw"] = sqrt_price_raw
                        
                        # Analyze sqrt_price values instead of filtering
                        if sqrt_price_raw == 2**96:
                            if self.logger:
                                self.logger.info(f"sqrt_price = 2^96 detected - likely indicates pool initialization or max bounds")
                            swap_info["sqrt_price_type"] = "max_bound_2_96"
                        elif sqrt_price_raw >= 2**95:
                            if self.logger and sqrt_price_raw is not None:
                                self.logger.info(f"Large sqrt_price detected: {sqrt_price_raw} - near maximum bounds")
                            swap_info["sqrt_price_type"] = "near_max_bound"
                        elif sqrt_price_raw <= 1000:
                            if self.logger and sqrt_price_raw is not None:
                                self.logger.info(f"Small sqrt_price detected: {sqrt_price_raw} - near minimum bounds")
                            swap_info["sqrt_price_type"] = "near_min_bound"
                        else:
                            # Calculate actual price from sqrt_price
                            # Price = (sqrt_price / 2^64)^2 for most CLMM implementations
                            try:
                                normalized_sqrt_price = sqrt_price_raw / (2**64)
                                calculated_price = normalized_sqrt_price ** 2
                                swap_info["sqrt_price"] = calculated_price
                                swap_info["price"] = calculated_price
                                swap_info["sqrt_price_type"] = "calculated_price"
                                swap_info["parsing_confidence"] += 0.25
                                if self.logger and calculated_price is not None:
                                    self.logger.debug(f"Calculated CLMM price from sqrt_price: {calculated_price}")
                            except (OverflowError, ZeroDivisionError) as e:
                                if self.logger and e is not None and sqrt_price_raw is not None:
                                    self.logger.warning(f"Error calculating price from sqrt_price {sqrt_price_raw}: {e}")
                                swap_info["sqrt_price_type"] = "calculation_error"
                        
                        swap_info["parsing_confidence"] += 0.15
                    except ValueError:
                        pass
                
                # Liquidity information
                liquidity_matches = re.findall(r'liquidity[_\s]*[:\s]+(\d+)', log_lower)
                if liquidity_matches:
                    try:
                        swap_info["liquidity"] = int(liquidity_matches[0])
                        swap_info["parsing_confidence"] += 0.1
                    except ValueError:
                        pass
                
                # Enhanced amount extraction patterns for CLMM
                amount_patterns = [
                    r'amount[_\s]*a[:\s]+(\d+)',
                    r'amount[_\s]*b[:\s]+(\d+)',
                    r'amount[_\s]*in[:\s]+(\d+)',
                    r'amount[_\s]*out[:\s]+(\d+)',
                    r'fee[_\s]*amount[:\s]+(\d+)'
                ]
                
                for pattern in amount_patterns:
                    amounts = re.findall(pattern, log, re.IGNORECASE)
                    for amount_str in amounts:
                        try:
                            amount = int(amount_str)
                            if 100 <= amount <= 1000000000000:  # CLMM amounts can be smaller
                                swap_info["raw_amounts"].append(amount)
                                
                                # Try to assign to specific amount fields
                                if "amount_a" in pattern and swap_info["amount_a"] is None:
                                    swap_info["amount_a"] = amount
                                elif "amount_b" in pattern and swap_info["amount_b"] is None:
                                    swap_info["amount_b"] = amount
                                elif "amount_in" in pattern and swap_info["amount_in"] is None:
                                    swap_info["amount_in"] = amount
                                elif "amount_out" in pattern and swap_info["amount_out"] is None:
                                    swap_info["amount_out"] = amount
                                elif "fee" in pattern and swap_info["fee_amount"] is None:
                                    swap_info["fee_amount"] = amount
                                    
                                swap_info["parsing_confidence"] += 0.05
                        except ValueError:
                            continue
            
            # Process amounts intelligently for CLMM
            if len(swap_info["raw_amounts"]) >= 2:
                unique_amounts = list(set(swap_info["raw_amounts"]))
                unique_amounts.sort(reverse=True)
                
                # Assign amounts if not already assigned by pattern matching
                if swap_info["amount_in"] is None and len(unique_amounts) >= 1:
                    swap_info["amount_in"] = unique_amounts[0]
                if swap_info["amount_out"] is None and len(unique_amounts) >= 2:
                    swap_info["amount_out"] = unique_amounts[1]
                    
                swap_info["parsing_confidence"] += 0.15
                
                # Calculate price ratio if amounts available and no sqrt_price was calculated
                if (swap_info["amount_in"] and swap_info["amount_out"] and 
                    swap_info.get("sqrt_price_type") != "calculated_price"):
                    try:
                        price_ratio = swap_info["amount_out"] / swap_info["amount_in"]
                        
                        # Only use this price if we don't have a better sqrt_price calculation
                        if not swap_info.get("price"):
                            swap_info["price"] = round(price_ratio, 8)
                            swap_info["parsing_confidence"] += 0.1
                            
                    except (ZeroDivisionError, TypeError):
                        pass
            
            # Enhance confidence based on transfer detection
            if transfer_count >= 2:
                swap_info["parsing_confidence"] += 0.2
                
            # CLMM requires higher confidence due to complexity
            if swap_info["found_swap"] and swap_info["parsing_confidence"] >= 0.4:
                return swap_info
            else:
                return None
                
        except Exception as e:
            if self.logger and e is not None:
                self.logger.error(f"Error parsing Raydium CLMM swap log: {e}", exc_info=True)
            return None

    def parse_account_update(self, raw_data: Any, pool_address: str = None) -> Optional[Dict[str, Any]]:
        """
        Parse Raydium CLMM account update data
        CLMM pools have more complex state than regular AMMs
        """
        try:
            if not raw_data:
                return None
                
            # For now, return basic structure - CLMM account parsing is complex
            # and would require the full borsh layout definition
            return {
                "event_type": "account_update",
                "pool_address": pool_address,
                "source": "raydium_clmm_account",
                "dex_id": self.DEX_ID,
                "note": "CLMM account parsing requires full layout implementation"
            }
                
        except Exception as e:
            if self.logger and e is not None and pool_address:
                self.logger.error(f"Error parsing Raydium CLMM account update for {pool_address}: {e}", exc_info=True)
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