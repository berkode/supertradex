import logging
import threading
from typing import Dict, Tuple, Optional
import sqlite3

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("SlippageChecker")

# Database configuration
DB_FILE = "slippage_data.db"

class SlippageChecker:
    """
    Class to ensure trades stay within defined slippage limits.
    """
    def __init__(self, default_slippage_tolerance: float = 0.5):
        """
        Initialize the slippage checker.

        Args:
            default_slippage_tolerance (float): Default allowable slippage in percentage.
        """
        self.default_slippage_tolerance = default_slippage_tolerance  # e.g., 0.5% slippage
        self.slippage_tolerances: Dict[str, float] = {}  # Per-asset slippage tolerances
        self.lock = threading.Lock()  # Ensure thread safety
        self._initialize_database()
        logger.info("SlippageChecker initialized with default tolerance: %.2f%%", default_slippage_tolerance)

    def _initialize_database(self):
        """
        Initialize the database for tracking slippage data.
        """
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS slippage_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset TEXT,
                    expected_price REAL,
                    executed_price REAL,
                    slippage_percentage REAL,
                    within_tolerance INTEGER,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
        logger.info("Slippage database initialized.")

    def _log_to_database(self, asset: str, expected_price: float, executed_price: float,
                         slippage_percentage: float, within_tolerance: bool):
        """
        Log slippage data to the database.

        Args:
            asset (str): Asset symbol.
            expected_price (float): Expected trade price.
            executed_price (float): Actual trade price.
            slippage_percentage (float): Calculated slippage percentage.
            within_tolerance (bool): Whether the trade was within tolerance.
        """
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO slippage_records (asset, expected_price, executed_price, 
                                              slippage_percentage, within_tolerance)
                VALUES (?, ?, ?, ?, ?)
            """, (asset, expected_price, executed_price, slippage_percentage, int(within_tolerance)))
            conn.commit()
        logger.info("Slippage data logged for %s: %.2f%%", asset, slippage_percentage)

    def set_slippage_tolerance(self, asset: str, tolerance: float):
        """
        Set custom slippage tolerance for a specific asset.

        Args:
            asset (str): Asset symbol (e.g., "BTC/USD").
            tolerance (float): Slippage tolerance in percentage.
        """
        with self.lock:
            self.slippage_tolerances[asset] = tolerance
            logger.info("Set slippage tolerance for %s: %.2f%%", asset, tolerance)

    def get_slippage_tolerance(self, asset: str) -> float:
        """
        Get the slippage tolerance for a specific asset.

        Args:
            asset (str): Asset symbol.

        Returns:
            float: Slippage tolerance in percentage.
        """
        with self.lock:
            return self.slippage_tolerances.get(asset, self.default_slippage_tolerance)

    def check_slippage(self, asset: str, expected_price: float, executed_price: float) -> Tuple[bool, float]:
        """
        Check if the slippage for a trade is within the allowable limit.

        Args:
            asset (str): Asset symbol (e.g., "BTC/USD").
            expected_price (float): The price at which the trade was expected to execute.
            executed_price (float): The actual price at which the trade executed.

        Returns:
            Tuple[bool, float]: (is_within_tolerance, slippage_percentage)
        """
        if expected_price <= 0 or executed_price <= 0:
            logger.error("Invalid prices provided for slippage check: expected=%f, executed=%f",
                         expected_price, executed_price)
            return False, 0.0

        slippage_percentage = abs((executed_price - expected_price) / expected_price) * 100
        tolerance = self.get_slippage_tolerance(asset)
        is_within_tolerance = slippage_percentage <= tolerance

        self._log_to_database(asset, expected_price, executed_price, slippage_percentage, is_within_tolerance)

        if is_within_tolerance:
            logger.info(
                "Trade within slippage tolerance for %s: %.2f%% (Tolerance: %.2f%%)",
                asset, slippage_percentage, tolerance
            )
        else:
            logger.warning(
                "Trade exceeded slippage tolerance for %s: %.2f%% (Tolerance: %.2f%%)",
                asset, slippage_percentage, tolerance
            )

        return is_within_tolerance, slippage_percentage

    def report_trade_slippage(self, asset: str, expected_price: float, executed_price: float):
        """
        Log detailed slippage information for a trade.

        Args:
            asset (str): Asset symbol.
            expected_price (float): Expected trade price.
            executed_price (float): Actual trade price.
        """
        is_within_tolerance, slippage_percentage = self.check_slippage(asset, expected_price, executed_price)
        if is_within_tolerance:
            logger.info(
                "Trade executed successfully within slippage limits for %s: Expected=%.2f, Executed=%.2f, Slippage=%.2f%%",
                asset, expected_price, executed_price, slippage_percentage
            )
        else:
            logger.warning(
                "Slippage violation for %s: Expected=%.2f, Executed=%.2f, Slippage=%.2f%%. Consider revising execution strategy.",
                asset, expected_price, executed_price, slippage_percentage
            )

