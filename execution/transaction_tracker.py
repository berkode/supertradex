import logging
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
from threading import RLock
import sqlite3  

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("TransactionTracker")

# Database configuration
DB_FILE = "transactions.db"

class TransactionStatus(Enum):
    """Enum to represent the status of a transaction."""
    PENDING = "Pending"
    SUCCESS = "Success"
    FAILURE = "Failure"
    CANCELLED = "Cancelled"

class Transaction:
    """Class representing a transaction."""
    def __init__(self, transaction_id: str, symbol: str, action: str, quantity: float, price: float):
        self.transaction_id = transaction_id
        self.symbol = symbol
        self.action = action  # e.g., "Buy" or "Sell"
        self.quantity = quantity
        self.price = price
        self.timestamp = datetime.now()
        self.status = TransactionStatus.PENDING
        self.error_message: Optional[str] = None

    def mark_success(self):
        self.status = TransactionStatus.SUCCESS
        logger.info(f"Transaction {self.transaction_id} marked as SUCCESS.")

    def mark_failure(self, error_message: str):
        self.status = TransactionStatus.FAILURE
        self.error_message = error_message
        logger.error(f"Transaction {self.transaction_id} marked as FAILURE: {error_message}")

    def mark_cancelled(self):
        self.status = TransactionStatus.CANCELLED
        logger.warning(f"Transaction {self.transaction_id} marked as CANCELLED.")

    def to_dict(self):
        """Convert transaction to a dictionary for database storage."""
        return {
            "transaction_id": self.transaction_id,
            "symbol": self.symbol,
            "action": self.action,
            "quantity": self.quantity,
            "price": self.price,
            "timestamp": self.timestamp.isoformat(),
            "status": self.status.value,
            "error_message": self.error_message,
        }

    @staticmethod
    def from_dict(data: dict) -> "Transaction":
        """Reconstruct a transaction object from a dictionary."""
        transaction = Transaction(
            transaction_id=data["transaction_id"],
            symbol=data["symbol"],
            action=data["action"],
            quantity=data["quantity"],
            price=data["price"],
        )
        transaction.timestamp = datetime.fromisoformat(data["timestamp"])
        transaction.status = TransactionStatus(data["status"])
        transaction.error_message = data.get("error_message")
        return transaction

class TransactionTracker:
    """Class to manage and track transactions."""
    def __init__(self):
        self.transactions: Dict[str, Transaction] = {}
        self.lock = RLock()
        self._initialize_db()

    def _initialize_db(self):
        """Initialize the SQLite database for transaction tracking."""
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    transaction_id TEXT PRIMARY KEY,
                    symbol TEXT,
                    action TEXT,
                    quantity REAL,
                    price REAL,
                    timestamp TEXT,
                    status TEXT,
                    error_message TEXT
                )
            """)
            conn.commit()
        logger.info("Transaction database initialized.")

    def _save_to_db(self, transaction: Transaction):
        """Save a transaction to the database."""
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO transactions (
                    transaction_id, symbol, action, quantity, price, timestamp, status, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                transaction.transaction_id,
                transaction.symbol,
                transaction.action,
                transaction.quantity,
                transaction.price,
                transaction.timestamp.isoformat(),
                transaction.status.value,
                transaction.error_message,
            ))
            conn.commit()

    def add_transaction(self, transaction: Transaction):
        """Add a new transaction to the tracker."""
        with self.lock:
            if transaction.transaction_id in self.transactions:
                logger.warning(f"Transaction ID {transaction.transaction_id} already exists. Overwriting.")
            self.transactions[transaction.transaction_id] = transaction
            self._save_to_db(transaction)
            logger.info(f"Transaction {transaction.transaction_id} added to tracker.")

    def get_transaction(self, transaction_id: str) -> Optional[Transaction]:
        """Retrieve a transaction by its ID."""
        with self.lock:
            if transaction_id in self.transactions:
                return self.transactions[transaction_id]

            # Check database if not in memory
            with sqlite3.connect(DB_FILE) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM transactions WHERE transaction_id = ?", (transaction_id,))
                row = cursor.fetchone()
                if row:
                    data = dict(zip([col[0] for col in cursor.description], row))
                    transaction = Transaction.from_dict(data)
                    self.transactions[transaction.transaction_id] = transaction
                    return transaction
        logger.error(f"Transaction ID {transaction_id} not found.")
        return None

    def list_transactions(self, status: TransactionStatus = None) -> List[Transaction]:
        """List all transactions, optionally filtered by status."""
        with self.lock:
            transactions = list(self.transactions.values())
            if status:
                transactions = [txn for txn in transactions if txn.status == status]

            # Include transactions from database not yet in memory
            with sqlite3.connect(DB_FILE) as conn:
                cursor = conn.cursor()
                query = "SELECT * FROM transactions"
                if status:
                    query += " WHERE status = ?"
                    cursor.execute(query, (status.value,))
                else:
                    cursor.execute(query)
                rows = cursor.fetchall()
                for row in rows:
                    data = dict(zip([col[0] for col in cursor.description], row))
                    if data["transaction_id"] not in self.transactions:
                        transaction = Transaction.from_dict(data)
                        self.transactions[transaction.transaction_id] = transaction
                        transactions.append(transaction)
            return transactions

    def update_status(self, transaction_id: str, status: TransactionStatus, error_message: str = None):
        """Update the status of a transaction."""
        transaction = self.get_transaction(transaction_id)
        if not transaction:
            logger.error(f"Transaction ID {transaction_id} not found in tracker.")
            return
        with self.lock:
            if status == TransactionStatus.SUCCESS:
                transaction.mark_success()
            elif status == TransactionStatus.FAILURE:
                transaction.mark_failure(error_message)
            elif status == TransactionStatus.CANCELLED:
                transaction.mark_cancelled()
            else:
                logger.warning(f"Unknown status update for Transaction ID {transaction_id}: {status}")
            self._save_to_db(transaction)

    def __repr__(self):
        return f"TransactionTracker(transactions={list(self.transactions.keys())})"
