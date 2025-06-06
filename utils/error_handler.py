import logging
import traceback
import json
import asyncio
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable, Union, Type, Set
from enum import Enum
import httpx
from dataclasses import dataclass, asdict
from collections import defaultdict

from utils.logger import get_logger
from utils.circuit_breaker import CircuitBreaker, CircuitBreakerType

logger = get_logger(__name__)

class ErrorSeverity(Enum):
    """Enum for error severity levels."""
    INFO = 1
    WARNING = 2
    ERROR = 3
    CRITICAL = 4

class ErrorRecoveryStrategy(Enum):
    """Strategies for error recovery."""
    RETRY = "retry"  # Retry the operation
    FALLBACK = "fallback"  # Use fallback mechanism
    CIRCUIT_BREAK = "circuit_break"  # Activate circuit breaker
    IGNORE = "ignore"  # Ignore the error
    ALERT = "alert"  # Send alert only

class ErrorPatternType(Enum):
    """Types of error patterns."""
    FREQUENCY = "frequency"  # High frequency of same error
    CASCADE = "cascade"  # Errors cascading through components
    CORRELATION = "correlation"  # Errors correlated in time
    SEQUENCE = "sequence"  # Specific sequence of errors
    ROOT_CAUSE = "root_cause"  # Common root cause

@dataclass
class ErrorPattern:
    """Information about a detected error pattern."""
    pattern_type: ErrorPatternType
    pattern_key: str
    occurrences: int
    first_seen: str
    last_seen: str
    affected_components: List[str]
    affected_operations: List[str]
    error_types: List[str]
    severity_distribution: Dict[str, int]
    metadata: Dict[str, Any]
    confidence: float
    is_active: bool = True

@dataclass
class ErrorContext:
    """Context information for errors."""
    component: str
    operation: str
    timestamp: str
    error_type: str
    error_message: str
    severity: ErrorSeverity
    traceback: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    user_id: Optional[str] = None
    request_id: Optional[str] = None
    session_id: Optional[str] = None
    recovery_strategy: Optional[ErrorRecoveryStrategy] = None
    retry_count: int = 0
    max_retries: int = 3
    circuit_breaker_id: Optional[str] = None
    pattern_ids: List[str] = None

    def __post_init__(self):
        if self.pattern_ids is None:
            self.pattern_ids = []

