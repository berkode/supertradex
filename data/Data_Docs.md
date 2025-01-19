# Synthron Crypto Trader: Data Module Documentation

## Overview
The `data` module of Synthron Crypto Trader handles data fetching, processing, analytics, and real-time monitoring for trading activities. This module includes classes and utilities for:
- Fetching live and historical data.
- Processing and cleaning raw data.
- Performing analytics and generating metrics.
- Monitoring token prices and order book movements.

---

## **1. `analytics.py`**
### Purpose:
Performs advanced data analytics, including trend detection, clustering, and monitoring wallet or developer activities.

### **Class: Analytics**
- **Constructor**:
  - `suspicious_threshold`: Minimum transfer amount to flag as suspicious.
  - `whale_threshold`: Transaction size to qualify as a whale movement.
  - `cluster_count`: Number of clusters for KMeans.
  - `min_liquidity`: Minimum liquidity for analysis.

#### **Methods**:
1. **`calculate_price_trend(prices: pd.Series) -> str`**  
   Detects the price trend: `uptrend`, `downtrend`, or `sideways`.

2. **`analyze_liquidity(liquidity_data: pd.DataFrame) -> dict`**  
   Summarizes liquidity trends with average and directional analysis.

3. **`detect_suspicious_wallets(transfer_data: pd.DataFrame) -> list`**  
   Identifies wallets with suspiciously high transaction amounts.

4. **`monitor_whale_movements(transfer_data: pd.DataFrame) -> pd.DataFrame`**  
   Tracks movements by large accounts (whales).

5. **`track_developer_activity(dev_wallets: list, activity_data: pd.DataFrame) -> dict`**  
   Monitors activities of developer wallets.

6. **`cluster_transactions(transaction_data: pd.DataFrame) -> dict`**  
   Applies clustering to transactions for pattern discovery.

---

## **2. `blockchain_listener.py`**
### Purpose:
Real-time listener for Solana blockchain events, monitoring account and program activities.

### **Class: BlockchainListener**
- **Constructor**:
  - `rpc_ws_endpoint`: WebSocket RPC endpoint for Solana.
  - `monitored_accounts`: Accounts to monitor for activity.
  - `monitored_programs`: Programs to monitor for interactions.

#### **Methods**:
1. **`listen()`**  
   Starts the event listener and processes blockchain events.

2. **`_process_event(event: dict)`**  
   Handles events and applies business logic for accounts or programs.

3. **`_handle_account_activity(account: str, value: dict)`**  
   Processes activity for monitored accounts (e.g., token transfers).

4. **`_handle_program_activity(program: str, value: dict)`**  
   Processes interactions with monitored programs (e.g., swaps, liquidity).

5. **`_subscribe_to_account(ws_connection, account_id: str)`**  
   Subscribes to events for a specific account.

6. **`_subscribe_to_program(ws_connection, program_id: str)`**  
   Subscribes to events for a specific program.

---

## **3. `data_fetcher.py`**
### Purpose:
Fetches data from APIs (DexScreener, Raydium) with robust retry mechanisms.

### **Class: DataFetcher**
- **Constructor**:
  - `dex_screener_api`: Base URL for DexScreener API.
  - `raydium_api`: Base URL for Raydium API.

#### **Methods**:
1. **`fetch_dex_screener_data(token_address: str) -> dict`**  
   Fetches token data from DexScreener.

2. **`fetch_raydium_pool_data(pool_address: str) -> dict`**  
   Retrieves liquidity pool data from Raydium.

3. **`fetch_batch_data(api_urls: list) -> list`**  
   Fetches data from multiple API endpoints with rate limiting.

4. **`validate_response(data: dict, required_keys: list = None) -> bool`**  
   Ensures API responses include required keys.

---

## **4. `data_processing.py`**
### Purpose:
Processes raw data by cleaning, normalizing, and removing outliers.

### **Class: DataProcessing**

#### **Methods**:
1. **`validate_dataframe(data: pd.DataFrame)`**  
   Ensures the input DataFrame is valid.

2. **`handle_missing_values(data: pd.DataFrame, strategy: str, fill_value: float) -> pd.DataFrame`**  
   Handles missing data using strategies like mean or constant value.

3. **`remove_outliers(data: pd.DataFrame, columns: list, method: str, threshold: float) -> pd.DataFrame`**  
   Removes outliers using z-score or IQR methods.

