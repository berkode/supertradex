"""
SYNTHRON CRYPTO TRADER
By Magna Opus Technologies
"""
import sys
from config import (
    Settings, SolanaConfig, LoggingConfig, FiltersConfig, Thresholds,
    DexScreenerAPIConfig, RaydiumAPIConfig
)
from utils.logger import get_logger
from wallet.wallet_manager import WalletManager
from wallet.gas_manager import GasManager
from wallet.balance_checker import BalanceChecker
from strategies.strategy_selector import StrategySelector
from execution.order_manager import OrderManager
from data.data_fetcher import DataFetcher
from data.analytics import Analytics
from performance.reporting import Reporting
from performance.backtesting import Backtesting
from filters.whitelist import Whitelist
from filters.blacklist import Blacklist

# Global Logger Setup
logger = get_logger("SynthronCryptoTrader")

def display_title():
    """Display the branded title."""
    title = """
 ███████╗██╗   ██╗███╗   ██╗████████╗██╗  ██╗██████╗ ███╗   ██╗     ██████╗ ██████╗ ████████╗ ██████╗ ██████╗ ████████╗ █████╗ ██████╗ 
 ██╔════╝██║   ██║████╗  ██║╚══██╔══╝██║  ██║██╔══██╗████╗  ██║    ██╔════╝██╔═══██╗╚══██╔══╝██╔═══██╗██╔══██╗╚══██╔══╝██╔══██╗██╔══██╗
 █████╗  ██║   ██║██╔██╗ ██║   ██║   ███████║██████╔╝██╔██╗ ██║    ██║     ██║   ██║   ██║   ██║   ██║██████╔╝   ██║   ███████║██████╔╝
 ██╔══╝  ██║   ██║██║╚██╗██║   ██║   ██╔══██║██╔═══╝ ██║╚██╗██║    ██║     ██║   ██║   ██║   ██║   ██║██╔═══╝    ██║   ██╔══██║██╔═══╝ 
 ███████╗╚██████╔╝██║ ╚████║   ██║   ██║  ██║██║     ██║ ╚████║    ╚██████╗╚██████╔╝   ██║   ╚██████╔╝██║        ██║   ██║  ██║██║     
 ╚══════╝ ╚═════╝ ╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝     ╚═╝  ╚═══╝     ╚═════╝ ╚═════╝    ╚═╝    ╚═════╝ ╚═╝        ╚═╝   ╚═╝  ╚═╝╚═╝     
"""
    print(title)
    print("\nBy Magna Opus Technologies\n")
    print("=" * 80)

def initialize_system():
    """Initialize all necessary modules and configurations."""
    logger.info("Initializing Synthron Crypto Trader system...")
    try:
        # Load configurations
        settings = Settings()
        solana_config = SolanaConfig()
        filters_config = FiltersConfig()
        thresholds = Thresholds()
        dex_screener_config = DexScreenerAPIConfig()
        raydium_config = RaydiumAPIConfig()
        LoggingConfig()  # Configure logging globally

        # Initialize wallet and utilities
        wallet = WalletManager()
        gas_manager = GasManager()
        balance_checker = BalanceChecker()
        order_manager = OrderManager()
        analytics = Analytics()
        data_fetcher = DataFetcher()
        whitelist = Whitelist()
        blacklist = Blacklist()
        strategy_selector = StrategySelector()
        reporting = Reporting()
        backtesting = Backtesting()

        logger.info("System initialized successfully.")
        return {
            "settings": settings,
            "wallet": wallet,
            "gas_manager": gas_manager,
            "balance_checker": balance_checker,
            "order_manager": order_manager,
            "analytics": analytics,
            "data_fetcher": data_fetcher,
            "whitelist": whitelist,
            "blacklist": blacklist,
            "strategy_selector": strategy_selector,
            "reporting": reporting,
            "backtesting": backtesting,
        }
    except Exception as e:
        logger.error(f"System initialization failed: {e}")
        sys.exit("Initialization failed. Please check the logs for more details.")

def display_menu():
    """Display the main menu for user interaction."""
    print("\n")
    print("=" * 80)
    print("MAIN MENU")
    print("=" * 80)
    print("1. Trading System")
    print("2. Backtesting System")
    print("3. Exit")
    print("=" * 80)

def run_trading_system(modules):
    """Run the live trading system."""
    logger.info("Starting live trading system...")
    print("Running the live trading system...")
    try:
        wallet = modules["wallet"]
        balance_checker = modules["balance_checker"]
        wallet.verify_wallet_setup()
        sol_balance = balance_checker.get_sol_balance()
        logger.info(f"SOL balance: {sol_balance}")
        
        whitelist = modules["whitelist"]
        whitelist.build_from_filters()
        
        strategy_selector = modules["strategy_selector"]
        strategy_selector.execute_trading_strategies()
    except Exception as e:
        logger.error(f"Error during trading: {e}")
    finally:
        logger.info("Trading session ended.")

def run_backtesting_system(modules):
    """Run the backtesting system."""
    logger.info("Starting backtesting system...")
    print("Running the backtesting system...")
    try:
        backtesting = modules["backtesting"]
        backtesting.load_data()
        backtesting.run_backtest()
        backtesting.evaluate_metrics()
        backtesting.save_results("backtesting_results.csv")
        logger.info("Backtesting results saved.")
    except Exception as e:
        logger.error(f"Error during backtesting: {e}")

def main():
    """Main entry point for the application."""
    display_title()
    modules = initialize_system()

    while True:
        display_menu()
        choice = input("Enter your choice (1-3): ").strip()
        if choice == "1":
            run_trading_system(modules)
        elif choice == "2":
            run_backtesting_system(modules)
        elif choice == "3":
            print("Exiting Synthron Crypto Trader. Goodbye!")
            logger.info("Application terminated by user.")
            break
        else:
            print("Invalid choice. Please select a valid option.")

if __name__ == "__main__":
    main()
