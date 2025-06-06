import pandas as pd
from datetime import datetime, timedelta
from data.token_scanner import TokenScanner
from strategies.entry_exit import EntryExitStrategy
from performance.backtesting import Backtesting
from performance.metrics import Metrics
from performance.reporting import Reporting
from config.settings import Settings
from data.token_database import TokenDatabase
import logging
import os
from execution.balance_checker import BalanceChecker
from wallet.trade_validator import TradeValidator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    # Initialize components
    settings = Settings()
    db = TokenDatabase()
    balance_checker = BalanceChecker()
    trade_validator = TradeValidator(balance_checker=balance_checker, settings=settings)
    strategy = EntryExitStrategy(settings=settings, db=db, balance_checker=balance_checker, trade_validator=trade_validator)
    backtester = Backtesting(strategy)
    metrics = Metrics()
    reporter = Reporting()

    try:
        # Load historical data
        logger.info("Loading historical data...")
        data_path = os.path.join("outputs", "historical_data.csv")
        backtester.load_data(source=data_path)
        
        # Run backtest
        logger.info("Starting backtest...")
        backtester.run_backtest()
        
        # Evaluate performance
        logger.info("Evaluating performance metrics...")
        performance_metrics = backtester.evaluate_metrics()
        
        # Generate report
        logger.info("Generating performance report...")
        report = reporter.generate_report(performance_metrics)
        
        # Save results
        logger.info("Saving backtest results...")
        results_path = os.path.join("outputs", "backtest_results.csv")
        backtester.save_results(results_path)
        
        # Save report
        report_path = os.path.join("outputs", "performance_report.txt")
        with open(report_path, "w") as f:
            f.write(report)
        
        # Print summary
        logger.info("\nBacktest Summary:")
        logger.info(f"Total Profit: ${performance_metrics['total_profit']:.2f}")
        logger.info(f"ROI: {performance_metrics['ROI']:.2f}%")
        logger.info(f"Max Drawdown: ${performance_metrics['max_drawdown']:.2f}")
        
        logger.info(f"\nResults saved to: {results_path}")
        logger.info(f"Report saved to: {report_path}")
        
    except Exception as e:
        logger.error(f"Error during backtesting: {e}")
        raise

if __name__ == "__main__":
    main() 