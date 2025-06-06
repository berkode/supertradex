import os
import logging
import json
import asyncio
import sqlite3
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from typing import Dict, List, Optional, AsyncGenerator, Set, Any, TYPE_CHECKING
from config.settings import Settings
from utils.logger import get_logger
from data.models import Base, Token, Trade, Alert, Position, Order, PaperPosition, PaperWalletSummary
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text, update, delete
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import and_, or_, exists
from sqlalchemy.sql import func

# Get logger for this module
logger = get_logger(__name__)

# Add a custom JSON encoder that can handle datetime objects
class DateTimeEncoder(json.JSONEncoder):
    """JSON Encoder that handles datetime objects by converting them to ISO format strings."""
    def default(self, obj):
        if isinstance(obj, datetime): # Assuming datetime refers to datetime.datetime or is correctly scoped
            return obj.isoformat()
        return super().default(obj)

# Custom JSON serializer for SQLAlchemy
def json_serializer(obj):
    """Custom JSON serializer that handles datetime objects"""
    return json.dumps(obj, cls=DateTimeEncoder)

# Custom JSON deserializer for SQLAlchemy
def json_deserializer(s):
    """Custom JSON deserializer for SQLAlchemy"""
    return json.loads(s)

class TokenDatabase:
    """
    Manages token data storage and retrieval using SQLAlchemy sessions
    bound to a dedicated engine. Table creation is handled externally.
    """

    @classmethod
    async def create(cls, db_path: str, settings: Settings) -> 'TokenDatabase':
        """Create a new database instance."""
        instance = cls(db_path, settings)
        await instance.initialize()
        return instance

    def __init__(self, db_path: str, settings: Settings):
        """Initialize the database with the given path."""
        self.logger = get_logger(__name__)
        self.settings = settings
        
        # Convert to Path object and ensure it's absolute
        self.db_path = Path(db_path).resolve()
        
        # Create parent directory if it doesn't exist
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Create SQLAlchemy engine with proper URL format
        db_url = f'sqlite+aiosqlite:///{self.db_path}'
        self.logger.info(f"Initializing database with URL: {db_url}")
        
        self.engine = create_async_engine(
            db_url, 
            echo=False,  # Set to True for debugging SQL queries
            json_serializer=json_serializer,
            json_deserializer=json_deserializer
        )
        self.session_factory = sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        self.lock = asyncio.Lock()  # Add lock for thread safety
        
    async def initialize(self) -> bool:
        """Initialize the database by creating tables and testing connection."""
        try:
            # Create tables (only if they don't exist)
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            self.logger.info(f"Ensured all database tables exist")
            
            # Test connection
            session = await self._get_session()
            async with session:
                # Try to query the database
                result = await session.execute(text("SELECT 1"))
                if result.scalar() == 1:
                    self.logger.info("Database connection test successful")
                    return True
                else:
                    self.logger.error("Database connection test failed")
                    return False
                    
        except Exception as e:
            self.logger.error(f"Error initializing database: {e}")
            return False

    def create_tables(self):
        """Create all database tables."""
        try:
            # Drop all tables first
            Base.metadata.drop_all(self.engine)
            self.logger.info("Dropped all existing tables")
            
            # Create all tables
            Base.metadata.create_all(self.engine)
            self.logger.info("Created all database tables successfully")
        except Exception as e:
            self.logger.error(f"Error creating database tables: {e}", exc_info=True)
            raise

    async def close(self):
        """Close the database connection safely."""
        # Check if Session factory exists, not async_session instance attribute
        if not hasattr(self, 'session_factory') or self.session_factory is None:
            logger.info(f"Database session factory already None for {self.db_path}. Assuming closed.")
            return

        # session_instance = self.async_session() # Don't need instance here

        try:
            # Scoped sessions are typically managed by the sessionmaker/scope, 
            # removing the factory reference might be enough.
            # Explicitly removing is often done at the application scope level.
            # session_instance.remove() # Commenting out direct removal
            logger.debug(f"SQLAlchemy session factory cleanup for {self.db_path}.")

            # Dispose the engine associated with this instance
            if hasattr(self, 'engine') and self.engine is not None:
                await self.engine.dispose() # Use await for async dispose
                logger.info(f"SQLAlchemy engine disposed for {self.db_path}")
            else:
                logger.warning(f"No engine found or engine already disposed for {self.db_path}.")

        except Exception as e:
            logger.error(f"Error closing database session/engine for {self.db_path}: {e}", exc_info=True)
        finally:
            # Ensure factory and engine attributes are set to None regardless of errors
            self.session_factory = None # Set factory to None
            if hasattr(self, 'engine'):
                 self.engine = None
            logger.info(f"Database connection cleanup finalized for {self.db_path}")

    # --- Data Access Methods ---
    # Ensure methods consistently use self.session_factory()

    async def _get_session(self) -> AsyncSession:
        """Get a database session.
        
        Returns:
            AsyncSession: A new AsyncSession that can be used as a context manager
        
        Raises:
            RuntimeError: If the database is not initialized
        """
        if not self.session_factory:
            raise RuntimeError("Database not initialized. Call initialize() first.")
            
        session = self.session_factory()
        return session  # Return the session directly - it already supports async context manager protocol

    async def get_tokens_list(self, filters: Optional[Dict] = None) -> List[Token]:
        """Get tokens from database matching optional filters."""
        session = await self._get_session()
        async with session as session:
            try:
                stmt = select(Token)
                if filters:
                    for key, value in filters.items():
                        if hasattr(Token, key):
                            stmt = stmt.filter(getattr(Token, key) == value)
                        else:
                            self.logger.warning(f"Attempted to filter by invalid column: {key}")
                
                result = await session.execute(stmt)
                tokens = result.scalars().all()
                return list(tokens)
            except SQLAlchemyError as e:
                self.logger.error(f"SQLAlchemyError getting tokens list: {e}", exc_info=True)
                return []
            except Exception as e:
                self.logger.error(f"Unexpected error getting tokens list: {e}", exc_info=True)
                return []

    async def save_token(self, token_data: Dict) -> bool:
        """Save or update a token in the database using SQLAlchemy sessions."""
        async with self.lock:
            session = await self._get_session() # Get session with await
            async with session as session: # Use session as context manager
                async with session.begin(): # Use begin() for transaction
                    try:
                        # Check if token exists
                        stmt = select(Token).filter_by(mint=token_data.get('mint'))
                        result = await session.execute(stmt)
                        existing_token = result.scalars().first()

                        if existing_token:
                            # Update existing token
                            for key, value in token_data.items():
                                if hasattr(existing_token, key):
                                    # Ensure that complex objects like JSON are handled correctly
                                    if isinstance(getattr(existing_token, key), dict) and isinstance(value, dict):
                                        # Merge dictionaries for JSON fields if needed, or replace
                                        current_json_val = getattr(existing_token, key)
                                        current_json_val.update(value) # Example: simple update
                                        setattr(existing_token, key, current_json_val)
                                    else:
                                        setattr(existing_token, key, value)
                            existing_token.last_updated = datetime.now(timezone.utc)
                            self.logger.debug(f"Updating token: {token_data.get('mint')}")
                        else:
                            # Create new token model instance
                            token_data['last_updated'] = token_data.get('last_updated', datetime.now(timezone.utc))
                            new_token = Token(**token_data)
                            session.add(new_token)
                            self.logger.debug(f"Adding new token: {token_data.get('mint')}")
                        return True
                    except SQLAlchemyError as e: # Catch specific SQLAlchemy errors
                        self.logger.error(f"SQLAlchemyError saving token {token_data.get('mint')}: {str(e)}", exc_info=True)
                        return False

    async def get_valid_tokens(self) -> List[Token]:
        """Get all valid tokens (is_valid == True) from the database, returning Token objects."""
        session = await self._get_session()
        async with session as session:
            try:
                # Use is_(True) instead of == True for proper boolean comparison in SQLite
                stmt = select(Token).filter(Token.is_valid.is_(True))
                result = await session.execute(stmt)
                tokens = result.scalars().all()
                self.logger.debug(f"Found {len(tokens)} valid tokens")
                return list(tokens)
            except SQLAlchemyError as e:
                self.logger.error(f"SQLAlchemyError getting valid tokens: {e}", exc_info=True)
                return []
            except Exception as e:
                self.logger.error(f"Error getting valid tokens: {e}", exc_info=True)
                return []

    # --- Trade / Position / Order Methods ---
    # Ensure these use async lock and self.session_factory()
    
    async def add_trade(self, trade_data: Dict) -> Optional[Trade]:
        """Adds a new trade record to the database."""
        async with self.lock:
            session = await self._get_session()
            async with session as session: # Use async with for session
                async with session.begin():
                    try:
                        # Ensure required fields or add defaults
                        trade_data.setdefault('created_at', datetime.now(timezone.utc))
                        trade_data.setdefault('last_updated', datetime.now(timezone.utc))
                        
                        new_trade = Trade(**trade_data)
                        session.add(new_trade)
                        # await session.flush() # Flush to get ID before commit if needed elsewhere, but refresh works after commit
                        self.logger.info(f"Added trade record for token {trade_data.get('token_mint_address')}, awaiting commit...")
                        # Commit is handled by session.begin()
                        # Refresh to get generated ID and other defaults after commit
                        # Need to commit before refresh if ID is auto-incremented by DB directly.
                        # If using await session.flush(), then await session.refresh(new_trade) can be used before commit.
                        # For now, assume commit happens and then we can fetch it if needed, or rely on return of ID.
                        # The method should ideally return the ID or the created object.
                        # Pydantic models might not automatically pick up DB-generated IDs without refresh.
                        # Let's try to refresh *after* the implicit commit from session.begin()
                        # This part is tricky with SQLAlchemy async.
                        # A common pattern is to commit, then query for the item if its ID is needed immediately.
                        # Or, if Trade model has an auto-incrementing ID, it might be populated after add+flush.
                        
                        # To get the ID after commit:
                        # We will commit, then if successful, the new_trade object might be populated
                        # if the session configuration allows it (expire_on_commit=False helps).
                        # Let's rely on 'expire_on_commit=False' and see if new_trade.id is populated.
                    except SQLAlchemyError as e:
                        self.logger.error(f"SQLAlchemyError adding trade: {e}", exc_info=True)
                        return None
                    except Exception as e:
                        self.logger.error(f"Unexpected error adding trade: {e}", exc_info=True)
                        return None
                
                # After commit, try to refresh to get DB-generated values like ID
                if new_trade and session.is_active: # Check if session is still usable
                    try:
                        await session.refresh(new_trade)
                        self.logger.info(f"Trade record ID: {new_trade.id} for token {trade_data.get('token_mint_address')} committed and refreshed.")
                        return new_trade
                    except Exception as e:
                        self.logger.error(f"Error refreshing trade after commit: {e}", exc_info=True)
                        # Return the object anyway, ID might be missing or stale
                        return new_trade 
                elif new_trade: # If session not active but trade object exists
                    self.logger.warning(f"Trade object created but session not active for refresh. ID: {new_trade.id if hasattr(new_trade, 'id') else 'Unknown'}")
                    return new_trade
                return None

    async def update_trade_status(self, trade_id: int, new_status: str, transaction_hash: Optional[str] = None, notes: Optional[str] = None, details: Optional[Dict] = None) -> bool:
        """Updates the status and optional details of a specific trade."""
        async with self.lock:
            session = await self._get_session()
            async with session as session:
                try:
                    async with session.begin():
                        stmt = select(Trade).filter(Trade.id == trade_id)
                        result = await session.execute(stmt)
                        trade = result.scalars().first()
                        
                        if trade:
                            trade.status = new_status
                            if transaction_hash:
                                trade.transaction_hash = transaction_hash
                            
                            # Handle notes: append if new notes are provided
                            if notes:
                                if trade.notes:
                                    trade.notes += f"\n{notes}"
                                else:
                                    trade.notes = notes
                            
                            # Handle details: store as JSON. If existing details, merge.
                            if details:
                                if isinstance(trade.details, dict):
                                    trade.details.update(details)
                                else: # If trade.details is None or not a dict, replace it
                                    trade.details = details
                                    
                            trade.last_updated = datetime.now(timezone.utc)
                            # session.add(trade) # Not strictly necessary if trade is already in session and modified
                            self.logger.info(f"Updating trade {trade_id} to status {new_status}")
                            # Commit handled by session.begin()
                            return True
                        else:
                            self.logger.warning(f"Trade with ID {trade_id} not found for status update.")
                            return False
                except SQLAlchemyError as e:
                    self.logger.error(f"SQLAlchemyError updating trade status for {trade_id}: {e}", exc_info=True)
                    return False
                except Exception as e:
                    self.logger.error(f"Unexpected error updating trade status for {trade_id}: {e}", exc_info=True)
                    return False

    async def get_pending_trades(self) -> List[Trade]:
        """Fetch all trades with 'pending' or 'submitted' status."""
        session = await self._get_session()
        async with session as session:
            try:
                stmt = (
                    select(Trade)
                    .filter(or_(Trade.status == 'pending', Trade.status == 'submitted'))
                    .order_by(Trade.created_at)
                )
                result = await session.execute(stmt)
                trades = result.scalars().all()
                return list(trades) # Ensure it's a list
            except SQLAlchemyError as e:
                self.logger.error(f"SQLAlchemyError fetching pending trades: {e}", exc_info=True)
                return []
            except Exception as e:
                self.logger.error(f"Unexpected error fetching pending trades: {e}", exc_info=True)
                return []

    async def fetch_active_positions(self) -> List[Dict]:
        """Fetch all active positions (amount > 0). Returns as list of dicts."""
        session = await self._get_session()
        async with session as session:
            try:
                stmt = select(Position).filter(Position.amount > 0)
                result = await session.execute(stmt)
                positions = result.scalars().all()
                # Convert Position objects to dictionaries
                return [
                    {c.name: getattr(pos, c.name) for c in pos.__table__.columns}
                    for pos in positions
                ]
            except SQLAlchemyError as e:
                self.logger.error(f"SQLAlchemyError fetching active positions: {e}", exc_info=True)
                return []
            except Exception as e:
                self.logger.error(f"Unexpected error fetching active positions: {e}", exc_info=True)
                return []

    async def fetch_active_orders(self) -> List[Dict]:
        """Fetch all active orders (status not 'completed', 'failed', 'cancelled', 'paper_completed'). Returns as list of dicts."""
        session = await self._get_session()
        async with session as session:
            try:
                inactive_statuses = ['completed', 'failed', 'cancelled', 'paper_completed']
                stmt = select(Order).filter(not_(Order.status.in_(inactive_statuses)))
                result = await session.execute(stmt)
                orders = result.scalars().all()
                # Convert Order objects to dictionaries
                return [
                    {c.name: getattr(order, c.name) for c in order.__table__.columns}
                    for order in orders
                ]
            except SQLAlchemyError as e:
                self.logger.error(f"SQLAlchemyError fetching active orders: {e}", exc_info=True)
                return []
            except Exception as e:
                self.logger.error(f"Unexpected error fetching active orders: {e}", exc_info=True)
                return []

    async def update_position_from_trade(self, trade: Trade) -> bool:
        """Updates or creates a position based on a completed trade."""
        if not trade or trade.status not in ['confirmed', 'paper_completed']:
            self.logger.warning(f"Cannot update position from trade {trade.id if trade else 'None'}, status is not 'confirmed' or 'paper_completed'.")
            return False

        async with self.lock:
            session = await self._get_session()
            async with session as session:
                async with session.begin():
                    try:
                        token_address = None
                        quantity_change = 0
                        # Determine token, quantity, and cost based on trade type (BUY/SELL)
                        # This assumes input_token_mint/output_token_mint and input_amount/output_amount are populated
                        
                        # If it's a BUY for a token (input is quote, output is base)
                        if trade.output_token_mint and trade.output_token_mint != self.settings.SOL_MINT: # Assuming SOL_MINT is available in settings or globally
                            token_address = trade.output_token_mint
                            quantity_change = trade.output_amount  # Amount of token received
                            cost_change = trade.input_amount    # Amount of quote currency spent
                            is_buy = True
                        # If it's a SELL of a token (input is base, output is quote)
                        elif trade.input_token_mint and trade.input_token_mint != self.settings.SOL_MINT:
                            token_address = trade.input_token_mint
                            quantity_change = -trade.input_amount # Amount of token sold (negative)
                            cost_change = -trade.output_amount   # Amount of quote currency received (negative cost impact)
                            is_buy = False
                        else:
                            self.logger.warning(f"Trade {trade.id} is not a clear buy/sell of a non-SOL token. Skipping position update.")
                            return False

                        if not token_address or quantity_change == 0:
                            self.logger.warning(f"Could not determine token address or quantity change for trade {trade.id}. Skipping position update.")
                            return False

                        stmt = select(Position).filter_by(token_address=token_address, user_id=trade.user_id) # Assuming user_id on trade
                        result = await session.execute(stmt)
                        position = result.scalars().first()

                        if position:
                            self.logger.info(f"Updating existing position for {token_address}, User ID: {trade.user_id}")
                            new_quantity = position.quantity + quantity_change
                            
                            if new_quantity < 0 and not self.settings.ALLOW_SHORTING: # Add ALLOW_SHORTING to settings if needed
                                self.logger.warning(f"Trade {trade.id} would result in a short position for {token_address} which is not allowed. Clamping quantity to 0.")
                                quantity_sold_actually = position.quantity # Sell only what's available
                                # Adjust cost based on actual quantity sold if clamping
                                if position.quantity > 0 and quantity_change < 0: # It was a sell
                                    cost_change_adjusted = (cost_change / quantity_change) * quantity_sold_actually if quantity_change != 0 else 0
                                else:
                                    cost_change_adjusted = cost_change
                                
                                quantity_change = -position.quantity # The actual change is selling all current holdings
                                cost_change = cost_change_adjusted
                                new_quantity = 0

                            if new_quantity == 0: # Position closed
                                position.average_entry_price = 0
                                position.total_cost = 0
                            elif is_buy: # Buying or adding to position
                                position.total_cost = (position.total_cost or 0) + cost_change
                                position.average_entry_price = position.total_cost / new_quantity if new_quantity else 0
                            else: # Selling from position
                                # Cost basis reduction is proportional to the quantity sold
                                if position.quantity > 0: # Ensure there was a position to sell from
                                    reduction_ratio = abs(quantity_change) / position.quantity if position.quantity != 0 else 0
                                    position.total_cost = (position.total_cost or 0) * (1 - reduction_ratio)
                                    # Average entry price remains the same unless all sold
                                else: # Selling when quantity was already zero (should have been caught by new_quantity < 0)
                                    position.total_cost = 0
                                    position.average_entry_price = 0

                            position.quantity = new_quantity
                            position.last_updated = datetime.now(timezone.utc)
                        else: # New position
                            if quantity_change < 0 and not self.settings.ALLOW_SHORTING:
                                self.logger.warning(f"Attempting to open a short position for {token_address} which is not allowed. Skipping.")
                                return False
                                
                            self.logger.info(f"Creating new position for {token_address}, User ID: {trade.user_id}")
                            position = Position(
                                user_id=trade.user_id,
                                token_address=token_address,
                                quantity=quantity_change,
                                average_entry_price=(cost_change / quantity_change) if quantity_change != 0 else 0,
                                total_cost=cost_change,
                                last_updated=datetime.now(timezone.utc)
                            )
                            session.add(position)
                        
                        self.logger.info(f"Position for {token_address} updated. New Qty: {position.quantity}, Avg Price: {position.average_entry_price}, Total Cost: {position.total_cost}")
                        return True

                    except SQLAlchemyError as e:
                        self.logger.error(f"SQLAlchemyError updating position from trade {trade.id}: {e}", exc_info=True)
                        return False
                    except Exception as e:
                        self.logger.error(f"Unexpected error updating position from trade {trade.id}: {e}", exc_info=True)
                        return False

    # Add other necessary methods like:
    # async def get_token_by_mint(self, mint_address: str) -> Optional[Token]: ...
    # async def get_trade_by_id(self, trade_id: int) -> Optional[Trade]: ...
    # async def get_token_price_history(self, mint_address: str, limit: int = 100) -> List[Dict]: ...
    # async def get_portfolio_value(self) -> float: ...
    # async def get_daily_pnl(self) -> List[float]: ...
    # ... etc.

    # --- Methods from old structure needing integration or removal ---

    # Record migrations (adjust to use self.session_factory)
    async def record_migrations(self, mint: str, migrations: List[Dict]):
        """Records migrations for a given token. Assumes 'migrations' is a JSON field on Token model."""
        async with self.lock:
            session = await self._get_session()
            async with session as session:
                async with session.begin():
                    try:
                        stmt = select(Token).filter_by(mint=mint) # Assuming mint is the identifier
                        result = await session.execute(stmt)
                        token = result.scalars().first()
                        
                        if token:
                            current_migrations = token.migrations if isinstance(token.migrations, list) else []
                            # If token.migrations was stored as a JSON string, it needs to be loaded first.
                            # For this example, let's assume Token.migrations is a mutable JSON type like JSONB 
                            # or it's handled by SQLAlchemy to be a Python list/dict directly.
                            # If it's a plain string, it would be: 
                            # current_migrations = json.loads(token.migrations) if token.migrations else []
                            
                            current_migrations.extend(migrations)
                            token.migrations = current_migrations # Assign back if mutable, or re-serialize if string
                            token.last_updated = datetime.now(timezone.utc)
                            # session.add(token) # Not strictly needed if token is in session & modified
                            self.logger.info(f"Recorded {len(migrations)} migrations for token {mint}")
                            return True
                        else:
                            self.logger.warning(f"Token {mint} not found for recording migrations.")
                            return False
                    except SQLAlchemyError as e:
                        self.logger.error(f"SQLAlchemyError recording migrations for {mint}: {e}", exc_info=True)
                        return False # Rollback handled by session.begin()
                    except Exception as e:
                        self.logger.error(f"Unexpected error recording migrations for {mint}: {e}", exc_info=True)
                        return False

    # Get platform history (requires defining how platform history is stored - maybe in TokenModel?)
    async def get_token_platform_history(self, mint: str) -> List[Dict]:
        """Get platform history for a token. Assumes 'platform_history' is a JSON field on Token model."""
        session = await self._get_session()
        async with session as session:
            try:
                stmt = select(Token.platform_history).filter_by(mint=mint)
                result = await session.execute(stmt)
                platform_history_data = result.scalars().first()
                
                if platform_history_data:
                    # If platform_history is stored as a JSON string: 
                    # return json.loads(platform_history_data) if isinstance(platform_history_data, str) else platform_history_data
                    # If it's already a Python dict/list (e.g. from JSONB type):
                    return platform_history_data if isinstance(platform_history_data, list) else []
                else:
                    self.logger.debug(f"No platform history found or token not found for mint {mint}")
                    return []
            except SQLAlchemyError as e:
                self.logger.error(f"SQLAlchemyError getting platform history for {mint}: {e}", exc_info=True)
                return []
            except Exception as e:
                self.logger.error(f"Unexpected error getting platform history for {mint}: {e}", exc_info=True)
                return []

    # Get token details (adjust to use self.session_factory and return model or dict)
    async def get_token(self, mint: str) -> Optional[Token]:
        """Fetch a single token by its mint address."""
        session = await self._get_session()
        async with session as session:
            try:
                stmt = select(Token).filter_by(mint=mint)
                result = await session.execute(stmt)
                token = result.scalars().first()
                return token
            except SQLAlchemyError as e:
                self.logger.error(f"SQLAlchemyError fetching token {mint}: {e}", exc_info=True)
                return None
            except Exception as e:
                self.logger.error(f"Unexpected error fetching token {mint}: {e}", exc_info=True)
                return None

    # Add potentially missing imports or models if needed
    async def get_token_market_data(self, mint: str) -> Optional[Dict]:
        """Get market data for a token.
        
        Args:
            mint: The token's mint address
            
        Returns:
            Optional[Dict]: Market data if available, None otherwise
        """
        self.logger.warning(f"get_token_market_data called for {mint}, but is only a placeholder.")
        return None

    # --- Platform Tracking Methods ---

    async def update_token_platforms(self, mint: str, platforms: List[Dict]):
        """Placeholder: Updates the platform information for a token."""
        # TODO: Implement actual database update logic.
        # This might involve updating a JSON field in the TokenModel or a separate PlatformStatus table.
        async with self.lock:
            session = await self._get_session()
            async with session as session:
                try:
                    self.logger.info(f"Placeholder: update_token_platforms called for mint: {mint}")
                    self.logger.info(f"Platforms data received: {json.dumps(platforms, indent=2)}")
                    # Example (Conceptual - Adapt to your actual model):
                    # token = session.query(Token).filter(Token.mint == mint).first()
                    # if token:
                    #     token.platform_data = json.dumps(platforms) # Assuming a JSON field
                    #     token.last_updated = datetime.now(timezone.utc)
                    #     session.commit()
                    #     self.logger.info(f"(Conceptual) Updated platform data for {mint}")
                    # else:
                    #     self.logger.warning(f"Token {mint} not found to update platforms.")
                except Exception as e:
                    self.logger.error(f"Error in placeholder update_token_platforms for {mint}: {e}", exc_info=True)
                    await session.rollback()
                finally:
                    await session.close()
                
    async def record_platform_migrations(self, mint: str, migrations: List[Dict]):
        """Placeholder: Records detected platform migrations."""
        # TODO: Implement actual database update logic.
        # This might involve a separate MigrationEvent table.
        async with self.lock:
            session = await self._get_session()
            try:
                self.logger.info(f"Placeholder: record_platform_migrations called for mint: {mint}")
                self.logger.info(f"Migrations data received: {json.dumps(migrations, indent=2)}")
                # Example (Conceptual):
                # for migration in migrations:
                #     new_migration = MigrationEvent(token_mint=mint, **migration)
                #     session.add(new_migration)
                # session.commit()
                # self.logger.info(f"(Conceptual) Recorded {len(migrations)} migrations for {mint}")
            except Exception as e:
                self.logger.error(f"Error in placeholder record_platform_migrations for {mint}: {e}", exc_info=True)
                await session.rollback()
            finally:
                await session.close()

    async def get_monitorable_mints(self) -> Set[str]:
        """Fetch all mint addresses that are currently being monitored (status='active')."""
        session = await self._get_session()
        async with session as session:
            try:
                stmt = select(Token.mint).filter(Token.monitoring_status == 'active')
                result = await session.execute(stmt)
                mints = result.scalars().all()
                return set(mints)
            except SQLAlchemyError as e:
                self.logger.error(f"SQLAlchemyError fetching monitorable mints: {e}", exc_info=True)
                return set()
            except Exception as e:
                self.logger.error(f"Unexpected error fetching monitorable mints: {e}", exc_info=True)
                return set()

    async def has_open_position(self, mint: str, user_id: Optional[int] = None) -> bool:
        """Check if there's an open position (quantity > 0) for a given mint and optional user_id."""
        session = await self._get_session()
        async with session as session:
            try:
                stmt = select(Position.quantity).filter_by(token_address=mint)
                if user_id: # If a user_id is provided, filter by it
                    stmt = stmt.filter_by(user_id=user_id)
                
                result = await session.execute(stmt)
                quantities = result.scalars().all() # Could be multiple positions if user_id is None and not unique by mint
                
                # Check if any position for this mint has quantity > 0
                for quantity in quantities:
                    if quantity > 0:
                        return True
                return False
            except SQLAlchemyError as e:
                self.logger.error(f"SQLAlchemyError checking open position for {mint}: {e}", exc_info=True)
                return False # Safer to assume no position on error
            except Exception as e:
                self.logger.error(f"Unexpected error checking open position for {mint}: {e}", exc_info=True)
                return False

    async def update_insert_token(self, records: List[Dict[str, Any]]):
        """Batch update or insert token records efficiently."""
        if not records:
            return

        async with self.lock:
            session = await self._get_session()  # Properly await the coroutine
            async with session as session:
                async with session.begin():
                    try:
                        mints_to_fetch = [record['mint'] for record in records if 'mint' in record]
                        existing_tokens_map = {}
                        if mints_to_fetch:
                            stmt = select(Token).filter(Token.mint.in_(mints_to_fetch))
                            result = await session.execute(stmt)
                            for token in result.scalars().all():
                                existing_tokens_map[token.mint] = token
                    
                        tokens_to_add = []
                        updated_count = 0
                        added_count = 0

                        for record in records:
                            mint = record.get('mint')
                            if not mint:
                                self.logger.warning(f"Skipping record due to missing mint: {record}")
                                continue

                            # Ensure timestamps are present
                            record.setdefault('last_updated', datetime.now(timezone.utc))

                            existing_token = existing_tokens_map.get(mint)
                            if existing_token:
                                # Update existing token
                                for key, value in record.items():
                                    if hasattr(existing_token, key):
                                        # Handle JSON fields by merging if they are dicts
                                        if key in ['metadata', 'filter_results', 'social_media_data', 'chart_data', 'rug_check_data'] and isinstance(getattr(existing_token, key), dict) and isinstance(value, dict):
                                            current_json_val = getattr(existing_token, key)
                                            if current_json_val:
                                                current_json_val.update(value)
                                                setattr(existing_token, key, current_json_val)
                                            else:
                                                setattr(existing_token, key, value) # If current is None, set directly
                                        else:
                                            setattr(existing_token, key, value)
                                # session.add(existing_token) # Mark as dirty, not strictly needed if already in session
                                updated_count += 1
                            else:
                                # Add new token
                                tokens_to_add.append(Token(**record))
                                added_count += 1
                        
                        if tokens_to_add:
                            session.add_all(tokens_to_add)
                        
                        # Commit is handled by session.begin()
                        self.logger.info(f"Token batch update/insert: {updated_count} updated, {added_count} added.")

                    except SQLAlchemyError as e:
                        self.logger.error(f"SQLAlchemyError in update_insert_token: {e}", exc_info=True)
                        # Rollback handled by session.begin()
                    except Exception as e:
                        self.logger.error(f"Unexpected error in update_insert_token: {e}", exc_info=True)
                        # Rollback handled by session.begin()

    async def update_token_filter_results(
        self, 
        mint: str, 
        filter_results: Dict,
        analysis_status: str, 
        overall_passed: bool, 
        last_filter_update: Optional[datetime] = None
    ):
        """Update token's filter results and analysis status."""
        async with self.lock:
            session = await self._get_session()
            async with session as session:
                async with session.begin():
                    try:
                        stmt = select(Token).filter_by(mint=mint)
                        result = await session.execute(stmt)
                        token = result.scalars().first()

                        if token:
                            token.filter_results = filter_results # Assuming this merges or replaces as desired
                            token.analysis_status = analysis_status
                            token.overall_filter_passed = overall_passed
                            token.last_filter_update = last_filter_update or datetime.now(timezone.utc)
                            token.last_updated = datetime.now(timezone.utc)
                            # session.add(token) # Mark as dirty
                            self.logger.debug(f"Updated filter results for token {mint}.")
                            # Commit handled by session.begin()
                            return True
                        else:
                            self.logger.warning(f"Token {mint} not found for updating filter results.")
                            return False
                    except SQLAlchemyError as e:
                        self.logger.error(f"SQLAlchemyError updating filter results for {mint}: {e}", exc_info=True)
                        return False
                    except Exception as e:
                        self.logger.error(f"Unexpected error updating filter results for {mint}: {e}", exc_info=True)
                        return False

    async def add_to_blacklist(self, mint: str, reason: str) -> bool:
        """Adds a token to the blacklist (updates its status)."""
        async with self.lock:
            session = await self._get_session()
            async with session as session:
                async with session.begin():
                    try:
                        stmt = select(Token).filter_by(mint=mint)
                        result = await session.execute(stmt)
                        token = result.scalars().first()

                        if token:
                            token.is_blacklisted = True
                            token.blacklist_reason = reason
                            token.monitoring_status = 'blacklisted' # Also update monitoring status
                            token.last_updated = datetime.now(timezone.utc)
                            # session.add(token)
                            self.logger.info(f"Token {mint} added to blacklist. Reason: {reason}")
                            return True
                        else:
                            # Optionally, create a new token entry if it doesn't exist and mark it as blacklisted
                            self.logger.warning(f"Token {mint} not found, cannot add to blacklist. Consider creating it first.")
                            # Example: Create if not found (consider if this is desired behavior)
                            # new_blacklisted_token = Token(
                            #     mint=mint,
                            #     symbol=mint[:10], # Placeholder symbol
                            #     name=f"Blacklisted: {mint[:10]}",
                            #     is_blacklisted=True,
                            #     blacklist_reason=reason,
                            #     monitoring_status='blacklisted',
                            #     created_at=datetime.now(timezone.utc),
                            #     last_updated=datetime.now(timezone.utc)
                            # )
                            # session.add(new_blacklisted_token)
                            # self.logger.info(f"New token {mint} created and added to blacklist. Reason: {reason}")
                            return False # Or True if created
                    except SQLAlchemyError as e:
                        self.logger.error(f"SQLAlchemyError adding {mint} to blacklist: {e}", exc_info=True)
                        return False
                    except Exception as e:
                        self.logger.error(f"Unexpected error adding {mint} to blacklist: {e}", exc_info=True)
                        return False

    async def remove_from_blacklist(self, mint: str) -> bool:
        """Removes a token from the blacklist (updates its status)."""
        async with self.lock:
            session = await self._get_session()
            async with session as session:
                async with session.begin():
                    try:
                        stmt = select(Token).filter_by(mint=mint)
                        result = await session.execute(stmt)
                        token = result.scalars().first()
                
                        if token:
                            token.is_blacklisted = False
                            token.blacklist_reason = None
                            # Decide what monitoring_status should be. Perhaps 'pending_review' or revert based on other fields.
                            # For now, let's set it to a neutral status that might trigger re-evaluation.
                            token.monitoring_status = 'pending_filter' 
                            token.last_updated = datetime.now(timezone.utc)
                            # session.add(token)
                            self.logger.info(f"Token {mint} removed from blacklist.")
                            return True
                        else:
                            self.logger.warning(f"Token {mint} not found, cannot remove from blacklist.")
                            return False
                    except SQLAlchemyError as e:
                        self.logger.error(f"SQLAlchemyError removing {mint} from blacklist: {e}", exc_info=True)
                        return False
                    except Exception as e:
                        self.logger.error(f"Unexpected error removing {mint} from blacklist: {e}", exc_info=True)
                        return False

    async def is_blacklisted(self, mint: str) -> bool:
        """Check if a token is currently blacklisted."""
        session = await self._get_session()
        async with session as session:
            try:
                # Correctly check for blacklist status based on is_valid and monitoring_status
                stmt = select(Token).filter_by(mint=mint).where(
                    or_(
                        Token.is_valid == False,
                        Token.monitoring_status == 'blacklisted'
                    )
                )
                result = await session.execute(stmt)
                token = result.scalars().first()
                return token is not None
            except Exception as e:
                self.logger.error(f"Unexpected error checking blacklist status for {mint}: {e}", exc_info=True)
                return False # Safer to assume not blacklisted on error, or handle as needed

    # --- NEW METHOD: Get tokens ready for monitoring ---
    async def get_tokens_ready_for_monitoring(self) -> List[Token]:
        """
        Get a list of tokens that are ready for monitoring based on specific criteria.

        Returns:
            List[Token]: A list of Token objects that meet the monitoring criteria.
        """
        session = await self._get_session()
        async with session as session:
            try:
                # Build query to fetch tokens eligible for monitoring
                stmt = select(Token).where(
                    and_(
                        Token.is_valid == True,  # Use is_valid instead of is_active
                        or_(
                            Token.monitoring_status == 'queued',  # New tokens waiting for monitoring
                            Token.monitoring_status == 'ready',   # Tokens ready to be monitored
                            Token.monitoring_status == 'waiting'  # Tokens waiting for the next monitoring cycle
                        )
                    )
                ).order_by(Token.last_updated.desc()).limit(5)  # Limit to 5 at a time to manage resources
                
                result = await session.execute(stmt)
                tokens = result.scalars().all()
                return list(tokens)
            except Exception as e:
                self.logger.error(f"Error fetching tokens ready for monitoring: {e}")
                return []

    # --- NEW METHOD: Update monitoring status ---
    async def update_token_monitoring_status(self, mint: str, status: str) -> bool:
        """Updates the monitoring_status of a specific token."""
        async with self.lock:
            session = await self._get_session()
            async with session as session:
                async with session.begin():
                    try:
                        stmt = select(Token).filter_by(mint=mint)
                        result = await session.execute(stmt)
                        token = result.scalars().first()

                        if token:
                            token.monitoring_status = status
                            token.last_updated = datetime.now(timezone.utc)
                            self.logger.info(f"Updated monitoring status for token {mint} to {status}.")
                            return True
                        else:
                            self.logger.warning(f"Token {mint} not found for updating monitoring status.")
                            return False
                    except SQLAlchemyError as e:
                        self.logger.error(f"SQLAlchemyError updating monitoring status for {mint}: {e}", exc_info=True)
                        return False
                    except Exception as e:
                        self.logger.error(f"Unexpected error updating monitoring status for {mint}: {e}", exc_info=True)
                        return False

    # --- NEW METHOD: Get tokens by monitoring status ---
    async def get_tokens_with_status(self, status: str) -> List[Token]:
        """Fetch all tokens with a specific monitoring_status."""
        session = await self._get_session()
        async with session as session:
            try:
                stmt = select(Token).filter(Token.monitoring_status == status).order_by(Token.last_updated.desc())
                result = await session.execute(stmt)
                tokens = result.scalars().all()
                return list(tokens)
            except SQLAlchemyError as e:
                self.logger.error(f"SQLAlchemyError fetching tokens with status '{status}': {e}", exc_info=True)
                return []
            except Exception as e:
                self.logger.error(f"Unexpected error fetching tokens with status '{status}': {e}", exc_info=True)
                return []

    async def get_best_token_for_trading(self, include_inactive_tokens: bool = False) -> Optional[Token]:
        """
        Selects the best token for trading based on predefined criteria.
        Can optionally include tokens not currently 'active' in monitoring.
        """
        session = await self._get_session()
        async with session as session:
            try:
                # Define base criteria for all tokens
                self.logger.debug(f"get_best_token_for_trading called with include_inactive_tokens={include_inactive_tokens}")
                stmt = (
                    select(Token)
                    .filter(Token.overall_filter_passed.is_(True))\
                    .filter(Token.volume_24h != None)\
                    .filter(Token.liquidity != None)\
                    .filter(Token.rugcheck_score != None)\
                    .filter(Token.pair_address != None) # Ensure pair_address is present
                    .filter(Token.dex_id != None)       # Ensure dex_id is present
                )
                self.logger.debug(f"Initial statement constructed: {stmt}")

                # Log count before status filter
                count_before_status_filter = await session.scalar(select(func.count()).select_from(stmt.subquery()))
                self.logger.debug(f"Tokens matching base criteria (before status filter): {count_before_status_filter}")

                if not include_inactive_tokens:
                    stmt = stmt.filter(Token.monitoring_status == 'active')
                    self.logger.debug("Applied filter: Token.monitoring_status == 'active'")
                    # Log count after status filter
                    count_after_status_filter = await session.scalar(select(func.count()).select_from(stmt.subquery()))
                    self.logger.debug(f"Tokens matching after 'active' status filter: {count_after_status_filter}")
                else:
                    self.logger.debug("Skipping monitoring_status filter as include_inactive_tokens is True.")
                # If include_inactive_tokens is True, we consider tokens with status like 'pending', 'stopped',
                # or any status that isn't explicitly excluded if we had such a concept.
                # For now, not filtering by status when include_inactive_tokens=True means we consider more candidates.

                # Get preferred DEX order from settings
                # Ensure MONITORED_PROGRAMS_LIST gives the actual program IDs, not friendly names
                preferred_dex_program_ids = self.settings.MONITORED_PROGRAMS_LIST
                self.logger.debug(f"Preferred DEX program IDs from settings: {preferred_dex_program_ids}")
                if not preferred_dex_program_ids:
                    self.logger.warning("No preferred DEXes configured in MONITORED_PROGRAMS_LIST. Cannot select best token effectively.")
                    return None # Or search all DEXes if Token.dex_id is reliable

                # Filter by preferred DEXes
                stmt = stmt.filter(Token.dex_id.in_(preferred_dex_program_ids))
                self.logger.debug(f"Applied filter: Token.dex_id.in_({preferred_dex_program_ids})")
                
                # Log count after DEX filter
                count_after_dex_filter = await session.scalar(select(func.count()).select_from(stmt.subquery()))
                self.logger.debug(f"Tokens matching after preferred DEX filter: {count_after_dex_filter}")

                # Order by criteria
                stmt = stmt.order_by(
                    Token.rugcheck_score.desc(),
                    Token.volume_24h.desc(),
                    Token.liquidity.desc(),
                    Token.last_updated.desc() # Added for tie-breaking with recent data
                )
                self.logger.debug(f"Applied ordering. Final statement: {stmt}")
                
                result = await session.execute(stmt)
                best_token = result.scalars().first()
                
                if best_token:
                    self.logger.info(
                        f"Best token for trading selected ({'including inactive' if include_inactive_tokens else 'active only'}): {best_token.mint} "
                        f"(DEX: {best_token.dex_id}, Pair: {best_token.pair_address}, "
                        f"Rug: {best_token.rugcheck_score}, "
                        f"Vol: ${best_token.volume_24h:,.2f}, "
                        f"Liq: ${best_token.liquidity:,.2f}, "
                        f"Status: {best_token.monitoring_status})"\
                    )
                    # ADDED: Log all candidates if multiple were found before picking the first one
                    all_candidates_result = await session.execute(stmt) # Re-execute without .first()
                    all_candidates = all_candidates_result.scalars().all()
                    if len(all_candidates) > 1:
                        self.logger.debug(f"Found {len(all_candidates)} candidates. Selected the first one based on ordering.")
                        for idx, cand in enumerate(all_candidates):
                            self.logger.debug(
                                f"  Candidate {idx+1}: {cand.mint}, Rug: {cand.rugcheck_score}, Vol: {cand.volume_24h}, Liq: {cand.liquidity}, LastUpdated: {cand.last_updated}"
                            )
                    elif all_candidates: # Exactly one candidate
                        self.logger.debug("Exactly one candidate found and selected.")
                    # END ADDED

                    return best_token

                self.logger.info(f"No suitable token found for trading at the moment based on current criteria ({'including inactive' if include_inactive_tokens else 'active only'}).")
                # ADDED: Log if any tokens made it past DEX filter but were then discarded (e.g., by .first() if ordering made them non-first)
                # This check is implicitly covered by the "all_candidates" logging above if no token is ultimately selected.
                # If count_after_dex_filter > 0 but best_token is None, it means no token matched all criteria or the query failed.
                if count_after_dex_filter > 0:
                    self.logger.debug(f"{count_after_dex_filter} tokens passed DEX filter, but no single 'best_token' was ultimately selected after ordering/limiting.")
                # END ADDED
                return None

            except SQLAlchemyError as e:
                self.logger.error(f"SQLAlchemyError selecting best token for trading: {e}", exc_info=True)
                return None
            except Exception as e:
                self.logger.error(f"Unexpected error selecting best token for trading: {e}", exc_info=True)
                return None

    async def get_top_tokens_for_trading(self, limit: int = 3, include_inactive_tokens: bool = False) -> List[Token]:
        """
        Selects the top N tokens for trading based on predefined criteria.
        Can optionally include tokens not currently 'active' in monitoring.
        """
        session = await self._get_session()
        async with session as session:
            try:
                # Define base criteria for all tokens
                self.logger.debug(f"get_top_tokens_for_trading called with limit={limit}, include_inactive_tokens={include_inactive_tokens}")
                stmt = (
                    select(Token)
                    .filter(Token.overall_filter_passed.is_(True))
                    .filter(Token.volume_24h != None)
                    .filter(Token.liquidity != None)
                    .filter(Token.rugcheck_score != None)
                    .filter(Token.pair_address != None)
                    .filter(Token.dex_id != None)
                )

                if not include_inactive_tokens:
                    stmt = stmt.filter(Token.monitoring_status == 'active')

                # Get preferred DEX order from settings
                preferred_dex_program_ids = self.settings.MONITORED_PROGRAMS_LIST
                if preferred_dex_program_ids:
                    stmt = stmt.filter(Token.dex_id.in_(preferred_dex_program_ids))

                # Order by criteria and limit
                stmt = stmt.order_by(
                    Token.rugcheck_score.desc(),
                    Token.volume_24h.desc(),
                    Token.liquidity.desc(),
                    Token.last_updated.desc()
                ).limit(limit)
                
                result = await session.execute(stmt)
                top_tokens = result.scalars().all()
                
                if top_tokens:
                    self.logger.info(f"Found {len(top_tokens)} top tokens for trading:")
                    for idx, token in enumerate(top_tokens, 1):
                        self.logger.info(
                            f"  {idx}. {token.mint} (DEX: {token.dex_id}, "
                            f"Rug: {token.rugcheck_score}, Vol: ${token.volume_24h:,.2f}, "
                            f"Liq: ${token.liquidity:,.2f})"
                        )
                    return list(top_tokens)

                self.logger.info(f"No suitable tokens found for trading at the moment.")
                return []

            except SQLAlchemyError as e:
                self.logger.error(f"SQLAlchemyError selecting top tokens for trading: {e}", exc_info=True)
                return []
            except Exception as e:
                self.logger.error(f"Unexpected error selecting top tokens for trading: {e}", exc_info=True)
                return []

    async def get_trades_for_token(
        self,
        mint: str, # Changed from coin_mint
        status: Optional[str] = None,
        action: Optional[str] = None, # e.g., 'BUY' or 'SELL'
        order_by_timestamp_desc: bool = False
    ) -> List[Trade]:
        """
        Fetches trades for a specific token mint, optionally filtered by status and action.
        For single-user context in paper trading, user_id filtering is handled outside.
        """
        session = await self._get_session()
        async with session as session:
            try:
                # Join with Token table to filter by mint
                stmt = select(Trade).join(Token, Trade.token_id == Token.id)\
                                    .filter(Token.mint == mint)

                if status:
                    stmt = stmt.filter(Trade.status == status)
                if action:
                    # Ensure action is compared against Trade.action
                    stmt = stmt.filter(Trade.action == action.upper()) 
                
                if order_by_timestamp_desc:
                    stmt = stmt.order_by(Trade.timestamp.desc()) # Or Trade.created_at
                else:
                    stmt = stmt.order_by(Trade.timestamp.asc()) # Or Trade.created_at

                result = await session.execute(stmt)
                trades = result.scalars().all()
                return list(trades)
            except SQLAlchemyError as e:
                self.logger.error(f"SQLAlchemyError fetching trades for token {mint}: {e}", exc_info=True)
                return []
            except Exception as e:
                self.logger.error(f"Unexpected error fetching trades for token {mint}: {e}", exc_info=True)
                return []

    # Cleanup and finalization
    async def delete_old_trades(self, days_old: int) -> int:
        """Deletes trade records older than a specified number of days."""
        async with self.lock:
            session = await self._get_session()
            async with session as session:
                async with session.begin():
                    try:
                        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_old)
                        # Assuming Trade has a 'created_at' or 'timestamp' field
                        # stmt = delete(Trade).where(Trade.created_at < cutoff_date) # If Trade.created_at exists
                        stmt = text("DELETE FROM trades WHERE created_at < :cutoff") # Using text for now
                        result = await session.execute(stmt, params={'cutoff': cutoff_date.isoformat()})
                        deleted_count = result.rowcount
                        self.logger.info(f"Deleted {deleted_count} trades older than {days_old} days.")
                        return deleted_count
                    except SQLAlchemyError as e:
                        self.logger.error(f"SQLAlchemyError deleting old trades: {e}", exc_info=True)
                        return 0
                    except Exception as e:
                        self.logger.error(f"Unexpected error deleting old trades: {e}", exc_info=True)
                        return 0

    async def vacuum_db(self):
        """Performs a VACUUM operation on the SQLite database to reclaim space."""
        async with self.lock: # VACUUM can be a blocking operation, ensure exclusive access
            try:
                # VACUUM cannot be executed within a transaction for SQLite when using SQLAlchemy's async interface directly
                # We need to get a raw connection
                async with self.engine.connect() as raw_conn:
                    await raw_conn.execute(text("VACUUM"))
                    await raw_conn.commit() # Commit the VACUUM operation
                self.logger.info("Database VACUUM operation completed successfully.")
            except SQLAlchemyError as e:
                self.logger.error(f"SQLAlchemyError during VACUUM: {e}", exc_info=True)
            except Exception as e:
                self.logger.error(f"Unexpected error during VACUUM: {e}", exc_info=True)

    # --- Paper Trading Persistence Methods ---

    async def get_paper_summary_value(self, key: str) -> Optional[Dict[str, Any]]:
        """Gets a summary value from the paper_wallet_summary table."""
        session = await self._get_session()
        async with session as session:
            try:
                stmt = select(PaperWalletSummary).filter_by(key=key)
                result = await session.execute(stmt)
                summary_entry = result.scalars().first()
                if summary_entry:
                    return {
                        "key": summary_entry.key,
                        "value_float": summary_entry.value_float,
                        "value_str": summary_entry.value_str,
                        "value_json": summary_entry.value_json,
                        "last_updated": summary_entry.last_updated
                    }
                return None
            except SQLAlchemyError as e:
                self.logger.error(f"SQLAlchemyError getting paper summary value for key {key}: {e}", exc_info=True)
                return None
            except Exception as e:
                self.logger.error(f"Unexpected error getting paper summary value for key {key}: {e}", exc_info=True)
                return None

    async def set_paper_summary_value(self, key: str, value_float: Optional[float] = None, value_str: Optional[str] = None, value_json: Optional[Dict] = None) -> bool:
        """Sets or updates a summary value in the paper_wallet_summary table."""
        async with self.lock:
            session = await self._get_session()
            async with session as session:
                async with session.begin():
                    try:
                        stmt = select(PaperWalletSummary).filter_by(key=key)
                        result = await session.execute(stmt)
                        summary_entry = result.scalars().first()

                        if summary_entry:
                            summary_entry.value_float = value_float
                            summary_entry.value_str = value_str
                            summary_entry.value_json = value_json
                            summary_entry.last_updated = datetime.now(timezone.utc)
                            self.logger.debug(f"Updating paper summary for key: {key}")
                        else:
                            summary_entry = PaperWalletSummary(
                                key=key,
                                value_float=value_float,
                                value_str=value_str,
                                value_json=value_json,
                                last_updated=datetime.now(timezone.utc)
                            )
                            session.add(summary_entry)
                            self.logger.debug(f"Adding new paper summary for key: {key}")
                        return True
                    except SQLAlchemyError as e:
                        self.logger.error(f"SQLAlchemyError setting paper summary for key {key}: {e}", exc_info=True)
                        return False
                    except Exception as e:
                        self.logger.error(f"Unexpected error setting paper summary for key {key}: {e}", exc_info=True)
                        return False

    async def get_paper_position(self, mint: str) -> Optional[PaperPosition]:
        """Gets a specific paper position by mint."""
        session = await self._get_session()
        async with session as session:
            try:
                stmt = select(PaperPosition).filter_by(mint=mint)
                result = await session.execute(stmt)
                position = result.scalars().first()
                return position
            except SQLAlchemyError as e:
                self.logger.error(f"SQLAlchemyError getting paper position for mint {mint}: {e}", exc_info=True)
                return None
            except Exception as e:
                self.logger.error(f"Unexpected error getting paper position for mint {mint}: {e}", exc_info=True)
                return None

    async def get_all_paper_positions(self) -> List[PaperPosition]:
        """Gets all stored paper positions."""
        session = await self._get_session()
        async with session as session:
            try:
                stmt = select(PaperPosition).order_by(PaperPosition.mint)
                result = await session.execute(stmt)
                positions = result.scalars().all()
                return list(positions)
            except SQLAlchemyError as e:
                self.logger.error(f"SQLAlchemyError getting all paper positions: {e}", exc_info=True)
                return []
            except Exception as e:
                self.logger.error(f"Unexpected error getting all paper positions: {e}", exc_info=True)
                return []

    async def upsert_paper_position(self, mint: str, quantity: float, total_cost_usd: float, average_price_usd: float) -> bool:
        """Updates or inserts a paper position."""
        async with self.lock:
            session = await self._get_session()
            async with session as session:
                async with session.begin():
                    try:
                        stmt = select(PaperPosition).filter_by(mint=mint)
                        result = await session.execute(stmt)
                        position = result.scalars().first()

                        if position:
                            position.quantity = quantity
                            position.total_cost_usd = total_cost_usd
                            position.average_price_usd = average_price_usd
                            position.last_updated = datetime.now(timezone.utc)
                            self.logger.debug(f"Updating paper position for mint: {mint}")
                        else:
                            position = PaperPosition(
                                mint=mint,
                                quantity=quantity,
                                total_cost_usd=total_cost_usd,
                                average_price_usd=average_price_usd,
                                last_updated=datetime.now(timezone.utc)
                            )
                            session.add(position)
                            self.logger.debug(f"Adding new paper position for mint: {mint}")
                        return True
                    except SQLAlchemyError as e:
                        self.logger.error(f"SQLAlchemyError upserting paper position for {mint}: {e}", exc_info=True)
                        return False
                    except Exception as e:
                        self.logger.error(f"Unexpected error upserting paper position for {mint}: {e}", exc_info=True)
                        return False

    async def delete_paper_position(self, mint: str) -> bool:
        """Deletes a paper position, typically when quantity is zero."""
        async with self.lock:
            session = await self._get_session()
            async with session as session:
                async with session.begin():
                    try:
                        stmt = select(PaperPosition).filter_by(mint=mint)
                        result = await session.execute(stmt)
                        position = result.scalars().first()

                        if position:
                            await session.delete(position)
                            self.logger.info(f"Deleted paper position for mint: {mint}")
                            return True
                        else:
                            self.logger.warning(f"Paper position for mint {mint} not found for deletion.")
                            return False # Or True, as it's already gone
                    except SQLAlchemyError as e:
                        self.logger.error(f"SQLAlchemyError deleting paper position for {mint}: {e}", exc_info=True)
                        return False
                    except Exception as e:
                        self.logger.error(f"Unexpected error deleting paper position for {mint}: {e}", exc_info=True)
                        return False

    # --- END Paper Trading Persistence Methods ---

    # Ensure all other methods are reviewed and made async if they interact with the DB.
    # For example, if methods like get_token_market_data, update_token_platforms etc.
    # were synchronous and did DB calls, they need conversion.

    async def get_token_data(self, mint: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves specific data fields for a token from the database.
        This method is an example and can be customized to fetch specific fields.
        """
        session = await self._get_session()
        async with session as session:
            try:
                stmt = select(Token.mint, Token.name, Token.symbol, Token.price_usd, Token.liquidity, Token.volume_24h, Token.last_updated).where(Token.mint == mint) # Changed token_address to mint
                result = await session.execute(stmt)
                token_row = result.fetchone() # Use fetchone() for a single row
                if token_row:
                    # Convert row to dictionary
                    return dict(token_row._asdict()) if hasattr(token_row, '_asdict') else dict(token_row)
                return None
            except SQLAlchemyError as e:
                self.logger.error(f"SQLAlchemyError getting token data for {mint}: {e}", exc_info=True) # Changed token_address to mint
                return None

    async def get_token_from_db(self, mint: str) -> Optional[Dict[str, Any]]:
        """Fetches a single token by its address from the database."""
        session = await self._get_session()
        async with session as session:
            try:
                stmt = select(Token).where(Token.mint == mint) # Changed token_address to mint
                result = await session.execute(stmt)
                token = result.scalars().first()
                if token:
                    # Convert SQLAlchemy model to dict (excluding non-serializable parts)
                    return {c.name: getattr(token, c.name) for c in token.__table__.columns}
                return None
            except SQLAlchemyError as e:
                self.logger.error(f"Error fetching token {mint} from DB: {e}", exc_info=True) # Changed token_address to mint
                return None
                
    async def store_token_data(self, token_data: Dict[str, Any]) -> None:
        """Stores or updates token data in the database."""
        mint_val = token_data.get('mint')
        if not mint_val:
            self.logger.error("store_token_data: 'mint' field is missing in token_data.")
            return

        session = await self._get_session()
        async with session as session:
            try:
                # Check if token exists
                stmt_select = select(Token).where(Token.mint == mint_val)
                result = await session.execute(stmt_select)
                db_token = result.scalars().first()

                if db_token:
                    # Update existing token
                    # Create a new dictionary for update values to avoid modifying original
                    update_values = {k: v for k, v in token_data.items() if hasattr(Token, k) and k != 'mint'} # Exclude mint from update values
                    update_values['last_updated'] = datetime.now(timezone.utc)
                    
                    stmt_update = update(Token).where(Token.mint == mint_val).values(**update_values)
                    await session.execute(stmt_update)
                    self.logger.debug(f"Updated token data for {mint_val} in DB.")
                else:
                    # Add new token
                    # Ensure all required fields for Token model are present or have defaults
                    token_data['created_at'] = token_data.get('created_at', datetime.now(timezone.utc))
                    token_data['last_updated'] = token_data.get('last_updated', datetime.now(timezone.utc))
                    # Filter token_data to only include columns present in the Token model
                    valid_data = {c.name: token_data.get(c.name) for c in Token.__table__.columns if c.name in token_data}
                    
                    # Ensure essential fields if not provided and no default in model
                    if 'mint' not in valid_data: valid_data['mint'] = mint_val # Should always be there
                    # Add other defaults if necessary, e.g., for boolean fields if not nullable
                    # if 'is_valid' not in valid_data: valid_data['is_valid'] = False 

                    new_token = Token(**valid_data)
                    session.add(new_token)
                    self.logger.debug(f"Stored new token data for {mint_val} in DB.")
                await session.commit()
            except SQLAlchemyError as e:
                self.logger.error(f"Error storing token data for {mint_val}: {e}", exc_info=True)
                await session.rollback()
            except Exception as e: # Catch broader exceptions
                self.logger.error(f"Unexpected error storing token data for {mint_val}: {e}", exc_info=True)
                await session.rollback()

    async def fetch_token_data(self, mint: str) -> Optional[Dict[str, Any]]:
        """
        Fetches all data for a token from the database.
        Returns a dictionary representation of the token.
        """
        session = await self._get_session()
        async with session as session:
            try:
                stmt = select(Token).where(Token.mint == mint) # Changed token_address to mint
                result = await session.execute(stmt)
                token_instance = result.scalars().first()
                if token_instance:
                    # Convert the SQLAlchemy model instance to a dictionary
                    return {column.name: getattr(token_instance, column.name) for column in Token.__table__.columns}
                else:
                    self.logger.debug(f"No token found in DB with mint: {mint}") # Changed token_address to mint
                    return None
            except SQLAlchemyError as e:
                self.logger.error(f"SQLAlchemyError fetching token data for {mint}: {e}", exc_info=True) # Changed token_address to mint
                return None
            except Exception as e:
                self.logger.error(f"Unexpected error fetching token data for {mint}: {e}", exc_info=True) # Changed token_address to mint
                return None
                
    async def get_token_by_mint(self, mint: str) -> Optional[Token]:
        """Fetch a single token by its mint address."""
        session = await self._get_session()
        async with session as session:
            try:
                stmt = select(Token).filter_by(mint=mint)
                result = await session.execute(stmt)
                token = result.scalars().first()
                return token
            except SQLAlchemyError as e:
                self.logger.error(f"SQLAlchemyError fetching token {mint}: {e}", exc_info=True)
                return None
            except Exception as e:
                self.logger.error(f"Unexpected error fetching token {mint}: {e}", exc_info=True)
                return None

    async def get_token_info(self, mint: str) -> Optional[Dict[str, Any]]:
        """
        Get comprehensive token information as a dictionary.
        This method is used by MarketData to fetch token details.
        
        Args:
            mint: Token mint address
            
        Returns:
            Optional[Dict]: Token information dictionary or None if not found
        """
        session = await self._get_session()
        async with session as session:
            try:
                stmt = select(Token).filter_by(mint=mint)
                result = await session.execute(stmt)
                token = result.scalars().first()
                
                if token:
                    # Convert SQLAlchemy model to dictionary
                    token_dict = {column.name: getattr(token, column.name) for column in Token.__table__.columns}
                    self.logger.debug(f"Retrieved token info for {mint}: {token_dict.get('symbol', 'Unknown')}")
                    return token_dict
                else:
                    self.logger.debug(f"No token info found for mint: {mint}")
                    return None
                    
            except SQLAlchemyError as e:
                self.logger.error(f"SQLAlchemyError getting token info for {mint}: {e}", exc_info=True)
                return None
            except Exception as e:
                self.logger.error(f"Unexpected error getting token info for {mint}: {e}", exc_info=True)
                return None

    async def store_token_info(self, mint: str, token_info: Dict[str, Any]) -> bool:
        """
        Store token information in the database.
        This method is used by MarketData to store processed token data.
        
        Args:
            mint: Token mint address
            token_info: Token information dictionary
            
        Returns:
            bool: True if stored successfully, False otherwise
        """
        try:
            # Add the mint to the token_info if not present
            token_info_copy = token_info.copy()
            token_info_copy['mint'] = mint
            token_info_copy['last_updated'] = datetime.now(timezone.utc)
            
            # Use the existing save_token method
            success = await self.save_token(token_info_copy)
            if success:
                self.logger.debug(f"Stored token info for {mint}: {token_info.get('symbol', 'Unknown')}")
            else:
                self.logger.warning(f"Failed to store token info for {mint}")
            return success
            
        except Exception as e:
            self.logger.error(f"Error storing token info for {mint}: {e}", exc_info=True)
            return False

    async def update_token_prices_batch(self, token_data_batch: Dict[str, Dict[str, Any]]) -> bool:
        """
        Updates specific market data fields for a batch of tokens.
        This method is designed to be called by PriceMonitor with data from DexScreener.
        It updates price_usd, price_native, liquidity, volume_24h, pair_address, dex_id,
        last_price_update_timestamp, and last_updated.
        It does NOT create new tokens if they don't exist.
        """
        if not token_data_batch:
            self.logger.info("update_token_prices_batch called with empty batch. No action taken.")
            return True

        session = await self._get_session()
        updated_count = 0
        async with session as session:
            async with session.begin():
                try:
                    for token_mint, pair_data in token_data_batch.items():
                        if not isinstance(pair_data, dict):
                            self.logger.warning(f"Skipping invalid pair_data for mint {token_mint} in batch update (not a dict): {pair_data}")
                            continue

                        fields_to_update = {
                            # "last_price_update_timestamp": datetime.now(timezone.utc), # Removed: Model uses 'last_updated'
                            "last_updated": datetime.now(timezone.utc)
                        }
                        
                        price_usd = pair_data.get("priceUsd")
                        if price_usd is not None:
                            try:
                                fields_to_update["price"] = float(price_usd) # Changed "price_usd" to "price"
                            except (ValueError, TypeError):
                                self.logger.warning(f"Could not convert priceUsd '{price_usd}' to float for {token_mint}")

                        # price_native = pair_data.get("priceNative") # Removed: Field does not exist in Token model
                        # if price_native is not None:
                        #     try:
                        #         fields_to_update["price_native"] = float(price_native)
                        #     except (ValueError, TypeError):
                        #         self.logger.warning(f"Could not convert priceNative '{price_native}' to float for {token_mint}")

                        liquidity_data = pair_data.get("liquidity", {})
                        if isinstance(liquidity_data, dict):
                            liquidity_usd = liquidity_data.get("usd")
                            if liquidity_usd is not None:
                                try:
                                    fields_to_update["liquidity"] = float(liquidity_usd) # Assumes Token model has 'liquidity'
                                except (ValueError, TypeError):
                                    self.logger.warning(f"Could not convert liquidity_usd '{liquidity_usd}' to float for {token_mint}")
                        
                        volume_data = pair_data.get("volume", {})
                        if isinstance(volume_data, dict):
                            volume_h24 = volume_data.get("h24")
                            if volume_h24 is not None:
                                try:
                                    fields_to_update["volume_24h"] = float(volume_h24) # Assumes Token model has 'volume_24h'
                                except (ValueError, TypeError):
                                    self.logger.warning(f"Could not convert volume_h24 '{volume_h24}' to float for {token_mint}")

                        if pair_data.get("pairAddress") is not None:
                            fields_to_update["pair_address"] = str(pair_data["pairAddress"])
                        
                        if pair_data.get("dexId") is not None:
                            fields_to_update["dex_id"] = str(pair_data["dexId"])

                        # Only proceed if there are actual fields to update beyond the 'last_updated' timestamp
                        # If only 'last_updated' is in fields_to_update, its length will be 1.
                        # We want to update if any other relevant field is also being updated.
                        if len(fields_to_update) > 1: # Changed from > 2 to > 1
                            stmt = (
                                update(Token)
                                .where(Token.mint == token_mint)
                                .values(**fields_to_update)
                            )
                            result = await session.execute(stmt)
                            if result.rowcount > 0:
                                updated_count += 1
                            else:
                                self.logger.debug(f"Token {token_mint} not found or no values changed during batch price update.")
                        else:
                            self.logger.debug(f"No updatable price/market fields found for {token_mint} in batch. Timestamps not updated alone.")

                    self.logger.info(f"Batch token price update: Attempted to update {len(token_data_batch)} tokens, {updated_count} were actually modified in the DB.")
                    return True
                except SQLAlchemyError as e:
                    self.logger.error(f"SQLAlchemyError during batch token price update: {e}", exc_info=True)
                    await session.rollback() # Rollback on error
                    return False
                except Exception as e:
                    self.logger.error(f"Unexpected error during batch token price update: {e}", exc_info=True)
                    await session.rollback() # Rollback on error
                    return False

    async def update_token_price(self, mint: str, price: float) -> bool:
        """
        Update the price for a single token.
        This method is called by MarketData for individual blockchain price updates.
        
        Args:
            mint: Token mint address
            price: New price value
            
        Returns:
            bool: True if updated successfully, False otherwise
        """
        session = await self._get_session()
        async with session as session:
            async with session.begin():
                try:
                    fields_to_update = {
                        "price": float(price),
                        "last_updated": datetime.now(timezone.utc)
                    }
                    
                    stmt = (
                        update(Token)
                        .where(Token.mint == mint)
                        .values(**fields_to_update)
                    )
                    result = await session.execute(stmt)
                    
                    if result.rowcount > 0:
                        self.logger.debug(f"Updated price for token {mint}: ${price}")
                        return True
                    else:
                        self.logger.debug(f"Token {mint} not found for price update.")
                        return False
                        
                except SQLAlchemyError as e:
                    self.logger.error(f"SQLAlchemyError updating token price for {mint}: {e}", exc_info=True)
                    await session.rollback()
                    return False
                except Exception as e:
                    self.logger.error(f"Unexpected error updating token price for {mint}: {e}", exc_info=True)
                    await session.rollback()
                    return False

# Example instantiation (if this file were runnable, usually done in main.py)
# async def main():
#     settings = Settings() # Load settings from .env
#     db = await TokenDatabase.create(settings.DATABASE_FILE_PATH)
#     # ... use db instance ...
#     await db.close()

# if __name__ == "__main__":
#     asyncio.run(main())

# --- End of Class ---