"""
Blockchain Data Models
Pydantic models for validating blockchain event data and ensuring type safety
"""

from pydantic import BaseModel, Field, validator, model_validator
from typing import Dict, List, Optional, Any, Union, Literal
from datetime import datetime
from enum import Enum
import time

class DEXType(str, Enum):
    """Supported DEX types"""
    RAYDIUM_V4 = "raydium_v4"
    PUMPSWAP = "pumpswap"
    RAYDIUM_CLMM = "raydium_clmm"
    ORCA = "orca"

class EventType(str, Enum):
    """Types of blockchain events"""
    SWAP = "swap"
    ACCOUNT_UPDATE = "account_update"
    POOL_CREATION = "pool_creation"
    LOG_NOTIFICATION = "log_notification"
    UNHANDLED = "unhandled"
    NON_SWAP_LOG = "non_swap_log"

class MessageSource(str, Enum):
    """Sources of WebSocket messages"""
    LOG_NOTIFICATION = "log_notification"
    ACCOUNT_NOTIFICATION = "account_notification"
    PROGRAM_NOTIFICATION = "program_notification"
    LOG_UPDATE = "log_update"
    ACCOUNT_UPDATE = "account_update"

class LiquidityQuality(str, Enum):
    """Liquidity quality assessment levels"""
    VERY_LOW = "very_low"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"

class SwapInfo(BaseModel):
    """Validated swap information extracted from logs"""
    found_swap: bool
    price: Optional[float] = None
    price_ratio: Optional[float] = None
    amount_in: Optional[float] = None
    amount_out: Optional[float] = None
    token_in: Optional[str] = None
    token_out: Optional[str] = None
    parsing_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    swap_direction: Optional[str] = None
    fee_amount: Optional[float] = None
    
    @validator('price', 'price_ratio', 'amount_in', 'amount_out', 'fee_amount')
    def validate_positive_numbers(cls, v):
        if v is not None and v <= 0:
            raise ValueError('Value must be positive')
        return v

class VolumeInfo(BaseModel):
    """Volume information for swaps"""
    amount_in: float = Field(gt=0)
    amount_out: float = Field(gt=0)
    estimated_volume_usd: Optional[float] = Field(default=None, gt=0)

class PoolMetadata(BaseModel):
    """Pool metadata information"""
    pool_address: str = Field(min_length=32, max_length=44)  # Solana address length
    dex_id: DEXType
    token_mint: Optional[str] = Field(default=None, min_length=32, max_length=44)
    quote_mint: Optional[str] = Field(default=None, min_length=32, max_length=44)
    base_decimal: Optional[int] = Field(default=None, ge=0, le=18)
    quote_decimal: Optional[int] = Field(default=None, ge=0, le=18)
    
    @validator('pool_address', 'token_mint', 'quote_mint')
    def validate_solana_address(cls, v):
        if v is not None and not (32 <= len(v) <= 44):
            raise ValueError('Invalid Solana address length')
        return v

class CreationMetadata(BaseModel):
    """Pool creation metadata"""
    pool_address: str = Field(min_length=32, max_length=44)
    dex_id: DEXType
    creation_signature: str = Field(min_length=64, max_length=128)
    timestamp: str  # ISO format datetime
    has_initial_price: bool = False
    initial_liquidity: Optional[float] = Field(default=None, gt=0)

class UpdateMetadata(BaseModel):
    """Account update metadata"""
    slot: Optional[int] = Field(default=None, gt=0)
    dex_id: DEXType
    has_price: bool = False
    data_size: int = Field(ge=0)
    processing_delay_ms: Optional[float] = Field(default=None, ge=0)

class BaseBlockchainEvent(BaseModel):
    """Base model for all blockchain events"""
    event_type: EventType
    source: MessageSource
    timestamp: float = Field(gt=0)
    processing_timestamp: Optional[float] = Field(default=None, gt=0)
    handler: str = Field(min_length=1)
    subscription_id: Optional[int] = None
    pool_address: Optional[str] = Field(default=None, min_length=32, max_length=44)
    dex_id: Optional[DEXType] = None
    signature: Optional[str] = Field(default=None, min_length=64, max_length=128)
    slot: Optional[int] = Field(default=None, gt=0)
    
    class Config:
        use_enum_values = True
        validate_assignment = True

