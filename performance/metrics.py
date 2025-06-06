import pandas as pd
import numpy as np
import logging
import json
from datetime import datetime, timedelta
from typing import Dict, Any


class Metrics:
    def __init__(self, results, base_currency="dSOL"):
        """
        Initializes the metrics class with trade results.
        :param results: List of trade dictionaries (trade logs).
        :param base_currency: The trading system's base currency.
        """
        self.results = pd.DataFrame(results)
        self.metrics = {}
        self.base_currency = base_currency
        self.timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        # Configure logging
        logging.basicConfig(
            filename="metrics.log",
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
        )
        logging.info(f"Metrics initialized for base currency: {base_currency}")

    def calculate_total_made(self):
        """
        Calculate the total profit made in the base currency.
        """
        try:
            total_made = self.results['profit'].sum()
            self.metrics[f"Total Made ({self.base_currency})"] = total_made
            logging.info("Total Made calculated: %s %s", total_made, self.base_currency)
        except Exception as e:
            logging.error(f"Error calculating Total Made: {e}")
            raise

    def calculate_total_roi(self):
        """
        Calculate the total ROI (Return on Investment).
        """
        try:
            total_profit = self.results['profit'].sum()
            invested_capital = self.results['profit'].abs().sum()
            roi = (total_profit / invested_capital) * 100 if invested_capital > 0 else 0
            self.metrics["Total ROI (%)"] = roi
            logging.info("Total ROI calculated: %s", roi)
        except Exception as e:
            logging.error(f"Error calculating Total ROI: {e}")
            raise

    def calculate_tokens_per_day(self):
        """
        Calculate total tokens bought and sold per day.
        """
        try:
            self.results['date'] = pd.to_datetime(self.results['timestamp']).dt.date
            daily_summary = self.results.groupby('date').agg(
                tokens_bought=('quantity', lambda x: x[self.results['action'] == 'buy'].sum()),
                tokens_sold=('quantity', lambda x: x[self.results['action'] == 'sell'].sum()),
            ).reset_index()

            self.metrics["Daily Token Summary"] = daily_summary.to_dict(orient="records")
            logging.info("Tokens per day calculated: %s", self.metrics["Daily Token Summary"])
        except Exception as e:
            logging.error(f"Error calculating tokens per day: {e}")
            raise

    def calculate_max_gain_loss(self):
        """
        Calculate the maximum gain and maximum loss during the period.
        """
        try:
            max_gain = self.results['profit'].max()
            max_loss = self.results['profit'].min()
            gain_loss_ratio = (max_gain / abs(max_loss)) if max_loss < 0 else np.inf
            self.metrics[f"Max Gain ({self.base_currency})"] = max_gain
            self.metrics[f"Max Loss ({self.base_currency})"] = max_loss
            self.metrics["Max Gain/Loss Ratio"] = gain_loss_ratio
            logging.info(
                "Max Gain: %s %s, Max Loss: %s %s, Max Gain/Loss Ratio: %s",
                max_gain, self.base_currency, max_loss, self.base_currency, gain_loss_ratio
            )
        except Exception as e:
            logging.error(f"Error calculating Max Gain/Loss: {e}")
            raise

    def calculate_sharpe_ratio(self, risk_free_rate=0):
        """
        Calculate Sharpe Ratio.
        :param risk_free_rate: Risk-free rate for the calculation.
        """
        try:
            returns = self.results['profit']
            avg_return = returns.mean()
            return_std = returns.std()
            sharpe_ratio = (avg_return - risk_free_rate) / return_std if return_std > 0 else 0
            self.metrics["Sharpe Ratio"] = sharpe_ratio
            logging.info("Sharpe Ratio calculated: %s", sharpe_ratio)
        except Exception as e:
            logging.error(f"Error calculating Sharpe Ratio: {e}")
            raise

    def calculate_all_metrics(self):
        """
        Calculate all metrics: Total Made in dSOL, Total ROI, Tokens Per Day, Max Gain/Loss, and Sharpe Ratio.
        """
        try:
            logging.info("Calculating all metrics...")
            self.calculate_total_made()
            self.calculate_total_roi()
            self.calculate_tokens_per_day()
            self.calculate_max_gain_loss()
            self.calculate_sharpe_ratio()
            logging.info("All metrics calculated successfully: %s", self.metrics)
            return self.metrics
        except Exception as e:
            logging.error(f"Error calculating all metrics: {e}")
            raise

    def save_metrics(self, filepath):
        """
        Save metrics to a JSON file.
        :param filepath: File path to save the metrics.
        """
        try:
            if not self.metrics:
                raise ValueError("No metrics to save. Calculate metrics first.")

            metrics_path = f"{filepath}/metrics_{self.timestamp}.json"
            with open(metrics_path, "w") as json_file:
                json.dump(self.metrics, json_file, indent=4)
            logging.info(f"Metrics saved to {metrics_path}")
        except Exception as e:
            logging.error(f"Error saving metrics: {e}")
            raise

