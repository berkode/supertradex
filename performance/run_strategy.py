import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from .fetch_historical_data import SolanaDataFetcher
from typing import Optional, Dict, List, Callable
import os
import threading
import time
import websocket
import logging

logger = logging.getLogger(__name__)

class MemeTokenStrategy:
    def __init__(self, mint: str, initial_capital: float = 10000.0, settings: Optional[dict] = None, helius_api_key: Optional[str] = None):
        """Initialize meme token trading strategy."""
        self.mint = mint
        self.data_fetcher = SolanaDataFetcher(helius_api_key)
        self.realtime_ws: Optional[websocket.WebSocketApp] = None
        self.realtime_thread: Optional[threading.Thread] = None
        self.latest_data = None
        self.running = False

        self.capital = initial_capital
        self.settings = settings or {}
        self.trades = []
        self.position = 0
        self.entry_price = 0.0
        self.symbol = "UNKNOWN"
        logger.info(f"Initialized MemeTokenStrategy for {self.symbol} ({self.mint}) with capital: ${initial_capital:.2f}")

    def start_realtime_monitoring(self, callback: Callable[[Dict], None]):
        """
        Start real-time price monitoring.
        
        Args:
            callback: Function to handle incoming price updates
        """
        def process_update(data):
            self.latest_data = data
            callback(data)
            
        self.realtime_ws = self.data_fetcher.subscribe_to_realtime_data(
            self.mint,
            process_update
        )
        
        if not isinstance(self.realtime_ws, websocket.WebSocketApp):
            logger.error(f"Failed to establish WebSocket connection for {self.symbol} ({self.mint})")
            return
            
        def run_websocket():
            self.running = True
            logger.info(f"Starting WebSocket listener for {self.symbol} ({self.mint})")
            while self.running and isinstance(self.realtime_ws, websocket.WebSocketApp):
                try:
                    self.realtime_ws.run_forever()
                except Exception as e:
                    logger.error(f"WebSocket error for {self.symbol} ({self.mint}): {str(e)}")
                    time.sleep(5)
            logger.info(f"WebSocket listener stopped for {self.symbol} ({self.mint})")

        self.realtime_thread = threading.Thread(target=run_websocket)
        self.realtime_thread.daemon = True
        self.realtime_thread.start()
        
    def stop_realtime_monitoring(self):
        """Stop real-time price monitoring."""
        logger.info(f"Stopping real-time monitoring for {self.symbol} ({self.mint})")
        if self.realtime_ws:
            self.running = False
            self.realtime_ws.close()
            if self.realtime_thread:
                self.realtime_thread.join(timeout=5)
        logger.info(f"Real-time monitoring stopped for {self.symbol} ({self.mint})")
        
    def _log_trade(self, action: str, price: float, quantity: float, reason: str):
        """Logs trade details."""
        trade_info = {
            "mint": self.mint,
            "symbol": self.symbol,
            "action": action,
            "price": price,
            "quantity": quantity,
            "capital_impact": -quantity * price if action == "BUY" else quantity * price,
            "timestamp": datetime.utcnow(),
            "reason": reason
        }
        self.trades.append(trade_info)
        logger.info(f"Trade logged for {self.symbol} ({self.mint}): {action} {quantity:.4f} @ ${price:.6f}. Reason: {reason}")

    def calculate_meme_metrics(self, df: pd.DataFrame) -> Dict:
        """Calculate meme-specific metrics for the current token."""
        if df.empty or 'price' not in df.columns or 'volume' not in df.columns:
             logger.warning(f"{self.symbol} ({self.mint}): DataFrame empty or missing required columns for metric calculation.")
             return {}
        if len(df) < 2:
             logger.warning(f"{self.symbol} ({self.mint}): Insufficient data points ({len(df)}) for metric calculation.")
             return {}

        price_change = (df['price'].iloc[-1] / df['price'].iloc[0] - 1) * 100 if df['price'].iloc[0] != 0 else 0
        max_price = df['price'].max()
        min_price = df['price'].min()
        
        avg_volume = df['volume'].mean()
        max_volume = df['volume'].max()
        volume_trend = (df['volume'].iloc[-1] / df['volume'].iloc[0] - 1) * 100 if df['volume'].iloc[0] != 0 else 0
        
        returns = df['price'].pct_change().dropna()
        volatility = returns.std() * np.sqrt(24) * 100 if len(returns) > 1 else 0
        
        recent_volume_period = min(24, len(df))
        recent_volume = df['volume'].iloc[-recent_volume_period:].mean()
        volume_spike = recent_volume / avg_volume if avg_volume > 0 else 0

        metrics = {
            'price_change_period': price_change,
            'max_price': max_price,
            'min_price': min_price,
            'avg_volume': avg_volume,
            'max_volume': max_volume,
            'volume_trend_period': volume_trend,
            'volatility_daily_est': volatility,
            'volume_spike_avg_ratio': volume_spike
        }
        logger.debug(f"Calculated metrics for {self.symbol} ({self.mint}): {metrics}")
        return metrics
    
    def calculate_signals(self, df: pd.DataFrame, 
                        short_window: int = 10, 
                        long_window: int = 30,
                        volume_threshold: float = 2.0) -> pd.DataFrame:
        """
        Calculate trading signals with meme-specific conditions for the current token.
        
        Args:
            df: Price and volume data
            short_window: Short moving average window
            long_window: Long moving average window
            volume_threshold: Volume spike threshold for entry
        """
        if df.empty or not all(c in df.columns for c in ['price', 'volume']):
            logger.warning(f"{self.symbol} ({self.mint}): DataFrame empty or missing columns for signal calculation.")
            return df
        if len(df) < long_window:
            logger.warning(f"{self.symbol} ({self.mint}): Insufficient data ({len(df)}) for signal calculation (long window: {long_window}).")
            return df

        df['short_ma'] = df['price'].rolling(window=short_window).mean()
        df['long_ma'] = df['price'].rolling(window=long_window).mean()
        
        vol_ma_period = min(24, len(df))
        df['volume_ma'] = df['volume'].rolling(window=vol_ma_period).mean()
        df['volume_ratio'] = (df['volume'] / df['volume_ma']).fillna(0).replace([np.inf, -np.inf], 0)
        
        df['signal'] = 0
        
        buy_condition = (
            (df['short_ma'].shift(1) > df['long_ma'].shift(1)) &
            (df['volume_ratio'] > volume_threshold) &
            (df['price'] > df['short_ma']) &
            (df['price'] > df['long_ma'])
        )
        
        sell_condition = (
            (df['short_ma'].shift(1) < df['long_ma'].shift(1)) &
            (df['price'] < df['short_ma']) &
            (df['price'] < df['long_ma'])
        )
        
        df.loc[buy_condition, 'signal'] = 1
        df.loc[sell_condition, 'signal'] = -1
        
        df['signal'] = df['signal'].replace(0, np.nan).ffill().fillna(0)
        
        logger.debug(f"Signals calculated for {self.symbol} ({self.mint}). Last signal: {df['signal'].iloc[-1]}")
        return df
    
    def execute_trade(self, action: str, price: float, reason: str = "Strategy signal"):
        """Simulates executing a trade based on action."""
        if action == "BUY":
            trade_amount_usd = self.capital * self.settings.get("POSITION_SIZE_PCT", 0.95)
            if self.capital <= 0 or trade_amount_usd <= 0 or price <= 0:
                 logger.warning(f"{self.symbol} ({self.mint}): Cannot BUY. Invalid price, capital, or trade amount (Capital: {self.capital}, Price: {price}).")
                 return
                 
            quantity = trade_amount_usd / price
            
            self.position += quantity
            self.capital -= quantity * price
            self.entry_price = price
            self._log_trade("BUY", price, quantity, reason)
            logger.info(f"{self.symbol} ({self.mint}): Executed BUY {quantity:.4f} @ ${price:.6f}. New capital: ${self.capital:.2f}, Position: {self.position:.4f}")

        elif action == "SELL":
            if self.position > 0:
                sell_quantity = self.position
                self.capital += sell_quantity * price
                self._log_trade("SELL", price, sell_quantity, reason)
                logger.info(f"{self.symbol} ({self.mint}): Executed SELL {sell_quantity:.4f} @ ${price:.6f}. New capital: ${self.capital:.2f}, Position: 0")
                self.position = 0
                self.entry_price = 0
            else:
                logger.warning(f"{self.symbol} ({self.mint}): Cannot SELL, no position held.")
        else:
             logger.warning(f"{self.symbol} ({self.mint}): Unknown action '{action}' requested for execute_trade.")

    def run_strategy(self, interval: str = '1h', limit: int = 720,
                    short_window: int = 10, long_window: int = 30,
                    volume_threshold: float = 2.0) -> Optional[pd.DataFrame]:
        """
        Run the trading strategy on historical data for the initialized token.
        
        Args:
            interval: Time interval for data fetching
            limit: Number of data points
            short_window: Short moving average window for signals
            long_window: Long moving average window for signals
            volume_threshold: Volume spike threshold for signals
        """
        logger.info(f"Fetching historical data ({limit} x {interval}) for {self.symbol} ({self.mint})...")
        df = self.data_fetcher.fetch_data(
            token_address=self.mint,
            interval=interval,
            limit=limit
        )

        if df is None or df.empty:
            logger.error(f"Could not fetch historical data for {self.symbol} ({self.mint}). Aborting strategy run.")
            return None

        if 'timestamp' in df.columns:
             try:
                 df['timestamp'] = pd.to_datetime(df['timestamp'])
                 df = df.set_index('timestamp').sort_index()
             except Exception as e:
                  logger.error(f"Error processing timestamp column for {self.symbol} ({self.mint}): {e}")
                  return None
        else:
             logger.error(f"Timestamp column missing in fetched data for {self.symbol} ({self.mint}).")
             return None

        metrics = self.calculate_meme_metrics(df)
        print(f"\nMeme Token Metrics for {self.symbol} ({self.mint}):")
        for metric, value in metrics.items():
            if isinstance(value, float):
                 print(f"  {metric}: {value:.4f}")
            else:
                 print(f"  {metric}: {value}")

        df = self.calculate_signals(
            df,
            short_window=short_window,
            long_window=long_window,
            volume_threshold=volume_threshold
        )

        initial_sim_capital = self.capital
        sim_capital = initial_sim_capital
        sim_position = 0.0
        sim_entry_price = 0.0
        sim_trades = []

        logger.info(f"Starting trade simulation for {self.symbol} ({self.mint}) with initial capital: ${sim_capital:.2f}")

        for timestamp, row in df.iterrows():
             current_price = row['price']
             signal = row['signal']
             
             if signal == 1 and sim_position <= 0:
                 trade_amount_usd = sim_capital * self.settings.get("POSITION_SIZE_PCT", 0.95)
                 if sim_capital <= 0 or trade_amount_usd <= 0 or current_price <= 0:
                     continue
                 
                 quantity = trade_amount_usd / current_price
                 
                 sim_position += quantity
                 sim_capital -= quantity * current_price
                 sim_entry_price = current_price
                 sim_trades.append({
                     'timestamp': timestamp,
                     'action': 'BUY',
                     'price': current_price,
                     'quantity': quantity,
                     'capital_after': sim_capital
                 })

             elif signal == -1 and sim_position > 0:
                 sell_quantity = sim_position
                 profit = (current_price - sim_entry_price) * sell_quantity
                 profit_pct = (current_price / sim_entry_price - 1) * 100 if sim_entry_price > 0 else 0
                 
                 sim_capital += sell_quantity * current_price
                 sim_position = 0
                 
                 sim_trades.append({
                     'timestamp': timestamp,
                     'action': 'SELL',
                     'price': current_price,
                     'quantity': sell_quantity,
                     'profit': profit,
                     'profit_pct': profit_pct,
                     'capital_after': sim_capital
                 })
                 sim_entry_price = 0

        trades_df = pd.DataFrame(sim_trades)
        final_value = sim_capital + sim_position * df.iloc[-1]['price']

        print(f"\nStrategy Simulation Results for {self.symbol} ({self.mint}):")
        print(f"  Initial Capital: ${initial_sim_capital:.2f}")
        print(f"  Final Portfolio Value: ${final_value:.2f}")
        profit_loss = final_value - initial_sim_capital
        profit_loss_pct = (profit_loss / initial_sim_capital) * 100 if initial_sim_capital > 0 else 0
        print(f"  Net Profit/Loss: ${profit_loss:.2f} ({profit_loss_pct:.2f}%)")

        if not trades_df.empty:
            buy_trades = trades_df[trades_df['action'] == 'BUY']
            sell_trades = trades_df[trades_df['action'] == 'SELL']
            print(f"  Total Trades Executed: {len(sell_trades)} round trips (Buy+Sell)")
            
            if not sell_trades.empty:
                 win_rate = (sell_trades['profit'] > 0).mean() * 100
                 avg_profit_pct = sell_trades['profit_pct'].mean()
                 max_profit_pct = sell_trades['profit_pct'].max()
                 max_loss_pct = sell_trades['profit_pct'].min()
                 print(f"  Win Rate: {win_rate:.2f}%" if not pd.isna(win_rate) else "Win Rate: N/A")
                 print(f"  Average Profit per Trade: {avg_profit_pct:.2f}%" if not pd.isna(avg_profit_pct) else "Avg Profit: N/A")
                 print(f"  Max Profit per Trade: {max_profit_pct:.2f}%" if not pd.isna(max_profit_pct) else "Max Profit: N/A")
                 print(f"  Max Loss per Trade: {max_loss_pct:.2f}%" if not pd.isna(max_loss_pct) else "Max Loss: N/A")
            
            output_dir = 'synthron/outputs'
            os.makedirs(output_dir, exist_ok=True)
            results_filename = f"{output_dir}/backtest_results_{self.symbol}_{self.mint[:6]}.csv"
            try:
                trades_df.to_csv(results_filename, index=False)
                logger.info(f"Saved simulation trade results to {results_filename}")
            except Exception as e:
                logger.error(f"Failed to save trade results for {self.symbol} ({self.mint}): {e}")
        else:
             print("  No trades were executed during the simulation.")

        return trades_df

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    token_mint_address = "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm"
    if token_mint_address == "YOUR_TOKEN_ADDRESS":
        print("Please replace 'YOUR_TOKEN_ADDRESS' with an actual Solana token mint address in performance/run_strategy.py")
        exit()

    strategy_settings = {
        "POSITION_SIZE_PCT": 0.95,
    }

    strategy = MemeTokenStrategy(
        mint=token_mint_address,
        initial_capital=10000.0,
        settings=strategy_settings,
        helius_api_key=os.getenv('HELIUS_API_KEY')
    )

    trades_df = strategy.run_strategy(
        interval='1h',
        limit=720,
        short_window=12,
        long_window=26,
        volume_threshold=1.8
    )

    print("\nBacktest complete.") 