4. **`normalize_data(data: pd.DataFrame, columns: list, method: str) -> pd.DataFrame`**  
   Normalizes numerical columns with min-max scaling or z-score.

5. **`clean_data(...) -> pd.DataFrame`**  
   End-to-end cleaning pipeline: handles missing values, outliers, and normalization.

---

## **5. `filtering.py`**
### Purpose:
Applies advanced filtering and rug pull detection on tokens.

### **Class: Filtering**
- **Constructor**:
  - `rug_threshold`: Threshold to classify as a rug pull.
  - `min_liquidity`: Minimum liquidity for token selection.

#### **Methods**:
1. **`fetch_token_data(token_address: str) -> dict`**  
   Retrieves token data from DexScreener.

2. **`calculate_rugpull_score(token_data: dict) -> float`**  
   Scores tokens on rug pull risk using liquidity, trading, and distribution metrics.

3. **`apply_standard_filters(token_data: dict) -> bool`**  
   Ensures tokens meet liquidity and volume thresholds.

4. **`apply_filters(token_address: str) -> dict`**  
   Combines rug pull and standard filters for token selection.

---

## **6. `indicators.py`**
### Purpose:
Provides a comprehensive suite of technical indicators for analyzing market data and supporting trading strategies.

### **Class: Indicators**
The `Indicators` class is optimized for real-world trading scenarios, offering a wide array of methods for price action analysis, volatility measurement, and pattern identification.

---

#### **Methods**
1. **`support_resistance_levels(prices: pd.Series, period: int = 14) -> List[Tuple[int, float]]`**  
   Identifies support and resistance levels based on historical price action.  
   - **Args**:  
     - `prices`: A `pd.Series` of prices.  
     - `period`: Look-back period for evaluating levels.  
   - **Returns**:  
     List of tuples representing the index and value of levels.

2. **`volume_profile(prices: pd.Series, volumes: pd.Series, bins: int = 10) -> List[Tuple[float, float]]`**  
   Calculates the volume profile, highlighting key trading levels.  
   - **Args**:  
     - `prices`: A `pd.Series` of prices.  
     - `volumes`: A `pd.Series` of traded volumes.  
     - `bins`: Number of price bins for aggregation.  
   - **Returns**:  
     List of tuples (price range, volume).

3. **`fibonacci_retracement(prices: pd.Series) -> List[float]`**  
   Calculates Fibonacci retracement levels based on price extremes.  
   - **Args**:  
     - `prices`: A `pd.Series` of prices.  
   - **Returns**:  
     List of retracement levels.

4. **`average_true_range(highs: pd.Series, lows: pd.Series, closes: pd.Series, period: int = 14) -> pd.Series`**  
   Measures market volatility using the Average True Range (ATR).  
   - **Args**:  
     - `highs`, `lows`, `closes`: High, low, and close prices as `pd.Series`.  
     - `period`: Look-back period.  
   - **Returns**:  
     A `pd.Series` of ATR values.

5. **`relative_strength_index(prices: pd.Series, period: int = 14) -> pd.Series`**  
   Evaluates overbought or oversold conditions using the RSI.  
   - **Args**:  
     - `prices`: A `pd.Series` of prices.  
     - `period`: Look-back period for RSI calculation.  
   - **Returns**:  
     A `pd.Series` of RSI values.

6. **`candlestick_patterns(data: pd.DataFrame) -> List[Tuple[int, str]]`**  
   Detects specific candlestick patterns like hammers.  
   - **Args**:  
     - `data`: A `pd.DataFrame` with `open`, `close`, `high`, `low` columns.  
   - **Returns**:  
     List of tuples (index, pattern name).

7. **`token_creation_time(token_start_time: str) -> pd.Timedelta`**  
   Calculates the time elapsed since a token's creation.  
   - **Args**:  
     - `token_start_time`: Start time as an ISO 8601 string.  
   - **Returns**:  
     A `pd.Timedelta` representing the elapsed time.

8. **`transaction_success_rate(wallet_transactions: List[dict]) -> float`**  
   Calculates the success rate of wallet transactions.  
   - **Args**:  
     - `wallet_transactions`: List of transaction dictionaries.  
   - **Returns**:  
     Success rate as a float.

