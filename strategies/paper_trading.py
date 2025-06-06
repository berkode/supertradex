import logging
import asyncio # Added for potential gather in load
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from data.models import Trade, PaperPosition # Keep Trade for type hinting, PaperPosition for DB load
from config.settings import Settings
from data.token_database import TokenDatabase
from wallet.wallet_manager import WalletManager
from data.price_monitor import PriceMonitor # Added PriceMonitor import

logger = logging.getLogger(__name__)

class PaperTrading:
    def __init__(self, settings: Settings, db: TokenDatabase, wallet_manager: WalletManager, price_monitor: PriceMonitor): # Added price_monitor
        """Initialize paper trading system. Call load_persistent_state() after this."""
        self.settings = settings
        self.db = db
        self.wallet_manager = wallet_manager
        self.price_monitor = price_monitor # Store PriceMonitor
        self.logger = logger
        
        # In-memory simulated paper wallet/portfolio - initialized empty, loaded by load_persistent_state
        self.paper_sol_balance: float = 0.0 # Loaded from DB or defaulted
        self.paper_token_balances: Dict[str, float] = {} # mint -> quantity
        
        # SOL-BASED TRADING: Track cost basis in SOL (primary) and USD (secondary for display)
        self.paper_token_total_cost_sol: Dict[str, float] = {} # mint -> total_sol_spent (PRIMARY)
        self.paper_token_total_cost_usd: Dict[str, float] = {} # mint -> total_usd_spent (DISPLAY ONLY)
        
        self.logger.info("PaperTrading instance created. Call load_persistent_state() to load/initialize data.")

    async def load_persistent_state(self):
        """Loads paper trading state (SOL balance, positions) from the database."""
        self.logger.info("Loading persistent paper trading state from database...")
        try:
            # Load SOL balance
            sol_balance_data = await self.db.get_paper_summary_value('paper_sol_balance')
            if sol_balance_data and sol_balance_data.get('value_float') is not None:
                self.paper_sol_balance = sol_balance_data['value_float']
                self.logger.info(f"Loaded paper SOL balance from DB: {self.paper_sol_balance:.2f} SOL")
            else:
                self.paper_sol_balance = getattr(self.settings, 'PAPER_INITIAL_SOL_BALANCE', 1000.0)
                self.logger.info(f"No paper SOL balance in DB or invalid, defaulting to: {self.paper_sol_balance:.2f} SOL. Saving default.")
                await self.db.set_paper_summary_value('paper_sol_balance', value_float=self.paper_sol_balance)

            # Load token positions with SOL-based cost tracking
            self.paper_token_balances.clear()
            self.paper_token_total_cost_sol.clear()
            self.paper_token_total_cost_usd.clear()
            all_positions = await self.db.get_all_paper_positions()
            if all_positions:
                for pos_model in all_positions:
                    if pos_model.quantity > 1e-9: # Only load if quantity is meaningful
                        self.paper_token_balances[pos_model.mint] = pos_model.quantity
                        
                        # Load SOL cost basis (primary) - may need to calculate from USD if not stored
                        total_cost_sol = getattr(pos_model, 'total_cost_sol', None)
                        if total_cost_sol is not None:
                            self.paper_token_total_cost_sol[pos_model.mint] = total_cost_sol
                        else:
                            # Fallback: estimate SOL cost from USD cost using current SOL price
                            current_sol_price_usd = await self._get_current_sol_price_usd()
                            if current_sol_price_usd and current_sol_price_usd > 0:
                                estimated_sol_cost = pos_model.total_cost_usd / current_sol_price_usd
                                self.paper_token_total_cost_sol[pos_model.mint] = estimated_sol_cost
                                self.logger.info(f"Estimated SOL cost for {pos_model.mint}: {estimated_sol_cost:.6f} SOL from ${pos_model.total_cost_usd:.2f} USD")
                            else:
                                self.paper_token_total_cost_sol[pos_model.mint] = 0.0
                                self.logger.warning(f"Could not estimate SOL cost for {pos_model.mint}, using 0")
                        
                        # Load USD cost basis (secondary for display)
                        self.paper_token_total_cost_usd[pos_model.mint] = pos_model.total_cost_usd
                        
                self.logger.info(f"Loaded {len(self.paper_token_balances)} paper token positions from DB with SOL-based cost tracking.")
            else:
                self.logger.info("No existing paper token positions found in DB.")
            
            self.logger.info("Persistent paper trading state loaded successfully.")
            
        except Exception as e:
            self.logger.error(f"Error loading persistent paper trading state: {e}", exc_info=True)
            # Fallback to defaults if loading fails critically
            self.paper_sol_balance = getattr(self.settings, 'PAPER_INITIAL_SOL_BALANCE', 1000.0)
            self.paper_token_balances.clear()
            self.paper_token_total_cost_sol.clear()
            self.paper_token_total_cost_usd.clear()
            self.logger.warning("Fell back to default paper wallet state due to loading error.")

    async def _get_current_sol_price_usd(self) -> Optional[float]:
        """Get current SOL price in USD for conversions."""
        try:
            if self.price_monitor:
                # Use the enhanced PriceMonitor method
                sol_price = await self.price_monitor.get_sol_price()
                if sol_price and sol_price > 0:
                    return sol_price
            
            # Fallback approximate price if price monitor unavailable
            self.logger.warning("Could not get SOL price from PriceMonitor, using fallback")
            return 150.0  # Approximate fallback
            
        except Exception as e:
            self.logger.error(f"Error getting SOL price: {e}")
            return 150.0  # Fallback price

    async def execute_trade_sol(self, trade_id: int, action: str, 
                               mint: str, price_sol: float, amount: float) -> bool:
        """
        Execute a SOL-based paper trade using SOL price (PRIMARY METHOD FOR SOL-BASED TRADING).
        
        Args:
            trade_id: The ID of the existing trade record to update.
            action: 'BUY' or 'SELL'.
            mint: The mint of the token traded.
            price_sol: The simulated SOL price of execution per token.
            amount: The amount of token units traded.
            
        Returns:
            True if successful (DB update and paper wallet update), False otherwise.
        """
        action_upper = action.upper()
        if action_upper not in ['BUY', 'SELL']:
            self.logger.error(f"Invalid action '{action}' for SOL-based paper trade ID {trade_id}. Must be BUY or SELL.")
            return False

        if price_sol <= 0 or amount < 0:
            if not (action_upper == 'SELL' and amount == 0 and price_sol > 0):
                self.logger.error(f"Invalid SOL price ({price_sol}) or amount ({amount}) for SOL-based paper trade ID {trade_id}. Price must be >0. Amount must be >=0.")
                return False

        # --- SOL-BASED Wallet Transaction (In-Memory) ---
        cost_or_proceeds_sol = amount * price_sol
        original_amount_for_sell_attempt = amount
        realized_pnl_sol: Optional[float] = None
        realized_pnl_usd: Optional[float] = None

        # Get current SOL price for USD conversion (display only)
        current_sol_price_usd = await self._get_current_sol_price_usd()
        cost_or_proceeds_usd = cost_or_proceeds_sol * current_sol_price_usd if current_sol_price_usd else 0

        if action_upper == 'BUY':
            if self.paper_sol_balance < cost_or_proceeds_sol:
                self.logger.warning(f"[SOL Paper Wallet] Insufficient paper SOL balance ({self.paper_sol_balance:.6f} SOL) to buy {amount:.4f} {mint} for {cost_or_proceeds_sol:.6f} SOL. Trade ID: {trade_id}")
                return False 
            
            # Update SOL balance
            self.paper_sol_balance -= cost_or_proceeds_sol
            
            # Update token quantities and cost basis
            current_quantity = self.paper_token_balances.get(mint, 0.0)
            current_total_cost_sol = self.paper_token_total_cost_sol.get(mint, 0.0)
            current_total_cost_usd = self.paper_token_total_cost_usd.get(mint, 0.0)
            
            self.paper_token_balances[mint] = current_quantity + amount
            self.paper_token_total_cost_sol[mint] = current_total_cost_sol + cost_or_proceeds_sol  # PRIMARY
            self.paper_token_total_cost_usd[mint] = current_total_cost_usd + cost_or_proceeds_usd  # SECONDARY
            
            self.logger.info(f"[SOL Paper Wallet] BUY: {amount:.4f} {mint} at {price_sol:.8f} SOL. Cost: {cost_or_proceeds_sol:.6f} SOL (${cost_or_proceeds_usd:.2f}). New SOL bal: {self.paper_sol_balance:.6f}")

        elif action_upper == 'SELL':
            current_quantity_before_sell = self.paper_token_balances.get(mint, 0.0)
            current_total_cost_sol_before = self.paper_token_total_cost_sol.get(mint, 0.0)
            current_total_cost_usd_before = self.paper_token_total_cost_usd.get(mint, 0.0)
            avg_cost_sol_before = (current_total_cost_sol_before / current_quantity_before_sell) if current_quantity_before_sell > 1e-9 else 0
            avg_cost_usd_before = (current_total_cost_usd_before / current_quantity_before_sell) if current_quantity_before_sell > 1e-9 else 0

            if current_quantity_before_sell < amount:
                self.logger.warning(f"[SOL Paper Wallet] Insufficient paper token balance ({current_quantity_before_sell:.4f} {mint}) to sell requested {amount:.4f}. Selling available {current_quantity_before_sell:.4f}. Trade ID: {trade_id}")
                amount = current_quantity_before_sell 
            
            if amount <= 1e-9: 
                self.logger.info(f"[SOL Paper Wallet] No actual amount of {mint} to sell for trade ID {trade_id} (balance: {current_quantity_before_sell:.8f}, requested: {original_amount_for_sell_attempt:.4f}). Trade will be marked, but wallet unchanged.")
                amount = 0.0
            
            # Recalculate proceeds if amount was adjusted
            cost_or_proceeds_sol = amount * price_sol
            cost_or_proceeds_usd = cost_or_proceeds_sol * current_sol_price_usd if current_sol_price_usd else 0
            
            # Update SOL balance
            self.paper_sol_balance += cost_or_proceeds_sol
            
            if amount > 1e-9: 
                # Calculate realized P&L in both SOL and USD
                cost_basis_sol_sold = amount * avg_cost_sol_before
                cost_basis_usd_sold = amount * avg_cost_usd_before
                realized_pnl_sol = cost_or_proceeds_sol - cost_basis_sol_sold
                realized_pnl_usd = cost_or_proceeds_usd - cost_basis_usd_sold
                
                # Update position
                self.paper_token_balances[mint] = current_quantity_before_sell - amount
                self.paper_token_total_cost_sol[mint] = current_total_cost_sol_before - cost_basis_sol_sold
                self.paper_token_total_cost_usd[mint] = current_total_cost_usd_before - cost_basis_usd_sold

                if self.paper_token_balances[mint] <= 1e-9: 
                    self.logger.info(f"[SOL Paper Wallet] Position for {mint} closed. Realized P&L: {realized_pnl_sol:.6f} SOL (${realized_pnl_usd:.2f})")
                    self.paper_token_balances.pop(mint, None)
                    self.paper_token_total_cost_sol.pop(mint, None)
                    self.paper_token_total_cost_usd.pop(mint, None)
                else:
                    self.logger.info(f"[SOL Paper Wallet] Sold {amount:.4f} {mint}. Remaining: {self.paper_token_balances[mint]:.4f}. Realized P&L: {realized_pnl_sol:.6f} SOL (${realized_pnl_usd:.2f})")
            else:
                self.logger.info(f"[SOL Paper Wallet] SELL: Attempted to sell {original_amount_for_sell_attempt:.4f} {mint} but no actual sell occurred (amount adjusted to 0). Proceeds: {cost_or_proceeds_sol:.6f} SOL. New SOL bal: {self.paper_sol_balance:.6f}")

            self.logger.info(f"[SOL Paper Wallet] SELL: {amount:.4f} {mint} at {price_sol:.8f} SOL. Proceeds: {cost_or_proceeds_sol:.6f} SOL (${cost_or_proceeds_usd:.2f}). New SOL bal: {self.paper_sol_balance:.6f}")

        # --- Persist SOL-Based Wallet State to Database ---
        try:
            # 1. Persist SOL balance
            await self.db.set_paper_summary_value('paper_sol_balance', value_float=self.paper_sol_balance)

            # 2. Persist token position with SOL cost basis
            final_token_quantity = self.paper_token_balances.get(mint, 0.0)
            final_total_cost_sol = self.paper_token_total_cost_sol.get(mint, 0.0)
            final_total_cost_usd = self.paper_token_total_cost_usd.get(mint, 0.0)
            final_avg_price_sol = (final_total_cost_sol / final_token_quantity) if final_token_quantity > 1e-9 else 0.0
            final_avg_price_usd = (final_total_cost_usd / final_token_quantity) if final_token_quantity > 1e-9 else 0.0

            if final_token_quantity > 1e-9:
                # Store both SOL and USD cost basis
                await self.db.upsert_paper_position(
                    mint=mint, 
                    quantity=final_token_quantity, 
                    total_cost_usd=final_total_cost_usd,  # Keep for compatibility
                    average_price_usd=final_avg_price_usd,
                    total_cost_sol=final_total_cost_sol,  # Add SOL cost basis
                    average_price_sol=final_avg_price_sol
                )
            else:
                await self.db.delete_paper_position(mint)
            
            # 3. Update trade record with SOL-based details
            notes = f"SOL Paper trade ({action_upper}): {amount:.4f} {mint} @ {price_sol:.8f} SOL. Sim Wallet SOL Bal: {self.paper_sol_balance:.6f}"
            details = {
                'paper_trade': True,
                'paper_trade_sol_based': True,  # Mark as SOL-based trade
                'paper_price_sol': price_sol,   # PRIMARY: SOL price
                'paper_price_usd': price_sol * current_sol_price_usd if current_sol_price_usd else None,  # SECONDARY: USD price
                'paper_amount_token_traded': amount,
                'paper_total_sol_value': cost_or_proceeds_sol,
                'paper_total_usd_value': cost_or_proceeds_usd,
                'paper_sim_sol_balance_after': self.paper_sol_balance,
                'paper_token_balance_after': final_token_quantity,
                'executed_at': datetime.now(timezone.utc).isoformat(),
                'sol_price_usd_at_execution': current_sol_price_usd
            }
            if realized_pnl_sol is not None:
                details['paper_realized_pnl_sol'] = realized_pnl_sol
                details['paper_realized_pnl_usd'] = realized_pnl_usd
            if action_upper == 'SELL' and original_amount_for_sell_attempt > amount:
                details['paper_sell_amount_requested'] = original_amount_for_sell_attempt
                details['paper_sell_amount_actual'] = amount
            
            db_trade_update_success = await self.db.update_trade_status(
                trade_id=trade_id, 
                new_status='paper_completed_sol', 
                notes=notes, 
                details=details
            )
            
            if db_trade_update_success:
                self.logger.info(f"SOL-based paper trade (ID: {trade_id}) successfully processed and persisted.")
                return True
            else:
                self.logger.error(f"Failed to update DB trade status for SOL-based trade ID {trade_id} after paper wallet persistence.")
                return False
                
        except Exception as e:
            self.logger.error(f"Error persisting SOL-based paper trade (ID: {trade_id}) state to DB: {e}", exc_info=True)
            return False

    async def execute_trade(self, trade_id: int, action: str, 
                           mint: str, price: float, amount: float) -> bool:
        """
        Marks an existing trade record as paper-traded and updates the simulated paper wallet (in-memory and DB).
        
        Args:
            trade_id: The ID of the existing trade record to update.
            action: 'BUY' or 'SELL'.
            mint: The mint of the token traded.
            price: The simulated USD price of execution per token.
            amount: The amount of token units traded.
            
        Returns:
            True if successful (DB update and paper wallet update), False otherwise.
        """
        action_upper = action.upper()
        if action_upper not in ['BUY', 'SELL']:
            self.logger.error(f"Invalid action '{action}' for paper trade ID {trade_id}. Must be BUY or SELL.")
            return False

        if price <= 0 or amount < 0: # Allow zero amount for sell that might get adjusted from dust
            if not (action_upper == 'SELL' and amount == 0 and price > 0):
                 self.logger.error(f"Invalid price ({price}) or amount ({amount}) for paper trade ID {trade_id}. Price must be >0. Amount must be >=0.")
                 return False

        # --- Simulate Wallet Transaction (In-Memory) --- 
        cost_or_proceeds_usd = amount * price
        original_amount_for_sell_attempt = amount
        realized_pnl_usd: Optional[float] = None

        if action_upper == 'BUY':
            if self.paper_sol_balance < cost_or_proceeds_usd:
                self.logger.warning(f"[Paper Wallet] Insufficient paper SOL balance ({self.paper_sol_balance:.2f} SOL) to buy {amount:.4f} {mint} for ${cost_or_proceeds_usd:.2f} USD. Trade ID: {trade_id}")
                return False 
            
            self.paper_sol_balance -= cost_or_proceeds_usd
            current_quantity = self.paper_token_balances.get(mint, 0.0)
            current_total_cost = self.paper_token_total_cost_usd.get(mint, 0.0)
            
            self.paper_token_balances[mint] = current_quantity + amount
            self.paper_token_total_cost_usd[mint] = current_total_cost + cost_or_proceeds_usd
            self.logger.info(f"[Paper Wallet MEM] BUY: {amount:.4f} {mint} at ${price:.4f}. Cost: ${cost_or_proceeds_usd:.2f}. New SOL bal: {self.paper_sol_balance:.2f}")

        elif action_upper == 'SELL':
            current_quantity_before_sell = self.paper_token_balances.get(mint, 0.0)
            current_total_cost_before_sell = self.paper_token_total_cost_usd.get(mint, 0.0)
            avg_cost_of_position_before_sell = (current_total_cost_before_sell / current_quantity_before_sell) if current_quantity_before_sell > 1e-9 else 0

            if current_quantity_before_sell < amount:
                self.logger.warning(f"[Paper Wallet] Insufficient paper token balance ({current_quantity_before_sell:.4f} {mint}) to sell requested {amount:.4f}. Selling available {current_quantity_before_sell:.4f}. Trade ID: {trade_id}")
                amount = current_quantity_before_sell 
            
            if amount <= 1e-9: 
                self.logger.info(f"[Paper Wallet] No actual amount of {mint} to sell for trade ID {trade_id} (balance is {current_quantity_before_sell:.8f}, requested {original_amount_for_sell_attempt:.4f}). Trade will be marked, but wallet unchanged.")
                amount = 0.0 # Ensure amount for DB log is zero if nothing was sold
            
            cost_or_proceeds_usd = amount * price # Recalculate if amount was adjusted
            self.paper_sol_balance += cost_or_proceeds_usd
            
            if amount > 1e-9: 
                cost_basis_of_amount_sold = amount * avg_cost_of_position_before_sell
                realized_pnl_usd = cost_or_proceeds_usd - cost_basis_of_amount_sold
                
                self.paper_token_balances[mint] = current_quantity_before_sell - amount
                self.paper_token_total_cost_usd[mint] = current_total_cost_before_sell - cost_basis_of_amount_sold

                if self.paper_token_balances[mint] <= 1e-9: 
                    self.logger.info(f"[Paper Wallet MEM] Position for {mint} closed. Realized P&L: ${realized_pnl_usd:.2f}")
                    self.paper_token_balances.pop(mint, None)
                    self.paper_token_total_cost_usd.pop(mint, None)
                else:
                    self.logger.info(f"[Paper Wallet MEM] Sold {amount:.4f} {mint}. Remaining: {self.paper_token_balances[mint]:.4f}. Realized P&L: ${realized_pnl_usd:.2f}")
            else: # amount is 0
                 self.logger.info(f"[Paper Wallet MEM] SELL: Attempted to sell {original_amount_for_sell_attempt:.4f} {mint} but no actual sell occurred (amount adjusted to 0). Proceeds: ${cost_or_proceeds_usd:.2f}. New SOL bal: {self.paper_sol_balance:.2f}")

            self.logger.info(f"[Paper Wallet MEM] SELL ({action_upper}): {amount:.4f} {mint} at ${price:.4f}. Proceeds: ${cost_or_proceeds_usd:.2f}. New SOL bal: {self.paper_sol_balance:.2f}")

        # --- Persist In-Memory Wallet State to Database & Update Trade Record --- 
        db_success = False
        try:
            # 1. Persist SOL balance
            await self.db.set_paper_summary_value('paper_sol_balance', value_float=self.paper_sol_balance)

            # 2. Persist token position
            final_token_quantity = self.paper_token_balances.get(mint, 0.0)
            final_total_cost_usd = self.paper_token_total_cost_usd.get(mint, 0.0)
            final_avg_price_usd = (final_total_cost_usd / final_token_quantity) if final_token_quantity > 1e-9 else 0.0

            if final_token_quantity > 1e-9:
                await self.db.upsert_paper_position(
                    mint=mint, 
                    quantity=final_token_quantity, 
                    total_cost_usd=final_total_cost_usd,
                    average_price_usd=final_avg_price_usd
                )
            else: # Quantity is zero, delete from DB
                await self.db.delete_paper_position(mint)
            
            # 3. Update the original trade record in DB
            notes = f"Paper trade ({action_upper}): {amount:.4f} {mint} @ ${price:.4f}. Sim Wallet SOL Bal: {self.paper_sol_balance:.2f}"
            details = {
                'paper_trade': True,
                'paper_price_usd': price, 
                'paper_amount_token_traded': amount, # Actual amount paper-traded from wallet
                'paper_total_usd_value': cost_or_proceeds_usd,
                'paper_sim_sol_balance_after': self.paper_sol_balance,
                'paper_token_balance_after': final_token_quantity,
                'executed_at': datetime.now(timezone.utc).isoformat()
            }
            if realized_pnl_usd is not None:
                details['paper_realized_pnl_usd'] = realized_pnl_usd
            if action_upper == 'SELL' and original_amount_for_sell_attempt > amount:
                 details['paper_sell_amount_requested'] = original_amount_for_sell_attempt
                 details['paper_sell_amount_actual'] = amount
            
            db_trade_update_success = await self.db.update_trade_status(
                trade_id=trade_id, 
                new_status='paper_completed', 
                notes=notes, 
                details=details
            )
            
            if db_trade_update_success:
                self.logger.info(f"Paper trade (ID: {trade_id}) successfully processed and persisted.")
                return True # Overall success
            else:
                self.logger.error(f"Failed to update DB trade status for trade ID {trade_id} after paper wallet persistence.")
                # TODO: Critical - Wallet state changed but trade record not updated. Potential inconsistency.
                # This might require a more complex transaction or compensation logic.
                return False # Indicate overall failure due to DB issue
            
        except Exception as e:
            self.logger.error(f"Error persisting paper trade (ID: {trade_id}) state to DB: {e}", exc_info=True)
            # TODO: Critical - Wallet state changed in memory but DB persistence failed. 
            # This is a point where data could become inconsistent if the app crashes.
            # For now, the in-memory change is done. A robust solution might try to queue this DB update.
            return False # Indicate overall failure

    async def get_paper_position(self, mint: str) -> Dict[str, Any]:
        """
        Get the current paper trading position for a token with SOL-based calculations (primary) and USD (secondary).
        Ensure load_persistent_state() was called at startup.
        
        Args:
            mint: The token mint.
            
        Returns:
            Dictionary with position information including SOL-based cost basis and P&L.
        """
        current_quantity = self.paper_token_balances.get(mint, 0.0)
        total_cost_basis_sol = self.paper_token_total_cost_sol.get(mint, 0.0)
        total_cost_basis_usd = self.paper_token_total_cost_usd.get(mint, 0.0)
        
        # Initialize return values
        average_price_sol = 0.0
        average_price_usd = 0.0
        unrealized_pnl_sol: Optional[float] = None
        unrealized_pnl_usd: Optional[float] = None
        current_market_price_sol: Optional[float] = None
        current_market_price_usd: Optional[float] = None
        current_market_value_sol: Optional[float] = None
        current_market_value_usd: Optional[float] = None

        if current_quantity > 1e-9:
            # Calculate average costs
            average_price_sol = total_cost_basis_sol / current_quantity
            average_price_usd = total_cost_basis_usd / current_quantity
            
            # Fetch current market prices for unrealized P&L
            if self.price_monitor:
                # PRIMARY: Get SOL price for SOL-based trading
                current_market_price_sol = await self.price_monitor.get_current_price_sol(mint, max_age_seconds=300)
                if current_market_price_sol is not None:
                    current_market_value_sol = current_market_price_sol * current_quantity
                    unrealized_pnl_sol = current_market_value_sol - total_cost_basis_sol
                
                # SECONDARY: Get USD price for display
                current_market_price_usd = await self.price_monitor.get_current_price_usd(mint, max_age_seconds=300)
                if current_market_price_usd is not None:
                    current_market_value_usd = current_market_price_usd * current_quantity
                    unrealized_pnl_usd = current_market_value_usd - total_cost_basis_usd
        else: 
            current_quantity = 0.0
            total_cost_basis_sol = 0.0 
            total_cost_basis_usd = 0.0
            
        return {
            'mint': mint,
            'amount': current_quantity,
            
            # SOL-based data (PRIMARY for trading decisions)
            'average_price_sol': average_price_sol,
            'total_cost_basis_sol': total_cost_basis_sol,
            'current_market_price_sol': current_market_price_sol,
            'current_market_value_sol': current_market_value_sol,
            'unrealized_pnl_sol': unrealized_pnl_sol,
            
            # USD-based data (SECONDARY for display)
            'average_price_usd': average_price_usd,
            'total_cost_basis_usd': total_cost_basis_usd,
            'current_market_price_usd': current_market_price_usd,
            'current_market_value_usd': current_market_value_usd,
            'unrealized_pnl_usd': unrealized_pnl_usd
        }

    def get_paper_sol_balance(self) -> float:
        """Returns the current simulated paper SOL balance (in-memory)."""
        return self.paper_sol_balance

    async def get_all_paper_positions_async(self) -> Dict[str, Dict[str, Any]]:
        """Returns all current paper positions from the in-memory state, including unrealized P&L."""
        positions = {}
        # Create a list of tasks to fetch all positions concurrently
        tasks = []
        mint_addresses = list(self.paper_token_balances.keys()) # Iterate over a copy of keys
        
        for mint_address in mint_addresses:
            if self.paper_token_balances.get(mint_address, 0.0) > 1e-9:
                tasks.append(self.get_paper_position(mint_address))
        
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    self.logger.error(f"Error fetching paper position for {mint_addresses[i]} in get_all_paper_positions_async: {result}")
                elif result and isinstance(result, dict):
                    positions[result['mint']] = result
        return positions

    async def close(self):
        """Clean up resources. Note: In-memory state is not persisted here automatically on close."""
        self.logger.info("Closing paper trading system. Ensure state is saved via execute_trade if needed.")
        # No explicit async resources to close here currently unless db or wallet_manager needed specific paper trading cleanup. 