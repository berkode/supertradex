"""
Blockchain Event Handlers
Specialized handlers for different types of blockchain events
"""

import time
import logging
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone
from abc import ABC, abstractmethod

from utils.logger import get_logger
from performance import SystemMonitoringMixin
from performance.decorators import monitor_event_handling
from data.blockchain_models import (
    SwapEvent, AccountUpdateEvent, PoolCreationEvent, UnhandledEvent,
    SwapInfo, VolumeInfo, CreationMetadata, UpdateMetadata,
    EventType, MessageSource, LiquidityQuality, DEXType,
    validate_blockchain_event
)

class BaseEventHandler(ABC, SystemMonitoringMixin):
    """Base class for blockchain event handlers"""
    
    COMPONENT_NAME = "event_handler"
    
    def __init__(self, settings, logger: Optional[logging.Logger] = None):
        super().__init__()
        self.settings = settings
        self.logger = logger or get_logger(__name__)
        self._update_health_status("healthy", {"initialized_at": time.time()})
    
    @abstractmethod
    async def can_handle(self, event_data: Dict[str, Any]) -> bool:
        """Check if this handler can process the given event"""
        pass
    
    @abstractmethod
    async def handle_event(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process the event and return enriched data"""
        pass

class SwapEventHandler(BaseEventHandler):
    """Handles swap/trade events from various DEXes"""
    
    COMPONENT_NAME = "swap_event_handler"
    
    def __init__(self, settings, parsers: Dict, price_aggregator, logger: Optional[logging.Logger] = None):
        super().__init__(settings, logger)
        self.parsers = parsers
        self.price_aggregator = price_aggregator
        self.supported_sources = ['log_notification', 'log_update']
        
        self._increment_counter("handlers_initialized", labels={"handler_type": "swap"})
        self.logger.info("SwapEventHandler initialized")
    
    async def can_handle(self, event_data: Dict[str, Any]) -> bool:
        """Check if this is a swap-related event"""
        try:
            self._increment_counter("can_handle_checks", labels={"handler_type": "swap"})
            
            # Check if it's from a supported source
            source = event_data.get('source', '')
            if source not in self.supported_sources:
                self._increment_counter("can_handle_rejected", labels={"reason": "unsupported_source", "source": source})
                return False
            
            # Check if we have logs to parse
            logs = event_data.get('logs', [])
            if not logs:
                self._increment_counter("can_handle_rejected", labels={"reason": "no_logs"})
                return False
            
            # Check if we have a DEX parser for this event
            dex_id = event_data.get('dex_id', '')
            if dex_id not in self.parsers:
                self._increment_counter("can_handle_rejected", labels={"reason": "no_parser", "dex_id": dex_id})
                return False
            
            self._increment_counter("can_handle_accepted", labels={"dex_id": dex_id})
            return True
            
        except Exception as e:
            self._increment_counter("can_handle_errors", labels={"error_type": type(e).__name__})
            self.logger.error(f"Error checking if swap event can be handled: {e}")
            return False
    
    @monitor_event_handling("swap")
    async def handle_event(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process swap event and extract trade information"""
        try:
            self._increment_counter("events_handled", labels={"handler_type": "swap"})
            logs = event_data.get('logs', [])
            dex_id = event_data.get('dex_id', '')
            signature = event_data.get('signature', 'unknown')
            pool_address = event_data.get('pool_address', '')
            
            self.logger.debug(f"Processing swap event for {dex_id} pool {pool_address}")
            
            # Use the appropriate parser to extract swap information
            parser = self.parsers.get(dex_id)
            if not parser:
                self.logger.warning(f"No parser available for DEX: {dex_id}")
                return event_data
            
            swap_info_raw = parser.parse_swap_logs(logs, signature)
            
            if swap_info_raw and swap_info_raw.get('found_swap'):
                try:
                    # Create validated SwapInfo model
                    swap_info = SwapInfo(**swap_info_raw)
                    
                    # Prepare data for SwapEvent
                    enriched_data = {
                        **event_data,
                        'event_type': EventType.SWAP,
                        'swap_info': swap_info.dict(),
                        'processing_timestamp': time.time(),
                        'handler': 'SwapEventHandler'
                    }
                    
                    # Extract key metrics
                    price = swap_info.price or swap_info.price_ratio
                    amount_in = swap_info.amount_in
                    amount_out = swap_info.amount_out
                    
                    if price:
                        enriched_data['price'] = price
                        
                        # Record price update for aggregation
                        try:
                            mint_key = f"pool_{pool_address[:8]}" if pool_address else f"swap_{signature[:8]}"
                            self.price_aggregator.record_price_update(
                                mint=mint_key,
                                price=price,
                                source='blockchain_swap',
                                dex_id=dex_id
                            )
                        except Exception as e:
                            self.logger.error(f"Error recording price update: {e}")
                    
                    # Add volume information if available
                    if amount_in and amount_out:
                        estimated_usd = self._estimate_volume_usd(amount_in, amount_out, price)
                        volume_info = VolumeInfo(
                            amount_in=amount_in,
                            amount_out=amount_out,
                            estimated_volume_usd=estimated_usd
                        )
                        enriched_data['volume_info'] = volume_info.dict()
                    
                    # Return the enriched data dict for now
                    # Note: Full validation can be added later if needed
                    self._increment_counter("swaps_processed_successfully", labels={"dex_id": dex_id})
                    self._record_metric("swap_parsing_confidence", swap_info.parsing_confidence, {"dex_id": dex_id})
                    if price:
                        self._record_metric("swap_price_extracted", price, {"dex_id": dex_id})
                    
                    self.logger.info(f"Processed {dex_id} swap: price={price}, volume_in={amount_in}, confidence={swap_info.parsing_confidence:.2f}")
                    return enriched_data
                    
                except Exception as validation_error:
                    self._increment_counter("swap_validation_errors", labels={"dex_id": dex_id, "error_type": type(validation_error).__name__})
                    self.logger.error(f"Error validating swap event: {validation_error}")
                    return event_data
            else:
                # No swap found in logs - create unhandled event
                self._increment_counter("no_swap_found", labels={"dex_id": dex_id})
                self.logger.debug(f"No swap events found in {dex_id} logs for signature {signature[:8]}...")
                return {
                    **event_data,
                    'event_type': EventType.UNHANDLED,
                    'handler': 'SwapEventHandler',
                    'reason': 'No swap found in logs'
                }
                
        except Exception as e:
            self._increment_counter("swap_handling_errors", labels={"error_type": type(e).__name__})
            self.logger.error(f"Error handling swap event: {e}", exc_info=True)
            return event_data
    
    def _estimate_volume_usd(self, amount_in: float, amount_out: float, price: float) -> Optional[float]:
        """Estimate USD volume from swap amounts"""
        try:
            if not all([amount_in, amount_out, price]):
                return None
            
            # Simple estimation - this could be enhanced with proper token price lookup
            # For now, assume the larger amount is the quote token (likely SOL or USDC)
            larger_amount = max(amount_in, amount_out)
            
            # If price suggests SOL-based pair, estimate using SOL price (~$140 as rough estimate)
            if price < 1.0:  # Likely token/SOL pair
                estimated_usd = larger_amount * 140  # Rough SOL price
            else:  # Likely higher-priced token
                estimated_usd = larger_amount * price
            
            return estimated_usd
            
        except Exception as e:
            self.logger.error(f"Error estimating USD volume: {e}")
            return None

class AccountUpdateHandler(BaseEventHandler):
    """Handles account state change events (price/liquidity updates)"""
    
    COMPONENT_NAME = "account_update_handler"
    
    def __init__(self, settings, logger: Optional[logging.Logger] = None):
        super().__init__(settings, logger)
        self.supported_sources = ['account_notification', 'account_update']
        
        self._increment_counter("handlers_initialized", labels={"handler_type": "account_update"})
        self.logger.info("AccountUpdateHandler initialized")
    
    async def can_handle(self, event_data: Dict[str, Any]) -> bool:
        """Check if this is an account update event"""
        try:
            source = event_data.get('source', '')
            event_type = event_data.get('type', '')
            
            return (source in self.supported_sources or 
                   event_type in self.supported_sources)
            
        except Exception as e:
            self.logger.error(f"Error checking if account update can be handled: {e}")
            return False
    
    @monitor_event_handling("account_update")
    async def handle_event(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process account update event"""
        try:
            self._increment_counter("events_handled", labels={"handler_type": "account_update"})
            pool_address = event_data.get('pool_address', '')
            dex_id = event_data.get('dex_id', '')
            slot = event_data.get('slot')
            
            self.logger.debug(f"Processing account update for {dex_id} pool {pool_address} at slot {slot}")
            
            enriched_data = {
                **event_data,
                'event_type': EventType.ACCOUNT_UPDATE,
                'processing_timestamp': time.time(),
                'handler': 'AccountUpdateHandler'
            }
            
            # Extract price information if available
            price = event_data.get('price')
            if price:
                enriched_data['price_source'] = 'account_state'
                self._increment_counter("account_updates_with_price", labels={"dex_id": dex_id})
                self._record_metric("account_update_price", price, {"dex_id": dex_id})
                
                # Add price quality indicators
                liquidity_sol = event_data.get('liquidity_sol')
                if liquidity_sol:
                    liquidity_quality = self._assess_liquidity_quality(liquidity_sol)
                    enriched_data['liquidity_quality'] = liquidity_quality
                    self._record_metric("account_update_liquidity", liquidity_sol, {"dex_id": dex_id, "quality": liquidity_quality.value})
                
                self.logger.info(f"Account update for {dex_id} pool {pool_address}: price={price}, liquidity={liquidity_sol}")
            else:
                self._increment_counter("account_updates_without_price", labels={"dex_id": dex_id})
            
            # Create validated metadata
            try:
                update_metadata = UpdateMetadata(
                    slot=slot,
                    dex_id=DEXType(dex_id) if dex_id else DEXType.RAYDIUM_V4,
                    has_price=price is not None,
                    data_size=len(str(event_data.get('raw_data', [])))
                )
                enriched_data['update_metadata'] = update_metadata.dict()
            except Exception as meta_error:
                self.logger.warning(f"Error creating update metadata: {meta_error}")
            
            # Return enriched data directly
            return enriched_data
            
        except Exception as e:
            self.logger.error(f"Error handling account update event: {e}", exc_info=True)
            return event_data
    
    def _assess_liquidity_quality(self, liquidity_sol: float) -> LiquidityQuality:
        """Assess the quality of liquidity for price reliability"""
        try:
            if liquidity_sol >= 100:
                return LiquidityQuality.HIGH
            elif liquidity_sol >= 10:
                return LiquidityQuality.MEDIUM
            elif liquidity_sol >= 1:
                return LiquidityQuality.LOW
            else:
                return LiquidityQuality.VERY_LOW
        except:
            return LiquidityQuality.UNKNOWN

class PoolCreationHandler(BaseEventHandler):
    """Handles new pool creation events"""
    
    COMPONENT_NAME = "pool_creation_handler"
    
    def __init__(self, settings, logger: Optional[logging.Logger] = None):
        super().__init__(settings, logger)
        self.creation_indicators = [
            'pool_creation',
            'initialize',
            'create_pool',
            'new_pool'
        ]
        
        self._increment_counter("handlers_initialized", labels={"handler_type": "pool_creation"})
        self.logger.info("PoolCreationHandler initialized")
    
    async def can_handle(self, event_data: Dict[str, Any]) -> bool:
        """Check if this is a pool creation event"""
        try:
            # Check logs for creation indicators
            logs = event_data.get('logs', [])
            for log in logs:
                log_lower = log.lower()
                if any(indicator in log_lower for indicator in self.creation_indicators):
                    return True
            
            # Check if it's marked as a creation event
            event_type = event_data.get('event_type', '').lower()
            if 'creation' in event_type or 'initialize' in event_type:
                return True
                
            return False
            
        except Exception as e:
            self.logger.error(f"Error checking if pool creation can be handled: {e}")
            return False
    
    @monitor_event_handling("pool_creation")
    async def handle_event(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process pool creation event"""
        try:
            self._increment_counter("events_handled", labels={"handler_type": "pool_creation"})
            
            pool_address = event_data.get('pool_address', '')
            dex_id = event_data.get('dex_id', '')
            signature = event_data.get('signature', '')
            
            self._increment_counter("pools_created", labels={"dex_id": dex_id})
            self.logger.info(f"Processing pool creation for {dex_id}: {pool_address}")
            
            # Create validated creation metadata with safe defaults
            try:
                creation_metadata = CreationMetadata(
                    pool_address=pool_address if len(pool_address) >= 32 else 'So11111111111111111111111111111111111111112',  # Valid default
                    dex_id=DEXType(dex_id) if dex_id else DEXType.RAYDIUM_V4,
                    creation_signature=signature if len(signature) >= 64 else '1' * 88,  # Valid default signature
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    has_initial_price=event_data.get('price') is not None
                )
            except Exception as meta_error:
                self.logger.warning(f"Error creating creation metadata: {meta_error}")
                # Use a simple dict fallback
                creation_metadata = {
                    'pool_address': pool_address,
                    'dex_id': dex_id,
                    'creation_signature': signature,
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'has_initial_price': event_data.get('price') is not None
                }
            
            enriched_data = {
                **event_data,
                'event_type': EventType.POOL_CREATION,
                'processing_timestamp': time.time(),
                'handler': 'PoolCreationHandler',
                'creation_metadata': creation_metadata.dict() if hasattr(creation_metadata, 'dict') else creation_metadata
            }
            
            # Extract initial pool parameters if available
            initial_price = event_data.get('price')
            if initial_price:
                enriched_data['initial_price'] = initial_price
                self._increment_counter("pools_with_initial_price", labels={"dex_id": dex_id})
                self._record_metric("pool_initial_price", initial_price, {"dex_id": dex_id})
            else:
                self._increment_counter("pools_without_initial_price", labels={"dex_id": dex_id})
            
            # Mark for potential monitoring
            enriched_data['monitoring_candidate'] = True
            
            self.logger.info(f"New {dex_id} pool detected: {pool_address} with initial price: {initial_price}")
            
            # Return enriched data directly
            return enriched_data
            
        except Exception as e:
            self.logger.error(f"Error handling pool creation event: {e}", exc_info=True)
            return event_data

class EventRouter(SystemMonitoringMixin):
    """Routes blockchain events to appropriate specialized handlers"""
    
    COMPONENT_NAME = "event_router"
    
    def __init__(self, settings, parsers: Dict, price_aggregator, logger: Optional[logging.Logger] = None):
        super().__init__()
        self.settings = settings
        self.logger = logger or get_logger(__name__)
        
        # Initialize specialized handlers
        self.handlers = [
            PoolCreationHandler(settings, logger),
            SwapEventHandler(settings, parsers, price_aggregator, logger),
            AccountUpdateHandler(settings, logger),
        ]
        
        # Statistics
        self.event_stats = {
            'total_processed': 0,
            'by_handler': {},
            'by_event_type': {},
            'unhandled': 0
        }
        
        self._increment_counter("routers_initialized")
        self._set_gauge("active_handlers", len(self.handlers))
        self._update_health_status("healthy", {"handler_count": len(self.handlers), "initialized_at": time.time()})
        
        self.logger.info(f"EventRouter initialized with {len(self.handlers)} handlers")
    
    async def route_event(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """Route event to appropriate handler and return enriched data"""
        try:
            self.event_stats['total_processed'] += 1
            self._increment_counter("events_routed")
            
            with self.performance_timer("event_routing_time", {"source": event_data.get('source', 'unknown')}):
                
                # Try each handler in order of priority
                for handler in self.handlers:
                    try:
                        if await handler.can_handle(event_data):
                            # Handler can process this event
                            result = await handler.handle_event(event_data)
                            
                            # Update statistics
                            handler_name = handler.__class__.__name__
                            self.event_stats['by_handler'][handler_name] = self.event_stats['by_handler'].get(handler_name, 0) + 1
                            
                            event_type = result.get('event_type', 'unknown')
                            self.event_stats['by_event_type'][event_type] = self.event_stats['by_event_type'].get(event_type, 0) + 1
                            
                            # Record successful routing
                            self._increment_counter("events_routed_successfully", labels={"handler": handler_name, "event_type": event_type})
                            
                            self.logger.debug(f"Event routed to {handler_name}, type: {event_type}")
                            return result
                            
                    except Exception as e:
                        self._increment_counter("handler_errors", labels={"handler": handler.__class__.__name__, "error_type": type(e).__name__})
                        self.logger.error(f"Error in handler {handler.__class__.__name__}: {e}", exc_info=True)
                        continue
                
                # No handler could process this event
                self.event_stats['unhandled'] += 1
                self._increment_counter("events_unhandled", labels={"source": event_data.get('source', 'unknown')})
                self.logger.debug(f"No handler found for event from {event_data.get('source', 'unknown')}")
                
                return {
                    **event_data,
                    'event_type': 'unhandled',
                    'handler': 'none',
                    'processing_timestamp': time.time()
                }
            
        except Exception as e:
            self.logger.error(f"Error routing event: {e}", exc_info=True)
            return event_data
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get routing statistics"""
        return {
            **self.event_stats,
            'handler_count': len(self.handlers),
            'handlers': [h.__class__.__name__ for h in self.handlers]
        }
    
    def reset_statistics(self):
        """Reset routing statistics"""
        self.event_stats = {
            'total_processed': 0,
            'by_handler': {},
            'by_event_type': {},
            'unhandled': 0
        } 