class SwapEvent(BaseBlockchainEvent):
    """Validated swap event data"""
    event_type: Literal[EventType.SWAP] = EventType.SWAP
    swap_info: SwapInfo
    price: Optional[float] = Field(default=None, gt=0)
    volume_info: Optional[VolumeInfo] = None
    logs: List[str] = Field(default_factory=list)
    
    @model_validator(mode='after')
    def validate_swap_consistency(self):
        swap_info = self.swap_info
        price = self.price
        
        if swap_info and swap_info.found_swap:
            # If swap was found, we should have some price information
            if not price and not swap_info.price and not swap_info.price_ratio:
                raise ValueError('Swap event must have price information')
        
        return self

class AccountUpdateEvent(BaseBlockchainEvent):
    """Validated account update event data"""
    event_type: Literal[EventType.ACCOUNT_UPDATE] = EventType.ACCOUNT_UPDATE
    price: Optional[float] = Field(default=None, gt=0)
    price_source: Optional[str] = None
    liquidity_sol: Optional[float] = Field(default=None, gt=0)
    liquidity_quality: Optional[LiquidityQuality] = None
    raw_data: List[Any] = Field(default_factory=list)
    update_metadata: Optional[UpdateMetadata] = None
    
    # Pool-specific fields
    token_reserve_raw: Optional[int] = Field(default=None, ge=0)
    sol_reserve_raw: Optional[int] = Field(default=None, ge=0)
    token_decimals_from_amm: Optional[int] = Field(default=None, ge=0, le=18)
    pool_base_vault: Optional[str] = None
    pool_quote_vault: Optional[str] = None
    base_decimal: Optional[int] = Field(default=None, ge=0, le=18)
    quote_decimal: Optional[int] = Field(default=None, ge=0, le=18)

class PoolCreationEvent(BaseBlockchainEvent):
    """Validated pool creation event data"""
    event_type: Literal[EventType.POOL_CREATION] = EventType.POOL_CREATION
    creation_metadata: CreationMetadata
    initial_price: Optional[float] = Field(default=None, gt=0)
    monitoring_candidate: bool = True
    logs: List[str] = Field(default_factory=list)

class LogNotificationEvent(BaseBlockchainEvent):
    """Validated log notification event data"""
    event_type: Literal[EventType.LOG_NOTIFICATION] = EventType.LOG_NOTIFICATION
    logs: List[str] = Field(min_items=1)
    parsed_data: Optional[Dict[str, Any]] = None

class UnhandledEvent(BaseBlockchainEvent):
    """Event that couldn't be processed by any handler"""
    event_type: Literal[EventType.UNHANDLED] = EventType.UNHANDLED
    reason: Optional[str] = None
    raw_message: Optional[Dict[str, Any]] = None

# Union type for all possible event types
BlockchainEvent = Union[
    SwapEvent,
    AccountUpdateEvent, 
    PoolCreationEvent,
    LogNotificationEvent,
    UnhandledEvent
]

class WebSocketMessage(BaseModel):
    """Base WebSocket message structure"""
    id: Optional[int] = None
    method: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None
    
    @model_validator(mode='after')
    def validate_message_type(self):
        # A valid message should have either result/error (response) or method/params (notification)
        has_response = self.result is not None or self.error is not None
        has_notification = self.method is not None and self.params is not None
        
        if not has_response and not has_notification:
            raise ValueError('Message must be either a response or notification')
        
        return self

class SubscriptionConfirmation(BaseModel):
    """Subscription confirmation response"""
    id: int = Field(gt=0)
    result: int = Field(gt=0)  # Subscription ID
    
class ErrorResponse(BaseModel):
    """Error response from WebSocket"""
    id: Optional[int] = None
    error: Dict[str, Any]

class LogsNotification(BaseModel):
    """Logs notification structure"""
    method: Literal["logsNotification"] = "logsNotification"
    params: Dict[str, Any]
    
    @validator('params')
    def validate_logs_params(cls, v):
        required_fields = ['subscription', 'result']
        for field in required_fields:
            if field not in v:
                raise ValueError(f'Missing required field: {field}')
        return v

