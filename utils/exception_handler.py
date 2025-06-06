import logging
import time
import traceback
from typing import Callable, Optional, Type

# Initialize logger
logger = logging.getLogger(__name__)
# logger.setLevel(logging.INFO) # Removed hardcoded level

# Formatter for logging
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)


class ExceptionHandler:
    """
    Centralized exception handler for managing network issues, invalid data,
    and runtime errors in a robust and scalable manner.
    """

    @staticmethod
    def handle_exception(exc: Exception, context: Optional[str] = None) -> None:
        """
        Log and handle a given exception with detailed traceback and optional context.

        Args:
            exc (Exception): The exception to handle.
            context (Optional[str]): Additional context about where the exception occurred.
        """
        context_message = f" in {context}" if context else ""
        logger.error(f"Exception occurred{context_message}: {str(exc)}")
        logger.debug("Full traceback:", exc_info=True)

    @staticmethod
    def retry_on_exception(
        retries: int = 3,
        backoff_factor: float = 0.3,
        exception_type: Type[Exception] = Exception,
        context: Optional[str] = None,
    ) -> Callable:
        """
        Decorator for retrying a function when a specific exception type occurs.

        Args:
            retries (int): Number of retries before giving up. Defaults to 3.
            backoff_factor (float): Backoff factor for exponential delay. Defaults to 0.3.
            exception_type (Type[Exception]): Exception type to catch and retry on. Defaults to `Exception`.
            context (Optional[str]): Additional context about where the retry is being applied.

        Returns:
            Callable: A decorator for retry logic.
        """
        def decorator(func: Callable) -> Callable:
            def wrapper(*args, **kwargs):
                attempt = 0
                while attempt < retries:
                    try:
                        logger.debug(f"Executing {func.__name__} with args={args}, kwargs={kwargs}")
                        return func(*args, **kwargs)
                    except exception_type as exc:
                        attempt += 1
                        wait_time = backoff_factor * (2 ** (attempt - 1))
                        logger.warning(
                            f"Attempt {attempt}/{retries} failed for {func.__name__}{f' ({context})' if context else ''}. "
                            f"Retrying in {wait_time:.2f} seconds... Exception: {exc}"
                        )
                        if attempt == retries:
                            ExceptionHandler.handle_exception(exc, context)
                            raise
                        time.sleep(wait_time)
            return wrapper
        return decorator

    @staticmethod
    def validate_and_handle(
        exception_type: Type[Exception] = Exception,
        fallback: Optional[Callable] = None,
        context: Optional[str] = None,
    ) -> Callable:
        """
        Decorator to handle exceptions for a function and optionally execute a fallback.

        Args:
            exception_type (Type[Exception]): Exception type to catch. Defaults to `Exception`.
            fallback (Optional[Callable]): Fallback function to execute if an exception occurs. Defaults to None.
            context (Optional[str]): Additional context for logging.

        Returns:
            Callable: A decorator for exception handling and fallback logic.
        """
        def decorator(func: Callable) -> Callable:
            def wrapper(*args, **kwargs):
                try:
                    logger.debug(f"Executing {func.__name__} with args={args}, kwargs={kwargs}")
                    return func(*args, **kwargs)
                except exception_type as exc:
                    ExceptionHandler.handle_exception(exc, context)
                    if fallback:
                        logger.info(f"Executing fallback for {func.__name__}{f' ({context})' if context else ''}.")
                        return fallback(*args, **kwargs)
                    raise
            return wrapper
        return decorator


