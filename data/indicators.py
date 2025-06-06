import numpy as np
import pandas as pd
from scipy.stats import zscore
from typing import List, Tuple, Union, Dict, Optional, Any, TYPE_CHECKING
import logging
import os
import json
from datetime import datetime, timedelta, timezone
import sqlite3
import httpx
import asyncio
from finta import TA

from data.token_database import TokenDatabase
from config.logging_config import LoggingConfig
from utils.logger import get_logger
from config.thresholds import Thresholds

# Remove premature logging setup
# LoggingConfig.setup_logging()
logger = get_logger(__name__)

# Import Settings for type hinting only
if TYPE_CHECKING:
    from config.settings import Settings # Ensure this line exists
    # Add other necessary imports for hints if needed
    from data.token_database import TokenDatabase
    from config.thresholds import Thresholds # Add Thresholds hint

# REMOVE module-level get_env call
# DEXSCREENER_API_URL = get_env("DEXSCREENER_API_URL")
# DEXSCREENER_OHLCV_URL = f"{DEXSCREENER_API_URL}/latest/dex/candles/" # This needs to be constructed using settings later

class Indicators:
    """
    A collection of technical indicators for trading systems.
    Uses httpx client for fetching external data like OHLCV.
    """

    def __init__(self, settings: 'Settings', thresholds: 'Thresholds', db: Optional['TokenDatabase'] = None, http_client: Optional[httpx.AsyncClient] = None):
        """
        Initializes the Indicators class.

        Args:
            settings: The application settings instance.
            thresholds: The application thresholds instance.
            db: An optional instance of TokenDatabase.
            http_client: An optional instance of httpx.AsyncClient for making API calls.
        """
        self.settings = settings
        self.db = db
        self.http_client = http_client
        self.thresholds = thresholds
        logger.info("Indicators class instance created")
        
    async def initialize(self) -> bool:
        """
        Initialize the indicators component.
        
        Returns:
            bool: True if initialization was successful, False otherwise
        """
        try:
            logger.info("Initializing Indicators")
            
            # Create HTTP client if not provided
            if not self.http_client:
                # Use timeout from settings
                timeout_value = getattr(self.settings, 'HTTP_TIMEOUT', 30.0) # Default 30s
                self.http_client = httpx.AsyncClient(timeout=timeout_value)
                logger.info(f"Created HTTP client for Indicators with timeout {timeout_value}s")
                
            # Create DB connection if not provided
            if not self.db:
                # Now create db instance using settings
                # TokenDatabase now reads settings internally
                self.db = TokenDatabase()
                self.logger.info(f"Indicators initialized database connection using settings.")

                # Assuming TokenDatabase needs explicit initialization
                if hasattr(self.db, 'initialize'):
                    await self.db.initialize() # Assuming initialize is async
                logger.info("Created database connection for Indicators")
                
            logger.info("Indicators initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error initializing Indicators: {e}", exc_info=True)
            # Allow continuation despite error?
            return True # Or False depending on desired robustness
            
    async def close(self):
        """
        Close resources used by the indicators component.
        """
        try:
            if self.http_client:
                await self.http_client.aclose()
                self.http_client = None
                logger.info("Closed HTTP client for Indicators")
            # Close DB if needed? Depends on how DB connection is managed.
            # if self.db and hasattr(self.db, 'close'):
            #     await self.db.close()
            #     logger.info("Closed DB connection for Indicators")
                
        except Exception as e:
            logger.error(f"Error closing Indicators resources: {e}")

    async def _fetch_ohlcv_data(self, pair_address: str, timeframe: str = 'h1', limit: int = 100) -> Optional[pd.DataFrame]:
        """
        Fetches OHLCV data for a given pair address from DexScreener asynchronously.
        """
        if not pair_address:
            logger.error("Pair address is required to fetch OHLCV data.")
            return None

        # Construct URL using settings
        try:
            base_url = self.settings.DEXSCREENER_API_URL
            ohlcv_url_base = f"{base_url}/latest/dex/candles/"
        except AttributeError:
            logger.error("DEXSCREENER_API_URL not found in settings. Cannot fetch OHLCV.")
            return None

        url = f"{ohlcv_url_base}{pair_address}?resolution={timeframe}&limit={limit}"
        logger.debug(f"Fetching OHLCV data from: {url}")

        # Ensure client is initialized
        if not self.http_client:
             logger.error("HTTP client not initialized in Indicators. Cannot fetch OHLCV.")
             # Attempt to initialize it here? Or rely on external initialization.
             await self.initialize() # Try initializing if not done
             if not self.http_client:
                 return None # Still failed

        try:
            response = await self.http_client.get(url)
            response.raise_for_status() 
            data = response.json()

            if data and data.get("candles"):
                candles = data["candles"]
                if not candles:
                    logger.warning(f"No candles returned for {pair_address} with timeframe {timeframe}")
                    return None

                df = pd.DataFrame(candles)
                # Convert timestamp (assuming Unix seconds from DexScreener) to datetime (UTC)
                df['timestamp'] = pd.to_datetime(df['ts'], unit='s', utc=True)
                # Select and rename columns to standard OHLCV
                df = df[['timestamp', 'o', 'h', 'l', 'c', 'v']]
                df.columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
                # Convert OHLCV columns to numeric, coercing errors to NaN
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = pd.to_numeric(df[col], errors='coerce')

                # Drop rows with NaN in critical OHLC columns if necessary
                df.dropna(subset=['open', 'high', 'low', 'close'], inplace=True)

                if df.empty:
                     logger.warning(f"DataFrame became empty after processing for {pair_address} TF {timeframe}")
                     return None

                df.set_index('timestamp', inplace=True) # Set timestamp as index
                df.sort_index(inplace=True) # Ensure data is sorted chronologically
                logger.info(f"Successfully fetched and processed {len(df)} OHLCV candles for {pair_address} TF {timeframe}")
                return df
            else:
                logger.warning(f"No 'candles' key found or empty candles in response for {pair_address} TF {timeframe}")
                return None

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching OHLCV for {pair_address} TF {timeframe}: {e.response.status_code} - {e.response.text}")
            return None
        except httpx.RequestError as e:
            logger.error(f"Request error fetching OHLCV for {pair_address} TF {timeframe}: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error fetching OHLCV for {pair_address} TF {timeframe}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error processing OHLCV data for {pair_address} TF {timeframe}: {e}", exc_info=True)
            return None

    # --- Static Indicator Calculation Methods ---
    # These methods operate purely on pandas Series/DataFrames

    @staticmethod
    def sma(prices: pd.Series, period: int) -> pd.Series:
        """Calculate Simple Moving Average (SMA)."""
        if len(prices) < period:
            return pd.Series(dtype=float) # Not enough data
        return prices.rolling(window=period).mean()

    @staticmethod
    def ema(prices: pd.Series, period: int) -> pd.Series:
        """Calculate Exponential Moving Average (EMA)."""
        if len(prices) < period:
            return pd.Series(dtype=float)
        return prices.ewm(span=period, adjust=False).mean()

    @staticmethod
    def rsi(prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculate Relative Strength Index (RSI)."""
        if len(prices) <= period:
            return pd.Series(dtype=float)

        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

        rs = gain / loss
        rsi_series = 100 - (100 / (1 + rs))
        # Handle potential division by zero if loss is zero for the entire period
        rsi_series.replace([np.inf, -np.inf], 100, inplace=True) # If gain>0, loss=0 -> RSI=100
        rsi_series.fillna(50, inplace=True) # Handle initial NaNs or cases where gain=loss=0

        return rsi_series

    @staticmethod
    def macd(prices: pd.Series, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Calculate Moving Average Convergence Divergence (MACD)."""
        if len(prices) < slow_period:
            return pd.Series(dtype=float), pd.Series(dtype=float), pd.Series(dtype=float) # Not enough data

        ema_fast = Indicators.ema(prices, fast_period)
        ema_slow = Indicators.ema(prices, slow_period)
        macd_line = ema_fast - ema_slow
        signal_line = Indicators.ema(macd_line, signal_period)
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    @staticmethod
    def bollinger_bands(prices: pd.Series, period: int = 20, std_dev: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Calculate Bollinger Bands."""
        if len(prices) < period:
            return pd.Series(dtype=float), pd.Series(dtype=float), pd.Series(dtype=float) # Not enough data

        sma = Indicators.sma(prices, period)
        rolling_std = prices.rolling(window=period).std()
        upper_band = sma + (rolling_std * std_dev)
        lower_band = sma - (rolling_std * std_dev)
        return upper_band, sma, lower_band # Upper, Middle, Lower

    @staticmethod
    def atr(highs: pd.Series, lows: pd.Series, closes: pd.Series, period: int = 14) -> pd.Series:
        """Calculate Average True Range (ATR)."""
        if len(highs) < period + 1: # Need at least period+1 for shift()
            return pd.Series(dtype=float)

        high_low = highs - lows
        high_close = np.abs(highs - closes.shift())
        low_close = np.abs(lows - closes.shift())

        # Combine the three components to find the True Range (TR)
        tr = pd.DataFrame({'hl': high_low, 'hc': high_close, 'lc': low_close}).max(axis=1)

        # Calculate ATR using Exponential Moving Average (common method)
        # alpha = 1 / period
        # atr_series = tr.ewm(alpha=alpha, adjust=False).mean()
        # Alternatively, use Simple Moving Average for ATR
        atr_series = tr.rolling(window=period).mean()

        return atr_series

    @staticmethod
    def adx(highs: pd.Series, lows: pd.Series, closes: pd.Series, period: int = 14) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        Calculate Average Directional Index (ADX).
        
        Returns:
            Tuple[pd.Series, pd.Series, pd.Series]: ADX, +DI, -DI
        """
        if len(highs) < period + 1:
            return pd.Series(dtype=float), pd.Series(dtype=float), pd.Series(dtype=float)
            
        # Calculate True Range
        tr = Indicators.atr(highs, lows, closes, period)
        
        # Calculate +DM and -DM
        high_diff = highs.diff()
        low_diff = lows.diff()
        
        plus_dm = pd.Series(0.0, index=highs.index)
        minus_dm = pd.Series(0.0, index=highs.index)
        
        # +DM = High - High(prev) if High - High(prev) > Low(prev) - Low and High - High(prev) > 0
        plus_dm[high_diff > low_diff.abs()] = high_diff[high_diff > low_diff.abs()]
        plus_dm[high_diff <= 0] = 0
        
        # -DM = Low(prev) - Low if Low(prev) - Low > High - High(prev) and Low(prev) - Low > 0
        minus_dm[low_diff.abs() > high_diff] = low_diff.abs()[low_diff.abs() > high_diff]
        minus_dm[low_diff >= 0] = 0
        
        # Calculate +DI and -DI
        plus_di = 100 * (plus_dm.rolling(window=period).mean() / tr)
        minus_di = 100 * (minus_dm.rolling(window=period).mean() / tr)
        
        # Calculate ADX
        dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di))
        adx = dx.rolling(window=period).mean()
        
        return adx, plus_di, minus_di

    @staticmethod
    def stochastic(highs: pd.Series, lows: pd.Series, closes: pd.Series, k_period: int = 14, d_period: int = 3) -> Tuple[pd.Series, pd.Series]:
        """
        Calculate Stochastic Oscillator.
        
        Returns:
            Tuple[pd.Series, pd.Series]: %K, %D
        """
        if len(highs) < k_period:
            return pd.Series(dtype=float), pd.Series(dtype=float)
            
        # Calculate %K
        lowest_low = lows.rolling(window=k_period).min()
        highest_high = highs.rolling(window=k_period).max()
        
        k = 100 * ((closes - lowest_low) / (highest_high - lowest_low))
        
        # Calculate %D (SMA of %K)
        d = k.rolling(window=d_period).mean()
        
        return k, d

    @staticmethod
    def calculate_volatility(prices: pd.Series, period: int = 20) -> pd.Series:
        """Calculate price volatility as standard deviation of returns."""
        if len(prices) < period + 1:
            return pd.Series(dtype=float)
            
        returns = prices.pct_change()
        volatility = returns.rolling(window=period).std()
        return volatility

    @staticmethod
    def calculate_net_volume(volume: pd.Series, closes: pd.Series, period: int = 20) -> pd.Series:
        """
        Calculate net volume (buying vs selling volume).
        
        Args:
            volume: Volume series
            closes: Close price series
            period: Period for calculation
            
        Returns:
            pd.Series: Net volume (positive for buying, negative for selling)
        """
        if len(volume) < period:
            return pd.Series(dtype=float)
            
        # Calculate price change
        price_change = closes.diff()
        
        # Determine if volume is buying or selling based on price change
        buying_volume = volume.copy()
        selling_volume = volume.copy()
        
        # If price went up, consider it buying volume
        buying_volume[price_change <= 0] = 0
        # If price went down, consider it selling volume
        selling_volume[price_change >= 0] = 0
        
        # Calculate net volume
        net_volume = buying_volume - selling_volume
        
        # Calculate moving average of net volume
        net_volume_ma = net_volume.rolling(window=period).mean()
        
        return net_volume_ma

    @staticmethod
    def calculate_volume_trend(volume: pd.Series, period: int = 20) -> pd.Series:
        """
        Calculate volume trend as the slope of volume over time.
        
        Args:
            volume: Volume series
            period: Period for calculation
            
        Returns:
            pd.Series: Volume trend (positive for increasing, negative for decreasing)
        """
        if len(volume) < period:
            return pd.Series(dtype=float)
            
        # Calculate volume moving average
        volume_ma = volume.rolling(window=period).mean()
        
        # Calculate volume trend as the difference between current and previous MA
        volume_trend = volume_ma.diff()
        
        return volume_trend

    @staticmethod
    def calculate_price_momentum(prices: pd.Series, period: int = 10) -> pd.Series:
        """
        Calculate price momentum as the percentage change over a period.
        
        Args:
            prices: Price series
            period: Period for calculation
            
        Returns:
            pd.Series: Price momentum (positive for upward, negative for downward)
        """
        if len(prices) < period:
            return pd.Series(dtype=float)
            
        # Calculate momentum as percentage change over period
        momentum = prices.pct_change(periods=period) * 100
        
        return momentum

    @staticmethod
    def check_buy_signal(rsi: Optional[float], macd_hist: Optional[float], lower_bb: Optional[float], current_price: Optional[float], adx: Optional[float] = None) -> Tuple[bool, str]:
        """
        Check if current indicators suggest a buy signal.
        
        Args:
            rsi: Current RSI value
            macd_hist: Current MACD histogram value
            lower_bb: Current lower Bollinger Band value
            current_price: Current price
            adx: Current ADX value (optional)
            
        Returns:
            Tuple[bool, str]: (is_buy_signal, reason)
        """
        if None in (rsi, macd_hist, lower_bb, current_price):
            return False, "Missing indicator data"
            
        # Check for oversold RSI
        if rsi < 30:
            return True, "RSI oversold"
            
        # Check for MACD histogram turning positive
        if macd_hist > 0 and macd_hist > 0:
            return True, "MACD histogram positive"
            
        # Check for price near lower Bollinger Band
        if current_price <= lower_bb * 1.01:  # Within 1% of lower band
            return True, "Price near lower Bollinger Band"
            
        # Check for strong trend with ADX if available
        if adx is not None and adx > 25:
            return True, "Strong trend (ADX > 25)"
            
        return False, "No clear buy signal"

    @staticmethod
    def evaluate_token(
        token_address: str,
        price_history_df: Optional[pd.DataFrame] = None, # Expect DataFrame with 'close', 'high', 'low', 'volume'
        ohlcv_df: Optional[pd.DataFrame] = None # Alternative: Pass pre-fetched OHLCV
        ) -> Dict:
        """
        Evaluate a token using technical indicators.
        
        Args:
            token_address: Token address to evaluate
            price_history_df: DataFrame with price history
            ohlcv_df: Alternative: Pre-fetched OHLCV data
            
        Returns:
            Dict: Evaluation results with indicators and signals
        """
        try:
            # Use provided OHLCV data or price history
            if ohlcv_df is not None and not ohlcv_df.empty:
                df = ohlcv_df
            elif price_history_df is not None and not price_history_df.empty:
                df = price_history_df
            else:
                return {"error": "No price data available"}
                
            # Ensure we have the required columns
            required_cols = ['close', 'high', 'low', 'volume']
            if not all(col in df.columns for col in required_cols):
                return {"error": f"Missing required columns. Need: {required_cols}"}
                
            # Get the most recent data point
            latest = df.iloc[-1]
            current_price = latest['close']
            
            # Calculate RSI
            rsi = Indicators.rsi(df['close'])
            current_rsi = rsi.iloc[-1] if not rsi.empty else None
            
            # Calculate MACD
            macd_line, signal_line, histogram = Indicators.macd(df['close'])
            current_macd_hist = histogram.iloc[-1] if not histogram.empty else None
            
            # Calculate Bollinger Bands
            upper_band, middle_band, lower_band = Indicators.bollinger_bands(df['close'])
            current_lower_bb = lower_band.iloc[-1] if not lower_band.empty else None
            
            # Calculate ADX
            adx, plus_di, minus_di = Indicators.adx(df['high'], df['low'], df['close'])
            current_adx = adx.iloc[-1] if not adx.empty else None
            
            # Check for buy signal
            is_buy, reason = Indicators.check_buy_signal(
                current_rsi, current_macd_hist, current_lower_bb, current_price, current_adx
            )
            
            # Calculate volatility
            volatility = Indicators.calculate_volatility(df['close'])
            current_volatility = volatility.iloc[-1] if not volatility.empty else None
            
            # Calculate net volume
            net_volume = Indicators.calculate_net_volume(df['volume'], df['close'])
            current_net_volume = net_volume.iloc[-1] if not net_volume.empty else None
            
            # Calculate volume trend
            volume_trend = Indicators.calculate_volume_trend(df['volume'])
            current_volume_trend = volume_trend.iloc[-1] if not volume_trend.empty else None
            
            # Calculate price momentum
            price_momentum = Indicators.calculate_price_momentum(df['close'])
            current_momentum = price_momentum.iloc[-1] if not price_momentum.empty else None
            
            # Return evaluation results
            return {
                "token_address": token_address,
                "current_price": current_price,
                "indicators": {
                    "rsi": current_rsi,
                    "macd_histogram": current_macd_hist,
                    "bollinger_bands": {
                        "upper": upper_band.iloc[-1] if not upper_band.empty else None,
                        "middle": middle_band.iloc[-1] if not middle_band.empty else None,
                        "lower": current_lower_bb
                    },
                    "adx": current_adx,
                    "volatility": current_volatility,
                    "net_volume": current_net_volume,
                    "volume_trend": current_volume_trend,
                    "price_momentum": current_momentum
                },
                "signals": {
                    "is_buy": is_buy,
                    "reason": reason
                }
            }
            
        except Exception as e:
            logger.error(f"Error evaluating token {token_address}: {e}")
            return {"error": str(e)}

    async def get_category_specific_indicators(self, token_address: str, category: str, pair_address: str = None) -> Dict[str, Any]:
        """
        Get technical indicators specific to a token category.
        
        Args:
            token_address: Token address
            category: Token category (FRESH, NEW, FINAL, MIGRATED, OLD)
            pair_address: Optional pair address for fetching OHLCV data
            
        Returns:
            Dict: Category-specific indicators
        """
        try:
            # Fetch OHLCV data if pair_address is provided
            ohlcv_df = None
            if pair_address:
                ohlcv_df = await self._fetch_ohlcv_data(pair_address, timeframe='m5', limit=100)
            
            # Get category-specific parameters
            if category == 'FRESH':
                rsi_period = self.thresholds.FRESH_RSI_PERIOD
                rsi_overbought = self.thresholds.FRESH_RSI_OVERBOUGHT
                rsi_oversold = self.thresholds.FRESH_RSI_OVERSOLD
                volume_ma_period = self.thresholds.FRESH_VOLUME_MA_PERIOD
                price_ma_period = self.thresholds.FRESH_PRICE_MA_PERIOD
            elif category == 'NEW':
                rsi_period = self.thresholds.NEW_RSI_PERIOD
                rsi_overbought = self.thresholds.NEW_RSI_OVERBOUGHT
                rsi_oversold = self.thresholds.NEW_RSI_OVERSOLD
                volume_ma_period = self.thresholds.NEW_VOLUME_MA_PERIOD
                price_ma_period = self.thresholds.NEW_PRICE_MA_PERIOD
            elif category == 'FINAL':
                rsi_period = self.thresholds.FINAL_RSI_PERIOD
                rsi_overbought = self.thresholds.FINAL_RSI_OVERBOUGHT
                rsi_oversold = self.thresholds.FINAL_RSI_OVERSOLD
                volume_ma_period = self.thresholds.FINAL_VOLUME_MA_PERIOD
                price_ma_period = self.thresholds.FINAL_PRICE_MA_PERIOD
            elif category == 'MIGRATED':
                rsi_period = self.thresholds.MIGRATED_RSI_PERIOD
                rsi_overbought = self.thresholds.MIGRATED_RSI_OVERBOUGHT
                rsi_oversold = self.thresholds.MIGRATED_RSI_OVERSOLD
                volume_ma_period = self.thresholds.MIGRATED_VOLUME_MA_PERIOD
                price_ma_period = self.thresholds.MIGRATED_PRICE_MA_PERIOD
            elif category == 'OLD':
                rsi_period = self.thresholds.OLD_RSI_PERIOD
                rsi_overbought = self.thresholds.OLD_RSI_OVERBOUGHT
                rsi_oversold = self.thresholds.OLD_RSI_OVERSOLD
                volume_ma_period = self.thresholds.OLD_VOLUME_MA_PERIOD
                price_ma_period = self.thresholds.OLD_PRICE_MA_PERIOD
            else:
                # Default to standard parameters
                rsi_period = 14
                rsi_overbought = 70
                rsi_oversold = 30
                volume_ma_period = 20
                price_ma_period = 20
            
            # Get price data from database if OHLCV data not available
            if ohlcv_df is None:
                # Try to get price history from database
                price_history = await self.db.get_price_history(token_address, limit=100)
                if price_history:
                    # Convert to DataFrame
                    ohlcv_df = pd.DataFrame(price_history)
                    ohlcv_df['timestamp'] = pd.to_datetime(ohlcv_df['timestamp'])
                    ohlcv_df.set_index('timestamp', inplace=True)
                    ohlcv_df.sort_index(inplace=True)
            
            if ohlcv_df is None or ohlcv_df.empty:
                return {"error": "No price data available"}
            
            # Calculate indicators with category-specific parameters
            rsi = self.rsi(ohlcv_df['close'], period=rsi_period)
            current_rsi = rsi.iloc[-1] if not rsi.empty else None
            
            # Calculate SMAs
            price_sma = self.sma(ohlcv_df['close'], period=price_ma_period)
            volume_sma = self.sma(ohlcv_df['volume'], period=volume_ma_period)
            
            # Calculate MACD with category-specific parameters
            macd_line, signal_line, histogram = self.macd(
                ohlcv_df['close'], 
                fast_period=self.thresholds.MACD_FAST_PERIOD,
                slow_period=self.thresholds.MACD_SLOW_PERIOD,
                signal_period=self.thresholds.MACD_SIGNAL_PERIOD
            )
            
            # Calculate Bollinger Bands
            upper_band, middle_band, lower_band = self.bollinger_bands(
                ohlcv_df['close'],
                period=self.thresholds.BB_PERIOD,
                std_dev=self.thresholds.BB_STD_DEV
            )
            
            # Calculate net volume
            net_volume = self.calculate_net_volume(ohlcv_df['volume'], ohlcv_df['close'])
            current_net_volume = net_volume.iloc[-1] if not net_volume.empty else None
            
            # Calculate volume trend
            volume_trend = self.calculate_volume_trend(ohlcv_df['volume'])
            current_volume_trend = volume_trend.iloc[-1] if not volume_trend.empty else None
            
            # Calculate price momentum
            price_momentum = self.calculate_price_momentum(ohlcv_df['close'])
            current_momentum = price_momentum.iloc[-1] if not price_momentum.empty else None
            
            # Get current values
            current_price = ohlcv_df['close'].iloc[-1]
            current_volume = ohlcv_df['volume'].iloc[-1]
            current_macd_hist = histogram.iloc[-1] if not histogram.empty else None
            current_price_sma = price_sma.iloc[-1] if not price_sma.empty else None
            current_volume_sma = volume_sma.iloc[-1] if not volume_sma.empty else None
            
            # Determine if price is above/below SMA
            price_above_sma = current_price > current_price_sma if current_price_sma is not None else None
            
            # Determine if volume is above/below SMA
            volume_above_sma = current_volume > current_volume_sma if current_volume_sma is not None else None
            
            # Check for exit signals based on category-specific thresholds
            exit_signals = []
            
            # RSI overbought/oversold
            if current_rsi is not None:
                if current_rsi >= rsi_overbought:
                    exit_signals.append(f"RSI overbought ({current_rsi:.2f} >= {rsi_overbought})")
                elif current_rsi <= rsi_oversold:
                    exit_signals.append(f"RSI oversold ({current_rsi:.2f} <= {rsi_oversold})")
            
            # Net volume negative
            if current_net_volume is not None and current_net_volume < self.thresholds.NET_VOLUME_THRESHOLD:
                exit_signals.append(f"Negative net volume ({current_net_volume:.2f} < {self.thresholds.NET_VOLUME_THRESHOLD})")
            
            # Volume trend decreasing
            if current_volume_trend is not None and current_volume_trend < self.thresholds.VOLUME_TREND_THRESHOLD:
                exit_signals.append(f"Volume trend decreasing ({current_volume_trend:.2f} < {self.thresholds.VOLUME_TREND_THRESHOLD})")
            
            # Price momentum negative
            if current_momentum is not None and current_momentum < self.thresholds.PRICE_MOMENTUM_THRESHOLD:
                exit_signals.append(f"Price momentum negative ({current_momentum:.2f} < {self.thresholds.PRICE_MOMENTUM_THRESHOLD})")
            
            # MACD bearish
            if current_macd_hist is not None and current_macd_hist < 0:
                exit_signals.append(f"MACD bearish ({current_macd_hist:.2f} < 0)")
            
            # Price below SMA
            if price_above_sma is False:
                exit_signals.append("Price below SMA")
            
            # Return category-specific indicators
            return {
                "token_address": token_address,
                "category": category,
                "current_price": current_price,
                "current_volume": current_volume,
                "indicators": {
                    "rsi": {
                        "value": current_rsi,
                        "period": rsi_period,
                        "overbought": rsi_overbought,
                        "oversold": rsi_oversold
                    },
                    "macd": {
                        "histogram": current_macd_hist,
                        "fast_period": self.thresholds.MACD_FAST_PERIOD,
                        "slow_period": self.thresholds.MACD_SLOW_PERIOD,
                        "signal_period": self.thresholds.MACD_SIGNAL_PERIOD
                    },
                    "bollinger_bands": {
                        "upper": upper_band.iloc[-1] if not upper_band.empty else None,
                        "middle": middle_band.iloc[-1] if not middle_band.empty else None,
                        "lower": lower_band.iloc[-1] if not lower_band.empty else None,
                        "period": self.thresholds.BB_PERIOD,
                        "std_dev": self.thresholds.BB_STD_DEV
                    },
                    "sma": {
                        "price": {
                            "value": current_price_sma,
                            "period": price_ma_period,
                            "price_above_sma": price_above_sma
                        },
                        "volume": {
                            "value": current_volume_sma,
                            "period": volume_ma_period,
                            "volume_above_sma": volume_above_sma
                        }
                    },
                    "net_volume": current_net_volume,
                    "volume_trend": current_volume_trend,
                    "price_momentum": current_momentum
                },
                "exit_signals": exit_signals,
                "should_exit": len(exit_signals) > 0
            }
            
        except Exception as e:
            logger.error(f"Error getting category-specific indicators for {token_address}: {e}")
            return {"error": str(e)}

