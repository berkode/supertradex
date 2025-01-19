# **Performance Documentation**

This document provides comprehensive details about the performance-related modules in the Synthron Crypto Trader system. These modules enable backtesting, metrics calculation, drawdown tracking, and reporting for effective trading system evaluation.

---

## **1. `backtesting.py`**

### **Class: Backtesting**
Simulates trading strategies on historical and live market data.

#### **Methods**
- **`__init__(strategy)`**
  - Initializes the backtesting system with a strategy function or class.

- **`load_data(source=None, live=False, symbol=None)`**
  - Loads historical data from CSV or fetches live data from an API.

- **`simulate_trade(action, price, quantity)`**
  - Simulates a buy or sell trade, updating capital and recording the trade.

- **`record_trade(action, price, quantity, profit)`**
  - Records the trade details for later evaluation.

- **`evaluate_metrics()`**
  - Calculates performance metrics such as total profit, ROI, and maximum drawdown.

- **`run_backtest()`**
  - Executes backtesting on the loaded historical data.

- **`run_forward_test(symbol)`**
  - Executes forward testing on live data in real-time.

- **`save_results(filepath)`**
  - Saves trade results to a CSV file.

---

## **2. `drawdown_tracker.py`**

### **Class: DrawdownTracker**
Monitors and manages drawdowns in the trading system to enforce risk limits.

#### **Methods**
- **`__init__(initial_equity, max_drawdown_percentage, alert_callback=None, auto_save_path=None)`**
  - Initializes the tracker with equity, drawdown limits, and optional alert functionality.

- **`calculate_drawdown()`**
  - Calculates the current drawdown percentage.

- **`calculate_recovery()`**
  - Calculates the recovery percentage after a drawdown.

- **`update_equity(trade_profit)`**
  - Updates equity after a trade and checks drawdown limits.

- **`trigger_drawdown_alert(current_drawdown)`**
  - Disables trading and triggers an alert when drawdown limits are breached.

- **`reset_drawdown()`**
  - Resets the tracker and re-enables trading.

- **`save_drawdowns(filepath)`**
  - Saves the drawdown history to a JSON file.

- **`get_drawdown_summary()`**
  - Provides a summary of drawdown history.

---

## **3. `metrics.py`**

### **Class: Metrics**
Calculates key performance metrics based on trade results.

#### **Methods**
- **`__init__(results, base_currency="dSOL")`**
  - Initializes the metrics system with trade results and the base currency.

- **`calculate_total_made()`**
  - Calculates total profit in the base currency.

- **`calculate_total_roi()`**
  - Calculates total ROI (Return on Investment).

- **`calculate_tokens_per_day()`**
  - Computes the total tokens bought and sold daily.

- **`calculate_max_gain_loss()`**
  - Calculates the maximum gain, maximum loss, and their ratio.

- **`calculate_sharpe_ratio(risk_free_rate=0)`**
  - Calculates the Sharpe Ratio to evaluate risk-adjusted returns.

- **`calculate_all_metrics()`**
  - Computes all supported metrics and returns them.

- **`save_metrics(filepath)`**
  - Saves calculated metrics to a JSON file.

---

## **4. `reporting.py`**

### **Class: Reporting**
Generates detailed reports and visualizations for trade performance.

#### **Methods**
- **`__init__(results)`**
  - Initializes the reporting system with trade results.

- **`calculate_metrics()`**
  - Calculates performance metrics including total profit, ROI, and win rate.

- **`save_report(filepath=None)`**
  - Saves trade results and metrics in CSV, JSON, and Excel formats.

- **`generate_visualizations(filepath=None)`**
  - Produces visualizations such as the equity curve and profit/loss distribution.

- **`generate_full_report(filepath=None)`**
  - Generates a complete report with metrics, visualizations, and trade logs.

---

### **Performance Reports**
The performance modules collectively offer:
- Backtesting and forward testing for strategy validation.
- Real-time drawdown monitoring with alert mechanisms.
- Advanced metrics calculations such as ROI, Sharpe Ratio, and gain/loss analysis.
- Comprehensive reporting with exportable formats and visualizations.

For further details, refer to the individual modules.
