import logging
from datetime import datetime, timedelta
from typing import Optional, Callable, Dict, List, Any
from enum import Enum
import json
import os
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

class CircuitBreakerType(Enum):
    """Types of circuit breakers."""
    GLOBAL = "global"  # Affects all operations
    COMPONENT = "component"  # Affects a specific component
    OPERATION = "operation"  # Affects a specific operation
    TOKEN = "token"  # Affects a specific token

@dataclass
class CircuitBreakerMetrics:
    """Metrics for circuit breaker monitoring."""
    total_activations: int = 0
    total_resets: int = 0
    total_failures: int = 0
    current_failures: int = 0
    last_activation_time: Optional[str] = None
    last_reset_time: Optional[str] = None
    average_reset_time: float = 0.0
    failure_rate: float = 0.0

class CircuitBreakerConfig:
    """
    Centralized configuration for circuit breakers.
    This class provides default settings for all circuit breakers in the application.
    """
    # Default settings for all circuit breakers
    DEFAULT_MAX_FAILURES = 20
    DEFAULT_RESET_MINUTES = 2
    
    # Component-specific settings
    COMPONENT_SETTINGS = {
        "trade_queue": {"max_failures": 20, "reset_minutes": 2},
        "order_manager": {"max_failures": 20, "reset_minutes": 2},
        "transaction_tracker": {"max_failures": 20, "reset_minutes": 2},
        "entry_exit_strategy": {"max_failures": 20, "reset_minutes": 2},
        "trade_validator": {"max_failures": 20, "reset_minutes": 2},
        "balance_checker": {"max_failures": 20, "reset_minutes": 2},
    }
    
    # Operation-specific settings
    OPERATION_SETTINGS = {
        "default": {"max_failures": 10, "reset_minutes": 5},
    }
    
    # Token-specific settings
    TOKEN_SETTINGS = {
        "default": {"max_failures": 10, "reset_minutes": 5},
    }
    
    @classmethod
    def get_settings(cls, breaker_type: CircuitBreakerType, identifier: str) -> Dict[str, int]:
        """
        Get the settings for a specific circuit breaker.
        
        Args:
            breaker_type: Type of circuit breaker
            identifier: Identifier of the circuit breaker
            
        Returns:
            Dictionary with max_failures and reset_minutes
        """
        if breaker_type == CircuitBreakerType.COMPONENT:
            return cls.COMPONENT_SETTINGS.get(identifier, {"max_failures": cls.DEFAULT_MAX_FAILURES, "reset_minutes": cls.DEFAULT_RESET_MINUTES})
        elif breaker_type == CircuitBreakerType.OPERATION:
            return cls.OPERATION_SETTINGS.get(identifier, cls.OPERATION_SETTINGS["default"])
        elif breaker_type == CircuitBreakerType.TOKEN:
            return cls.TOKEN_SETTINGS.get(identifier, cls.TOKEN_SETTINGS["default"])
        else:
            return {"max_failures": cls.DEFAULT_MAX_FAILURES, "reset_minutes": cls.DEFAULT_RESET_MINUTES}

