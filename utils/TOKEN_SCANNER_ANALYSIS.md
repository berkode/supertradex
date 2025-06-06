# Token Scanner Analysis - SupertradeX System

## Overview

The **TokenScanner** is a core component of the SupertradeX automated trading system that continuously discovers, analyzes, and qualifies new Solana tokens for potential trading opportunities. It operates as an automated token discovery and filtering pipeline that runs every 60 seconds.

## What the Token Scanner Does

### 🔍 Primary Functions

1. **Token Discovery**: Fetches trending tokens from DexScreener API
2. **Multi-Stage Filtering**: Applies progressive filters to identify high-quality tokens
3. **Data Enrichment**: Gathers comprehensive token metadata from multiple sources
4. **Risk Assessment**: Evaluates tokens using various security and quality metrics
5. **Database Management**: Stores qualified tokens with full analysis results
6. **Trading Preparation**: Selects the best tokens for automated trading strategies

### 🔄 Scanning Process Flow

#### Step 1: Fetch Trending Tokens
- **Source**: DexScreener API trending tokens endpoint
- **Initial Filter**: Requires both icon and Twitter presence
- **Chain Filter**: Solana tokens only
- **Quantity Limit**: Configurable via `DEXSCREENER_TOKEN_QTY` setting

#### Step 2: Pre-Qualification
- **Liquidity Check**: Minimum USD liquidity threshold
- **Volume Check**: Minimum 24-hour trading volume
- **Age Calculation**: Token age in minutes from pair creation
- **Blacklist Check**: Ensures token is not blacklisted

#### Step 3: Data Enrichment
- **DexScreener Details**: Market cap, price, volume, liquidity metrics
- **Token Categorization**: Based on age, market cap, and activity
- **Social Media Data**: Twitter verification and follower counts
- **Security Analysis**: RugCheck and SolSniffer scores

#### Step 4: Comprehensive Filtering
The FilterManager applies multiple filters in sequence:

##### Critical Filters (Early Exit)
- **Blacklist Filter**: Checks against known scam/problematic tokens
- **DumpCheck Filter**: Security score analysis (must be lower than MAX_RUGCHECK_SCORE from env)
- **SolSniffer Filter**: Additional security verification

##### Quality Filters
- **Liquidity Filter**: Ensures adequate trading liquidity
- **Volume Filter**: Validates trading activity levels
- **Social Filter**: Verifies social media presence and engagement
- **Whale Filter**: Analyzes holder distribution
- **Dump Filter**: Detects potential dump patterns
- **Scam Filter**: Identifies scam indicators

##### Special Filters
- **Bonding Curve Filter**: For PumpFun tokens only
- **Moonshot Filter**: Identifies high-potential tokens
- **Whitelist Filter**: Prioritizes pre-approved tokens

#### Step 5: Database Storage
- **Token Metadata**: Complete token information
- **Filter Results**: All analysis outcomes
- **Monitoring Status**: Tracking and trading readiness
- **Historical Data**: Price and volume tracking

#### Step 6: Best Token Selection
- **Scoring Algorithm**: Volume + liquidity weighted
- **Trading Readiness**: Marks tokens ready for strategies
- **Risk Assessment**: Final risk categorization

## 📊 Token Categories

The scanner categorizes tokens based on multiple factors:

### By Age
- **FRESH**: 0-5 minutes old
- **NEW**: 1-45 minutes old
- **FINAL**: 45-120 minutes old
- **MIGRATED**: Up to 5 minutes old (bonding curve completion > 0.8)
- **OLD**: 120+ minutes old

### By Market Cap
- **MICRO**: < $100K
- **SMALL**: $100K - $1M
- **MEDIUM**: $1M - $10M
- **LARGE**: > $10M

### By Risk Level
- **LOW_RISK**: High security scores, established
- **MEDIUM_RISK**: Moderate scores, some concerns
- **HIGH_RISK**: New tokens, lower scores
- **EXTREME_RISK**: Multiple red flags

## 🛡️ Security & Quality Filters

### DumpCheck Analysis
- **Score Range**: 0-100 (lower is better)
- **Threshold**: Must be lower than MAX_RUGCHECK_SCORE (default: 55)
- **Checks**: Contract security, ownership, liquidity locks

### SolSniffer Verification
- **Score Range**: 0-100 (higher is better)
- **Threshold**: Must be higher than MIN_SOLSNIFFER_SCORE (default: 61)
- **Multi-Factor Analysis**: Contract code, behavior patterns
- **Risk Indicators**: Honeypot detection, mint authority
- **Community Signals**: Reputation and trust scores

### Social Media Verification
- **Twitter Presence**: Active account required
- **Follower Count**: Minimum threshold validation
- **Engagement Quality**: Real vs. bot followers
- **Content Analysis**: Project legitimacy indicators

### Liquidity & Volume Filters
- **Minimum Liquidity**: Set by MIN_LIQUIDITY environment variable
- **24h Volume**: Set by MIN_VOLUME_24H environment variable
- **Volume/Liquidity Ratio**: Healthy trading activity
- **Price Stability**: Volatility within acceptable ranges

