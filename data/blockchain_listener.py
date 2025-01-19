import os
import logging
import asyncio
from solana.rpc.websocket_api import connect as solana_websocket_connect
from solana.publickey import PublicKey
from dotenv import load_dotenv
from datetime import datetime
from decimal import Decimal

# Load environment variables from .env
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.getenv("LOG_FILE", "blockchain_listener.log")),
        logging.StreamHandler() if os.getenv("ENABLE_CONSOLE_LOGGING", "True").lower() == "true" else None
    ]
)


class BlockchainListener:
    def __init__(self):
        self.rpc_ws_endpoint = os.getenv("SOLANA_RPC_WS_URL", "wss://api.mainnet-beta.solana.com")
        self.monitored_accounts = [acc.strip() for acc in os.getenv("MONITORED_ACCOUNTS", "").split(",") if acc.strip()]
        self.monitored_programs = [prog.strip() for prog in os.getenv("MONITORED_PROGRAMS", "").split(",") if prog.strip()]

        if not self.rpc_ws_endpoint:
            raise ValueError("SOLANA_RPC_WS_URL must be set in the environment variables.")

    def _log_event(self, event: dict):
        """
        Log event details to a file or database for further analysis.

        Args:
            event (dict): The event data.
        """
        event_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logging.info(f"Event logged at {event_timestamp}: {event}")

    async def _process_event(self, event: dict):
        """
        Process blockchain events and apply business logic.

        Args:
            event (dict): The event data received from the blockchain.
        """
        try:
            logging.info(f"New event received: {event}")

            if "result" in event:
                result = event["result"]
                account = result.get("pubkey")
                program = result.get("owner")
                value = result.get("value", {})

                if account in self.monitored_accounts:
                    logging.info(f"Activity detected for monitored account: {account}")
                    await self._handle_account_activity(account, value)

                if program in self.monitored_programs:
                    logging.info(f"Activity detected for monitored program: {program}")
                    await self._handle_program_activity(program, value)

                self._log_event(event)
        except Exception as e:
            logging.error(f"Error processing event: {e}")

    async def _handle_account_activity(self, account: str, value: dict):
        """
        Handle activity for monitored accounts.

        Args:
            account (str): Account ID.
            value (dict): Event details.
        """
        # Token transfer example
        lamports = value.get("lamports", 0)
        token_balance = value.get("tokenAmount", {}).get("uiAmount", 0)
        transaction_details = value.get("transaction", {})
        timestamp = value.get("blockTime")

        logging.info(f"Account {account} activity detected.")
        logging.info(f"  Lamports: {lamports}")
        logging.info(f"  Token Balance: {token_balance}")
        logging.info(f"  Transaction Details: {transaction_details}")
        logging.info(f"  Timestamp: {datetime.fromtimestamp(timestamp) if timestamp else 'Unknown'}")

        # Trigger alerts for large transfers (editable threshold)
        if lamports > 1_000_000_000:  
            logging.warning(f"Large transfer detected from account {account}: {lamports / 10**9} SOL.")

        # Trigger actions based on updated token balance (editable threshold)
        if token_balance > 1000:  
            logging.info(f"High token balance detected for {account}: {token_balance} tokens.")

    async def _handle_program_activity(self, program: str, value: dict):
        """
        Handle activity for monitored programs.

        Args:
            program (str): Program ID.
            value (dict): Event details.
        """
        instruction_data = value.get("instruction", {})
        logging.info(f"Program {program} interaction detected.")
        logging.info(f"  Instruction Details: {instruction_data}")

        # Swap detection
        if "swap" in instruction_data:
            logging.info(f"Swap detected in program {program}.")
            token_in = instruction_data.get("inputToken", "Unknown")
            token_out = instruction_data.get("outputToken", "Unknown")
            amount_in = instruction_data.get("amountIn", 0)
            amount_out = instruction_data.get("amountOut", 0)

            logging.info(f"  Token In: {token_in} | Amount In: {Decimal(amount_in) / 10**9} SOL")
            logging.info(f"  Token Out: {token_out} | Amount Out: {Decimal(amount_out) / 10**9} SOL")

        # Custom logic for contract calls (e.g., liquidity additions)
        if "addLiquidity" in instruction_data:
            logging.info(f"Liquidity addition detected in program {program}. Details: {instruction_data}")

    async def _subscribe_to_account(self, ws_connection, account_id: str):
        """
        Subscribe to events for a specific account.

        Args:
            ws_connection: Active WebSocket connection.
            account_id (str): Account ID to monitor.
        """
        try:
            logging.info(f"Subscribing to account ID: {account_id}")
            await ws_connection.account_subscribe(PublicKey(account_id))
        except Exception as e:
            logging.error(f"Error subscribing to account {account_id}: {e}")

    async def _subscribe_to_program(self, ws_connection, program_id: str):
        """
        Subscribe to events for a specific program.

        Args:
            ws_connection: Active WebSocket connection.
            program_id (str): Program ID to monitor.
        """
        try:
            logging.info(f"Subscribing to program ID: {program_id}")
            await ws_connection.account_subscribe(PublicKey(program_id))
        except Exception as e:
            logging.error(f"Error subscribing to program {program_id}: {e}")

    async def listen(self):
        """
        Listen to blockchain events on the Solana network.
        """
        try:
            logging.info(f"Connecting to Solana WebSocket RPC: {self.rpc_ws_endpoint}")
            async with solana_websocket_connect(self.rpc_ws_endpoint) as ws_connection:
                # Subscribe to monitored accounts
                for account in self.monitored_accounts:
                    await self._subscribe_to_account(ws_connection, account)

                # Subscribe to monitored programs
                for program in self.monitored_programs:
                    await self._subscribe_to_program(ws_connection, program)

                logging.info("Listening to Solana blockchain events...")
                async for message in ws_connection:
                    await self._process_event(message)
        except asyncio.CancelledError:
            logging.info("Listener cancelled.")
        except Exception as e:
            logging.error(f"Error in blockchain listener: {e}")
        finally:
            logging.info("Listener stopped.")