class TechnicalIndicators(Indicators):
    """
    Specialized class inheriting from Indicators for technical analysis.
    May add specific methods or overrides relevant to trading strategies.
    """
    def __init__(self, settings: 'Settings', thresholds: 'Thresholds', db: Optional['TokenDatabase'] = None, http_client: Optional[httpx.AsyncClient] = None):
        """
        Initializes the TechnicalIndicators class.
        
        Args:
            settings: The application settings instance.
            thresholds: The application thresholds instance.
            db: An optional instance of TokenDatabase.
            http_client: An optional instance of httpx.AsyncClient for making API calls.
        """
        # Pass thresholds to the parent __init__
        super().__init__(settings, thresholds, db, http_client)
        self.logger = get_logger(__name__) # Get logger specific to this subclass
        # Add any specific initialization for TechnicalIndicators here
        self.logger.info("TechnicalIndicators initialized.")
        # Validation can remain here or be moved to base class if applicable to both
        try:
            _ = self.settings.TAKE_PROFIT_PCT 
            _ = self.settings.STOP_LOSS_PCT
            _ = self.settings.TRAILING_STOP_PCT 
            logger.debug("Required strategy parameters found in settings.")
        except AttributeError as e:
            logger.error(f"Missing required strategy parameter in settings: {e}")

    def calculate_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate all supported technical indicators."""
        if df.empty or 'close' not in df.columns:
            logger.warning("DataFrame is empty or missing 'close' column for indicator calculation.")
            return df

        try:
            # Ensure 'close' is float type
            df['close'] = pd.to_numeric(df['close'], errors='coerce')
            df.dropna(subset=['close'], inplace=True)
            if df.empty:
                logger.warning("DataFrame became empty after converting 'close' to numeric and dropping NaNs.")
                return df

            # Calculate indicators using finta
            # Note: finta typically returns a Series, which needs to be assigned to the DataFrame.
            # Input DataFrame for finta usually needs columns: 'open', 'high', 'low', 'close', 'volume' (case-insensitive)
            # Let's ensure columns are lowercase for compatibility, although finta might handle it.
            df.columns = map(str.lower, df.columns)

            # Basic SMAs
            # finta.TA.SMA(df, period=10) -> Returns a Series
            df['SMA_10'] = TA.SMA(df, period=10)
            df['SMA_20'] = TA.SMA(df, period=20)
            df['SMA_50'] = TA.SMA(df, period=50)

            # RSI
            # finta.TA.RSI(df, period=14) -> Returns a Series
            df['RSI_14'] = TA.RSI(df, period=14)

            # MACD
            # finta.TA.MACD(df, period_fast=12, period_slow=26, signal=9) -> Returns a DataFrame with 'MACD' and 'SIGNAL' columns
            macd_df = TA.MACD(df, period_fast=12, period_slow=26, signal=9)
            df['MACD_12_26_9'] = macd_df['MACD']
            df['MACDs_12_26_9'] = macd_df['SIGNAL']
            df['MACDh_12_26_9'] = df['MACD_12_26_9'] - df['MACDs_12_26_9'] # Calculate histogram manually

            # Bollinger Bands
            # finta.TA.BBANDS(df, period=20, std_multiplier=2) -> Returns a DataFrame with 'BB_UPPER', 'BB_MIDDLE', 'BB_LOWER'
            # Note: finta uses 'std_multiplier', pandas-ta used 'std'
            bbands_df = TA.BBANDS(df, period=20, std_multiplier=2.0)
            df['BBL_20_2.0'] = bbands_df['BB_LOWER']
            df['BBM_20_2.0'] = bbands_df['BB_MIDDLE']
            df['BBU_20_2.0'] = bbands_df['BB_UPPER']
            # pandas-ta also calculated BBB (bandwidth) and BBP (percent), finta doesn't directly.
            # We can calculate them if needed:
            df['BBB_20_2.0'] = ((df['BBU_20_2.0'] - df['BBL_20_2.0']) / df['BBM_20_2.0']) * 100
            df['BBP_20_2.0'] = (df['close'] - df['BBL_20_2.0']) / (df['BBU_20_2.0'] - df['BBL_20_2.0'])

            # Volume SMA (if available)
            if 'volume' in df.columns:
                df['volume'] = pd.to_numeric(df['volume'], errors='coerce')
                # finta.TA.SMA(df, period=20, column='volume') -> Returns Series
                df['VOL_SMA_20'] = TA.SMA(df, period=20, column='volume')
            else:
                logger.debug("'volume' column not found, skipping volume-based indicators.")

            # ADX (if available)
            # finta.TA.ADX(df, period=14) -> Returns a DataFrame with 'ADX', '+DI', '-DI'
            if all(col in df.columns for col in ['high', 'low', 'close']):
                for col in ['high', 'low']:
                     df[col] = pd.to_numeric(df[col], errors='coerce')
                df.dropna(subset=['high', 'low', 'close'], inplace=True) # Ensure close is also checked for dropna
                if not df.empty:
                     adx_df = TA.ADX(df, period=14)
                     # pandas-ta named columns DMP_14, DMN_14. finta uses +DI, -DI.
                     df['ADX_14'] = adx_df['ADX']
                     df['DMP_14'] = adx_df['+DI'] # Renaming +DI to match previous convention
                     df['DMN_14'] = adx_df['-DI'] # Renaming -DI to match previous convention
            else:
                 logger.debug("'high' or 'low' or 'close' columns not found or data insufficient, skipping ADX calculation.")

            logger.debug(f"Calculated indicators using finta. DataFrame shape: {df.shape}")

        except Exception as e:
            logger.error(f"Error calculating technical indicators: {e}", exc_info=True)
            # Return original df or df with successfully calculated indicators up to the error point
        
        return df

    def apply_stop_loss_take_profit(self, entry_price: float, current_price: float, position_type: str) -> tuple[Optional[float], Optional[float]]:
        """Calculate stop-loss and take-profit levels based on settings."""
        
        try:
            take_profit_pct = self.settings.TAKE_PROFIT_PCT
            stop_loss_pct = self.settings.STOP_LOSS_PCT
        except AttributeError as e:
             logger.error(f"Missing SL/TP setting: {e}. Cannot apply SL/TP.")
             return None, None
             
        if not (all(isinstance(p, (int, float)) for p in [entry_price, current_price, take_profit_pct, stop_loss_pct])):
            logger.error(f"Invalid input types for SL/TP calculation: entry={entry_price}, current={current_price}, tp%={take_profit_pct}, sl%={stop_loss_pct}")
            return None, None

        stop_loss_price = None
        take_profit_price = None

        if position_type == 'long':
            stop_loss_price = entry_price * (1 - stop_loss_pct)
            take_profit_price = entry_price * (1 + take_profit_pct)
        elif position_type == 'short':
            stop_loss_price = entry_price * (1 + stop_loss_pct)
            take_profit_price = entry_price * (1 - take_profit_pct)
        else:
            logger.warning(f"Invalid position_type '{position_type}' for SL/TP calculation.")
            return None, None

        return stop_loss_price, take_profit_price

    def apply_trailing_stop_loss(self, entry_price: float, current_high: float, current_price: float, position_type: str) -> Optional[float]:
        """Calculate trailing stop loss based on settings and current high/low."""
        try:
            trailing_stop_pct = self.settings.TRAILING_STOP_PCT
        except AttributeError:
             logger.error(f"Missing TRAILING_STOP_PCT setting. Cannot apply trailing SL.")
             return None

        if not (all(isinstance(p, (int, float)) for p in [entry_price, current_high, current_price, trailing_stop_pct])):
             logger.error("Invalid input types for trailing SL calculation.")
             return None

        trailing_stop_price = None
        if position_type == 'long':
             activation_price = entry_price * (1 + trailing_stop_pct) # Example activation
             if current_price > activation_price:
                 potential_tsl = current_high * (1 - trailing_stop_pct)
                 trailing_stop_price = potential_tsl # Simplified
        else:
             logger.warning(f"Trailing stop loss not implemented for position_type '{position_type}'.")

        return trailing_stop_price
