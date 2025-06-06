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
  - Raydium API URL
  - Dex Screener API Base URL
- Solana Cluster:
  - Mainnet and Testnet endpoints.
  - SOLANA_MAINNET_RPC: Main RPC endpoint for Solana mainnet
  - SOLANA_TESTNET_RPC: RPC endpoint for Solana testnet
  - SOLANA_MAINNET_WSS: WebSocket endpoint for Solana mainnet (used as fallback)
  - HELIUS_RPC_URL: Helius RPC endpoint (primary)
  - HELIUS_WSS_URL: Helius WebSocket endpoint (primary, base URL stored in .env; API key appended by Settings class)
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
- Network Timeouts:
  - HTTP_TIMEOUT: General timeout for HTTP requests

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

--------------------------------------------------------------------------------
9. External API Documentation
--------------------------------------------------------------------------------
Purpose:
- Quick reference links to documentation for external services used.

Links:
- **RugCheck:** [https://api.rugcheck.xyz/swagger/index.html](https://api.rugcheck.xyz/swagger/index.html)
- **SolSniffer:** [https://solsniffer.com/api/docs/](https://solsniffer.com/api/docs/)
- **DexScreener:** [https://dexscreener.com/docs](https://dexscreener.com/docs)
- **SolanaTracker:** [https://docs.solanatracker.io/public-data-api/docs](https://docs.solanatracker.io/public-data-api/docs)
- **Jupiter Swap API:** [https://station.jup.ag/docs/apis/swap-api](https://station.jup.ag/docs/apis/swap-api)
- **Jupiter Token List API:** [https://station.jup.ag/docs/token-list/token-list-api](https://station.jup.ag/docs/token-list/token-list-api)
- **Helius:** [https://docs.helius.dev/](https://docs.helius.dev/)
- **Twikit (Twitter):** [https://twikit.readthedocs.io/en/latest/index.html](https://twikit.readthedocs.io/en/latest/index.html)
- **GoPlus Security:** [https://docs.gopluslabs.io/docs/getting-started](https://docs.gopluslabs.io/docs/getting-started)

================================================================================

--------------------------------------------------------------------------------
10. RugCheck JSON Example Output
--------------------------------------------------------------------------------
Purpose:
- Shows an example of the JSON structure returned by the RugCheck API for a token.

Example (JOJO Token):
```json
{
  "mint": "7YygHaahdKVNtbu9GyFRnnBgf7hKzC76hnuHHfxCKRij",
  "tokenProgram": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
  "creator": "7hEUKwCEVFPAXVuPQXQERhzv5dPrxuZnMCBV7mHr4Up2",
  "token": {
    "mintAuthority": null,
    "supply": 73762315093282,
    "decimals": 6,
    "isInitialized": true,
    "freezeAuthority": null
  },
  "token_extensions": null,
  "tokenMeta": {
    "name": "JOJO ",
    "symbol": "JOJO ",
    "uri": "https://gateway.irys.xyz/EFl0_nzv2WNlEhX33qycWcpXnPpMsbDBk7hap2nbkRI",
    "mutable": false,
    "updateAuthority": "7hEUKwCEVFPAXVuPQXQERhzv5dPrxuZnMCBV7mHr4Up2"
  },
  "topHolders": [
    {
      "address": "8eFNC7DNxxQrbyi8Uxw3i9AfbETBb1nyLFR859kRgT6f",
      "amount": 14923748599339,
      "decimals": 6,
      "pct": 20.232212858918526,
      "uiAmount": 14923748.599339,
      "uiAmountString": "14923748.599339",
      "owner": "ricEmGn6WZ9kN2ASm1MAt7LoE1hBgu1VcQrjRwkAPfc",
      "insider": false
    },
    {
      "address": "6TK6ayJNMgh888d6LWm3eVtWGKSHZL86cUgZG3XbMe4C",
      "amount": 14376759712514,
      "decimals": 6,
      "pct": 19.490656840600415,
      "uiAmount": 14376759.712514,
      "uiAmountString": "14376759.712514",
      "owner": "64AeW12cWDCLU6Z9moJwGq4dBAAJkoUrjv2vX2wj6FFi",
      "insider": false
    }
  ],
  "freezeAuthority": null,
  "mintAuthority": null,
  "risks": [
    {
      "name": "Top 10 holders high ownership",
      "value": "",
      "description": "The top 10 users hold more than 70% token supply",
      "score": 8272,
      "level": "danger"
    },
    {
      "name": "Low Liquidity",
      "value": "$5.18",
      "description": "Low amount of liquidity in the token pool",
      "score": 2994,
      "level": "danger"
    },
    {
      "name": "Single holder ownership",
      "value": "20.23%",
      "description": "One user holds a large amount of the token supply",
      "score": 2023,
      "level": "warn"
    },
    {
      "name": "High ownership",
      "value": "",
      "description": "The top users hold more than 80% token supply",
      "score": 1317,
      "level": "danger"
    },
    {
      "name": "Low amount of LP Providers",
      "value": "",
      "description": "Only a few users are providing liquidity",
      "score": 500,
      "level": "warn"
    }
  ],
  "score": 15107,
  "score_normalised": 56,
  "fileMeta": {
    "description": "",
    "name": "JOJO ",
    "symbol": "JOJO ",
    "image": "https://gateway.irys.xyz/GHgqkIFr-DBEXw2mwluGu_J8J9SatalCle2ju7B2zy4"
  },
  "lockerOwners": {},
  "lockers": {},
  "markets": [
    {
      "pubkey": "6kcuAhrA1dhVFCzosrUeRKPUTXE3FZ4X1Xk8GRHTkqan",
      "marketType": "raydium_cpmm",
      "mintA": "So11111111111111111111111111111111111111112",
      "mintB": "7YygHaahdKVNtbu9GyFRnnBgf7hKzC76hnuHHfxCKRij",
      "mintLP": "CShf4G4A19uCes1YaHfpEvAgu4VQUo1ULnv3z9jwk1Ak",
      "liquidityA": "5amZL3NeKBT5A4CBCTpXSYWh5UtzVh6gXeqqQXHh3Rwr",
      "liquidityB": "5z1vuTsWqnktM39Q1jFx5GSUKBMKxhftzvwim4Yv7fSp",
      "mintAAccount": {
        "mintAuthority": null,
        "supply": 0,
        "decimals": 9,
        "isInitialized": true,
        "freezeAuthority": null
      },
      "mintBAccount": {
        "mintAuthority": null,
        "supply": 73762315093282,
        "decimals": 6,
        "isInitialized": true,
        "freezeAuthority": null
      },
      "mintLPAccount": {
        "mintAuthority": "GpMZbSM2GgvTKHJirzeGfMFoaZ8UR2X7F4v8vHTvxFbL",
        "supply": 0,
        "decimals": 9,
        "isInitialized": true,
        "freezeAuthority": null
      },
      "liquidityAAccount": {
        "mint": "So11111111111111111111111111111111111111112",
        "owner": "GpMZbSM2GgvTKHJirzeGfMFoaZ8UR2X7F4v8vHTvxFbL",
        "amount": 38280787,
        "delegate": null,
        "state": 1,
        "delegatedAmount": 0,
        "closeAuthority": null
      },
      "liquidityBAccount": {
        "mint": "7YygHaahdKVNtbu9GyFRnnBgf7hKzC76hnuHHfxCKRij",
        "owner": "GpMZbSM2GgvTKHJirzeGfMFoaZ8UR2X7F4v8vHTvxFbL",
        "amount": 314947236295,
        "delegate": null,
        "state": 1,
        "delegatedAmount": 0,
        "closeAuthority": null
      },
      "lp": {
        "baseMint": "So11111111111111111111111111111111111111112",
        "quoteMint": "7YygHaahdKVNtbu9GyFRnnBgf7hKzC76hnuHHfxCKRij",
        "lpMint": "CShf4G4A19uCes1YaHfpEvAgu4VQUo1ULnv3z9jwk1Ak",
        "quotePrice": 1.2023241815210117e-7,
        "basePrice": 134.395686967205,
        "base": 0.038280787,
        "quote": 314947.236295,
        "reserveSupply": 100,
        "currentSupply": 0,
        "quoteUSD": 0.03786686781006906,
        "baseUSD": 5.14477266651025,
        "pctReserve": 0,
        "pctSupply": 0,
        "holders": null,
        "totalTokensUnlocked": 0,
        "tokenSupply": 0,
        "lpLocked": 100,
        "lpUnlocked": 0,
        "lpLockedPct": 100,
        "lpLockedUSD": 5.1826395343203195,
        "lpMaxSupply": 0,
        "lpCurrentSupply": 0,
        "lpTotalSupply": 100
      }
    }
  ],
  "totalMarketLiquidity": 5.1826395343203195,
  "totalLPProviders": 0,
  "totalHolders": 30,
  "price": 1.2023241815210117e-7,
  "rugged": false,
  "tokenType": "",
  "transferFee": {
    "pct": 0,
    "maxAmount": 0,
    "authority": "11111111111111111111111111111111"
  },
  "knownAccounts": {
    "7hEUKwCEVFPAXVuPQXQERhzv5dPrxuZnMCBV7mHr4Up2": {
      "name": "Creator",
      "type": "CREATOR"
    },
    "GpMZbSM2GgvTKHJirzeGfMFoaZ8UR2X7F4v8vHTvxFbL": {
      "name": "Raydium CPMM Pool",
      "type": "AMM"
    }
  },
  "events": [],
  "verification": null,
  "graphInsidersDetected": 9,
  "insiderNetworks": [
    {
      "id": "little-lavender-zebra",
      "size": 9,
      "type": "transfer",
      "tokenAmount": 1000000000000000,
      "activeAccounts": 9
    }
  ],
  "detectedAt": "2025-04-17T19:31:15.439775809Z",
  "creatorTokens": null
}
```

================================================================================

--------------------------------------------------------------------------------
11. DexScreener Token Details JSON Example Output
--------------------------------------------------------------------------------
Purpose:
- Shows an example of the JSON structure returned by the DexScreener API when fetching details for a specific token (using `/tokens/v1/{chainId}/{tokenAddress}`).

Example (JOJO Token - 7YygHaahdKVNtbu9GyFRnnBgf7hKzC76hnuHHfxCKRij):
```json
[
  {
    "chainId": "solana",
    "dexId": "raydium",
    "url": "https://dexscreener.com/solana/6kcuahra1dhvfczosruerkputxe3fz4x1xk8grhtkqan",
    "pairAddress": "6kcuAhrA1dhVFCzosrUeRKPUTXE3FZ4X1Xk8GRHTkqan",
    "labels": [
      "CPMM"
    ],
    "baseToken": {
      "address": "7YygHaahdKVNtbu9GyFRnnBgf7hKzC76hnuHHfxCKRij",
      "name": "JOJO ",
      "symbol": "JOJO "
    },
    "quoteToken": {
      "address": "So11111111111111111111111111111111111111112",
      "name": "Wrapped SOL",
      "symbol": "SOL"
    },
    "priceNative": "0.0000001113",
    "priceUsd": "0.00001499",
    "txns": {
      "m5": {
        "buys": 0,
        "sells": 0
      },
      "h1": {
        "buys": 0,
        "sells": 0
      },
      "h6": {
        "buys": 93,
        "sells": 48
      },
      "h24": {
        "buys": 93,
        "sells": 48
      }
    },
    "volume": {
      "h24": 2201.67,
      "h6": 2201.67,
      "h1": 0,
      "m5": 0
    },
    "priceChange": {
      "h6": 31.43,
      "h24": 31.43
    },
    "liquidity": {
      "usd": 10.31,
      "base": 343909,
      "quote": 0.03828
    },
    "fdv": 14996,
    "marketCap": 14996,
    "pairCreatedAt": 1744919973000,
    "info": {
      "imageUrl": "https://dd.dexscreener.com/ds-data/tokens/solana/7YygHaahdKVNtbu9GyFRnnBgf7hKzC76hnuHHfxCKRij.png?key=f54bc0",
      "header": "https://dd.dexscreener.com/ds-data/tokens/solana/7YygHaahdKVNtbu9GyFRnnBgf7hKzC76hnuHHfxCKRij/header.png?key=f54bc0",
      "openGraph": "https://cdn.dexscreener.com/token-images/og/solana/7YygHaahdKVNtbu9GyFRnnBgf7hKzC76hnuHHfxCKRij?timestamp=1744939800000",
      "websites": [
        {
          "label": "Website",
          "url": "https://jojomeme.online/"
        }
      ],
      "socials": [
        {
          "type": "twitter",
          "url": "https://x.com/jojomemesol"
        },
        {
          "type": "telegram",
          "url": "https://t.me/solanajojomeme"
        }
      ]
    }
  }
]
```

================================================================================

--------------------------------------------------------------------------------
12. SolSniffer Batch Token API Example (/tokens)
--------------------------------------------------------------------------------
Purpose:
- Fetches detailed information for multiple tokens by their addresses in a batch using the SolSniffer API.

Endpoint Details:
- **Method:** `POST`
- **URL:** `https://solsniffer.com/api/v2/tokens`
- **Description:** Retrieves data for up to 100 token addresses per request. Requires an API key.

Required Headers:
- `accept: application/json`
- `Content-Type: application/json`
- `Authorization: Bearer YOUR_API_KEY` (Note: Replace `YOUR_API_KEY` with your actual Solsniffer API key. The specific header name might vary, check Solsniffer documentation if `Authorization: Bearer` doesn't work).

Request Body Format:
- A JSON object containing a single key `addresses`, which is an array of token address strings.

Request Body Example:
```json
{
  "addresses": [
    "7YygHaahdKVNtbu9GyFRnnBgf7hKzC76hnuHHfxCKRij"
  ]
}
```

Successful Response (Code 200) Format:
- Returns a JSON object with a `data` key. `data` is an array where each element corresponds to a requested token address.
- Each token object includes `address`, `basicTokenData` (with `score`, `indicatorData`, `deployTime`, `auditRisk`), and potentially an `error` field if data retrieval failed for that specific token.

Successful Response (Code 200) Example Schema:
```json
{
  "data": [
    {
      "address": "2FPyTwcZLUg1MDrwsyoP4D6s1tM7hAkHYRjkNb5w6Pxk", // Example address
      "basicTokenData": {
        "score": 85,
        "indicatorData": {
          "high": {
            "count": 5,
            "details": "{\"Previous scams by owner's wallet found\":true,\"Mintable risks found\":false,\"Freeze risks found\":true,\"Token transferability risks found\":true,\"A private wallet owns a significant share of the supply\":false,\"Tokens auto-freeze risks found\":true,\"Significant ownership by top 10 wallets\":false,\"Significant ownership by top 20 wallets\":false,\"Permanent control risks found\":true,\"Presence of token metadata\":true,\"High locked supply risks found\":false,\"Sufficient liquidity detected\":true,\"Very low liquidity\":true}"
          },
          "moderate": {
            "count": 1,
            "details": "{\"Token metadata are immutable\":false,\"Token operates without custom fees\":true,\"Token has recent user activity\":true,\"Unknown liquidity pools\":true,\"Low count of LP providers\":true}"
          },
          "low": {
            "count": 0,
            "details": "{\"Contract was not recently deployed\":true}"
          },
          "specific": {
            "count": 0,
            "details": "{\"Recent interaction within the last 30 days\":true}"
          }
        },
        "deployTime": "2023-01-01T00:00:00Z", // Example timestamp
        "auditRisk": {
          "mintDisabled": false,
          "freezeDisabled": true,
          "lpBurned": false,
          "top10Holders": false
        }
      },
      "error": null // Or "Token data not found" if applicable
    }
    // ... more token objects if multiple addresses requested
  ]
}

```

Common Error Responses:
- **Code 400 (Bad Request):** Indicates invalid input, such as malformed JSON in the request body.
  - *Example Body:* `{"errors": [{"message": "Unexpected token Y in JSON at position 24"}]}` (if address wasn't quoted)
- **Code 401 (Unauthorized):** Invalid or missing API key.
  - *Example Body:* `{"error": "Invalid API key", "message": "The provided API key is not valid.", ...}`
- **Code 429 (Too Many Requests):** API rate limit exceeded.
- **Code 500 (Internal Server Error):** An error occurred on the Solsniffer server side.

================================================================================

--------------------------------------------------------------------------------
13. DexScreener Latest Token Profiles API Example (/token-profiles/latest/v1)
--------------------------------------------------------------------------------
Purpose:
- Fetches a list of the latest token profiles created on DexScreener.

Endpoint Details:
- **Method:** `GET`
- **URL:** `https://api.dexscreener.com/token-profiles/latest/v1`
- **Description:** Returns an array of token profile objects.

Python Example (using `requests` library):
```python
import requests

response = requests.get(
    "https://api.dexscreener.com/token-profiles/latest/v1",
    headers={"Accept":"*/*"},
)

if response.status_code == 200:
    data = response.json()
    # Process the data (list of token profiles)
    print(f"Successfully fetched {len(data)} token profiles.")
else:
    print(f"Error fetching data: {response.status_code}")

```

Response Body Format:
- A JSON array where each object represents a token profile.
- Each profile includes details like DexScreener URL, chain ID, token address, image links, description, and social/website links.

Response Body Example (Truncated):
```json
[
  {
    "url": "https://dexscreener.com/ethereum/0x1492bf16c9879c928b861ec6f4fed976a3113a0f",
    "chainId": "ethereum",
    "tokenAddress": "0x1492BF16C9879C928B861Ec6F4Fed976a3113A0F",
    "icon": "https://dd.dexscreener.com/ds-data/tokens/ethereum/0x1492bf16c9879c928b861ec6f4fed976a3113a0f.png",
    "header": "https://dd.dexscreener.com/ds-data/tokens/ethereum/0x1492bf16c9879c928b861ec6f4fed976a3113a0f/header.png",
    "openGraph": "https://cdn.dexscreener.com/token-images/og/ethereum/0x1492bf16c9879c928b861ec6f4fed976a3113a0f?timestamp=1744941300000",
    "description": "Peep is the less famous half-brother of Pepe.",
    "links": [
      {
        "label": "Website",
        "url": "https://peeperc.fun/"
      },
      {
        "type": "twitter",
        "url": "https://x.com/peepthetoad_erc"
      },
      {
        "type": "telegram",
        "url": "https://t.me/Peep_eth"
      }
    ]
  },
  {
    "url": "https://dexscreener.com/solana/6pwrctnrxwelqdtqaz9xywqu3gk87wrkn9grrxlqpump",
    "chainId": "solana",
    "tokenAddress": "6pwrctNrXweLQDtQAz9XYwqu3GK87wRkn9GrrXLqpump",
    "icon": "https://dd.dexscreener.com/ds-data/tokens/solana/6pwrctNrXweLQDtQAz9XYwqu3GK87wRkn9GrrXLqpump.png",
    "header": "https://dd.dexscreener.com/ds-data/tokens/solana/6pwrctNrXweLQDtQAz9XYwqu3GK87wRkn9GrrXLqpump/header.png",
    "openGraph": "https://cdn.dexscreener.com/token-images/og/solana/6pwrctNrXweLQDtQAz9XYwqu3GK87wRkn9GrrXLqpump?timestamp=1744941300000",
    "description": "REPO is a 2025 online co-op horror video game that is one of the most memeable games & is taking tiktok by storm.",
    "links": [
      {
        "label": "Website",
        "url": "https://therepogame.com"
      },
      {
        "type": "twitter",
        "url": "https://x.com/RepoSolana"
      },
      {
        "type": "telegram",
        "url": "https://t.me/TheRepoGame"
      }
    ]
  },
  {
    "url": "https://dexscreener.com/solana/guquaeufene3cgsevkmswueigwdtr25nwt9hxengoeyx",
    "chainId": "solana",
    "tokenAddress": "GuquAeUFeNe3cgsEvKMSWUEigWDTR25nwt9HxENGoeYx",
    "icon": "https://dd.dexscreener.com/ds-data/tokens/solana/GuquAeUFeNe3cgsEvKMSWUEigWDTR25nwt9HxENGoeYx.png",
    "header": "https://dd.dexscreener.com/ds-data/tokens/solana/GuquAeUFeNe3cgsEvKMSWUEigWDTR25nwt9HxENGoeYx/header.png",
    "openGraph": "https://cdn.dexscreener.com/token-images/og/solana/GuquAeUFeNe3cgsEvKMSWUEigWDTR25nwt9HxENGoeYx?timestamp=1744941300000",
    "description": "I say what you're too dumb to think.RETARD POWER. 🧢",
    "links": [
      {
        "label": "Website",
        "url": "http://retardtrump.xyz"
      },
      {
        "type": "twitter",
        "url": "https://x.com/RETARD_TRUMP_"
      },
      {
        "type": "telegram",
        "url": "https://t.me/RETARD_TRUMP_Official"
      }
    ]
  }
  // ... more token profile objects (response truncated)
]
```

================================================================================
