import pandas as pd
import requests
from datetime import datetime, timedelta
import time
import os
from typing import Optional, Dict, List, Any, Callable
import json
from dotenv import load_dotenv
import logging
from pathlib import Path

# Import settings
from config.settings import Settings

# Load environment variables
load_dotenv()

class SolanaDataFetcher:
    def __init__(self, settings: Optional[Settings] = None, helius_api_key: Optional[str] = None):
        """
        Initialize Solana data fetcher.
        
        Args:
            settings: Settings object for configuration
            helius_api_key: Helius API key for enhanced data access (overrides settings if provided)
        """
        # Use provided settings or create a new instance
        self.settings = settings or Settings()
        
        # Use provided API key or get from settings
        self.helius_api_key = helius_api_key or self.settings.HELIUS_API_KEY
        
        # Get all URL endpoints from settings
        self.helius_rpc_url = self.settings.HELIUS_RPC_URL
        self.solana_mainnet_rpc = self.settings.SOLANA_MAINNET_RPC
        
        # Log configuration
        logging.debug(f"SolanaDataFetcher initialized with Helius RPC: {self.helius_rpc_url}")
            
        self.base_urls = {
            'primary': self.helius_rpc_url,  # Use Helius as primary
            'fallback': self.solana_mainnet_rpc,  # Solana mainnet as fallback
            'dex_screener': 'https://api.dexscreener.com/latest/dex',
            'pump_fun': 'https://api.pump.fun/v1',
            'raydium': self.settings.RAYDIUM_API_URL  # Use RAYDIUM_API_URL from settings
        }
    
    def fetch_helius_data(self, mint: str, interval: str = '1h', limit: int = 720) -> Optional[pd.DataFrame]:
        """Fetch historical data from Helius API using RPC endpoint with fallback support."""
        if not self.helius_api_key:
            print("Warning: Helius API key not provided. Using alternative data sources.")
            return None
            
        # Prepare RPC request
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenPriceHistory",
            "params": {
                "tokenAddress": mint,
                "interval": interval,
                "limit": limit
            }
        }
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.helius_api_key}'
        }
        
        # Try primary endpoint first (Helius)
        try:
            print(f"Fetching from primary RPC endpoint: {self.base_urls['primary']}")
            response = requests.post(str(self.base_urls['primary']), json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            if 'error' in data:
                print(f"Primary RPC Error: {data['error']}")
                raise Exception(f"Primary RPC Error: {data['error']}")
                
            # Convert to DataFrame
            prices = data.get('result', {}).get('prices', [])
            if not prices:
                raise Exception("No price data returned from primary endpoint")
                
            df = pd.DataFrame(prices)
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.rename(columns={'price': 'price', 'volume': 'volume'}, inplace=True)
            
            print("Successfully fetched data from primary endpoint")
            return df
            
        except Exception as primary_error:
            print(f"Error fetching data from primary RPC: {str(primary_error)}")
            
            # Try fallback endpoint (Solana)
            try:
                if not self.base_urls['fallback']:
                    print("No fallback RPC URL configured.")
                    return None
                    
                print(f"Trying fallback RPC endpoint: {self.base_urls['fallback']}")
                response = requests.post(str(self.base_urls['fallback']), json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
                
                if 'error' in data:
                    print(f"Fallback RPC Error: {data['error']}")
                    return None
                    
                # Convert to DataFrame
                prices = data.get('result', {}).get('prices', [])
                if not prices:
                    return None
                    
                df = pd.DataFrame(prices)
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df.rename(columns={'price': 'price', 'volume': 'volume'}, inplace=True)
                
                print("Successfully fetched data from fallback endpoint")
                return df
                
            except Exception as fallback_error:
                print(f"Error fetching data from fallback RPC: {str(fallback_error)}")
            return None
    
    def subscribe_to_realtime_data(self, mint: str, callback):
        """
        Subscribe to real-time price updates using WebSocket.
        
        Args:
            mint: Token mint to monitor
            callback: Function to handle incoming data
        """
        import websocket
        import json
        
        # Get WebSocket URLs from settings via property
        helius_wss_url = self.settings.HELIUS_WSS_URL  # This now includes API key
        solana_mainnet_wss = self.settings.SOLANA_MAINNET_WSS
        
        # Create connection attempt wrappers to try different endpoints
        def create_primary_connection():
            """Create WebSocket connection to primary endpoint (Helius)"""
            logging.debug(f"Creating WebSocket connection to primary endpoint (Helius)")
            return self._create_websocket_connection(
                helius_wss_url, 
                mint, 
                callback, 
                "primary", 
                create_fallback_connection
            )
            
        def create_fallback_connection():
            """Create WebSocket connection to fallback endpoint (Solana Mainnet)"""
            if not solana_mainnet_wss:
                logging.warning("No fallback WebSocket URL configured.")
                return None
                
            logging.debug(f"Creating WebSocket connection to fallback endpoint (Solana Mainnet)")
            return self._create_websocket_connection(
                solana_mainnet_wss, 
                mint, 
                callback, 
                "fallback", 
                None  # No further fallback
            )
            
        # Start with primary connection
        return create_primary_connection()
        
    def _create_websocket_connection(self, ws_url, mint, callback, endpoint_name, fallback_fn=None):
        """
        Helper method to create a WebSocket connection with proper handlers
        
        Args:
            ws_url: WebSocket endpoint URL
            mint: Token mint to monitor
            callback: Function to handle incoming data
            endpoint_name: Name of endpoint for logging
            fallback_fn: Function to call if this connection fails
        """
        import websocket
        import json
        
        def on_message(ws, message):
            try:
                data = json.loads(message)
                callback(data)
            except Exception as e:
                print(f"Error processing WebSocket message: {str(e)}")
        
        def on_error(ws, error):
            print(f"WebSocket Error ({endpoint_name}): {str(error)}")
            # If fallback is available and defined, try it
            if fallback_fn:
                print(f"Attempting fallback WebSocket connection...")
                fallback_fn()
        
        def on_close(ws, close_status_code, close_msg):
            print(f"WebSocket connection closed ({endpoint_name})")
            # Could retry or switch to fallback here as well
        
        def on_open(ws):
            print(f"WebSocket connection established to {endpoint_name} endpoint")
            # Subscribe to token price updates
            subscribe_message = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "subscribe",
                "params": {
                    "tokenAddress": mint
                }
            }
            ws.send(json.dumps(subscribe_message))
        
        websocket.enableTrace(True)
        ws = websocket.WebSocketApp(ws_url,
                                  on_open=on_open,
                                  on_message=on_message,
                                  on_error=on_error,
                                  on_close=on_close)
        
        return ws
    
    def fetch_dex_screener_data(self, mint: str, interval: str = '1h', limit: int = 720) -> Optional[pd.DataFrame]:
        """Fetch historical data from DexScreener."""
        endpoint = f"{self.base_urls['dex_screener']}/tokens/{mint}"
        
        try:
            response = requests.get(endpoint)
            response.raise_for_status()
            data = response.json()
            
            # Get pair data
            pairs = data.get('pairs', [])
            if not pairs:
                return None
                
            # Get the most liquid pair
            pair = max(pairs, key=lambda x: x.get('liquidity', {}).get('usd', 0))
            pair_address = pair['pairAddress']
            
            # Fetch historical data
            history_endpoint = f"{self.base_urls['dex_screener']}/pairs/{pair_address}/history"
            history_params = {
                'interval': interval,
                'limit': limit
            }
            
            history_response = requests.get(history_endpoint, params=history_params)
            history_response.raise_for_status()
            history_data = history_response.json()
            
            # Convert to DataFrame
            df = pd.DataFrame(history_data)
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.rename(columns={'priceUsd': 'price', 'volumeUsd': 'volume'}, inplace=True)
            
            return df
            
        except Exception as e:
            print(f"Error fetching data from DexScreener: {str(e)}")
            return None
    
    def fetch_pump_fun_data(self, mint: str, interval: str = '1h', limit: int = 720) -> Optional[pd.DataFrame]:
        """Fetch historical data from Pump.fun."""
        endpoint = f"{self.base_urls['pump_fun']}/tokens/{mint}/history"
        params = {
            'interval': interval,
            'limit': limit
        }
        
        try:
            response = requests.get(endpoint, params=params)
            response.raise_for_status()
            data = response.json()
            
            # Convert to DataFrame
            df = pd.DataFrame(data)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.rename(columns={'price': 'price', 'volume': 'volume'}, inplace=True)
            
            return df
            
        except Exception as e:
            print(f"Error fetching data from Pump.fun: {str(e)}")
            return None
    
    def fetch_data(self, mint: str, interval: str = '1h', limit: int = 720) -> Optional[pd.DataFrame]:
        """
        Fetch historical data from multiple sources and combine them.
        Prioritizes data sources based on availability and quality.
        """
        # Try Helius first (best quality)
        df = self.fetch_helius_data(mint, interval, limit)
        if df is not None:
            return df
            
        # Try DexScreener next
        df = self.fetch_dex_screener_data(mint, interval, limit)
        if df is not None:
            return df
            
        # Try Pump.fun last
        df = self.fetch_pump_fun_data(mint, interval, limit)
        if df is not None:
            return df
            
        print("Error: Could not fetch data from any source")
        return None

def save_historical_data(df: pd.DataFrame, output_path: str) -> bool:
    """Save historical data to CSV file."""
    try:
        df.to_csv(output_path, index=False)
        print(f"Data saved successfully to {output_path}")
        return True
    except Exception as e:
        print(f"Error saving data: {str(e)}")
        return False

def fetch_and_save_data(mint: str, interval: str = '1h', 
                       limit: int = 720, output_path: str = 'synthron/outputs/historical_data.csv',
                       helius_api_key: Optional[str] = None) -> Optional[pd.DataFrame]:
    """
    Fetch historical data and save it to a CSV file.
    
    Args:
        mint: Solana token mint
        interval: Time interval (1m, 5m, 15m, 1h, etc.)
        limit: Number of data points
        output_path: Path to save the data
        helius_api_key: Optional Helius API key for enhanced data access
    """
    print(f"Fetching {limit} {interval} candles for token {mint}...")
    
    fetcher = SolanaDataFetcher(helius_api_key)
    df = fetcher.fetch_data(mint, interval, limit)
    
    if df is not None:
        success = save_historical_data(df, output_path)
        if success:
            print(f"Successfully fetched and saved {len(df)} data points")
            return df
    return None

if __name__ == "__main__":
    # Example usage with a Solana meme token (Updated Comment)
    mint = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263" # Example: BONK
    if mint == "YOUR_TOKEN_ADDRESS":
        print("Please replace 'YOUR_TOKEN_ADDRESS' with an actual Solana token mint address in performance/fetch_historical_data.py")
        exit()

    df = fetch_and_save_data(
        mint=mint,
        interval='1h',
        limit=720,
        output_path='synthron/outputs/historical_data.csv',
        helius_api_key=os.getenv('HELIUS_API_KEY')
    ) 