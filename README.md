# **SYNTHRON CRYPTO TRADER**
### By Magna Opus Technologies

---

## **Overview**
Synthron Crypto Trader is a cutting-edge, production-level cryptocurrency trading system designed to provide:
- **Automated Trading**: A live trading system powered by advanced strategies and real-time market analytics.
- **Backtesting Capabilities**: Test trading strategies on historical data to optimize performance.
- **Comprehensive Risk Management**: Features to safeguard your investments, including stop-loss, position sizing, and drawdown tracking.
- **Scalability**: A modular design that adapts seamlessly to evolving market dynamics.
- **Robust Security**: Secure wallet management with optimized gas reserves and compliance validation.

---

## **Features**
1. **Trading System**:
   - Real-time market data fetching and analysis.
   - Dynamic strategy execution for profitable trades.
   - Integrated whitelist and blacklist for token selection.

2. **Backtesting System**:
   - Historical data simulation to refine trading strategies.
   - Performance metrics evaluation (e.g., ROI, Sharpe ratio).

3. **Data Processing**:
   - Advanced analytics with clustering, trend detection, and whale activity monitoring.
   - Rug pull and scam detection filters.

4. **Risk and Wallet Management**:
   - Gas fee optimization and reserve tracking.
   - Secure wallet integration with transaction validation.

5. **Performance Tracking**:
   - Detailed reporting with metrics visualization.
   - Alerts for key performance thresholds.

---

## **Getting Started**

### **Prerequisites**
- **Python Version**: 3.9 or higher.
- **Dependencies**: Install required libraries using `pip install -r requirements.txt`.
- **Environment Variables**: Configure sensitive data in a `.env` file:
  ```plaintext
  WALLET_PRIVATE_KEY=your_wallet_private_key
  SOLANA_CLUSTER_URL=your_solana_cluster_url
  LOGGING_LEVEL=INFO
  ```

---

