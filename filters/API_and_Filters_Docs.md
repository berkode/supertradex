# **API Integration and Filters Documentation**

This comprehensive documentation outlines both the API integration architecture and the filtering system used in the Synthron Crypto Trader system.

---

## **Part 1: API Integration**

### **Overview**

The token scanner system integrates with multiple APIs to gather comprehensive token data. This section outlines the API integration architecture and implementation details.

### **API Clients**

#### **Solsniffer API**
- **Purpose**: Token analysis and scoring
- **Key Features**:
  - Token data retrieval
  - Score calculation
  - Risk assessment
- **Configuration**:
  - API Key: `SOLSNIFFER_API_KEY`
  - Base URL: `SOLSNIFFER_API_URL`
  - Minimum Score: `MIN_SOLSNIFFER_SCORE`

#### **SolanaTracker API**
- **Purpose**: Token tracking and analytics
- **Key Features**:
  - Token data retrieval
  - Market metrics
  - Trading activity
- **Configuration**:
  - API Key: `SOLANATRACKER_API_KEY`
  - Base URL: `SOLANATRACKER_URL`

#### **Rugcheck API**
- **Purpose**: Token security analysis
- **Key Features**:
  - Token report generation
  - Security assessment
  - Risk analysis
- **Configuration**:
  - API Key: `RUGCHECK_API_KEY`
  - Base URL: `RUGCHECK_URL`

### **Integration Architecture**

#### **TokenScanner Class**
The `TokenScanner` class serves as the main orchestrator for API integration:

1. **Initialization**:
   - Validates required API credentials
   - Initializes API clients with proper configuration
   - Sets up error handling and logging

2. **Data Collection**:
   - Fetches data from multiple APIs concurrently
   - Handles API errors gracefully
   - Implements rate limiting and retries

3. **Data Processing**:
   - Processes raw API responses
   - Merges data from different sources
   - Validates token data

#### **Error Handling**
- Each API call is wrapped in try-catch blocks
- Detailed error logging for debugging
- Graceful fallback when APIs fail
- Retry mechanism for transient failures

#### **Rate Limiting**
- Built-in rate limiting for each API
- Configurable delays between requests
- Proxy rotation support

### **Usage Example**

```python
# Initialize TokenScanner
scanner = TokenScanner(
    db=token_database,
    http_client=httpx.AsyncClient(),
    settings=settings,
    thresholds=thresholds
)

# Get token data
token_data = await scanner.get_token_data(token_mint)

# Scan tokens
await scanner.scan_tokens()
```

### **Environment Variables**

Required environment variables for API integration:

```env
SOLSNIFFER_API_KEY=your_api_key
SOLSNIFFER_API_URL=https://api.solsniffer.com
MIN_SOLSNIFFER_SCORE=50

SOLANATRACKER_API_KEY=your_api_key
SOLANATRACKER_URL=https://api.solanatracker.com

RUGCHECK_API_KEY=your_api_key
RUGCHECK_URL=https://api.rugcheck.com
```

### **Best Practices**

1. **Error Handling**:
   - Always check for None values in API responses
   - Implement proper error logging
   - Use fallback values when needed

2. **Rate Limiting**:
   - Respect API rate limits
   - Implement exponential backoff
   - Use proxy rotation when available

3. **Data Processing**:
   - Validate API responses
   - Handle missing data gracefully
   - Normalize data from different sources

4. **Monitoring**:
   - Monitor API response times
   - Track error rates
   - Log API usage statistics

### **Troubleshooting**

Common issues and solutions:

1. **API Authentication Errors**:
   - Verify API keys are correct
   - Check API key permissions
   - Ensure proper header formatting

2. **Rate Limiting Issues**:
   - Implement proper delays
   - Use proxy rotation
   - Monitor request frequency

3. **Data Processing Errors**:
   - Validate API responses
   - Check data types
   - Handle missing fields

---

## **Part 2: Filters System**

This section outlines the key functionalities of each filter in the system. These filters ensure robust token selection, mitigate risks, and enhance trading decision-making.

### **1. `blacklist.py`**

#### **Class: Blacklist**
Manages a blacklist of tokens to avoid trading, with features for manual updates and external source integration.

##### **Methods**
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

### **2. `liquidity_filter.py`**

#### **Class: LiquidityFilter**
Identifies tokens with inadequate liquidity for safe trading.

##### **Methods**
- **`__init__(min_liquidity_threshold: float, min_liquidity_ratio: float, logging_level: int)`**
  - Initializes the filter with thresholds and logging.

- **`analyze_token(token_data: Dict[str, Any]) -> Dict[str, Any]`**
  - Analyzes a token's liquidity and market cap for risks.