class AccountNotification(BaseModel):
    """Account notification structure"""
    method: Literal["accountNotification"] = "accountNotification"
    params: Dict[str, Any]
    
    @validator('params')
    def validate_account_params(cls, v):
        required_fields = ['subscription', 'result']
        for field in required_fields:
            if field not in v:
                raise ValueError(f'Missing required field: {field}')
        return v

class PriceUpdate(BaseModel):
    """Price update record for aggregation"""
    mint: str = Field(min_length=1)
    price: float = Field(gt=0)
    source: str = Field(min_length=1)
    dex_id: Optional[DEXType] = None
    timestamp: float = Field(gt=0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    volume: Optional[float] = Field(default=None, gt=0)

class EventStatistics(BaseModel):
    """Statistics for event processing"""
    total_processed: int = Field(ge=0)
    by_handler: Dict[str, int] = Field(default_factory=dict)
    by_event_type: Dict[str, int] = Field(default_factory=dict)
    unhandled: int = Field(ge=0)
    handler_count: int = Field(ge=0)
    handlers: List[str] = Field(default_factory=list)
    
    @validator('by_handler', 'by_event_type')
    def validate_non_negative_counts(cls, v):
        for key, count in v.items():
            if count < 0:
                raise ValueError(f'Count for {key} cannot be negative')
        return v

class ConnectionMetrics(BaseModel):
    """WebSocket connection metrics"""
    total_connections: int = Field(ge=0)
    successful_connections: int = Field(ge=0)
    failed_connections: int = Field(ge=0)
    reconnections: int = Field(ge=0)
    current_endpoint: Optional[str] = None
    connection_uptime_seconds: float = Field(ge=0)
    messages_sent: int = Field(ge=0)
    messages_received: int = Field(ge=0)
    bytes_sent: int = Field(ge=0)
    bytes_received: int = Field(ge=0)
    
    @model_validator(mode='after')
    def validate_connection_consistency(self):
        total = self.total_connections
        successful = self.successful_connections
        failed = self.failed_connections
        
        if successful + failed > total:
            raise ValueError('Sum of successful and failed connections cannot exceed total')
        
        return self

def validate_blockchain_event(event_data: Dict[str, Any]) -> BlockchainEvent:
    """
    Validate and convert raw event data to appropriate typed model
    
    Args:
        event_data: Raw event data dictionary
        
    Returns:
        Validated BlockchainEvent instance
        
    Raises:
        ValidationError: If data doesn't match any known event type
    """
    event_type = event_data.get('event_type')
    
    try:
        if event_type == EventType.SWAP:
            return SwapEvent(**event_data)
        elif event_type == EventType.ACCOUNT_UPDATE:
            return AccountUpdateEvent(**event_data)
        elif event_type == EventType.POOL_CREATION:
            return PoolCreationEvent(**event_data)
        elif event_type == EventType.LOG_NOTIFICATION:
            return LogNotificationEvent(**event_data)
        elif event_type == EventType.UNHANDLED:
            return UnhandledEvent(**event_data)
        else:
            # Default to unhandled if type is unknown
            return UnhandledEvent(
                event_type=EventType.UNHANDLED,
                source=event_data.get('source', MessageSource.LOG_NOTIFICATION),
                timestamp=event_data.get('timestamp', 0),
                handler='validation',
                reason=f'Unknown event type: {event_type}',
                raw_message=event_data
            )
    except Exception as e:
        # If validation fails, create an unhandled event with safe defaults
        timestamp = event_data.get('timestamp', time.time())
        # Ensure timestamp is positive
        if timestamp <= 0:
            timestamp = time.time()
            
        return UnhandledEvent(
            event_type=EventType.UNHANDLED,
            source=event_data.get('source', MessageSource.LOG_NOTIFICATION),
            timestamp=timestamp,
            handler='validation',
            reason=f'Validation error: {str(e)}',
            raw_message=event_data
        )

def validate_websocket_message(message_data: Dict[str, Any]) -> WebSocketMessage:
    """
    Validate raw WebSocket message data
    
    Args:
        message_data: Raw message dictionary
        
    Returns:
        Validated WebSocketMessage instance
    """
    return WebSocketMessage(**message_data) 