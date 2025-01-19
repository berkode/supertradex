import numpy as np
import pandas as pd
from scipy.stats import zscore
from typing import List, Tuple, Union

class Indicators:
    """
    A collection of technical indicators for trading systems. 
    Optimized for high-performance and real-world trading scenarios.
    """

    @staticmethod
    def support_resistance_levels(prices: pd.Series, period: int = 14) -> List[Tuple[int, float]]:
        """Identify support and resistance levels based on historical price action."""
        if len(prices) < period * 2:
            raise ValueError("Insufficient data for calculating support and resistance levels.")
        levels = []
        for i in range(period, len(prices) - period):
            high = max(prices[i - period:i + period])
            low = min(prices[i - period:i + period])
            if prices[i] == high or prices[i] == low:
                levels.append((i, prices[i]))
        return levels

    @staticmethod
    def volume_profile(prices: pd.Series, volumes: pd.Series, bins: int = 10) -> List[Tuple[float, float]]:
        """Calculate volume profile to identify key trading levels."""
        if len(prices) != len(volumes):
            raise ValueError("Prices and volumes must have the same length.")
        hist, bin_edges = np.histogram(prices, bins=bins, weights=volumes)
        return list(zip(bin_edges[:-1], hist))

    @staticmethod
    def fibonacci_retracement(prices: pd.Series) -> List[float]:
        """Calculate Fibonacci retracement levels based on price extremes."""
        high = prices.max()
        low = prices.min()
        return [high - (high - low) * ratio for ratio in [0.236, 0.382, 0.5, 0.618, 0.786]]

    @staticmethod
    def average_true_range(highs: pd.Series, lows: pd.Series, closes: pd.Series, period: int = 14) -> pd.Series:
        """Calculate Average True Range (ATR) to assess market volatility."""
        tr = pd.DataFrame({
            'high-low': highs - lows,
            'high-close': abs(highs - closes.shift(1)),
            'low-close': abs(lows - closes.shift(1))
        }).max(axis=1)
        return tr.rolling(window=period).mean()

    @staticmethod
    def relative_strength_index(prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculate Relative Strength Index (RSI) to evaluate overbought/oversold conditions."""
        delta = prices.diff()
        gain = delta.where(delta > 0, 0).rolling(window=period).mean()
        loss = -delta.where(delta < 0, 0).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def candlestick_patterns(data: pd.DataFrame) -> List[Tuple[int, str]]:
        """Identify candlestick patterns, such as hammers."""
        patterns = []
        for i in range(1, len(data)):
            if data['close'][i] > data['open'][i] and data['low'][i] == data['low'][i - 1]:
                patterns.append((i, 'Hammer'))
        return patterns

    @staticmethod
    def token_creation_time(token_start_time: str) -> pd.Timedelta:
        """Calculate the time since the token's creation."""
        return pd.Timestamp.now() - pd.Timestamp(token_start_time)

    @staticmethod
    def transaction_success_rate(wallet_transactions: List[dict]) -> float:
        """Analyze the success rate of transactions."""
        successful = sum(1 for tx in wallet_transactions if tx.get('status') == 'success')
        return successful / len(wallet_transactions)

    @staticmethod
    def trade_recency(trades: List[dict]) -> pd.Timestamp:
        """Identify the most recent trade time."""
        return max(trades, key=lambda x: x['time'])['time']

    @staticmethod
    def risk_reward_analysis(entry: float, stop_loss: float, take_profit: float) -> Union[float, None]:
        """Assess the risk/reward ratio for a trade."""
        risk = abs(entry - stop_loss)
        reward = abs(take_profit - entry)
        return reward / risk if risk > 0 else None

    @staticmethod
    def moving_averages(prices: pd.Series, period: int) -> pd.Series:
        """Calculate Simple Moving Average (SMA)."""
        return prices.rolling(window=period).mean()

    @staticmethod
    def macd(prices: pd.Series, short: int = 12, long: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series]:
        """Calculate MACD (Moving Average Convergence Divergence) and signal line."""
        short_ma = prices.ewm(span=short, adjust=False).mean()
        long_ma = prices.ewm(span=long, adjust=False).mean()
        macd_line = short_ma - long_ma
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        return macd_line, signal_line

    @staticmethod
    def adx(highs: pd.Series, lows: pd.Series, closes: pd.Series, period: int = 14) -> pd.Series:
        """Calculate Average Directional Index (ADX) to measure trend strength."""
        atr = Indicators.average_true_range(highs, lows, closes, period)
        plus_dm = highs.diff()
        minus_dm = lows.diff()
        plus_di = 100 * (plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0).rolling(window=period).mean() / atr)
        minus_di = 100 * (minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0).rolling(window=period).mean() / atr)
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        return dx.rolling(window=period).mean()

    @staticmethod
    def bollinger_bands(prices: pd.Series, period: int = 20) -> Tuple[pd.Series, pd.Series]:
        """Calculate Bollinger Bands to identify potential breakouts."""
        sma = prices.rolling(window=period).mean()
        std_dev = prices.rolling(window=period).std()
        upper_band = sma + (2 * std_dev)
        lower_band = sma - (2 * std_dev)
        return upper_band, lower_band

    @staticmethod
    def z_score(prices: pd.Series, window: int = 20) -> pd.Series:
        """Calculate Z-score for price deviation from the mean."""
        return (prices - prices.rolling(window).mean()) / prices.rolling(window).std()

    @staticmethod
    def price_channels(prices: pd.Series, period: int = 14) -> Tuple[pd.Series, pd.Series]:
        """Define breakout levels using price highs and lows."""
        high = prices.rolling(window=period).max()
        low = prices.rolling(window=period).min()
        return high, low

    @staticmethod
    def volume_analysis(volumes: pd.Series, period: int = 10) -> pd.Series:
        """Perform volume analysis over a rolling window."""
        return volumes.rolling(window=period).mean()

    @staticmethod
    def rsi_divergence(prices: pd.Series, rsi: pd.Series) -> List[int]:
        """Identify RSI divergence points."""
        divergences = []
        for i in range(1, len(prices)):
            if (prices[i] > prices[i - 1] and rsi[i] < rsi[i - 1]) or (prices[i] < prices[i - 1] and rsi[i] > rsi[i - 1]):
                divergences.append(i)
        return divergences