class ErrorHandler:
    """
    Enhanced centralized error handling system with circuit breaker integration,
    error recovery strategies, and sophisticated pattern detection.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the error handler.
        
        Args:
            config: Configuration dictionary with settings
        """
        self.config = config or {}
        
        # Default configuration
        self.alert_threshold = self.config.get("alert_threshold", ErrorSeverity.ERROR)
        self.max_errors_per_minute = self.config.get("max_errors_per_minute", 100)
        self.error_retention_days = self.config.get("error_retention_days", 30)
        self.alert_channels = self.config.get("alert_channels", ["log"])
        self.error_history: List[ErrorContext] = []
        self.error_counts: Dict[str, int] = {}
        self.last_reset_time = time.time()
        
        # Circuit breakers
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._init_circuit_breakers()
        
        # Error patterns
        self.error_patterns: Dict[str, ErrorPattern] = {}
        self.pattern_detection_window = timedelta(hours=1)
        self.pattern_frequency_threshold = self.config.get("pattern_frequency_threshold", 3)
        self.pattern_correlation_window = timedelta(minutes=5)
        self.pattern_confidence_threshold = self.config.get("pattern_confidence_threshold", 0.7)
        
        # Component dependency graph for cascade detection
        self.component_dependencies: Dict[str, Set[str]] = defaultdict(set)
        self._init_component_dependencies()
        
        # Alert callbacks
        self.alert_callbacks: List[Callable[[ErrorContext], None]] = []
        
        # Recovery strategies
        self.recovery_strategies: Dict[Type[Exception], ErrorRecoveryStrategy] = {
            # Add default recovery strategies for common exceptions
            ConnectionError: ErrorRecoveryStrategy.RETRY,
            TimeoutError: ErrorRecoveryStrategy.RETRY,
            ValueError: ErrorRecoveryStrategy.FALLBACK,
            KeyError: ErrorRecoveryStrategy.FALLBACK,
        }
        
        # HTTP client for external notifications
        self.http_client = httpx.AsyncClient(timeout=10.0)
        
        # Load environment variables
        self.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.discord_webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
        self.slack_webhook_url = os.getenv("SLACK_WEBHOOK_URL")
        
        logger.info("ErrorHandler initialized")
    
    def _init_component_dependencies(self) -> None:
        """Initialize component dependency graph for cascade detection."""
        # Define component dependencies
        self.component_dependencies["market_data"] = {"blockchain", "order_manager"}
        self.component_dependencies["order_manager"] = {"trade_executor", "blockchain"}
        self.component_dependencies["trade_executor"] = {"blockchain"}
        self.component_dependencies["blockchain"] = set()
    
    def _init_circuit_breakers(self) -> None:
        """Initialize circuit breakers for different components and operations."""
        # Global circuit breaker
        self.circuit_breakers["global"] = CircuitBreaker(
            breaker_type=CircuitBreakerType.GLOBAL,
            identifier="global",
            max_consecutive_failures=5,
            reset_after_minutes=30,
            persistence_path="data/circuit_breakers/global.json"
        )
        
        # Component circuit breakers
        components = ["market_data", "order_manager", "trade_executor", "blockchain"]
        for component in components:
            self.circuit_breakers[f"component_{component}"] = CircuitBreaker(
                breaker_type=CircuitBreakerType.COMPONENT,
                identifier=component,
                max_consecutive_failures=3,
                reset_after_minutes=15,
                persistence_path=f"data/circuit_breakers/component_{component}.json"
            )
    
    def register_alert_callback(self, callback: Callable[[ErrorContext], None]) -> None:
        """
        Register a callback function to be called when an error occurs.
        
        Args:
            callback: Function to call with error context
        """
        self.alert_callbacks.append(callback)
        logger.info(f"Registered alert callback: {callback.__name__}")
    
    def register_recovery_strategy(self, exception_type: Type[Exception], strategy: ErrorRecoveryStrategy) -> None:
        """
        Register a recovery strategy for a specific exception type.
        
        Args:
            exception_type: Type of exception to handle
            strategy: Recovery strategy to use
        """
        self.recovery_strategies[exception_type] = strategy
        logger.info(f"Registered recovery strategy {strategy.value} for {exception_type.__name__}")
    
    def register_component_dependency(self, component: str, depends_on: str) -> None:
        """
        Register a dependency between components for cascade detection.
        
        Args:
            component: The dependent component
            depends_on: The component it depends on
        """
        self.component_dependencies[component].add(depends_on)
        logger.info(f"Registered dependency: {component} depends on {depends_on}")
    
    async def handle_error(
        self,
        error: Exception,
        component: str,
        operation: str,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        metadata: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> ErrorContext:
        """
        Handle an error with structured logging, circuit breaker integration,
        and recovery strategies.
        
        Args:
            error: The exception that occurred
            component: The component where the error occurred
            operation: The operation that was being performed
            severity: The severity of the error
            metadata: Additional context information
            user_id: ID of the user if applicable
            request_id: ID of the request if applicable
            session_id: ID of the session if applicable
            
        Returns:
            ErrorContext object with error information
        """
        # Determine recovery strategy
        recovery_strategy = self._determine_recovery_strategy(error)
        
        # Create error context
        error_context = ErrorContext(
            component=component,
            operation=operation,
            timestamp=datetime.now().isoformat(),
            error_type=type(error).__name__,
            error_message=str(error),
            severity=severity,
            traceback=traceback.format_exc(),
            metadata=metadata or {},
            user_id=user_id,
            request_id=request_id,
            session_id=session_id,
            recovery_strategy=recovery_strategy
        )
        
        # Update circuit breakers
        self._update_circuit_breakers(error_context)
        
        # Check circuit breakers
        if self._check_circuit_breakers(component, operation):
            error_context.recovery_strategy = ErrorRecoveryStrategy.CIRCUIT_BREAK
            logger.warning(f"Circuit breaker active for {component}/{operation}")
        
        # Log the error
        self._log_error(error_context)
        
        # Update error counts and patterns
        self._update_error_counts(error_context)
        self._update_error_patterns(error_context)
        
        # Add to history
        self.error_history.append(error_context)
        
        # Trim history if needed
        if len(self.error_history) > 1000:  # Keep last 1000 errors
            self.error_history = self.error_history[-1000:]
        
        # Check if we should alert
        if severity.value >= self.alert_threshold.value:
            await self._send_alert(error_context)
        
        # Call registered callbacks
        for callback in self.alert_callbacks:
            try:
                callback(error_context)
            except Exception as e:
                logger.error(f"Error in alert callback: {e}", exc_info=True)
        
        return error_context
    
    def _determine_recovery_strategy(self, error: Exception) -> ErrorRecoveryStrategy:
        """
        Determine the appropriate recovery strategy for an error.
        
        Args:
            error: The exception that occurred
            
        Returns:
            ErrorRecoveryStrategy to use
        """
        # Check registered strategies
        for exception_type, strategy in self.recovery_strategies.items():
            if isinstance(error, exception_type):
                return strategy
        
        # Default to alert for unknown errors
        return ErrorRecoveryStrategy.ALERT
    
    def _update_circuit_breakers(self, error_context: ErrorContext) -> None:
        """
        Update circuit breakers based on error context.
        
        Args:
            error_context: Error context to process
        """
        # Update global circuit breaker
        self.circuit_breakers["global"].increment_failures()
        
        # Update component circuit breaker
        component_breaker = self.circuit_breakers.get(f"component_{error_context.component}")
        if component_breaker:
            component_breaker.increment_failures()
    
    def _check_circuit_breakers(self, component: str, operation: str) -> bool:
        """
        Check if any relevant circuit breakers are active.
        
        Args:
            component: Component to check
            operation: Operation to check
            
        Returns:
            bool: True if any circuit breaker is active
        """
        # Check global circuit breaker
        if self.circuit_breakers["global"].check():
            return True
        
        # Check component circuit breaker
        component_breaker = self.circuit_breakers.get(f"component_{component}")
        if component_breaker and component_breaker.check():
            return True
        
        return False
    
    def _update_error_patterns(self, error_context: ErrorContext) -> None:
        """
        Update error patterns with sophisticated pattern detection.
        
        Args:
            error_context: Error context to process
        """
        # Clean up old patterns first
        self._cleanup_old_patterns()
        
        # Detect different types of patterns
        self._detect_frequency_patterns(error_context)
        self._detect_cascade_patterns(error_context)
        self._detect_correlation_patterns(error_context)
        self._detect_sequence_patterns(error_context)
        self._detect_root_cause_patterns(error_context)
    
    def _cleanup_old_patterns(self) -> None:
        """Clean up old patterns that are no longer active."""
        current_time = datetime.now()
        cutoff_time = current_time - self.pattern_detection_window
        
        patterns_to_remove = []
        for pattern_id, pattern in self.error_patterns.items():
            # Check if pattern is old
            last_seen = datetime.fromisoformat(pattern.last_seen)
            if last_seen < cutoff_time:
                patterns_to_remove.append(pattern_id)
        
        # Remove old patterns
        for pattern_id in patterns_to_remove:
            del self.error_patterns[pattern_id]
            logger.info(f"Removed old pattern: {pattern_id}")
    
    def _detect_frequency_patterns(self, error_context: ErrorContext) -> None:
        """
        Detect patterns based on error frequency.
        
        Args:
            error_context: Error context to process
        """
        # Create pattern key
        pattern_key = f"freq:{error_context.component}:{error_context.operation}:{error_context.error_type}"
        
        # Get recent errors of the same type
        recent_errors = [
            e for e in self.error_history
            if e.component == error_context.component and
               e.operation == error_context.operation and
               e.error_type == error_context.error_type and
               datetime.fromisoformat(e.timestamp) > datetime.now() - self.pattern_detection_window
        ]
        
        # Check if frequency exceeds threshold
        if len(recent_errors) >= self.pattern_frequency_threshold:
            # Create or update pattern
            if pattern_key not in self.error_patterns:
                self.error_patterns[pattern_key] = ErrorPattern(
                    pattern_type=ErrorPatternType.FREQUENCY,
                    pattern_key=pattern_key,
                    occurrences=len(recent_errors),
                    first_seen=recent_errors[0].timestamp,
                    last_seen=error_context.timestamp,
                    affected_components=[error_context.component],
                    affected_operations=[error_context.operation],
                    error_types=[error_context.error_type],
                    severity_distribution=self._calculate_severity_distribution(recent_errors),
                    metadata={"frequency": len(recent_errors) / self.pattern_detection_window.total_seconds() * 3600},
                    confidence=min(1.0, len(recent_errors) / (self.pattern_frequency_threshold * 2))
                )
                logger.warning(f"Frequency pattern detected: {pattern_key}")
                logger.warning(f"Occurrences: {len(recent_errors)}")
            else:
                # Update existing pattern
                pattern = self.error_patterns[pattern_key]
                pattern.occurrences = len(recent_errors)
                pattern.last_seen = error_context.timestamp
                pattern.severity_distribution = self._calculate_severity_distribution(recent_errors)
                pattern.metadata["frequency"] = len(recent_errors) / self.pattern_detection_window.total_seconds() * 3600
                pattern.confidence = min(1.0, len(recent_errors) / (self.pattern_frequency_threshold * 2))
            
            # Add pattern ID to error context
            error_context.pattern_ids.append(pattern_key)
    
    def _detect_cascade_patterns(self, error_context: ErrorContext) -> None:
        """
        Detect patterns based on error cascades through components.
        
        Args:
            error_context: Error context to process
        """
        # Get recent errors
        recent_errors = [
            e for e in self.error_history
            if datetime.fromisoformat(e.timestamp) > datetime.now() - self.pattern_detection_window
        ]
        
        # Check for cascades
        for component, dependencies in self.component_dependencies.items():
            if error_context.component == component:
                # Check if any dependent components had errors recently
                dependent_errors = [
                    e for e in recent_errors
                    if e.component in dependencies and
                       datetime.fromisoformat(e.timestamp) < datetime.fromisoformat(error_context.timestamp)
                ]
                
                if dependent_errors:
                    # Create pattern key
                    pattern_key = f"cascade:{component}:{','.join(e.component for e in dependent_errors)}"
                    
                    # Create or update pattern
                    if pattern_key not in self.error_patterns:
                        affected_components = [component] + [e.component for e in dependent_errors]
                        self.error_patterns[pattern_key] = ErrorPattern(
                            pattern_type=ErrorPatternType.CASCADE,
                            pattern_key=pattern_key,
                            occurrences=len(dependent_errors) + 1,
                            first_seen=dependent_errors[0].timestamp,
                            last_seen=error_context.timestamp,
                            affected_components=affected_components,
                            affected_operations=[e.operation for e in dependent_errors] + [error_context.operation],
                            error_types=[e.error_type for e in dependent_errors] + [error_context.error_type],
                            severity_distribution=self._calculate_severity_distribution(dependent_errors + [error_context]),
                            metadata={"cascade_path": [e.component for e in dependent_errors] + [component]},
                            confidence=min(1.0, len(dependent_errors) / 3)
                        )
                        logger.warning(f"Cascade pattern detected: {pattern_key}")
                        logger.warning(f"Cascade path: {' -> '.join(affected_components)}")
                    else:
                        # Update existing pattern
                        pattern = self.error_patterns[pattern_key]
                        pattern.occurrences += 1
                        pattern.last_seen = error_context.timestamp
                        pattern.affected_operations.append(error_context.operation)
                        pattern.error_types.append(error_context.error_type)
                        pattern.severity_distribution = self._calculate_severity_distribution(dependent_errors + [error_context])
                        pattern.confidence = min(1.0, pattern.occurrences / 3)
                    
                    # Add pattern ID to error context
                    error_context.pattern_ids.append(pattern_key)
    
    def _detect_correlation_patterns(self, error_context: ErrorContext) -> None:
        """
        Detect patterns based on correlated errors in time.
        
        Args:
            error_context: Error context to process
        """
        # Get recent errors within correlation window
        recent_errors = [
            e for e in self.error_history
            if abs((datetime.fromisoformat(e.timestamp) - datetime.fromisoformat(error_context.timestamp)).total_seconds()) < self.pattern_correlation_window.total_seconds()
        ]
        
        # Group errors by component
        errors_by_component = defaultdict(list)
        for error in recent_errors:
            errors_by_component[error.component].append(error)
        
        # Check for correlations between components
        if len(errors_by_component) > 1:
            # Create pattern key
            components = sorted(errors_by_component.keys())
            pattern_key = f"corr:{':'.join(components)}"
            
            # Create or update pattern
            if pattern_key not in self.error_patterns:
                all_errors = [e for errors in errors_by_component.values() for e in errors]
                self.error_patterns[pattern_key] = ErrorPattern(
                    pattern_type=ErrorPatternType.CORRELATION,
                    pattern_key=pattern_key,
                    occurrences=len(all_errors),
                    first_seen=min(e.timestamp for e in all_errors),
                    last_seen=max(e.timestamp for e in all_errors),
                    affected_components=components,
                    affected_operations=[e.operation for e in all_errors],
                    error_types=[e.error_type for e in all_errors],
                    severity_distribution=self._calculate_severity_distribution(all_errors),
                    metadata={"correlation_window": self.pattern_correlation_window.total_seconds()},
                    confidence=min(1.0, len(all_errors) / (len(components) * 2))
                )
                logger.warning(f"Correlation pattern detected: {pattern_key}")
                logger.warning(f"Components: {', '.join(components)}")
            else:
                # Update existing pattern
                pattern = self.error_patterns[pattern_key]
                pattern.occurrences = len(recent_errors)
                pattern.last_seen = error_context.timestamp
                pattern.affected_operations.append(error_context.operation)
                pattern.error_types.append(error_context.error_type)
                pattern.severity_distribution = self._calculate_severity_distribution(recent_errors)
                pattern.confidence = min(1.0, len(recent_errors) / (len(components) * 2))
            
            # Add pattern ID to error context
            error_context.pattern_ids.append(pattern_key)
    
    def _detect_sequence_patterns(self, error_context: ErrorContext) -> None:
        """
        Detect patterns based on specific sequences of errors.
        
        Args:
            error_context: Error context to process
        """
        # Get recent errors
        recent_errors = [
            e for e in self.error_history
            if datetime.fromisoformat(e.timestamp) > datetime.now() - self.pattern_detection_window
        ]
        
        # Look for sequences of 3 or more errors
        if len(recent_errors) >= 3:
            # Create sequence key
            sequence = [f"{e.component}:{e.operation}:{e.error_type}" for e in recent_errors[-3:]]
            sequence_key = "->".join(sequence)
            pattern_key = f"seq:{sequence_key}"
            
            # Check if this sequence has occurred before
            sequence_count = 0
            for i in range(len(recent_errors) - 2):
                check_sequence = [f"{e.component}:{e.operation}:{e.error_type}" for e in recent_errors[i:i+3]]
                if "->".join(check_sequence) == sequence_key:
                    sequence_count += 1
            
            if sequence_count >= 2:  # Sequence has occurred at least twice
                # Create or update pattern
                if pattern_key not in self.error_patterns:
                    self.error_patterns[pattern_key] = ErrorPattern(
                        pattern_type=ErrorPatternType.SEQUENCE,
                        pattern_key=pattern_key,
                        occurrences=sequence_count,
                        first_seen=recent_errors[-3].timestamp,
                        last_seen=error_context.timestamp,
                        affected_components=[e.component for e in recent_errors[-3:]],
                        affected_operations=[e.operation for e in recent_errors[-3:]],
                        error_types=[e.error_type for e in recent_errors[-3:]],
                        severity_distribution=self._calculate_severity_distribution(recent_errors[-3:]),
                        metadata={"sequence": sequence},
                        confidence=min(1.0, sequence_count / 3)
                    )
                    logger.warning(f"Sequence pattern detected: {pattern_key}")
                    logger.warning(f"Sequence: {' -> '.join(sequence)}")
                else:
                    # Update existing pattern
                    pattern = self.error_patterns[pattern_key]
                    pattern.occurrences = sequence_count
                    pattern.last_seen = error_context.timestamp
                    pattern.confidence = min(1.0, sequence_count / 3)
                
                # Add pattern ID to error context
                error_context.pattern_ids.append(pattern_key)
    
    def _detect_root_cause_patterns(self, error_context: ErrorContext) -> None:
        """
        Detect patterns based on common root causes.
        
        Args:
            error_context: Error context to process
        """
        # Extract potential root cause from error message
        root_cause = self._extract_root_cause(error_context)
        
        if root_cause:
            # Get recent errors
            recent_errors = [
                e for e in self.error_history
                if datetime.fromisoformat(e.timestamp) > datetime.now() - self.pattern_detection_window
            ]
            
            # Find errors with similar root causes
            similar_errors = [
                e for e in recent_errors
                if self._extract_root_cause(e) == root_cause
            ]
            
            if len(similar_errors) >= 2:  # At least 2 errors with same root cause
                # Create pattern key
                pattern_key = f"root:{root_cause}"
                
                # Create or update pattern
                if pattern_key not in self.error_patterns:
                    self.error_patterns[pattern_key] = ErrorPattern(
                        pattern_type=ErrorPatternType.ROOT_CAUSE,
                        pattern_key=pattern_key,
                        occurrences=len(similar_errors),
                        first_seen=similar_errors[0].timestamp,
                        last_seen=error_context.timestamp,
                        affected_components=[e.component for e in similar_errors],
                        affected_operations=[e.operation for e in similar_errors],
                        error_types=[e.error_type for e in similar_errors],
                        severity_distribution=self._calculate_severity_distribution(similar_errors),
                        metadata={"root_cause": root_cause},
                        confidence=min(1.0, len(similar_errors) / 3)
                    )
                    logger.warning(f"Root cause pattern detected: {pattern_key}")
                    logger.warning(f"Root cause: {root_cause}")
                else:
                    # Update existing pattern
                    pattern = self.error_patterns[pattern_key]
                    pattern.occurrences = len(similar_errors)
                    pattern.last_seen = error_context.timestamp
                    pattern.affected_components.append(error_context.component)
                    pattern.affected_operations.append(error_context.operation)
                    pattern.error_types.append(error_context.error_type)
                    pattern.severity_distribution = self._calculate_severity_distribution(similar_errors)
                    pattern.confidence = min(1.0, len(similar_errors) / 3)
                
                # Add pattern ID to error context
                error_context.pattern_ids.append(pattern_key)
    
    def _extract_root_cause(self, error_context: ErrorContext) -> Optional[str]:
        """
        Extract potential root cause from error context.
        
        Args:
            error_context: Error context to analyze
            
        Returns:
            Extracted root cause or None
        """
        # Simple root cause extraction based on error message
        error_message = error_context.error_message.lower()
        
        if "connection" in error_message or "timeout" in error_message:
            return "network_issue"
        elif "permission" in error_message or "access" in error_message:
            return "permission_issue"
        elif "validation" in error_message or "invalid" in error_message:
            return "validation_issue"
        elif "not found" in error_message or "missing" in error_message:
            return "resource_not_found"
        elif "rate limit" in error_message or "too many requests" in error_message:
            return "rate_limiting"
        elif "blockchain" in error_message or "transaction" in error_message:
            return "blockchain_issue"
        
        return None
    
    def _calculate_severity_distribution(self, errors: List[ErrorContext]) -> Dict[str, int]:
        """
        Calculate severity distribution for a list of errors.
        
        Args:
            errors: List of error contexts
            
        Returns:
            Dictionary with severity distribution
        """
        distribution = defaultdict(int)
        for error in errors:
            distribution[error.severity.name] += 1
        return dict(distribution)
    
    def get_error_patterns(self) -> Dict[str, ErrorPattern]:
        """
        Get detected error patterns.
        
        Returns:
            Dictionary of error patterns
        """
        return self.error_patterns
    
    def get_active_patterns(self) -> Dict[str, ErrorPattern]:
        """
        Get currently active error patterns.
        
        Returns:
            Dictionary of active error patterns
        """
        return {k: v for k, v in self.error_patterns.items() if v.is_active}
    
    def get_pattern_by_id(self, pattern_id: str) -> Optional[ErrorPattern]:
        """
        Get a specific error pattern by ID.
        
        Args:
            pattern_id: Pattern ID to retrieve
            
        Returns:
            Error pattern or None if not found
        """
        return self.error_patterns.get(pattern_id)
    
    def get_patterns_by_type(self, pattern_type: ErrorPatternType) -> Dict[str, ErrorPattern]:
        """
        Get error patterns of a specific type.
        
        Args:
            pattern_type: Type of patterns to retrieve
            
        Returns:
            Dictionary of error patterns
        """
        return {k: v for k, v in self.error_patterns.items() if v.pattern_type == pattern_type}
    
    def get_patterns_by_component(self, component: str) -> Dict[str, ErrorPattern]:
        """
        Get error patterns affecting a specific component.
        
        Args:
            component: Component to filter by
            
        Returns:
            Dictionary of error patterns
        """
        return {k: v for k, v in self.error_patterns.items() if component in v.affected_components}
    
    def visualize_pattern(self, pattern_id: str) -> Dict[str, Any]:
        """
        Generate a visualization of an error pattern.
        
        Args:
            pattern_id: ID of the pattern to visualize
            
        Returns:
            Dictionary with visualization data
        """
        pattern = self.error_patterns.get(pattern_id)
        if not pattern:
            return {}
        
        # Get errors associated with this pattern
        pattern_errors = [
            e for e in self.error_history
            if pattern_id in e.pattern_ids
        ]
        
        # Generate timeline data
        timeline = []
        for error in pattern_errors:
            timeline.append({
                "timestamp": error.timestamp,
                "component": error.component,
                "operation": error.operation,
                "error_type": error.error_type,
                "severity": error.severity.name
            })
        
        # Generate component interaction data
        component_interactions = []
        if pattern.pattern_type == ErrorPatternType.CASCADE:
            # For cascade patterns, show the flow between components
            for i in range(len(pattern.affected_components) - 1):
                component_interactions.append({
                    "from": pattern.affected_components[i],
                    "to": pattern.affected_components[i + 1],
                    "count": sum(1 for e in pattern_errors if e.component == pattern.affected_components[i])
                })
        
        # Generate severity distribution data
        severity_data = []
        for severity, count in pattern.severity_distribution.items():
            severity_data.append({
                "severity": severity,
                "count": count
            })
        
        # Generate error type distribution
        error_type_counts = defaultdict(int)
        for error in pattern_errors:
            error_type_counts[error.error_type] += 1
        
        error_type_data = [
            {"error_type": error_type, "count": count}
            for error_type, count in error_type_counts.items()
        ]
        
        return {
            "pattern_id": pattern_id,
            "pattern_type": pattern.pattern_type.value,
            "occurrences": pattern.occurrences,
            "confidence": pattern.confidence,
            "first_seen": pattern.first_seen,
            "last_seen": pattern.last_seen,
            "affected_components": pattern.affected_components,
            "timeline": timeline,
            "component_interactions": component_interactions,
            "severity_distribution": severity_data,
            "error_type_distribution": error_type_data,
            "metadata": pattern.metadata
        }
    
    def predict_future_errors(self, pattern_id: str, hours: int = 24) -> Dict[str, Any]:
        """
        Predict potential future errors based on a pattern.
        
        Args:
            pattern_id: ID of the pattern to analyze
            hours: Number of hours to predict ahead
            
        Returns:
            Dictionary with prediction data
        """
        pattern = self.error_patterns.get(pattern_id)
        if not pattern:
            return {}
        
        # Get errors associated with this pattern
        pattern_errors = [
            e for e in self.error_history
            if pattern_id in e.pattern_ids
        ]
        
        # Calculate error frequency
        if not pattern_errors:
            return {}
        
        # Calculate time span of pattern
        first_seen = datetime.fromisoformat(pattern_errors[0].timestamp)
        last_seen = datetime.fromisoformat(pattern_errors[-1].timestamp)
        time_span = (last_seen - first_seen).total_seconds() / 3600  # in hours
        
        if time_span == 0:
            time_span = 1  # Avoid division by zero
        
        # Calculate errors per hour
        errors_per_hour = len(pattern_errors) / time_span
        
        # Predict future errors
        predicted_errors = int(errors_per_hour * hours)
        
        # Calculate confidence based on pattern stability
        if pattern.pattern_type == ErrorPatternType.FREQUENCY:
            # For frequency patterns, check if the frequency is stable
            time_buckets = defaultdict(int)
            for error in pattern_errors:
                hour = datetime.fromisoformat(error.timestamp).replace(minute=0, second=0, microsecond=0)
                time_buckets[hour] += 1
            
            # Calculate standard deviation of hourly counts
            counts = list(time_buckets.values())
            if counts:
                mean = sum(counts) / len(counts)
                variance = sum((x - mean) ** 2 for x in counts) / len(counts)
                std_dev = variance ** 0.5
                
                # Lower standard deviation means more stable pattern
                stability = 1.0 - min(1.0, std_dev / mean if mean > 0 else 1.0)
            else:
                stability = 0.5
        else:
            # For other pattern types, use pattern confidence
            stability = pattern.confidence
        
        # Calculate prediction confidence
        prediction_confidence = stability * min(1.0, len(pattern_errors) / 10)
        
        # Generate prediction data
        return {
            "pattern_id": pattern_id,
            "pattern_type": pattern.pattern_type.value,
            "predicted_errors": predicted_errors,
            "prediction_hours": hours,
            "confidence": prediction_confidence,
            "errors_per_hour": errors_per_hour,
            "affected_components": pattern.affected_components,
            "likely_error_types": list(set(e.error_type for e in pattern_errors)),
            "prediction_time": datetime.now().isoformat()
        }
    
    def generate_recommendations(self, pattern_id: str) -> List[Dict[str, Any]]:
        """
        Generate recommendations based on an error pattern.
        
        Args:
            pattern_id: ID of the pattern to analyze
            
        Returns:
            List of recommendations
        """
        pattern = self.error_patterns.get(pattern_id)
        if not pattern:
            return []
        
        recommendations = []
        
        # Get errors associated with this pattern
        pattern_errors = [
            e for e in self.error_history
            if pattern_id in e.pattern_ids
        ]
        
        # Generate recommendations based on pattern type
        if pattern.pattern_type == ErrorPatternType.FREQUENCY:
            # For frequency patterns, recommend circuit breaker or retry strategy
            if pattern.occurrences > 10:
                recommendations.append({
                    "type": "circuit_breaker",
                    "component": pattern.affected_components[0],
                    "description": f"Implement circuit breaker for {pattern.affected_components[0]} to prevent cascading failures",
                    "priority": "high",
                    "impact": "Reduces system load and prevents cascading failures"
                })
            else:
                recommendations.append({
                    "type": "retry_strategy",
                    "component": pattern.affected_components[0],
                    "description": f"Implement exponential backoff retry strategy for {pattern.affected_operations[0]}",
                    "priority": "medium",
                    "impact": "Improves resilience to transient failures"
                })
        
        elif pattern.pattern_type == ErrorPatternType.CASCADE:
            # For cascade patterns, recommend isolation or fallback
            recommendations.append({
                "type": "isolation",
                "components": pattern.affected_components,
                "description": f"Isolate components in the cascade path: {' -> '.join(pattern.affected_components)}",
                "priority": "high",
                "impact": "Prevents cascading failures through the system"
            })
            
            recommendations.append({
                "type": "fallback",
                "component": pattern.affected_components[-1],
                "description": f"Implement fallback mechanism for {pattern.affected_operations[-1]}",
                "priority": "medium",
                "impact": "Provides graceful degradation when dependencies fail"
            })
        
        elif pattern.pattern_type == ErrorPatternType.CORRELATION:
            # For correlation patterns, recommend investigation or monitoring
            recommendations.append({
                "type": "investigation",
                "components": pattern.affected_components,
                "description": f"Investigate common factors affecting components: {', '.join(pattern.affected_components)}",
                "priority": "medium",
                "impact": "Identifies root cause of correlated failures"
            })
            
            recommendations.append({
                "type": "monitoring",
                "components": pattern.affected_components,
                "description": f"Enhance monitoring for correlated components: {', '.join(pattern.affected_components)}",
                "priority": "medium",
                "impact": "Provides early warning of potential failures"
            })
        
        elif pattern.pattern_type == ErrorPatternType.SEQUENCE:
            # For sequence patterns, recommend prevention or detection
            recommendations.append({
                "type": "prevention",
                "components": pattern.affected_components,
                "description": f"Implement prevention mechanism for error sequence: {' -> '.join(pattern.affected_components)}",
                "priority": "high",
                "impact": "Prevents known error sequences from occurring"
            })
            
            recommendations.append({
                "type": "detection",
                "components": pattern.affected_components,
                "description": f"Implement early detection for sequence: {' -> '.join(pattern.affected_components)}",
                "priority": "medium",
                "impact": "Provides early warning of potential error sequences"
            })
        
        elif pattern.pattern_type == ErrorPatternType.ROOT_CAUSE:
            # For root cause patterns, recommend specific fixes
            root_cause = pattern.metadata.get("root_cause", "unknown")
            
            if root_cause == "network_issue":
                recommendations.append({
                    "type": "resilience",
                    "components": pattern.affected_components,
                    "description": "Improve network resilience with better retry strategies and timeouts",
                    "priority": "high",
                    "impact": "Reduces impact of network issues"
                })
            
            elif root_cause == "permission_issue":
                recommendations.append({
                    "type": "security",
                    "components": pattern.affected_components,
                    "description": "Review and fix permission issues in affected components",
                    "priority": "high",
                    "impact": "Resolves permission-related errors"
                })
            
            elif root_cause == "validation_issue":
                recommendations.append({
                    "type": "validation",
                    "components": pattern.affected_components,
                    "description": "Improve input validation in affected components",
                    "priority": "medium",
                    "impact": "Prevents validation errors"
                })
            
            elif root_cause == "resource_not_found":
                recommendations.append({
                    "type": "error_handling",
                    "components": pattern.affected_components,
                    "description": "Improve handling of missing resources",
                    "priority": "medium",
                    "impact": "Provides better user experience when resources are missing"
                })
            
            elif root_cause == "rate_limiting":
                recommendations.append({
                    "type": "rate_limiting",
                    "components": pattern.affected_components,
                    "description": "Implement better rate limiting strategies",
                    "priority": "medium",
                    "impact": "Prevents rate limiting issues"
                })
            
            elif root_cause == "blockchain_issue":
                recommendations.append({
                    "type": "blockchain",
                    "components": pattern.affected_components,
                    "description": "Improve blockchain interaction error handling",
                    "priority": "high",
                    "impact": "Reduces blockchain-related errors"
                })
        
        return recommendations
    
    def export_patterns(self, format: str = "json", file_path: Optional[str] = None) -> Union[str, Dict[str, Any]]:
        """
        Export error patterns in the specified format.
        
        Args:
            format: Export format (json, csv, html)
            file_path: Optional file path to save the export
            
        Returns:
            Exported data as string or dictionary
        """
        # Prepare data for export
        export_data = {
            "patterns": [],
            "metadata": {
                "export_time": datetime.now().isoformat(),
                "total_patterns": len(self.error_patterns),
                "active_patterns": len(self.get_active_patterns()),
                "pattern_types": {t.value: len(self.get_patterns_by_type(t)) for t in ErrorPatternType}
            }
        }
        
        # Add pattern data
        for pattern_id, pattern in self.error_patterns.items():
            pattern_data = asdict(pattern)
            pattern_data["pattern_type"] = pattern.pattern_type.value
            
            # Add visualization data
            pattern_data["visualization"] = self.visualize_pattern(pattern_id)
            
            # Add recommendations
            pattern_data["recommendations"] = self.generate_recommendations(pattern_id)
            
            # Add prediction
            pattern_data["prediction"] = self.predict_future_errors(pattern_id)
            
            export_data["patterns"].append(pattern_data)
        
        # Export in requested format
        if format == "json":
            result = json.dumps(export_data, indent=2)
        elif format == "csv":
            # Simple CSV export of pattern summaries
            import csv
            from io import StringIO
            
            output = StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow([
                "Pattern ID", "Type", "Occurrences", "First Seen", "Last Seen",
                "Components", "Confidence", "Is Active"
            ])
            
            # Write data
            for pattern in export_data["patterns"]:
                writer.writerow([
                    pattern["pattern_key"],
                    pattern["pattern_type"],
                    pattern["occurrences"],
                    pattern["first_seen"],
                    pattern["last_seen"],
                    ",".join(pattern["affected_components"]),
                    pattern["confidence"],
                    pattern["is_active"]
                ])
            
            result = output.getvalue()
        elif format == "html":
            # Simple HTML report
            html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Error Patterns Report</title>
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 20px; }}
                    table {{ border-collapse: collapse; width: 100%; }}
                    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                    th {{ background-color: #f2f2f2; }}
                    tr:nth-child(even) {{ background-color: #f9f9f9; }}
                    .active {{ color: green; }}
                    .inactive {{ color: red; }}
                </style>
            </head>
            <body>
                <h1>Error Patterns Report</h1>
                <p>Generated at: {export_data["metadata"]["export_time"]}</p>
                <p>Total Patterns: {export_data["metadata"]["total_patterns"]}</p>
                <p>Active Patterns: {export_data["metadata"]["active_patterns"]}</p>
                
                <h2>Patterns by Type</h2>
                <ul>
            """
            
            for pattern_type, count in export_data["metadata"]["pattern_types"].items():
                html += f"<li>{pattern_type}: {count}</li>"
            
            html += """
                </ul>
                
                <h2>Error Patterns</h2>
                <table>
                    <tr>
                        <th>Pattern ID</th>
                        <th>Type</th>
                        <th>Occurrences</th>
                        <th>First Seen</th>
                        <th>Last Seen</th>
                        <th>Components</th>
                        <th>Confidence</th>
                        <th>Status</th>
                    </tr>
            """
            
            for pattern in export_data["patterns"]:
                status_class = "active" if pattern["is_active"] else "inactive"
                status_text = "Active" if pattern["is_active"] else "Inactive"
                
                html += f"""
                    <tr>
                        <td>{pattern["pattern_key"]}</td>
                        <td>{pattern["pattern_type"]}</td>
                        <td>{pattern["occurrences"]}</td>
                        <td>{pattern["first_seen"]}</td>
                        <td>{pattern["last_seen"]}</td>
                        <td>{", ".join(pattern["affected_components"])}</td>
                        <td>{pattern["confidence"]:.2f}</td>
                        <td class="{status_class}">{status_text}</td>
                    </tr>
                """
            
            html += """
                </table>
            </body>
            </html>
            """
            
            result = html
        else:
            result = export_data
        
        # Save to file if requested
        if file_path:
            with open(file_path, 'w') as f:
                f.write(result)
            logger.info(f"Exported patterns to {file_path}")
        
        return result
    
    def get_circuit_breaker_status(self) -> Dict[str, Any]:
        """
        Get status of all circuit breakers.
        
        Returns:
            Dictionary with circuit breaker status
        """
        status = {}
        for breaker_id, breaker in self.circuit_breakers.items():
            status[breaker_id] = {
                "is_active": breaker.is_active,
                "consecutive_failures": breaker.consecutive_failures,
                "time_since_activation": breaker.time_since_activation,
                "metrics": asdict(breaker.metrics)
            }
        return status
    
    def _log_error(self, error_context: ErrorContext) -> None:
        """
        Log an error with structured information.
        
        Args:
            error_context: Error context to log
        """
        log_data = asdict(error_context)
        log_data["severity"] = log_data["severity"].name
        
        if error_context.severity == ErrorSeverity.INFO:
            logger.info(json.dumps(log_data))
        elif error_context.severity == ErrorSeverity.WARNING:
            logger.warning(json.dumps(log_data))
        elif error_context.severity == ErrorSeverity.ERROR:
            logger.error(json.dumps(log_data))
        elif error_context.severity == ErrorSeverity.CRITICAL:
            logger.critical(json.dumps(log_data))
    
    def _update_error_counts(self, error_context: ErrorContext) -> None:
        """
        Update error counts for rate limiting and monitoring.
        
        Args:
            error_context: Error context to count
        """
        # Reset counts if needed
        current_time = time.time()
        if current_time - self.last_reset_time > 60:  # Reset every minute
            self.error_counts = {}
            self.last_reset_time = current_time
        
        # Update counts
        key = f"{error_context.component}:{error_context.operation}:{error_context.error_type}"
        self.error_counts[key] = self.error_counts.get(key, 0) + 1
    
    async def _send_alert(self, error_context: ErrorContext) -> None:
        """
        Send alerts for errors through configured channels.
        
        Args:
            error_context: Error context to alert about
        """
        # Check rate limiting
        if self._is_rate_limited():
            logger.warning("Alert rate limited, skipping alert")
            return
        
        # Send to configured channels
        for channel in self.alert_channels:
            try:
                if channel == "log":
                    # Already logged in _log_error
                    pass
                elif channel == "telegram" and self.telegram_bot_token and self.telegram_chat_id:
                    await self._send_telegram_alert(error_context)
                elif channel == "discord" and self.discord_webhook_url:
                    await self._send_discord_alert(error_context)
                elif channel == "slack" and self.slack_webhook_url:
                    await self._send_slack_alert(error_context)
            except Exception as e:
                logger.error(f"Error sending alert to {channel}: {e}", exc_info=True)
    
    def _is_rate_limited(self) -> bool:
        """
        Check if alerts are being rate limited.
        
        Returns:
            bool: True if rate limited, False otherwise
        """
        total_errors = sum(self.error_counts.values())
        return total_errors > self.max_errors_per_minute
    
    async def _send_telegram_alert(self, error_context: ErrorContext) -> None:
        """
        Send alert to Telegram.
        
        Args:
            error_context: Error context to alert about
        """
        message = self._format_alert_message(error_context)
        url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
        data = {
            "chat_id": self.telegram_chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        
        try:
            await self.http_client.post(url, json=data)
        except Exception as e:
            logger.error(f"Error sending Telegram alert: {e}", exc_info=True)
    
    async def _send_discord_alert(self, error_context: ErrorContext) -> None:
        """
        Send alert to Discord.
        
        Args:
            error_context: Error context to alert about
        """
        message = self._format_alert_message(error_context)
        data = {
            "content": message
        }
        
        try:
            await self.http_client.post(self.discord_webhook_url, json=data)
        except Exception as e:
            logger.error(f"Error sending Discord alert: {e}", exc_info=True)
    
    async def _send_slack_alert(self, error_context: ErrorContext) -> None:
        """
        Send alert to Slack.
        
        Args:
            error_context: Error context to alert about
        """
        message = self._format_alert_message(error_context)
        data = {
            "text": message
        }
        
        try:
            await self.http_client.post(self.slack_webhook_url, json=data)
        except Exception as e:
            logger.error(f"Error sending Slack alert: {e}", exc_info=True)
    
    def _format_alert_message(self, error_context: ErrorContext) -> str:
        """
        Format error context into a readable alert message.
        
        Args:
            error_context: Error context to format
            
        Returns:
            Formatted message string
        """
        severity_emoji = {
            ErrorSeverity.INFO: "ℹ️",
            ErrorSeverity.WARNING: "⚠️",
            ErrorSeverity.ERROR: "❌",
            ErrorSeverity.CRITICAL: "🔥"
        }
        
        emoji = severity_emoji.get(error_context.severity, "❓")
        
        message = (
            f"{emoji} <b>{error_context.severity.name}</b> in {error_context.component}\n"
            f"Operation: {error_context.operation}\n"
            f"Error: {error_context.error_type} - {error_context.error_message}\n"
            f"Time: {error_context.timestamp}"
        )
        
        if error_context.user_id:
            message += f"\nUser: {error_context.user_id}"
        
        if error_context.request_id:
            message += f"\nRequest: {error_context.request_id}"
        
        if error_context.metadata:
            message += f"\nMetadata: {json.dumps(error_context.metadata)}"
        
        return message
    
    def get_error_history(
        self,
        component: Optional[str] = None,
        severity: Optional[ErrorSeverity] = None,
        limit: int = 100
    ) -> List[ErrorContext]:
        """
        Get error history with optional filtering.
        
        Args:
            component: Filter by component
            severity: Filter by severity
            limit: Maximum number of errors to return
            
        Returns:
            List of error contexts
        """
        filtered = self.error_history
        
        if component:
            filtered = [e for e in filtered if e.component == component]
        
        if severity:
            filtered = [e for e in filtered if e.severity == severity]
        
        return filtered[-limit:]
    
    def get_error_counts(self) -> Dict[str, int]:
        """
        Get current error counts.
        
        Returns:
            Dictionary of error counts
        """
        return self.error_counts.copy()
    
    def get_error_summary(self) -> Dict[str, Any]:
        """
        Get a summary of error statistics.
        
        Returns:
            Dictionary with error statistics
        """
        total_errors = len(self.error_history)
        errors_by_severity = {
            severity.name: len([e for e in self.error_history if e.severity == severity])
            for severity in ErrorSeverity
        }
        
        errors_by_component = {}
        for error in self.error_history:
            component = error.component
            if component not in errors_by_component:
                errors_by_component[component] = 0
            errors_by_component[component] += 1
        
        return {
            "total_errors": total_errors,
            "errors_by_severity": errors_by_severity,
            "errors_by_component": errors_by_component,
            "current_error_counts": self.error_counts
        }
    
    async def close(self) -> None:
        """Close the error handler and clean up resources."""
        await self.http_client.aclose()
        logger.info("ErrorHandler closed") 