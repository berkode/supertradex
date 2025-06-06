"""
Message Dispatcher for WebSocket Messages
Handles routing and processing of different WebSocket message types
"""

import json
import time
import logging
from typing import Dict, Any, Optional, Callable, Awaitable
from datetime import datetime, timezone

from utils.logger import get_logger
from performance import get_system_monitor, SystemMonitoringMixin
from performance.decorators import monitor_message_processing
from performance.system_monitor import record_message_processing_time
from data.blockchain_models import (
    validate_websocket_message, validate_blockchain_event,
    WebSocketMessage, MessageSource, EventType
)

class MessageDispatcher(SystemMonitoringMixin):
    """
    Dispatches WebSocket messages to appropriate handlers based on message type
    Simplifies the main message processing loop in BlockchainListener
    """
    
    COMPONENT_NAME = "message_dispatcher"
    
    def __init__(self, blockchain_listener, logger: Optional[logging.Logger] = None):
        # Initialize performance monitoring mixin first
        super().__init__()
        
        self.blockchain_listener = blockchain_listener
        self.logger = logger or get_logger(__name__)
        
        # Message type handlers
        self.handlers = {
            'subscription_confirmation': self._handle_subscription_confirmation,
            'error_response': self._handle_error_response,
            'logs_notification': self._handle_logs_notification,
            'account_notification': self._handle_account_notification,
            'program_notification': self._handle_program_notification,
        }
        
        # Initialize event router for specialized event handling
        self._initialize_event_router()
        
        # Initialize performance monitoring
        self._update_health_status("healthy", {"initialized_at": time.time()})
        
        self.logger.info("MessageDispatcher initialized with event router and performance monitoring")
    
    def _initialize_event_router(self):
        """Initialize the event router with access to blockchain listener resources"""
        try:
            from data.blockchain_event_handlers import EventRouter
            
            # Get required components from blockchain listener
            parsers = getattr(self.blockchain_listener, 'parsers', {})
            price_aggregator = getattr(self.blockchain_listener, 'price_aggregator', None)
            settings = getattr(self.blockchain_listener, 'settings', None)
            
            if parsers and price_aggregator and settings:
                self.event_router = EventRouter(settings, parsers, price_aggregator, self.logger)
                self.logger.info("Event router initialized successfully")
            else:
                self.event_router = None
                self.logger.warning("Event router not initialized - missing required components")
                
        except Exception as e:
            self.logger.error(f"Error initializing event router: {e}")
            self.event_router = None
    
    @monitor_message_processing("")
    async def dispatch_message(self, message_str: str, program_id_str: str) -> bool:
        """
        Main dispatch method that routes messages to appropriate handlers
        
        Args:
            message_str: Raw WebSocket message as string
            program_id_str: Program ID context for the message
            
        Returns:
            bool: True if message was handled successfully, False otherwise
        """
        start_time = time.time()
        
        try:
            # Track message processing attempt
            self._increment_counter("messages_received", labels={"program": program_id_str})
            
            message_data = json.loads(message_str)
            
            # Validate the WebSocket message structure
            try:
                validated_message = validate_websocket_message(message_data)
                message = validated_message.dict()
            except Exception as validation_error:
                self.logger.warning(f"WebSocket message validation failed: {validation_error}")
                self._increment_counter("validation_failures", labels={"program": program_id_str})
                message = message_data  # Fall back to raw data
            
            message_type = self._determine_message_type(message)
            
            # Track message by type
            self._increment_counter("messages_by_type", labels={"message_type": message_type, "program": program_id_str})
            
            if message_type in self.handlers:
                handler = self.handlers[message_type]
                with self.performance_timer("message_handler_time", {"message_type": message_type, "program": program_id_str}):
                    result = await handler(message, program_id_str)
                
                if result:
                    self._increment_counter("messages_handled_successfully", labels={"message_type": message_type, "program": program_id_str})
                else:
                    self._increment_counter("messages_handled_unsuccessfully", labels={"message_type": message_type, "program": program_id_str})
                
                return result
            else:
                self.logger.warning(f"Unknown message type '{message_type}' for program {program_id_str}")
                self._increment_counter("unknown_message_types", labels={"message_type": message_type, "program": program_id_str})
                return False
                
        except json.JSONDecodeError:
            self.logger.error(f"Failed to decode JSON from WebSocket message for {program_id_str}: {message_str[:500]}")
            self._increment_counter("json_decode_failures", labels={"program": program_id_str})
            return False
        except Exception as e:
            self.logger.error(f"Error dispatching message for {program_id_str}: {e}. Message: {message_str[:500]}", exc_info=True)
            self._increment_counter("dispatch_errors", labels={"program": program_id_str, "error_type": type(e).__name__})
            return False
        finally:
            # Record processing time
            processing_time = time.time() - start_time
            record_message_processing_time(processing_time, "general")
            
            # Update health status periodically
            if hasattr(self, '_last_health_update'):
                if time.time() - self._last_health_update > 60:  # Update every minute
                    self._update_health_status("healthy", {"last_message_processed": time.time()})
                    self._last_health_update = time.time()
            else:
                self._last_health_update = time.time()
                self._update_health_status("healthy", {"last_message_processed": time.time()})
    
    def _determine_message_type(self, message: Dict[str, Any]) -> str:
        """
        Determine the type of WebSocket message based on its structure
        
        Args:
            message: Parsed JSON message
            
        Returns:
            str: Message type identifier
        """
        # Subscription confirmation response
        if 'id' in message and 'result' in message and isinstance(message['result'], int):
            return 'subscription_confirmation'
        
        # Error response
        if 'error' in message:
            return 'error_response'
        
        # Method-based notifications
        method = message.get('method')
        if method == 'logsNotification':
            return 'logs_notification'
        elif method == 'accountNotification':
            return 'account_notification'
        elif method == 'programNotification':
            return 'program_notification'
        
        return 'unknown'
    
    async def _handle_subscription_confirmation(self, message: Dict[str, Any], program_id_str: str) -> bool:
        """Handle subscription confirmation responses"""
        try:
            request_id = message['id']
            subscription_id = message['result']
            
            self.logger.info(f"SUBSCRIPTION CONFIRMATION [Req ID: {request_id}, Prog: {program_id_str}]: Sub ID {subscription_id}")
            
            # Check if this request ID is in pending confirmations
            if request_id in self.blockchain_listener._pending_confirmations:
                pending_item = self.blockchain_listener._pending_confirmations[request_id]
                
                if isinstance(pending_item, tuple) and len(pending_item) >= 2:
                    event_to_set = pending_item[0]
                    result_holder = pending_item[1]
                    
                    if hasattr(event_to_set, 'set') and isinstance(result_holder, dict):
                        result_holder['subscription_id'] = subscription_id
                        result_holder['success'] = True
                        if not event_to_set.is_set():
                            event_to_set.set()
                            self.logger.info(f"✅ Subscription confirmed for request ID {request_id} with sub ID {subscription_id}")
                        else:
                            self.logger.warning(f"Event for request ID {request_id} was already set")
                    else:
                        self.logger.error(f"Invalid pending item structure for request ID {request_id}")
                else:
                    self.logger.error(f"Unexpected pending item type for request ID {request_id}: {type(pending_item)}")
            else:
                self.logger.warning(f"Received confirmation for unknown request ID: {request_id}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error handling subscription confirmation: {e}", exc_info=True)
            return False
    
    async def _handle_error_response(self, message: Dict[str, Any], program_id_str: str) -> bool:
        """Handle error responses from WebSocket"""
        try:
            error_info = message.get('error', 'Unknown error')
            request_id = message.get('id')
            
            # Only log if there's actual error content
            if error_info and error_info != 'Unknown error':
                self.logger.error(f"WebSocket error for {program_id_str}: {error_info}")
            elif error_info is None:
                self.logger.debug(f"Received error response with None error info for {program_id_str} (request {request_id})")
            else:
                self.logger.warning(f"WebSocket unknown error for {program_id_str}: {error_info}")
            
            # If it's an error for a pending request, notify the waiting task
            if request_id and request_id in self.blockchain_listener._pending_confirmations:
                pending_item = self.blockchain_listener._pending_confirmations[request_id]
                if isinstance(pending_item, tuple) and len(pending_item) >= 2:
                    event_to_set = pending_item[0]
                    result_holder = pending_item[1]
                    
                    result_holder['subscription_id'] = None  # Signal error
                    result_holder['success'] = False
                    if hasattr(event_to_set, 'set'):
                        event_to_set.set()
                        self.logger.error(f"❌ Subscription failed for request ID {request_id}: {error_info}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error handling error response: {e}", exc_info=True)
            return False
    
    async def _handle_logs_notification(self, message: Dict[str, Any], program_id_str: str) -> bool:
        """Handle log notification messages"""
        try:
            params = message.get('params', {})
            result = params.get('result', {})
            value = result.get('value', {})
            logs = value.get('logs', [])
            signature = value.get('signature')
            slot = value.get('slot')
            sub_id = params.get('subscription')
            
            if sub_id in self.blockchain_listener._active_subscriptions:
                pool_address, dex_id, sub_type = self.blockchain_listener._active_subscriptions[sub_id]
                
                self.blockchain_listener.blockchain_logger.debug(
                    f"Log notification for {sub_type} sub {sub_id} ({pool_address}, {dex_id}): "
                    f"Slot {slot}, Sig {signature}, Logs: {len(logs)}"
                )
                
                # Create callback data
                callback_data = {
                    'type': 'log_update',
                    'subscription_id': sub_id,
                    'pool_address': pool_address,
                    'dex_id': dex_id,
                    'signature': signature,
                    'slot': slot,
                    'logs': logs,
                    'source': MessageSource.LOG_NOTIFICATION,
                    'timestamp': time.time()
                }
                
                # Extract price information from swap logs
                try:
                    swap_info = await self.blockchain_listener._extract_price_from_logs(logs, dex_id, signature)
                    if swap_info:
                        callback_data.update(swap_info)
                        price = swap_info.get('price')
                        if price:
                            self.blockchain_listener.blockchain_logger.info(
                                f"Extracted swap price from {dex_id} logs: {price} (signature: {signature[:8]}...)"
                            )
                            
                            # Record price for aggregation
                            self.blockchain_listener.price_aggregator.record_price_update(
                                mint=f"pool_{pool_address[:8]}", 
                                price=price, 
                                source='blockchain',
                                dex_id=dex_id
                            )
                except Exception as e:
                    self.logger.error(f"Error extracting price from logs for {dex_id}: {e}", exc_info=True)
                
                # Route through event router for specialized processing
                if self.event_router:
                    enriched_data = await self.event_router.route_event(callback_data)
                else:
                    enriched_data = callback_data
                
                # Forward to callback
                if self.blockchain_listener._callback:
                    await self.blockchain_listener._callback(enriched_data)
                
                return True
            else:
                self.logger.warning(f"Received logs for unknown subscription ID: {sub_id}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error handling logs notification: {e}", exc_info=True)
            return False
    
    async def _handle_account_notification(self, message: Dict[str, Any], program_id_str: str) -> bool:
        """Handle account notification messages"""
        try:
            params = message.get('params', {})
            sub_id = params.get('subscription')
            result = params.get('result', {})
            value = result.get('value', {})
            raw_data_list = value.get('data')
            slot = result.get('context', {}).get('slot')
            
            if sub_id in self.blockchain_listener._active_subscriptions:
                pool_address, dex_id, sub_type = self.blockchain_listener._active_subscriptions[sub_id]
                
                self.blockchain_listener.blockchain_logger.debug(
                    f"Account notification for {sub_type} sub {sub_id} ({pool_address}, {dex_id}): Slot {slot}"
                )
                
                callback_data = {
                    'type': 'account_update',
                    'subscription_id': sub_id,
                    'pool_address': pool_address,
                    'dex_id': dex_id,
                    'raw_data': raw_data_list,
                    'slot': slot,
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'source': MessageSource.ACCOUNT_NOTIFICATION
                }
                
                # Process account data based on DEX type
                await self._process_account_data(callback_data, raw_data_list, dex_id, pool_address)
                
                # Route through event router for specialized processing
                if self.event_router:
                    enriched_data = await self.event_router.route_event(callback_data)
                else:
                    enriched_data = callback_data
                
                # Forward to callback
                if self.blockchain_listener._callback:
                    await self.blockchain_listener._callback(enriched_data)
                
                return True
            else:
                self.logger.warning(f"Received account data for unknown subscription ID: {sub_id}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error handling account notification: {e}", exc_info=True)
            return False
    
    async def _handle_program_notification(self, message: Dict[str, Any], program_id_str: str) -> bool:
        """Handle program notification messages (similar to logs)"""
        # For now, treat program notifications similar to logs notifications
        return await self._handle_logs_notification(message, program_id_str)
    
    async def _process_account_data(self, callback_data: Dict[str, Any], raw_data_list: Any, dex_id: str, pool_address: str):
        """Process account data based on DEX type"""
        try:
            if not raw_data_list or not isinstance(raw_data_list, list) or len(raw_data_list) == 0:
                return
            
            if dex_id == 'pumpswap':
                await self._process_pumpswap_account_data(callback_data, raw_data_list[0], pool_address)
            elif dex_id == 'raydium_v4':
                await self._process_raydium_v4_account_data(callback_data, raw_data_list[0], pool_address)
            
        except Exception as e:
            self.logger.error(f"Error processing account data for {dex_id}: {e}", exc_info=True)
    
    async def _process_pumpswap_account_data(self, callback_data: Dict[str, Any], raw_data: str, pool_address: str):
        """Process PumpSwap account data to extract price"""
        try:
            if not self.blockchain_listener._pumpswap_amm_layout:
                self.logger.error("PumpSwap AMM layout not available for parsing")
                return
            
            import base64
            decoded_data = base64.b64decode(raw_data)
            parsed_state = self.blockchain_listener._pumpswap_amm_layout.parse(decoded_data)
            
            token_decimals = parsed_state.decimals
            sol_decimals = 9
            token_balance_raw = parsed_state.token_balance
            sol_balance_raw = parsed_state.sol_balance
            
            if token_balance_raw > 0 and sol_balance_raw > 0 and token_decimals is not None:
                price = (sol_balance_raw / (10**sol_decimals)) / (token_balance_raw / (10**token_decimals))
                callback_data['price'] = price
                callback_data['liquidity_sol'] = sol_balance_raw / (10**sol_decimals)
                callback_data['token_reserve_raw'] = token_balance_raw
                callback_data['sol_reserve_raw'] = sol_balance_raw
                callback_data['token_decimals_from_amm'] = token_decimals
                
                self.logger.info(f"Parsed PumpSwap ({pool_address}) live data. Price: {price}, SOL Liquidity: {callback_data['liquidity_sol']}")
            else:
                self.logger.warning(f"Insufficient data in PumpSwap state for {pool_address} to calculate price")
                
        except Exception as e:
            self.logger.error(f"Error parsing PumpSwap account data for {pool_address}: {e}", exc_info=True)
    
    async def _process_raydium_v4_account_data(self, callback_data: Dict[str, Any], raw_data: str, pool_address: str):
        """Process Raydium V4 account data to extract price"""
        try:
            import base64
            decoded_data = base64.b64decode(raw_data)
            
            if len(decoded_data) < 752:  # Raydium V4 pool state is 752 bytes
                self.logger.warning(f"Raydium V4 pool {pool_address} account data too short: {len(decoded_data)} bytes")
                return
            
            # Try to use the Raydium V4 pool layout if available
            if hasattr(self.blockchain_listener, '_raydium_v4_pool_layout') and self.blockchain_listener._raydium_v4_pool_layout:
                parsed_state = self.blockchain_listener._raydium_v4_pool_layout.parse(decoded_data)
                
                # Extract vault addresses and decimals
                base_vault = bytes(parsed_state.pool_base_vault)
                quote_vault = bytes(parsed_state.pool_quote_vault)
                base_decimal = parsed_state.base_decimal
                quote_decimal = parsed_state.quote_decimal
                
                # Calculate price using vault balances
                price = await self.blockchain_listener._calculate_raydium_v4_price(
                    base_vault, quote_vault, base_decimal, quote_decimal
                )
                
                if price and price > 0:
                    callback_data['price'] = price
                    callback_data['base_decimal'] = base_decimal
                    callback_data['quote_decimal'] = quote_decimal
                    callback_data['pool_base_vault'] = base_vault.hex()
                    callback_data['pool_quote_vault'] = quote_vault.hex()
                    
                    self.logger.info(f"Calculated Raydium V4 price for {pool_address}: {price}")
                else:
                    self.logger.warning(f"Could not calculate valid price for Raydium V4 pool {pool_address}")
            else:
                # Fallback parsing if layout not available
                await self._fallback_raydium_v4_parsing(callback_data, decoded_data, pool_address)
                
        except Exception as e:
            self.logger.error(f"Error processing Raydium V4 account data for {pool_address}: {e}", exc_info=True)
    
    async def _fallback_raydium_v4_parsing(self, callback_data: Dict[str, Any], decoded_data: bytes, pool_address: str):
        """Fallback parsing for Raydium V4 when layout is not available"""
        try:
            import struct
            
            # Extract decimals from known offsets
            base_decimal = struct.unpack('<Q', decoded_data[32:40])[0]
            quote_decimal = struct.unpack('<Q', decoded_data[40:48])[0]
            
            # Extract vault addresses from known offsets
            base_vault_offset = 296
            quote_vault_offset = 328
            
            if len(decoded_data) >= base_vault_offset + 32 and len(decoded_data) >= quote_vault_offset + 32:
                base_vault = decoded_data[base_vault_offset:base_vault_offset + 32]
                quote_vault = decoded_data[quote_vault_offset:quote_vault_offset + 32]
                
                # Calculate price using vault balances
                price = await self.blockchain_listener._calculate_raydium_v4_price(
                    base_vault, quote_vault, base_decimal, quote_decimal
                )
                
                if price and price > 0:
                    callback_data['price'] = price
                    callback_data['base_decimal'] = base_decimal
                    callback_data['quote_decimal'] = quote_decimal
                    callback_data['pool_base_vault'] = base_vault.hex()
                    callback_data['pool_quote_vault'] = quote_vault.hex()
                    
                    self.logger.info(f"Calculated Raydium V4 price for {pool_address}: {price} (fallback parsing)")
                else:
                    self.logger.warning(f"Could not calculate valid price for Raydium V4 pool {pool_address} (fallback)")
            else:
                self.logger.warning(f"Insufficient data to extract vault addresses for Raydium V4 pool {pool_address}")
                
        except Exception as e:
            self.logger.error(f"Error in fallback Raydium V4 parsing for {pool_address}: {e}", exc_info=True)
    
    def get_event_router_statistics(self) -> Dict[str, Any]:
        """Get statistics from the event router"""
        if self.event_router:
            return self.event_router.get_statistics()
        else:
            return {"error": "Event router not available"}