import logging
import asyncio
import time
from datetime import datetime, timedelta
from typing import Callable, List,Any, Dict, Optional, TYPE_CHECKING
from enum import Enum
import os
import json
import pandas as pd
from config.settings import Settings

# Set up logging
logger = logging.getLogger("TradeScheduler")

# Import necessary components under TYPE_CHECKING if needed
if TYPE_CHECKING:
    from execution.order_manager import OrderManager
    from data.token_database import TokenDatabase

class TriggerType(Enum):
    """Enum to represent different types of trade triggers."""
    TIME = "Time-based"
    PRICE = "Price-based"
    CUSTOM = "Custom"


class TradeTrigger:
    """Represents a trade trigger."""
    def __init__(
        self,
        trigger_id: str,
        trigger_type: TriggerType,
        condition: Callable[..., bool],
        action: Callable[..., Any],
        description: Optional[str] = None,
        next_run: Optional[datetime] = None
    ):
        self.trigger_id = trigger_id
        self.trigger_type = trigger_type
        self.condition = condition  # Function that returns True when the trigger is activated
        self.action = action  # Function to execute when the trigger activates
        self.description = description or f"{trigger_type.value} trigger"
        self.next_run = next_run  # For time-based triggers
        self.is_active = True
        self.last_checked = datetime.now()
        self.last_triggered = None

        # Extract token address from trigger name (assuming format like 'buy_0x1234')
        parts = trigger_id.split('_')
        self.token_address = parts[1] if len(parts) > 1 else None

    async def check_and_execute(self):
        """Check if the condition is met and execute the action. Now async."""
        if not self.is_active:
            return

        execute = False
        if self.trigger_type == TriggerType.TIME:
            if self.next_run and datetime.now() >= self.next_run:
                execute = True
                self.next_run += timedelta(minutes=1) # Example: schedule next run 1 minute later
            elif self.trigger_type in [TriggerType.PRICE, TriggerType.CUSTOM]:
                try:
                    # Assuming condition is sync for now. If it becomes async, needs await.
                    if self.condition():
                        execute = True
                except Exception as e:
                    logger.error(f"Error evaluating condition for trigger {self.trigger_id}: {e}")
                    execute = False # Prevent execution if condition fails

        if execute:
            try:
                logger.info(f"{self.trigger_type.value} trigger {self.trigger_id} activated. Executing action.")
                if asyncio.iscoroutinefunction(self.action):
                    # Execute the coroutine and let the scheduler handle it
                    await self.action()
                else:
                    # Run synchronous actions in the event loop's default executor
                    # to avoid blocking the main scheduler loop.
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, self.action)
                    self.last_triggered = datetime.now()
            except Exception as e:
                logger.error(f"Error while executing action for trigger {self.trigger_id}: {e}")

    def deactivate(self):
        """Deactivate the trigger."""
        self.is_active = False
        logger.info(f"Trigger {self.trigger_id} deactivated.")

    def activate(self):
        """Activate the trigger."""
        self.is_active = True
        logger.info(f"Trigger {self.trigger_id} activated.")

    async def check(self) -> bool:
        """Check if trigger condition is met. Now async."""
        self.last_checked = datetime.now()
        try:
            # Assuming condition is sync. If it becomes async, needs await.
            is_triggered = self.condition()
            
            # Record trigger status (Assuming db.update_trigger_status is sync)
            # If db operation becomes async, this needs `await loop.run_in_executor`
            # self._record_trigger_status(is_triggered)
            
            if is_triggered and self.is_active:
                # self.last_triggered = datetime.now() # Moved to check_and_execute
                logger.info(f"Trigger {self.trigger_id} condition met.")
                return True
            return False
        except Exception as e:
            logger.error(f"Error checking trigger {self.trigger_id}: {e}")
            return False

    def _record_trigger_status(self, is_triggered: bool):
        """
        Record trigger status in database and CSV.
        NOTE: This remains SYNCHRONOUS. If DB calls become async, this needs refactoring.
        """
        if not self.token_address:
            logger.debug(f"Skipping trigger status recording for {self.trigger_id} (no token address).")
            return

        try:
            # Re-instantiate TokenDatabase locally as before
            from data.token_database import TokenDatabase # Import locally if not at top level
            # Assuming TokenDatabase() is synchronous initialization
            db = TokenDatabase()
            now = datetime.now().isoformat()
            
            # Prepare trigger data
            trigger_data = {
                'active': self.is_active,
                'triggered': is_triggered,
                'last_checked': now,
                'last_triggered': self.last_triggered.isoformat() if self.last_triggered else None
            }
            
            # Update trigger status in database (and CSV via sync)
            # Assuming db.update_trigger_status is synchronous
            db.update_trigger_status(
                self.token_address, 
                f"{self.trigger_type.value}", 
                trigger_data
            )
            
            logger.debug(f"Recorded trigger status for {self.token_address}")
        except Exception as e:
            logger.error(f"Error recording trigger status: {e}")


