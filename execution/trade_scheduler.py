import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Callable, List, Dict, Optional
from enum import Enum

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("TradeScheduler")


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
        action: Callable[..., None],
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

    def check_and_execute(self):
        """Check if the condition is met and execute the action."""
        if not self.is_active:
            return

        try:
            if self.trigger_type == TriggerType.TIME and self.next_run and datetime.now() >= self.next_run:
                logger.info(f"Time trigger {self.trigger_id} activated. Executing action.")
                self.action()
                self.next_run += timedelta(minutes=1)  # Example: schedule next run 1 minute later
            elif self.trigger_type in [TriggerType.PRICE, TriggerType.CUSTOM]:
                if self.condition():
                    logger.info(f"{self.trigger_type.value} trigger {self.trigger_id} activated. Executing action.")
                    self.action()
        except Exception as e:
            logger.error(f"Error while executing trigger {self.trigger_id}: {e}")

    def deactivate(self):
        """Deactivate the trigger."""
        self.is_active = False
        logger.info(f"Trigger {self.trigger_id} deactivated.")

    def activate(self):
        """Activate the trigger."""
        self.is_active = True
        logger.info(f"Trigger {self.trigger_id} activated.")


class TradeScheduler:
    """Class to manage and schedule trade triggers."""
    def __init__(self, interval: int = 1):
        self.triggers: Dict[str, TradeTrigger] = {}
        self.interval = interval  # Polling interval in seconds
        self.scheduler_thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self._stop_event = threading.Event()
        logger.info("TradeScheduler initialized.")

    def _run_scheduler(self):
        """Continuously checks and executes triggers."""
        while not self._stop_event.is_set():
            for trigger in list(self.triggers.values()):
                if trigger.is_active:
                    trigger.check_and_execute()
            time.sleep(self.interval)

    def add_trigger(self, trigger: TradeTrigger):
        """Add a new trade trigger."""
        if trigger.trigger_id in self.triggers:
            logger.warning(f"Trigger ID {trigger.trigger_id} already exists. Overwriting.")
        self.triggers[trigger.trigger_id] = trigger
        logger.info(f"Trigger {trigger.trigger_id} added: {trigger.description}")

    def remove_trigger(self, trigger_id: str):
        """Remove a trade trigger."""
        if trigger_id in self.triggers:
            self.triggers.pop(trigger_id)
            logger.info(f"Trigger {trigger_id} removed.")
        else:
            logger.warning(f"Trigger ID {trigger_id} not found.")

    def start(self):
        """Start the trade scheduler."""
        if not self.scheduler_thread.is_alive():
            self._stop_event.clear()
            self.scheduler_thread.start()
            logger.info("TradeScheduler started.")

    def stop(self):
        """Stop the trade scheduler."""
        self._stop_event.set()
        self.scheduler_thread.join()
        logger.info("TradeScheduler stopped.")

    def list_triggers(self) -> List[TradeTrigger]:
        """List all triggers."""
        return list(self.triggers.values())

    def __repr__(self):
        return f"TradeScheduler(triggers={list(self.triggers.keys())})"