### **Installation**
1. Clone the repository:
   ```bash
   git clone https://github.com/your-repo/Synthron-Crypto-Trader.git
   cd Synthron-Crypto-Trader
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Set up the `.env` file:
   ```plaintext
   WALLET_PRIVATE_KEY=your_wallet_private_key
   SOLANA_CLUSTER_URL=your_solana_cluster_url
   LOGGING_LEVEL=INFO
   ```

---

### **Usage**

#### **Running the Application**
1. Launch the application:
   ```bash
   python main.py
   ```

2. Select from the main menu:
   - **1**: Run the live trading system.
   - **2**: Run the backtesting system.
   - **3**: Exit the application.

#### **Live Trading**
- The system fetches real-time data, applies strategies, and executes trades automatically.
- Logs are saved in `logs/synthron_trader.log` for debugging and review.

#### **Backtesting**
- Simulate strategies on historical data to refine and optimize trading performance.
- Results are saved as `backtesting_results.csv`.

---

## **Project Structure**
```plaintext
Synthron_Crypto_Trader/
│
├── config/                # Configuration modules (settings, thresholds, logging)
├── data/                  # Data fetching, processing, and analytics
├── execution/             # Trade execution and order management
├── filters/               # Token selection filters (whitelist, blacklist, rug detection)
├── performance/           # Performance tracking, reporting, and backtesting
├── strategies/            # Trading strategies and risk management
├── utils/                 # Utilities for logging, validation, and exceptions
├── wallet/                # Wallet and gas management
├── main.py                # Main script for running the application
├── requirements.txt       # Python dependencies
└── README.md              # Project documentation
```

---

## **License**
This project is licensed under the MIT License - see the LICENSE file for details.

---

## **Contributing**
We welcome contributions to improve the Synthron Crypto Trader. Please follow these steps:
1. Fork the repository.
2. Create a feature branch (`git checkout -b feature-branch`).
3. Commit your changes (`git commit -m 'Add feature'`).
4. Push to the branch (`git push origin feature-branch`).
5. Open a pull request.

---

## **Support**
For support or inquiries, please contact us at support@magnatechnologies.com.

---

## **Disclaimer**
Trading cryptocurrencies involves significant risk. Synthron Crypto Trader is provided "as is" without any guarantees. Users are responsible for their trading decisions and outcomes.

# SuperTradeX API Error Handling

This document outlines the error handling strategies for the various APIs used in the SuperTradeX token scanning system.

## General Principles

1. **No Mock Data:** The system does not use mock data under any circumstances. Each API failure is handled according to specific rules.

2. **Exponential Backoff:** All API clients implement exponential backoff for retries, with increasing delays between attempts.

3. **API-Specific Strategies:** Each API service has a different strategy for handling failures after retries.

## API-Specific Error Handling

### DexScreener API

- **Strategy:** Keep retrying with increasing delays between attempts (up to 10 retries).
- **On Failure:** Return an empty DataFrame. This will result in no tokens to process.
- **Delay Pattern:** Base delay is 5 seconds, doubled after each attempt (capped at 5 minutes).

### Rugcheck API

- **Strategy:** Retry up to 2 times with exponential backoff.
- **On Failure:** Return a score of 100, which will cause the token to fail validation and be dropped.
- **Reason:** High rugcheck scores indicate risk, so we assume potential problems with tokens that can't be verified.

### Solsniffer API

- **Strategy:** Retry up to 2 times with exponential backoff.
- **On Failure:** Apply the minimum configured score (`MIN_SOLSNIFFER_SCORE`).
- **Reason:** We use a minimum threshold for validity, so we give tokens the benefit of the doubt at exactly that threshold.

### SolanaTracker API

- **Strategy:** Retry up to 2 times with exponential backoff.
- **On Failure:** Return `None` and drop the token.
- **Reason:** SolanaTracker provides essential validation data like LP burn percentage and Twitter information.

## Twitter Verification

- Tokens without a valid Twitter account are always dropped.
- Twitter URLs must begin with "https://twitter.com/" or "http://twitter.com/".
- Empty Twitter fields cause tokens to be rejected.

## Implementation Details

- All API clients include detailed logging for debugging.
- Proxy support is included for handling rate limits.
- The system implements database cleanup before each scan to refresh the valid tokens list.

# SuperTradeX

SuperTradeX is an automated cryptocurrency trading system focused on the Solana blockchain. The platform identifies, analyzes, and trades promising tokens using various strategies and validation layers.

## Features

- **Token Discovery & Validation**
  - Real-time token scanning using DexScreener API
  - Multi-layer validation using RugCheck, SolSniffer, and Twitter
  - Configurable validation thresholds

- **Trading Strategies**
  - Entry/exit strategy with support for multiple criteria
  - Risk management with position sizing and stop-loss
  - Take-profit targets and technical exit conditions

- **Order Management**
  - Automated order placement and execution
  - Position tracking and management
  - Balance monitoring and risk controls

- **Data Management**
  - SQLite database for token and trade storage
  - Real-time price and volume tracking
  - Historical data analysis

## System Architecture

The platform consists of several key components:

1. **Configuration & Settings**
   - Centralized settings management
   - Environment variable configuration
   - API key management

2. **Token Scanner**
   - Discovers trending tokens
   - Validates tokens using multiple APIs
   - Filters tokens based on configurable criteria

3. **Strategy Selector**
   - Implements trading strategies
   - Manages entry and exit conditions
   - Handles position sizing and risk management

4. **Order Manager**
   - Places and executes trades
   - Tracks positions and orders
   - Manages account balance

5. **Data Management**
   - Stores token and trade data
   - Tracks performance metrics
   - Provides historical analysis

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/supertradex.git
   cd supertradex
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Copy the example environment file and configure your settings:
   ```bash
   cp .env.example .env
   ```

4. Edit the `.env` file with your API keys and configuration:
   ```
   DEXSCREENER_API_KEY=your_key
   RUGCHECK_API_KEY=your_key
   SOLSNIFFER_API_KEY=your_key
   TWITTER_API_KEY=your_key
   TWITTER_API_KEY_SECRET=your_secret
   ```

## Usage

1. Start the trading system:
   ```bash
   python main.py
   ```

2. Monitor the logs:
   ```bash
   tail -f logs/trader.log
   ```

## Configuration

The system can be configured through environment variables in the `.env` file:

- **API Settings**: Configure API endpoints and keys
- **Trading Settings**: Set cycle intervals and retry parameters
- **Token Validation**: Define minimum thresholds for token validation
- **Risk Management**: Configure position sizing and stop-loss parameters
- **Logging**: Set log level and file location

## Development

The codebase is organized into the following directories:

- `config/`: Configuration and settings management
- `data/`: Data management and token scanning
- `strategies/`: Trading strategy implementation
- `execution/`: Order execution and management
- `utils/`: Utility functions and helpers

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Disclaimer

This software is for educational purposes only. Use at your own risk. The developers are not responsible for any financial losses incurred through the use of this software.