## 🔧 Configuration & Thresholds

### Key Settings (Environment Variables)
```
# Scanning Configuration
TOKEN_SCAN_INTERVAL=300         # Seconds between scans (from env)
DEXSCREENER_TOKEN_QTY=7        # Max tokens per scan (from env)

# Filter Thresholds (all from environment variables)
MIN_LIQUIDITY=1000             # Minimum USD liquidity
MIN_VOLUME_24H=500            # Minimum 24h volume
MAX_RUGCHECK_SCORE=55         # Maximum acceptable risk (lower is better)
MIN_SOLSNIFFER_SCORE=61       # Minimum security score (higher is better)

# Filter Enablement (from environment variables)
FILTER_RUGCHECK_ENABLED=true
FILTER_SOCIAL_ENABLED=true
FILTER_LIQUIDITY_ENABLED=false
FILTER_VOLUME_ENABLED=false
FILTER_SCAM_ENABLED=false
FILTER_BONDING_CURVE_ENABLED=false
```

### Filter Priority Order
1. **Blacklist** (Critical - immediate rejection)
2. **Whitelist** (Priority - immediate approval)
3. **DumpCheck** (Critical - security assessment)
4. **SolSniffer** (Critical - additional security)
5. **Scam Detection** (Critical - pattern analysis)
6. **Liquidity** (Quality - trading viability)
7. **Volume** (Quality - activity validation)
8. **Social Media** (Quality - legitimacy check)
9. **Whale Analysis** (Risk - distribution check)
10. **Dump Detection** (Risk - pattern analysis)
11. **Bonding Curve** (Special - PumpFun tokens)
12. **Moonshot** (Opportunity - high potential)

## 📈 Integration with Trading System

### Database Schema
The scanner populates the token database with:
- **Basic Info**: mint, symbol, name, pair_address
- **Market Data**: price, liquidity, volume, market_cap
- **Analysis Results**: filter outcomes, scores, categories
- **Metadata**: age, dex_id, monitoring_status
- **Raw Data**: Complete API responses in JSON format

### Trading Strategy Integration
- **Token Selection**: Best tokens marked for trading
- **Risk Management**: Category-based position sizing
- **Entry Conditions**: Filter results inform timing
- **Exit Strategies**: Continuous monitoring for changes

### Monitoring & Alerts
- **Price Tracking**: Real-time price updates
- **Volume Monitoring**: Trading activity surveillance
- **Risk Changes**: Updated security scores
- **Market Conditions**: Liquidity and volatility tracking

## 🚨 Risk Management

### Early Exit Conditions
During initial scans, the scanner implements early exit for efficiency:
- **Blacklisted Tokens**: Immediate rejection
- **Failed Security Checks**: Stop processing on critical failures
- **API Errors**: Graceful handling with retry logic

### Error Handling
- **API Failures**: Fallback mechanisms and retry logic
- **Data Validation**: Comprehensive input sanitization
- **Circuit Breakers**: Prevent cascade failures
- **Logging**: Detailed audit trail for debugging

### Performance Optimization
- **Batch Processing**: Efficient API usage
- **Caching**: Reduce redundant API calls
- **Parallel Processing**: Concurrent filter application
- **Database Optimization**: Efficient storage and retrieval

## 📊 Typical Scan Results

Based on real-world operation:
- **Initial Fetch**: 50-100 trending tokens
- **Chain Filter**: ~30-60 Solana tokens
- **Icon/Twitter Filter**: ~20-40 tokens
- **Pre-qualification**: ~10-25 tokens
- **Full Analysis**: ~5-15 tokens
- **Final Qualification**: ~1-5 tokens per scan

### Success Metrics
- **Discovery Rate**: New tokens found per hour
- **Quality Score**: Percentage passing all filters
- **Trading Success**: Performance of selected tokens
- **Risk Avoidance**: Scams and rugs prevented

## 🔄 Continuous Operation

The TokenScanner runs continuously with:
- **300-second intervals**: Regular discovery cycles (TOKEN_SCAN_INTERVAL from env)
- **24/7 operation**: Constant market monitoring
- **Automatic recovery**: Resilient error handling
- **Performance monitoring**: System health tracking

## ⚠️ Important Notes

**All thresholds and configuration values are sourced from environment variables:**
- No hardcoded constants in code, settings, or thresholds files
- All values configurable via environment variables
- Default values only used as fallbacks when env vars are missing
- Token categories: FRESH, NEW, FINAL, MIGRATED, OLD (not the generic age-based categories)
- DumpCheck scores: Lower is better (must be < MAX_RUGCHECK_SCORE)
- SolSniffer scores: Higher is better (must be > MIN_SOLSNIFFER_SCORE)
- Bonding Curve analysis: PumpFun tokens only (not PumpSwap)

This comprehensive token discovery and analysis system ensures that only high-quality, secure, and potentially profitable tokens are selected for automated trading, while maintaining strict risk management and security standards. 