9. **`trade_recency(trades: List[dict]) -> pd.Timestamp`**  
   Finds the timestamp of the most recent trade.  
   - **Args**:  
     - `trades`: List of trade dictionaries.  
   - **Returns**:  
     A `pd.Timestamp` of the latest trade.

10. **`risk_reward_analysis(entry: float, stop_loss: float, take_profit: float) -> Union[float, None]`**  
    Assesses the risk/reward ratio of a trade.  
    - **Args**:  
      - `entry`: Entry price.  
      - `stop_loss`: Stop-loss price.  
      - `take_profit`: Take-profit price.  
    - **Returns**:  
      Risk/reward ratio or `None` if invalid.

11. **`moving_averages(prices: pd.Series, period: int) -> pd.Series`**  
    Calculates the Simple Moving Average (SMA).  
    - **Args**:  
      - `prices`: A `pd.Series` of prices.  
      - `period`: Look-back period.  
    - **Returns**:  
      A `pd.Series` of SMA values.

12. **`macd(prices: pd.Series, short: int = 12, long: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series]`**  
    Calculates the MACD line and signal line.  
    - **Args**:  
      - `prices`: A `pd.Series` of prices.  
      - `short`, `long`, `signal`: Periods for EMA calculations.  
    - **Returns**:  
      Tuple (MACD line, Signal line).

13. **`adx(highs: pd.Series, lows: pd.Series, closes: pd.Series, period: int = 14) -> pd.Series`**  
    Measures trend strength using the ADX.  
    - **Args**:  
      - `highs`, `lows`, `closes`: High, low, and close prices as `pd.Series`.  
      - `period`: Look-back period.  
    - **Returns**:  
      A `pd.Series` of ADX values.

14. **`bollinger_bands(prices: pd.Series, period: int = 20) -> Tuple[pd.Series, pd.Series]`**  
    Calculates upper and lower Bollinger Bands.  
    - **Args**:  
      - `prices`: A `pd.Series` of prices.  
      - `period`: Look-back period.  
    - **Returns**:  
      Tuple (Upper band, Lower band).

15. **`z_score(prices: pd.Series, window: int = 20) -> pd.Series`**  
    Computes the Z-score for price deviations.  
    - **Args**:  
      - `prices`: A `pd.Series` of prices.  
      - `window`: Rolling window size.  
    - **Returns**:  
      A `pd.Series` of Z-scores.

16. **`price_channels(prices: pd.Series, period: int = 14) -> Tuple[pd.Series, pd.Series]`**  
    Defines breakout levels using highs and lows.  
    - **Args**:  
      - `prices`: A `pd.Series` of prices.  
      - `period`: Look-back period.  
    - **Returns**:  
      Tuple (Highs, Lows).

17. **`volume_analysis(volumes: pd.Series, period: int = 10) -> pd.Series`**  
    Performs volume analysis over a rolling window.  
    - **Args**:  
      - `volumes`: A `pd.Series` of traded volumes.  
      - `period`: Look-back period.  
    - **Returns**:  
      A `pd.Series` of rolling averages.

18. **`rsi_divergence(prices: pd.Series, rsi: pd.Series) -> List[int]`**  
    Identifies points of divergence between RSI and price.  
    - **Args**:  
      - `prices`: A `pd.Series` of prices.  
      - `rsi`: A `pd.Series` of RSI values.  
    - **Returns**:  
      List of indices with divergence.

---

## **7. `price_monitor.py`**
### Purpose:
Monitors token prices and order books in real-time.

### **Class: PriceMonitor**

#### **Methods**:
1. **`fetch_token_price_and_order_book(token_address: str) -> dict`**  
   Retrieves token price and order book details.

2. **`monitor_prices(token_addresses: list)`**  
   Continuously polls prices for a list of tokens.

---

## **8. `token_metrics.py`**
### Purpose:
Generates key token metrics including price, market cap, and trading volume.

### **Class: TokenMetrics**

#### **Methods**:
1. **`fetch_token_data(token_address: str) -> dict`**  
   Fetches raw token data from DexScreener.

2. **`generate_metrics(token_address: str) -> dict`**  
   Extracts price, market cap, and 24-hour volume from token data.

3. **`validate_token_address(token_address: str)`**  
   Validates the format of a Solana token address.

---

### Note:
Each class and method in this module is optimized for high performance in live trading systems.