- **`filter_tokens(tokens_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]`**
  - Filters a list of tokens for liquidity risks.

### **3. `rug_filter.py`**

#### **Class: RugPullFilter**
Detects tokens with rug-pull risks using key risk indicators and developer activity thresholds.

##### **Methods**
- **`__init__(rug_pull_score_threshold: float, dev_wallet_activity_threshold: float, logging_level: int)`**
  - Initializes the filter with thresholds and logging.

- **`analyze_token(token_data: Dict[str, Any]) -> Dict[str, Any]`**
  - Assesses rug-pull risks for a token.

- **`filter_tokens(tokens_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]`**
  - Filters tokens for rug-pull risks.

### **4. `scam_filter.py`**

#### **Class: ScamFilter**
Analyzes smart contracts for scam patterns like hidden fees, unrestricted mint functions, and burnt liquidity.

##### **Methods**
- **`__init__(logging_level: int)`**
  - Initializes the filter with a predefined list of scam patterns.

- **`analyze_contract(contract_data: Dict[str, any]) -> Dict[str, any]`**
  - Scans a smart contract for known scam patterns.

- **`filter_contracts(contracts_data: List[Dict[str, any]]) -> List[Dict[str, any]]`**
  - Filters a list of smart contracts for potential scams.

### **5. `trending_moonshot_coin_filter.py`**

#### **Class: TrendingMoonshotCoinFilter**
Filters coins based on trending criteria to identify potential moonshot opportunities.

##### **Methods**
- **`__init__(min_volume_threshold: float, min_trending_score: float, min_price_change_percent: float, logging_level: int)`**
  - Initializes the filter with thresholds for trading volume, trending score, and price change.

- **`filter_coins(coins_data: List[Dict]) -> List[Dict]`**
  - Filters coins based on trending moonshot criteria.

### **6. `volume_filter.py`**

#### **Class: VolumeFilter**
Filters out tokens with low trading volume.

##### **Methods**
- **`__init__(min_volume_threshold: float, logging_level: int)`**
  - Initializes the filter with a minimum volume threshold.

- **`filter_tokens(tokens_volume: Dict[str, float]) -> List[str]`**
  - Filters tokens based on their trading volume.

### **7. `whale_filter.py`**

#### **Class: WhaleFilter**
Detects tokens with suspicious whale activity based on predefined thresholds.

##### **Methods**
- **`__init__(whale_threshold: float, suspicious_threshold: int, logging_level: int)`**
  - Initializes the filter with thresholds for whale activity and suspicious account counts.

- **`analyze_token(token: str, holder_data: Dict[str, float]) -> bool`**
  - Analyzes a token for whale activity.

- **`filter_tokens(tokens_data: Dict[str, Dict[str, float]]) -> List[str]`**
  - Filters tokens based on whale activity.

### **8. `whitelist.py`**

#### **Class: Whitelist**
Manages a list of safe tokens for immediate trading.

##### **Methods**
- **`__init__(initial_tokens: List[str], whitelist_file: str)`**
  - Initializes the whitelist with optional preloaded tokens and file support.

- **`scan_token(token: str) -> bool`**
  - Uses TokenScanner to list and add tokens to the whitelist.

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

### **9. `token_scanner.py`**

#### **Class: TokenScanner**
Creates a list of safe tokens for immediate trading.

### **10. `twitter_check.py`**

#### **Class: TwitterCheck**
Checks token twitter page for followers and user credibility.

---

## **Part 3: Integration of APIs and Filters**

The APIs and filters work together to create a comprehensive token evaluation system:

1. **Data Collection**: APIs collect token data from various sources
2. **Data Processing**: Raw data is processed into a standardized format
3. **Filtering**: Multiple filters are applied to identify safe, promising tokens
4. **Decision Making**: Filtered tokens are passed to trading strategies

### **Workflow**

1. `TokenScanner` collects data using various APIs
2. Data is processed and standardized
3. Filters are applied in sequence:
   - Blacklist/Whitelist validation
   - Security filters (Rug, Scam)
   - Market filters (Volume, Liquidity)
   - Strategy-specific filters (Trending, Whale)
4. Filtered tokens are stored in the database and made available for trading strategies

### **Configuration**

The entire system is configurable through environment variables and configuration classes:
- `Settings`: General application settings
- `Thresholds`: Trading and filtering thresholds
- `FiltersConfig`: Filter-specific configuration

This allows for flexible deployment and easy adjustment of trading parameters.

---

## **Conclusion**

The combination of robust API integration and comprehensive filtering creates a powerful system for identifying high-potential trading opportunities while mitigating risks. The modular architecture allows for easy extension with additional data sources and filtering criteria. 