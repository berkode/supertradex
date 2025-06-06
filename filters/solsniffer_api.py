import os
import time
import random
import logging
import aiohttp
import asyncio
import requests
import pandas as pd
from typing import Optional, Dict, Any, List, Union
from datetime import datetime, timezone
from config.settings import Settings
from utils.logger import get_logger
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import json

# Get logger for this module
logger = get_logger(__name__)

class SolsnifferAPI:
    """API client for Solsniffer."""
    
    def __init__(self, settings: Settings):
        """Initialize the Solsniffer API client.
        
        Args:
            settings: Application settings
        """
        self.settings = settings
        self.api_url = settings.SOLSNIFFER_API_URL
        self.api_key = settings.SOLSNIFFER_API_KEY
        self.timeout = float(settings.HTTP_TIMEOUT)  # Use timeout from settings
        self.logger = get_logger(__name__)
        self.semaphore = asyncio.Semaphore(settings.API_CONCURRENCY_LIMIT) # Use concurrency from settings
        self.api_available = False
        self.max_retries = 3
        self.retry_delay = 1  # Base delay in seconds
        
        # Get min solsniffer score from settings
        self.min_score = settings.MIN_SOLSNIFFER_SCORE
        self.logger.info(f"SolsnifferAPI initialized with min score: {self.min_score}")
        self.logger.info(f"SolsnifferAPI concurrency limit set to: {self.semaphore._value}")
        
        self.batch_size = settings.SOLSNIFFER_BATCH_SIZE
        self.base_delay = settings.ERROR_RETRY_INTERVAL
        self._session = None
        self._logged_first_passed_token = False # Add flag
        
    async def initialize(self) -> bool:
        """Initialize the Solsniffer API client.
        
        Returns:
            bool: True if initialization was successful, False otherwise
        """
        try:
            if not self.api_key:
                self.logger.error("Solsniffer API key is missing. Set SOLSNIFFER_API_KEY environment variable.")
                return False
            
            # Test connection to API
            if not await self._test_connection():
                self.logger.error("Failed Solsniffer API connection test")
                return False
                
            self.logger.info("Solsniffer API client initialized successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Error initializing Solsniffer API: {str(e)}")
            self.api_available = False
            return False
            
    async def _test_connection(self) -> bool:
        """Test connection to Solsniffer API by requesting a known token."""
        logger.debug("Entering _test_connection for SolsnifferAPI...")
        known_token_mint = "So11111111111111111111111111111111111111112" # Wrapped SOL
        url = f"{self.api_url}/tokens" # Use the POST /tokens endpoint
        payload = {"addresses": [known_token_mint]}
        
        try:
            logger.debug(f"Attempting POST to {url} with payload: {payload}")
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=self._get_headers(), json=payload) as response:
                    logger.debug(f"Received status code {response.status} from {url}")
                    if response.status == 200:
                        # Even if the response for SOL isn't useful, 200 means API is reachable and key is valid
                        logger.debug("POST /tokens OK (Status 200). Setting api_available=True.")
                        self.api_available = True
                        logger.debug(f"_test_connection returning True. self.api_available={self.api_available}")
                        return True
                    elif response.status == 401:
                        logger.error(f"Solsniffer API test failed: Invalid API key (401 Unauthorized)")
                        logger.debug("Setting api_available=False due to 401.")
                        self.api_available = False
                        logger.debug(f"_test_connection returning False. self.api_available={self.api_available}")
                        return False
                    elif response.status == 402:
                         logger.warning(f"Solsniffer API test failed: Payment Required (402). Check credits/subscription.")
                         logger.debug("Setting api_available=False due to 402.")
                         self.api_available = False # Treat as unavailable if credits are out
                         logger.debug(f"_test_connection returning False. self.api_available={self.api_available}")
                         return False # Or True depending on desired behavior?
                    elif response.status == 403:
                         logger.error(f"Solsniffer API test failed: Forbidden (403). Check API key permissions.")
                         logger.debug("Setting api_available=False due to 403.")
                         self.api_available = False
                         logger.debug(f"_test_connection returning False. self.api_available={self.api_available}")
                         return False
                    elif response.status == 429:
                         logger.warning(f"Solsniffer API test failed: Rate Limited (429).")
                         logger.debug("Setting api_available=False due to 429.")
                         # Can technically connect, but rate limited. Treat as unavailable for now.
                         self.api_available = False 
                         logger.debug(f"_test_connection returning False. self.api_available={self.api_available}")
                         return False
                    else:
                        error_text = await response.text()
                        logger.error(f"Solsniffer API test failed with status {response.status}. Response: {error_text[:100]}")
                        logger.debug(f"Setting api_available=False due to unexpected status {response.status}.")
                        self.api_available = False
                        logger.debug(f"_test_connection returning False. self.api_available={self.api_available}")
                        return False
                        
        except aiohttp.ClientConnectorError as e:
            logger.error(f"Error testing Solsniffer API connection (Connection Error): {e}")
            logger.debug("Setting api_available=False due to ClientConnectorError.")
            self.api_available = False
            logger.debug(f"_test_connection returning False. self.api_available={self.api_available}")
            return False
        except Exception as e:
            logger.error(f"Error testing Solsniffer API connection (Unexpected Error): {e}", exc_info=True) # Add exc_info
            logger.debug(f"Setting api_available=False due to unexpected error: {type(e).__name__}.")
            self.api_available = False
            logger.debug(f"_test_connection returning False. self.api_available={self.api_available}")
            return False
            
    def _get_headers(self) -> Dict[str, str]:
        """Get headers for API requests."""
        headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        # Log headers for debugging (masking API key)
        masked_key = self.api_key[:5] + "..." if self.api_key else "None"
        self.logger.debug(f"Request headers: {headers}")
        self.logger.debug(f"API Key (first 5 chars): {masked_key}")
        return headers

    def _get_http_session(self) -> requests.Session:
        """Get or create an HTTP session with retry configuration.
        
        Returns:
            requests.Session: Configured session with retry logic
        """
        if not hasattr(self, '_session') or self._session is None:
            session = requests.Session()
            
            # Configure retry strategy
            retry_strategy = Retry(
                total=self.max_retries,
                backoff_factor=self.retry_delay,
                status_forcelist=[429, 500, 502, 503, 504],
            )
            
            # Mount the adapter with retry strategy
            adapter = HTTPAdapter(max_retries=retry_strategy)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            
            # Set default timeout
            session.timeout = self.timeout
            
            # Set default headers
            session.headers.update(self._get_headers())
            
            self._session = session
            
        return self._session

    async def close(self):
        """
        Close the HTTP session and clean up resources.
        """
        if self._session:
            await self._session.close()
            self._session = None
            logger.info("Closed Solsniffer API session")
            
    def _get_minimal_data(self, failing: bool = False, error_message: str = "API unavailable or error") -> Dict[str, Any]:
        """
        Get minimal token data with default values.
        Used when token data processing fails or API is unavailable.
        
        Args:
            failing: If True, return data that will fail validation
            error_message: Specific error message to include
        
        Returns:
            Dictionary with default token data values
        """
        # Return structure should match the expected output of analyze_token / get_token_score
        # Keys updated: score -> solsniffer_score, add solsniffer_passed
        return {
            'solsniffer_score': 0 if failing else 101, # Fail with 0, indicate API error with 101
            'solsniffer_passed': False, # Always False when this is called
            'risk_count': 100 if failing else 0, # Example value for risk count in error cases
            'details': {
                'error': error_message
            }
            # Add other fields if the calling functions expect them in error cases
            # e.g., 'mint_disabled': None, 'freeze_disabled': None, etc.
        }

    def process_token_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process raw token data from Solsniffer API response.
        Extracts score and risk details.
        Renames 'score' to 'solsniffer_score' and adds 'solsniffer_passed'.
        
        Args:
            data: Raw token data from API
            
        Returns:
            Processed token data dictionary
        """
        try:
            # --- Data Extraction --- 
            raw_score = data.get('score', 0) # Default to 0 if missing
            risk_details = data.get('details', {})
            risk_count = data.get('risk', 0) # 'risk' key seems to hold the count
            
            # --- Data Transformation --- 
            processed_data = {
                'solsniffer_score': raw_score, # Rename score
                'solsniffer_passed': True, # Assume True if successfully processed
                'risk_count': risk_count,
                'details': risk_details 
                # Add any other fields from 'data' that are needed downstream
            }
            
            # --- Validation (Optional within processing) --- 
            # You might perform basic validation here if needed
            if not isinstance(raw_score, (int, float)):
                 self.logger.warning(f"Solsniffer score is not a number: {raw_score}. Defaulting to 0.")
                 processed_data['solsniffer_score'] = 0
                 processed_data['solsniffer_passed'] = False # Fail if score is invalid?
            
            self.logger.debug(f"Processed Solsniffer data: Score={processed_data['solsniffer_score']}, Passed={processed_data['solsniffer_passed']}, Risks={risk_count}")
            return processed_data
            
        except Exception as e:
            self.logger.error(f"Error processing Solsniffer token data: {e}", exc_info=True)
            # Return minimal failing data on processing error
            # Use the updated error structure from _get_minimal_data
            return self._get_minimal_data(failing=True, error_message=f"Data processing error: {e}")

    async def get_token_score(self, token_mint: str) -> Dict[str, Any]:
        """Get Solsniffer score and risk details for a single token.
        Handles API errors and returns a standardized dictionary.
        Includes 'solsniffer_score' and 'solsniffer_passed' keys.
        """
        # Use the updated error structure
        default_error_result = self._get_minimal_data(failing=False, error_message="API unavailable")
        
        if not self.api_available:
            self.logger.warning(f"Solsniffer API unavailable - returning default error data for {token_mint}")
            return default_error_result

        if not token_mint:
             logger.warning("get_token_score called with empty mint address.")
             # Use failing=True for invalid input
             return self._get_minimal_data(failing=True, error_message="Missing mint address")
             
        url = f"{self.api_url}/tokens"
        payload = {"addresses": [token_mint]}
        attempt = 0
        
        while attempt < self.max_retries:
            attempt += 1
            async with self.semaphore: # Acquire semaphore before making the call
                try:
                     self.logger.debug(f"Fetching Solsniffer data for {token_mint} (Attempt {attempt}/{self.max_retries}). URL: {url}")
                     async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
                         async with session.post(url, headers=self._get_headers(), json=payload) as response:
                             self.logger.debug(f"Solsniffer API response status for {token_mint}: {response.status}")
                             
                             if response.status == 200:
                                 try:
                                     data_list = await response.json()
                                     if isinstance(data_list, list) and len(data_list) > 0:
                                          raw_data = data_list[0]
                                          # Check if the API itself reported an error for this token
                                          if isinstance(raw_data.get('details'), dict) and raw_data['details'].get('error'):
                                               error_msg = raw_data['details']['error']
                                               self.logger.warning(f"Solsniffer API reported error for {token_mint}: {error_msg}")
                                               # Return error state (score 101, passed False)
                                               return self._get_minimal_data(failing=False, error_message=f"API Error: {error_msg}") 
                                          else:
                                               # Process valid data
                                               processed_data = self.process_token_data(raw_data)
                                               # Check if processing itself failed (should return passed=False)
                                               if not processed_data.get('solsniffer_passed', False):
                                                    return processed_data # Return the error structure from process_token_data
                                               else:
                                                    self.logger.debug(f"Successfully fetched and processed Solsniffer data for {token_mint}")
                                                    return processed_data
                                     else:
                                          self.logger.warning(f"Solsniffer API returned unexpected data format for {token_mint}: {str(data_list)[:100]}")
                                          # Return error state
                                          return self._get_minimal_data(failing=False, error_message="Unexpected API response format") 
                                 except Exception as json_err:
                                     self.logger.error(f"Error decoding Solsniffer JSON response for {token_mint}: {json_err}", exc_info=True)
                                     # Return error state
                                     return self._get_minimal_data(failing=False, error_message=f"JSON decode error: {json_err}") 
                                     
                             elif response.status == 401:
                                 self.logger.error(f"Solsniffer Unauthorized (401) for {token_mint}. Check API key.")
                                 self.api_available = False
                                 # Return error state
                                 return self._get_minimal_data(failing=False, error_message="Unauthorized (Invalid API Key)") 
                             elif response.status == 402:
                                  self.logger.warning(f"Solsniffer Payment Required (402) for {token_mint}. Check credits.")
                                  # Return error state
                                  return self._get_minimal_data(failing=False, error_message="Payment Required (Check Credits)") 
                             elif response.status == 403:
                                  self.logger.error(f"Solsniffer Forbidden (403) for {token_mint}. Check API key permissions.")
                                  self.api_available = False
                                  # Return error state
                                  return self._get_minimal_data(failing=False, error_message="Forbidden (Check Permissions)") 
                             elif response.status == 429:
                                 self.logger.warning(f"Solsniffer Rate Limited (429) for {token_mint}. Retrying (Attempt {attempt}/{self.max_retries})...")
                                 # Handled by retry loop
                             elif response.status == 404:
                                  self.logger.warning(f"Solsniffer token {token_mint} not found (404). Returning default error.")
                                  # Return error state
                                  return self._get_minimal_data(failing=False, error_message="Token not found by API (404)") 
                             else:
                                 error_text = await response.text()
                                 self.logger.error(f"Solsniffer API error {response.status} for {token_mint}. Response: {error_text[:100]}. Retrying (Attempt {attempt}/{self.max_retries})...")
                                 # Handled by retry loop
                                 
                except aiohttp.ClientConnectorError as e:
                     self.logger.error(f"Solsniffer connection error for {token_mint} (Attempt {attempt}/{self.max_retries}): {e}")
                     # Handled by retry loop, maybe mark API unavailable if persistent?
                except asyncio.TimeoutError:
                     self.logger.warning(f"Solsniffer request timed out for {token_mint} (Attempt {attempt}/{self.max_retries}). Retrying...")
                     # Handled by retry loop
                except Exception as e:
                     self.logger.error(f"Unexpected error fetching Solsniffer data for {token_mint} (Attempt {attempt}/{self.max_retries}): {e}", exc_info=True)
                     # Handled by retry loop
                     
            # If retrying, wait before next attempt
            if attempt < self.max_retries:
                 await asyncio.sleep(self.retry_delay * (2 ** (attempt - 1))) # Exponential backoff
                 
        # If all retries fail
        self.logger.error(f"Solsniffer API call failed for {token_mint} after {self.max_retries} attempts.")
        # Return error state (score 101, passed False)
        return self._get_minimal_data(failing=False, error_message=f"API call failed after {self.max_retries} retries") 

    # Ensure analyze_token calls get_token_score and returns its result
    async def analyze_token(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyzes a token using Solsniffer API. 
        Expected to be called by FilterManager.
        
        Args:
            token_data: Dictionary containing token info, must include 'mint'.
            
        Returns:
            Dictionary with Solsniffer analysis results using new keys:
            { 'solsniffer_score': int, 'solsniffer_passed': bool, 'risk_count': int, 'details': {...} }
        """
        mint = token_data.get('mint')
        if not mint:
            logger.warning("Solsniffer analyze_token called without mint in token_data.")
            return self._get_minimal_data(failing=True, error_message="Missing mint address in input data")
            
        # Call the method that fetches and processes the data
        analysis_result = await self.get_token_score(mint)
        return analysis_result
