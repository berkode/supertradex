================================================================================
                     Synthron Crypto Trader: Config Directory
================================================================================

Overview:
The `config` directory centralizes all configuration-related functionality,
ensuring a clean and secure separation of concerns for the Synthron Crypto 
Trader system. It includes environment variables, API integrations, filtering 
rules, logging configurations, thresholds, and global settings.

--------------------------------------------------------------------------------
1. .env File
--------------------------------------------------------------------------------
Purpose:
- Stores environment variables for secure and centralized configuration.

Key Features:
- API Configuration:
  - Raydium API Base URL
  - Dex Screener API Base URL
- Solana Cluster:
  - Mainnet and Testnet endpoints.
- Logging Configuration:
  - Log levels, file paths, rotation, and console output.
- Trading Thresholds:
  - Volume, price, slippage, and liquidity ranges.
- Risk Management:
  - Daily, weekly risk limits, and slippage tolerance.
- Wallet Configuration:
  - Paths for private keys and passwords.
- Performance Metrics:
  - Sharpe ratio, drawdown, and risk of ruin toggles.

--------------------------------------------------------------------------------
2. dexscreener_api.py
--------------------------------------------------------------------------------
Purpose:
- Provides an interface to the Dex Screener API.

Key Functionalities:
- Fetch token profiles, boosted tokens, and active orders.
- Search for trading pairs and retrieve liquidity pool data.
- Implements retry mechanisms for robust API interactions.

--------------------------------------------------------------------------------
3. filters_config.py
--------------------------------------------------------------------------------
Purpose:
- Defines and manages token validation and filtering criteria.

Key Functionalities:
- Validation rules based on:
  - Liquidity, volume, gains, and holder thresholds.
  - Immutability, minting, and burning status.
- Dynamic updates from environment variables.
- Supports token whitelists and blacklists.

--------------------------------------------------------------------------------
4. logging_config.py
--------------------------------------------------------------------------------
Purpose:
- Centralizes logging for the entire trading system.

Key Functionalities:
- File-based logging with rotation and retention.
- Optional console logging for real-time debugging.
- Asynchronous logging using `QueueHandler` and `QueueListener`.
- Suppression of verbose external library logs.

--------------------------------------------------------------------------------
5. raydium_api.py
--------------------------------------------------------------------------------
Purpose:
- Interacts with the Raydium V3 API for trading and pool management.

Key Functionalities:
- Fetch chain times, TVL, and 24-hour trading volumes.
- Access stake pool and farm pool details.
- Retrieve mint prices and pool information by IDs.

--------------------------------------------------------------------------------
6. settings.py
--------------------------------------------------------------------------------
Purpose:
- Manages global settings governing the trading system.

Key Functionalities:
- Risk Management:
  - Trade size, slippage tolerance, and risk limits.
- Gain and Loss Targets:
  - Configurable targets for multiple trading strategies.
- Dynamic Validation:
  - Ensures correctness and safety of all settings.

--------------------------------------------------------------------------------
7. solana_config.py
--------------------------------------------------------------------------------
Purpose:
- Handles Solana network configurations for the system.

Key Functionalities:
- Manage mainnet and testnet RPC endpoints.
- Validate and sanitize RPC URLs.
- Provide active RPC endpoint based on selected cluster.

--------------------------------------------------------------------------------
8. thresholds.py
--------------------------------------------------------------------------------
Purpose:
- Defines and validates trading thresholds.

Key Functionalities:
- Thresholds include:
  - Volume, price, liquidity, gas fee, holders, slippage, and spread.
- Dynamic updates of thresholds during runtime.
- Automatic validation of all threshold configurations.

================================================================================
