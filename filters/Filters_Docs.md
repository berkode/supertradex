# **Filters Documentation**

This documentation outlines the key functionalities of each filter in the Synthron Crypto Trader system. These filters ensure robust token selection, mitigate risks, and enhance trading decision-making.

---

## **1. `blacklist.py`**

### **Class: Blacklist**
Manages a blacklist of tokens to avoid trading, with features for manual updates and external source integration.

#### **Methods**
- **`__init__(blacklist_file: Optional[str], logging_level: int)`**
  - Initializes the blacklist with optional file loading and logging configuration.

- **`add_token(token: str) -> bool`**
  - Adds a token to the blacklist.

- **`remove_token(token: str) -> bool`**
  - Removes a token from the blacklist.

- **`is_blacklisted(token: str) -> bool`**
  - Checks if a token is in the blacklist.

- **`get_blacklist() -> List[str]`**
  - Retrieves a sorted list of blacklisted tokens.

- **`update_blacklist_from_source(source: List[str]) -> List[str]`**
  - Updates the blacklist using tokens from an external source.

---

## **2. `liquidity_filter.py`**

### **Class: LiquidityFilter**
Identifies tokens with inadequate liquidity for safe trading.

#### **Methods**
- **`__init__(min_liquidity_threshold: float, min_liquidity_ratio: float, logging_level: int)`**
  - Initializes the filter with thresholds and logging.

- **`analyze_token(token_data: Dict[str, Any]) -> Dict[str, Any]`**
  - Analyzes a token's liquidity and market cap for risks.

- **`filter_tokens(tokens_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]`**
  - Filters a list of tokens for liquidity risks.

---

## **3. `rug_filter.py`**

### **Class: RugPullFilter**
Detects tokens with rug-pull risks using key risk indicators and developer activity thresholds.

#### **Methods**
- **`__init__(rug_pull_score_threshold: float, dev_wallet_activity_threshold: float, logging_level: int)`**
  - Initializes the filter with thresholds and logging.

- **`analyze_token(token_data: Dict[str, Any]) -> Dict[str, Any]`**
  - Assesses rug-pull risks for a token.

- **`filter_tokens(tokens_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]`**
  - Filters tokens for rug-pull risks.

---

## **4. `scam_filter.py`**

### **Class: ScamFilter**
Analyzes smart contracts for scam patterns like hidden fees, unrestricted mint functions, and burnt liquidity.

#### **Methods**
- **`__init__(logging_level: int)`**
  - Initializes the filter with a predefined list of scam patterns.

- **`analyze_contract(contract_data: Dict[str, any]) -> Dict[str, any]`**
  - Scans a smart contract for known scam patterns.

- **`filter_contracts(contracts_data: List[Dict[str, any]]) -> List[Dict[str, any]]`**
  - Filters a list of smart contracts for potential scams.

---

## **5. `trending_moonshot_coin_filter.py`**

### **Class: TrendingMoonshotCoinFilter**
Filters coins based on trending criteria to identify potential moonshot opportunities.

#### **Methods**
- **`__init__(min_volume_threshold: float, min_trending_score: float, min_price_change_percent: float, logging_level: int)`**
  - Initializes the filter with thresholds for trading volume, trending score, and price change.

- **`filter_coins(coins_data: List[Dict]) -> List[Dict]`**
  - Filters coins based on trending moonshot criteria.

---

## **6. `volume_filter.py`**

### **Class: VolumeFilter**
Filters out tokens with low trading volume.

#### **Methods**
- **`__init__(min_volume_threshold: float, logging_level: int)`**
  - Initializes the filter with a minimum volume threshold.

- **`filter_tokens(tokens_volume: Dict[str, float]) -> List[str]`**
  - Filters tokens based on their trading volume.

---

## **7. `whale_filter.py`**

### **Class: WhaleFilter**
Detects tokens with suspicious whale activity based on predefined thresholds.

#### **Methods**
- **`__init__(whale_threshold: float, suspicious_threshold: int, logging_level: int)`**
  - Initializes the filter with thresholds for whale activity and suspicious account counts.

- **`analyze_token(token: str, holder_data: Dict[str, float]) -> bool`**
  - Analyzes a token for whale activity.

- **`filter_tokens(tokens_data: Dict[str, Dict[str, float]]) -> List[str]`**
  - Filters tokens based on whale activity.

---

## **8. `whitelist.py`**

### **Class: Whitelist**
Manages a list of safe tokens for immediate trading.

#### **Methods**
- **`__init__(initial_tokens: List[str], whitelist_file: str)`**
  - Initializes the whitelist with optional preloaded tokens and file support.

- **`add_token(token: str) -> bool`**
  - Adds a token to the whitelist.

- **`remove_token(token: str) -> bool`**
  - Removes a token from the whitelist.

- **`is_whitelisted(token: str) -> bool`**
  - Checks if a token is in the whitelist.

- **`get_all_tokens() -> List[str]`**
  - Retrieves all tokens in the whitelist.

- **`clear_whitelist()`**
  - Clears all tokens from the whitelist.

---