class TradeScheduler:
    """Class to manage and schedule trade triggers within asyncio loop."""
    def __init__(self, settings: 'Settings', order_manager: 'OrderManager', interval: Optional[int] = None):
        """
        Initialize the trade scheduler with shared resources and configurations.
        
        Args:
            settings: The global application settings object. MUST be provided.
            order_manager: An initialized OrderManager instance. MUST be provided.
            interval: Polling interval in seconds. Defaults to settings.POLL_INTERVAL or 1.
        """
        self.logger = logging.getLogger(__name__)
        self.logger.propagate = True
        
        if settings is None:
            self.logger.error("TradeScheduler initialized without a Settings object. This is required.")
            raise ValueError("TradeScheduler requires a valid Settings object.")
        if order_manager is None:
            self.logger.error("TradeScheduler initialized without an OrderManager. This is required.")
            raise ValueError("TradeScheduler requires a valid OrderManager.")

        self.order_manager = order_manager
        self.settings = settings
        
        # Load settings from the injected Settings instance
        # resolved_interval = interval if interval is not None else getattr(settings, 'POLL_INTERVAL', 1)
        # self.interval = int(resolved_interval)
        self.interval = int(settings.TRADE_SCHEDULER_INTERVAL) # Use specific interval for trade scheduling
        if self.interval <= 0:
             self.logger.warning(f"Scheduler interval is {self.interval}, setting to 1 second minimum.")
             self.interval = 1
        
        self.triggers: Dict[str, TradeTrigger] = {}
        self._scheduler_task: Optional[asyncio.Task] = None # Changed from thread
        self._stop_requested: bool = False
        self.is_running = False
        self.logger.info("TradeScheduler initialized for asyncio operation.")

    async def run_scheduler_loop(self):
        """Continuously checks and executes triggers within the asyncio loop."""
        self.is_running = True
        self._stop_requested = False
        self.logger.info(f"TradeScheduler loop started with interval: {self.interval}s")
        
        while not self._stop_requested:
            start_time = time.monotonic()
            try:
                # Create a list of tasks to run checks concurrently (optional improvement)
                # check_tasks = [trigger.check() for trigger in self.triggers.values() if trigger.is_active]
                # results = await asyncio.gather(*check_tasks)
                # For simplicity, run sequentially for now:
                active_triggers = list(self.triggers.values())
                self.logger.debug(f"Checking {len(active_triggers)} triggers...")
                for trigger in active_triggers:
                    if trigger.is_active:
                        await trigger.check_and_execute()
                        
            except asyncio.CancelledError:
                 self.logger.info("Scheduler loop cancelled.")
                 self.is_running = False
                 break # Exit loop if cancelled
            except Exception as e:
                 self.logger.error(f"Error in scheduler loop iteration: {e}", exc_info=True)
                 # Avoid tight loop on continuous error
                 await asyncio.sleep(min(self.interval * 2, 60)) 

            # Calculate sleep time, ensuring it's not negative
            elapsed = time.monotonic() - start_time
            sleep_time = max(0, self.interval - elapsed)
            await asyncio.sleep(sleep_time)
            
        self.is_running = False
        self.logger.info("TradeScheduler loop stopped.")

    def add_trigger(self, trigger: TradeTrigger):
        """Add a new trade trigger."""
        if trigger.trigger_id in self.triggers:
            self.logger.warning(f"Trigger ID {trigger.trigger_id} already exists. Overwriting.")
        self.triggers[trigger.trigger_id] = trigger
        self.logger.info(f"Trigger {trigger.trigger_id} added: {trigger.description}")

    def remove_trigger(self, trigger_id: str):
        """Remove a trade trigger."""
        if trigger_id in self.triggers:
            del self.triggers[trigger_id]
            self.logger.info(f"Trigger {trigger_id} removed.")
        else:
            self.logger.warning(f"Trigger ID {trigger_id} not found.")

    def start(self):
        """Starts the scheduler loop as an asyncio task."""
        if self._scheduler_task and not self._scheduler_task.done():
            self.logger.warning("TradeScheduler task already running or scheduled.")
            return

        self.logger.info("Creating TradeScheduler asyncio task...")
        self._stop_requested = False
        self._scheduler_task = asyncio.create_task(self.run_scheduler_loop(), name="TradeSchedulerLoop")
        # No need to set self.is_running here, run_scheduler_loop does it
        self.logger.info("TradeScheduler task created.")

    async def stop(self):
        """Requests the scheduler loop to stop and waits for the task to finish."""
        if not self._scheduler_task or self._scheduler_task.done():
            self.logger.info("TradeScheduler task not running or already stopped.")
            self.is_running = False # Ensure state is correct
            return

        if self._stop_requested:
            self.logger.warning("Stop already requested for TradeScheduler task.")
            return

        self.logger.info("Requesting TradeScheduler loop to stop...")
        self._stop_requested = True
        
        # Attempt to cancel the task gracefully
        self._scheduler_task.cancel()
        
        try:
            # Wait for the task to complete (or be cancelled)
            await self._scheduler_task
            self.logger.info("TradeScheduler task finished.")
        except asyncio.CancelledError:
            self.logger.info("TradeScheduler task was cancelled successfully.")
        except Exception as e:
            self.logger.error(f"Error encountered while waiting for scheduler task to stop: {e}", exc_info=True)
        finally:
             self.is_running = False # Ensure state is correct
             self._scheduler_task = None # Clear the task reference

    def list_triggers(self) -> List[TradeTrigger]:
        """List all triggers."""
        return list(self.triggers.values())

    def __repr__(self):
        return f"TradeScheduler(triggers={list(self.triggers.keys())})"