class CircuitBreaker:
    """
    Enhanced circuit breaker implementation with support for different types,
    metrics collection, and state persistence.
    """
    
    def __init__(self, 
                 breaker_type: CircuitBreakerType,
                 identifier: str,
                 max_consecutive_failures: Optional[int] = None,
                 reset_after_minutes: Optional[int] = None,
                 on_activate: Optional[Callable] = None,
                 on_reset: Optional[Callable] = None,
                 persistence_path: Optional[str] = None):
        """
        Initialize the circuit breaker.
        
        Args:
            breaker_type: Type of circuit breaker
            identifier: Unique identifier for the breaker (component/operation name)
            max_consecutive_failures: Number of consecutive failures before activation
            reset_after_minutes: Minutes to wait before auto-reset
            on_activate: Optional callback when circuit breaker activates
            on_reset: Optional callback when circuit breaker resets
            persistence_path: Optional path to persist state
        """
        self._type = breaker_type
        self._identifier = identifier
        
        # Get settings from centralized configuration
        settings = CircuitBreakerConfig.get_settings(breaker_type, identifier)
        self._max_consecutive_failures = max_consecutive_failures or settings["max_failures"]
        self._reset_after_minutes = reset_after_minutes or settings["reset_minutes"]
        
        self._on_activate = on_activate
        self._on_reset = on_reset
        self._persistence_path = persistence_path
        
        # State variables
        self._consecutive_failures = 0
        self._is_active = False
        self._activated_at: Optional[datetime] = None
        
        # Metrics
        self._metrics = CircuitBreakerMetrics()
        
        # Load persisted state if available
        if persistence_path and os.path.exists(persistence_path):
            self._load_state()
        
        logger.info(f"CircuitBreaker initialized: type={breaker_type.value}, "
                   f"id={identifier}, max_failures={max_consecutive_failures}, "
                   f"reset_after={reset_after_minutes} minutes")

    def check(self) -> bool:
        """
        Check if the circuit breaker is active and handle automatic reset if needed.
        
        Returns:
            bool: True if circuit breaker is active, False otherwise
        """
        if not self._is_active:
            return False
            
        if self._activated_at:
            now = datetime.now()
            elapsed_minutes = (now - self._activated_at).total_seconds() / 60
            
            if elapsed_minutes >= self._reset_after_minutes:
                logger.info(f"Auto-resetting circuit breaker after {elapsed_minutes:.1f} minutes")
                self.reset()
                return False
                
        return True

    def increment_failures(self) -> None:
        """Increment the failure counter and activate circuit breaker if needed."""
        self._consecutive_failures += 1
        self._metrics.total_failures += 1
        self._metrics.current_failures = self._consecutive_failures
        
        logger.warning(f"Failure count: {self._consecutive_failures}/{self._max_consecutive_failures}")
        
        if self._consecutive_failures >= self._max_consecutive_failures:
            if not self._is_active:
                self.activate()

    def reset_failures(self) -> None:
        """Reset the failure counter."""
        if self._consecutive_failures > 0:
            logger.info(f"Resetting failure count from {self._consecutive_failures} to 0")
            self._consecutive_failures = 0
            self._metrics.current_failures = 0

    def activate(self) -> None:
        """Activate the circuit breaker."""
        self._is_active = True
        self._activated_at = datetime.now()
        self._metrics.total_activations += 1
        self._metrics.last_activation_time = self._activated_at.isoformat()
        
        logger.error(f"CIRCUIT BREAKER ACTIVATED after {self._consecutive_failures} consecutive failures!")
        logger.error(f"Operations suspended for {self._reset_after_minutes} minutes")
        
        if self._on_activate:
            try:
                self._on_activate()
            except Exception as e:
                logger.error(f"Error in circuit breaker activation callback: {e}")
        
        self._persist_state()

    def reset(self) -> None:
        """Reset the circuit breaker state."""
        if self._is_active:
            self._metrics.total_resets += 1
            self._metrics.last_reset_time = datetime.now().isoformat()
            
            if self._activated_at:
                reset_time = (datetime.now() - self._activated_at).total_seconds() / 60
                self._metrics.average_reset_time = (
                    (self._metrics.average_reset_time * (self._metrics.total_resets - 1) + reset_time)
                    / self._metrics.total_resets
                )
        
        self._is_active = False
        self._activated_at = None
        self._consecutive_failures = 0
        self._metrics.current_failures = 0
        
        logger.info("Circuit breaker reset")
        
        if self._on_reset:
            try:
                self._on_reset()
            except Exception as e:
                logger.error(f"Error in circuit breaker reset callback: {e}")
        
        self._persist_state()

    def _persist_state(self) -> None:
        """Persist the current state to disk."""
        if not self._persistence_path:
            return
            
        state = {
            "type": self._type.value,
            "identifier": self._identifier,
            "is_active": self._is_active,
            "consecutive_failures": self._consecutive_failures,
            "activated_at": self._activated_at.isoformat() if self._activated_at else None,
            "metrics": asdict(self._metrics)
        }
        
        try:
            with open(self._persistence_path, 'w') as f:
                json.dump(state, f)
        except Exception as e:
            logger.error(f"Error persisting circuit breaker state: {e}")

    def _load_state(self) -> None:
        """Load persisted state from disk."""
        if not self._persistence_path or not os.path.exists(self._persistence_path):
            return
            
        try:
            with open(self._persistence_path, 'r') as f:
                state = json.load(f)
                
            self._is_active = state["is_active"]
            self._consecutive_failures = state["consecutive_failures"]
            self._activated_at = datetime.fromisoformat(state["activated_at"]) if state["activated_at"] else None
            self._metrics = CircuitBreakerMetrics(**state["metrics"])
            
            logger.info(f"Loaded persisted state for circuit breaker {self._identifier}")
        except Exception as e:
            logger.error(f"Error loading circuit breaker state: {e}")

    @property
    def is_active(self) -> bool:
        """Check if the circuit breaker is currently active."""
        return self._is_active

    @property
    def consecutive_failures(self) -> int:
        """Get the current number of consecutive failures."""
        return self._consecutive_failures

    @property
    def time_since_activation(self) -> Optional[float]:
        """Get the time in minutes since the circuit breaker was activated."""
        if self._activated_at:
            return (datetime.now() - self._activated_at).total_seconds() / 60
        return None

    @property
    def metrics(self) -> CircuitBreakerMetrics:
        """Get the current metrics."""
        return self._metrics

    @property
    def breaker_type(self) -> CircuitBreakerType:
        """Get the type of circuit breaker."""
        return self._type

    @property
    def identifier(self) -> str:
        """Get the identifier of the circuit breaker."""
        return self._identifier 