def calculate_metrics(results: Dict[str, Any]) -> Dict[str, float]:
    """
    Calculate comprehensive performance metrics for backtest results.
    
    Args:
        results: Dictionary containing backtest results including trades and equity curve
        
    Returns:
        Dictionary of calculated metrics
    """
    trades = results['trades']
    equity_curve = results['equity_curve']
    
    # Basic performance metrics
    total_return = (equity_curve.iloc[-1] / equity_curve.iloc[0] - 1) * 100
    win_rate = (trades['profit'] > 0).mean() * 100
    profit_factor = abs(trades[trades['profit'] > 0]['profit'].sum() / 
                       trades[trades['profit'] < 0]['profit'].sum())
    
    # Risk metrics
    returns = equity_curve.pct_change().dropna()
    volatility = returns.std() * np.sqrt(252) * 100  # Annualized
    sharpe_ratio = calculate_sharpe_ratio(returns)
    sortino_ratio = calculate_sortino_ratio(returns)
    max_drawdown = calculate_max_drawdown(equity_curve)
    
    # Trade statistics
    total_trades = len(trades)
    avg_trade_duration = trades['duration'].mean()
    avg_profit = trades['profit'].mean()
    avg_win = trades[trades['profit'] > 0]['profit'].mean()
    avg_loss = trades[trades['profit'] < 0]['profit'].mean()
    
    # Additional metrics
    kelly_criterion = calculate_kelly_criterion(win_rate, avg_win, avg_loss)
    recovery_factor = calculate_recovery_factor(equity_curve)
    profit_per_day = calculate_profit_per_day(trades)
    
    return {
        'total_return': round(total_return, 2),
        'win_rate': round(win_rate, 2),
        'profit_factor': round(profit_factor, 2),
        'volatility': round(volatility, 2),
        'sharpe_ratio': round(sharpe_ratio, 2),
        'sortino_ratio': round(sortino_ratio, 2),
        'max_drawdown': round(max_drawdown, 2),
        'total_trades': total_trades,
        'avg_trade_duration': round(avg_trade_duration, 2),
        'avg_profit': round(avg_profit, 2),
        'avg_win': round(avg_win, 2),
        'avg_loss': round(avg_loss, 2),
        'kelly_criterion': round(kelly_criterion, 2),
        'recovery_factor': round(recovery_factor, 2),
        'profit_per_day': round(profit_per_day, 2)
    }

def calculate_sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.02) -> float:
    """Calculate Sharpe ratio."""
    excess_returns = returns - risk_free_rate/252
    return np.sqrt(252) * excess_returns.mean() / excess_returns.std()

def calculate_sortino_ratio(returns: pd.Series, risk_free_rate: float = 0.02) -> float:
    """Calculate Sortino ratio."""
    excess_returns = returns - risk_free_rate/252
    downside_returns = excess_returns[excess_returns < 0]
    if len(downside_returns) == 0:
        return 0
    return np.sqrt(252) * excess_returns.mean() / downside_returns.std()

def calculate_max_drawdown(equity_curve: pd.Series) -> float:
    """Calculate maximum drawdown."""
    rolling_max = equity_curve.expanding().max()
    drawdowns = (equity_curve - rolling_max) / rolling_max
    return abs(drawdowns.min() * 100)

def calculate_kelly_criterion(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """Calculate Kelly Criterion for position sizing."""
    if avg_loss == 0:
        return 0
    return (win_rate/100) - ((1 - win_rate/100) / (abs(avg_win/avg_loss)))

def calculate_recovery_factor(equity_curve: pd.Series) -> float:
    """Calculate recovery factor (net profit / max drawdown)."""
    max_drawdown = calculate_max_drawdown(equity_curve)
    if max_drawdown == 0:
        return 0
    net_profit = (equity_curve.iloc[-1] / equity_curve.iloc[0] - 1) * 100
    return net_profit / max_drawdown

def calculate_profit_per_day(trades: pd.DataFrame) -> float:
    """Calculate average profit per trading day."""
    if len(trades) == 0:
        return 0
    total_days = (trades['exit_time'].max() - trades['entry_time'].min()).days
    if total_days == 0:
        return 0
    total_profit = trades['profit'].sum()
    return total_profit / total_days

def calculate_trade_distribution(trades: pd.DataFrame) -> Dict[str, Any]:
    """Calculate trade distribution statistics."""
    if len(trades) == 0:
        return {}
    
    # Profit distribution
    profit_bins = np.linspace(trades['profit'].min(), trades['profit'].max(), 10)
    profit_dist = np.histogram(trades['profit'], bins=profit_bins)
    
    # Duration distribution
    duration_bins = np.linspace(0, trades['duration'].max(), 10)
    duration_dist = np.histogram(trades['duration'], bins=duration_bins)
    
    # Time of day distribution
    trades['hour'] = trades['entry_time'].dt.hour
    hour_dist = trades['hour'].value_counts().sort_index()
    
    return {
        'profit_distribution': {
            'bins': profit_bins.tolist(),
            'counts': profit_dist[0].tolist()
        },
        'duration_distribution': {
            'bins': duration_bins.tolist(),
            'counts': duration_dist[0].tolist()
        },
        'hour_distribution': {
            'hours': hour_dist.index.tolist(),
            'counts': hour_dist.values.tolist()
        }
    }
