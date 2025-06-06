import numpy as np
import pandas as pd
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from config.logging_config import LoggingConfig
from utils.logger import get_logger

# Remove premature logging setup call
# LoggingConfig.setup_logging()
logger = get_logger(__name__)

class DataProcessing:
    @staticmethod
    async def initialize() -> bool:
        """
        Initialize the DataProcessing class.
        Since this is a static class with utility methods only, 
        there's no actual initialization needed.
        
        Returns:
            bool: Always returns True
        """
        logger.info("Initializing DataProcessing static class")
        return True
        
    @staticmethod
    async def close():
        """
        Clean up resources.
        Since this is a static class with utility methods only,
        there's no cleanup needed.
        """
        logger.info("Closing DataProcessing static class (no action needed)")

    @staticmethod
    def validate_dataframe(data: pd.DataFrame):
        """
        Validate the input DataFrame to ensure it's not empty and has valid data.

        Args:
            data (pd.DataFrame): The input DataFrame.

        Raises:
            ValueError: If the DataFrame is empty or invalid.
        """
        if data is None or data.empty:
            logger.error("Input DataFrame is empty or None.")
            raise ValueError("The input DataFrame is empty or None.")
        logger.info(f"Validated DataFrame with {data.shape[0]} rows and {data.shape[1]} columns.")

    @staticmethod
    def handle_missing_values(data: pd.DataFrame, strategy: str = "mean", fill_value: Optional[float] = None) -> pd.DataFrame:
        """
        Handle missing values in the dataset.

        Args:
            data (pd.DataFrame): The input DataFrame.
            strategy (str): Strategy for handling missing values: 'mean', 'median', 'mode', or 'constant'.
            fill_value (float): Value to use if strategy is 'constant'.

        Returns:
            pd.DataFrame: DataFrame with missing values handled.
        """
        DataProcessing.validate_dataframe(data)
        logger.info(f"Handling missing values using strategy: {strategy}")
        try:
            # Only select numeric columns to avoid issues with dictionary values
            numeric_columns = data.select_dtypes(include=['number']).columns
            
            if strategy == "mean":
                if not numeric_columns.empty:
                    data[numeric_columns] = data[numeric_columns].fillna(data[numeric_columns].mean())
                # For non-numeric columns, fill with empty values
                for col in data.columns:
                    if col not in numeric_columns:
                        if pd.api.types.is_string_dtype(data[col]):
                            data[col] = data[col].fillna('')
                        elif pd.api.types.is_object_dtype(data[col]):
                            if data[col].isna().any():
                                # For dictionaries/objects, fill with empty dict
                                if any(isinstance(val, dict) for val in data[col].dropna()):
                                    data[col] = data[col].fillna({})
                                # For lists, fill with empty list
                                elif any(isinstance(val, list) for val in data[col].dropna()):
                                    data[col] = data[col].fillna([])
                                # For other objects, fill with None
                                else:
                                    data[col] = data[col].fillna(None)
            elif strategy == "median":
                if not numeric_columns.empty:
                    data[numeric_columns] = data[numeric_columns].fillna(data[numeric_columns].median())
                # Handle non-numeric columns as above
                for col in data.columns:
                    if col not in numeric_columns:
                        if pd.api.types.is_string_dtype(data[col]):
                            data[col] = data[col].fillna('')
                        elif pd.api.types.is_object_dtype(data[col]):
                            if data[col].isna().any():
                                if any(isinstance(val, dict) for val in data[col].dropna()):
                                    data[col] = data[col].fillna({})
                                elif any(isinstance(val, list) for val in data[col].dropna()):
                                    data[col] = data[col].fillna([])
                                else:
                                    data[col] = data[col].fillna(None)
            elif strategy == "mode":
                if not numeric_columns.empty:
                    # For each numeric column, get the mode and fill NA values
                    for col in numeric_columns:
                        if data[col].isna().any():
                            mode_val = data[col].mode().iloc[0] if not data[col].mode().empty else 0
                            data[col] = data[col].fillna(mode_val)
                # Handle non-numeric columns
                for col in data.columns:
                    if col not in numeric_columns:
                        if pd.api.types.is_string_dtype(data[col]):
                            mode_val = data[col].mode().iloc[0] if not data[col].mode().empty else ''
                            data[col] = data[col].fillna(mode_val)
                        elif pd.api.types.is_object_dtype(data[col]):
                            if data[col].isna().any():
                                if any(isinstance(val, dict) for val in data[col].dropna()):
                                    data[col] = data[col].fillna({})
                                elif any(isinstance(val, list) for val in data[col].dropna()):
                                    data[col] = data[col].fillna([])
                                else:
                                    data[col] = data[col].fillna(None)
            elif strategy == "constant":
                if fill_value is None:
                    raise ValueError("`fill_value` must be provided for 'constant' strategy.")
                # Only apply constant fill value to numeric columns
                if not numeric_columns.empty:
                    data[numeric_columns] = data[numeric_columns].fillna(fill_value)
                # For non-numeric columns, fill with appropriate empty values
                for col in data.columns:
                    if col not in numeric_columns:
                        if pd.api.types.is_string_dtype(data[col]):
                            data[col] = data[col].fillna('')
                        elif pd.api.types.is_object_dtype(data[col]):
                            if data[col].isna().any():
                                if any(isinstance(val, dict) for val in data[col].dropna()):
                                    data[col] = data[col].fillna({})
                                elif any(isinstance(val, list) for val in data[col].dropna()):
                                    data[col] = data[col].fillna([])
                                else:
                                    data[col] = data[col].fillna(None)
            else:
                raise ValueError("Invalid strategy. Choose from 'mean', 'median', 'mode', or 'constant'.")
            
            return data
        except Exception as e:
            logger.error(f"Error handling missing values: {e}")
            raise

    @staticmethod
    def remove_outliers(data: pd.DataFrame, columns: list, method: str = "zscore", threshold: float = 3.0) -> pd.DataFrame:
        """
        Remove outliers from the dataset.

        Args:
            data (pd.DataFrame): The input DataFrame.
            columns (list): List of column names to check for outliers.
            method (str): Method for detecting outliers: 'zscore' or 'iqr'.
            threshold (float): Threshold for identifying outliers.

        Returns:
            pd.DataFrame: DataFrame with outliers removed.
        """
        DataProcessing.validate_dataframe(data)
        logger.info(f"Removing outliers using method: {method}")
        try:
            for col in columns:
                if method == "zscore":
                    z_scores = (data[col] - data[col].mean()) / data[col].std()
                    data = data[np.abs(z_scores) <= threshold]
                elif method == "iqr":
                    Q1 = data[col].quantile(0.25)
                    Q3 = data[col].quantile(0.75)
                    IQR = Q3 - Q1
                    lower_bound = Q1 - (threshold * IQR)
                    upper_bound = Q3 + (threshold * IQR)
                    data = data[(data[col] >= lower_bound) & (data[col] <= upper_bound)]
                else:
                    raise ValueError("Invalid method. Choose 'zscore' or 'iqr'.")
        except Exception as e:
            logger.error(f"Error removing outliers: {e}")
            raise
        return data

    @staticmethod
    def normalize_data(data: pd.DataFrame, columns: list, method: str = "minmax") -> pd.DataFrame:
        """
        Normalize data in specified columns.

        Args:
            data (pd.DataFrame): The input DataFrame.
            columns (list): List of column names to normalize.
            method (str): Normalization method: 'minmax' or 'zscore'.

        Returns:
            pd.DataFrame: DataFrame with normalized data.
        """
        DataProcessing.validate_dataframe(data)
        logger.info(f"Normalizing data using method: {method}")
        try:
            for col in columns:
                if method == "minmax":
                    min_val = data[col].min()
                    max_val = data[col].max()
                    data[col] = (data[col] - min_val) / (max_val - min_val)
                elif method == "zscore":
                    data[col] = (data[col] - data[col].mean()) / data[col].std()
                else:
                    raise ValueError("Invalid method. Choose 'minmax' or 'zscore'.")
        except Exception as e:
            logger.error(f"Error normalizing data: {e}")
            raise
        return data

    @staticmethod
    def clean_data(data: pd.DataFrame, missing_strategy: str = "mean", 
                   outlier_columns: Optional[List[str]] = None,
                   outlier_method: str = "zscore", outlier_threshold: float = 3.0,
                   normalize_columns: Optional[List[str]] = None, 
                   normalize_method: str = "minmax") -> pd.DataFrame:
        """
        Clean the dataset by handling missing values, removing outliers, and normalizing.

        Args:
            data (pd.DataFrame): The input DataFrame.
            missing_strategy (str): Strategy for handling missing values.
            outlier_columns (list): List of columns to check for outliers.
            outlier_method (str): Method for detecting outliers.
            outlier_threshold (float): Threshold for identifying outliers.
            normalize_columns (list): List of columns to normalize.
            normalize_method (str): Method for normalization.

        Returns:
            pd.DataFrame: Cleaned DataFrame.
        """
        logger.info("Cleaning data...")
        try:
            # Handle missing values
            data = DataProcessing.handle_missing_values(data, strategy=missing_strategy)

            # Remove outliers
            if outlier_columns:
                data = DataProcessing.remove_outliers(data, columns=outlier_columns, method=outlier_method,
                                                      threshold=outlier_threshold)

            # Normalize data
            if normalize_columns:
                data = DataProcessing.normalize_data(data, columns=normalize_columns, method=normalize_method)

            logger.info("Data cleaning complete.")
        except Exception as e:
            logger.error(f"Error cleaning data: {e}")
            raise
        return data

class TokenDataProcessor:
    """Class for processing token-specific data."""
    
    @staticmethod
    def process_rugcheck_data(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process raw token data from Rugcheck API.
        
        Args:
            data: Raw token data from API
            
        Returns:
            Processed token data dictionary
        """
        try:
            score = float(data.get('score_normalised', 100.0))
            risk_factors = data.get('risk_factors', {})
            contract_analysis = data.get('contract_analysis', {})
            liquidity_analysis = data.get('liquidity_analysis', {})
            holder_analysis = data.get('holder_analysis', {})
            
            return {
                'score': score,
                'risk_factors': risk_factors,
                'contract_analysis': contract_analysis,
                'liquidity_analysis': liquidity_analysis,
                'holder_analysis': holder_analysis
            }
            
        except Exception as e:
            logger.error(f"Error processing Rugcheck data: {e}", exc_info=True)
            return {
                'score': 100.0,
                'risk_factors': {},
                'contract_analysis': {},
                'liquidity_analysis': {},
                'holder_analysis': {}
            }
            
    @staticmethod
    def process_solsniffer_data(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process raw token data from Solsniffer API.
        
        Args:
            data: Raw token data from API
            
        Returns:
            Processed token data dictionary
        """
        try:
            contract_data = data.get('tokenData', {})
            
            # Get score and audit risk data
            score = int(contract_data.get("score", 0))
            audit_risk = contract_data.get("auditRisk", {})
            mint_disabled = bool(audit_risk.get("mintDisabled", False))
            freeze_disabled = bool(audit_risk.get("freezeDisabled", False))
            lp_burned = bool(audit_risk.get("lpBurned", False))
            top10_holders = bool(audit_risk.get("top10Holders", False))
            
            # Get indicator data counts
            indicator_data = contract_data.get("indicatorData", {})
            high_count = indicator_data.get("high", {}).get("count", 0)
            moderate_count = indicator_data.get("moderate", {}).get("count", 0)
            low_count = indicator_data.get("low", {}).get("count", 0)
            specific_count = indicator_data.get("specific", {}).get("count", 0)
            
            # Calculate holder statistics
            owners_list = contract_data.get("ownersList", [])
            total_holders = len(set(owner["address"] for owner in owners_list))
            total_percentage = sum(float(owner["percentage"]) for owner in owners_list)
            top_holder_percentage = float(owners_list[0]["percentage"]) if owners_list else 0.0
            top10_percentage = sum(float(owner["percentage"]) for owner in owners_list[:10]) if len(owners_list) >= 10 else 0.0
            
            return {
                'score': score,
                'mint_disabled': mint_disabled,
                'freeze_disabled': freeze_disabled,
                'lp_burned': lp_burned,
                'top10_holders': top10_holders,
                'top10_holders_percentage': round(top10_percentage, 2),
                'top_holder_percentage': round(top_holder_percentage, 2),
                'total_holders': total_holders,
                'total_holders_percentage': round(total_percentage, 2),
                'high_risk_count': high_count,
                'moderate_risk_count': moderate_count,
                'low_risk_count': low_count,
                'specific_risk_count': specific_count
            }
            
        except Exception as e:
            logger.error(f"Error processing Solsniffer data: {e}", exc_info=True)
            return {
                'score': 0,
                'mint_disabled': False,
                'freeze_disabled': False,
                'lp_burned': False,
                'top10_holders': False,
                'top10_holders_percentage': 0.0,
                'top_holder_percentage': 0.0,
                'total_holders': 0,
                'total_holders_percentage': 0.0,
                'high_risk_count': 0,
                'moderate_risk_count': 0,
                'low_risk_count': 0,
                'specific_risk_count': 0
            }
            
    @staticmethod
    def process_solanatracker_data(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process raw SolanaTracker data into a standardized format.
        
        Args:
            data: Raw data from SolanaTracker API
            
        Returns:
            Processed token data dictionary
        """
        try:
            # Handle case when data is empty or None
            if not data:
                return TokenDataProcessor._get_default_solanatracker_data()
                
            # Extract data with safety checks
            token_data = data.get('token', {})
            pools_data = data.get('pools', [{}])[0] if data.get('pools') else {}
            txns_data = pools_data.get('txns', {})
            events_data = data.get('events', {})
            risk_data = data.get('risk', {})
            
            # Extract token information with default values
            mint = token_data.get('mint', '')
            symbol = token_data.get('symbol', '')
            twitter = token_data.get('twitter', '')
            creator_site = token_data.get('website', '')
            has_file_metadata = token_data.get('hasFileMetaData', False)
            
            # Extract price and market data with default values
            price = float(pools_data.get('price', {}).get('usd', 0) or 0)
            market_cap_usd = float(pools_data.get('marketCap', {}).get('usd', 0) or 0)
            liquidity_usd = float(pools_data.get('liquidity', {}).get('usd', 0) or 0)
            txns_volume = float(txns_data.get('volume', 0) or 0)
            
            # Handle missing buysCount and sellsCount fields
            buysCount = int(data.get('buysCount', txns_data.get('buys', 0)) or 0)
            sellsCount = int(data.get('sellsCount', txns_data.get('sells', 0)) or 0)
            
            txns_buys = int(txns_data.get('buys', 0) or 0)
            txns_sells = int(txns_data.get('sells', 0) or 0)
            lpburn = float(pools_data.get('lpBurn', 0) or 0)
            
            # Extract price changes
            price_change_1m = round(float(events_data.get('1m', {}).get('priceChangePercentage', 0) or 0), 2)
            price_change_5m = round(float(events_data.get('5m', {}).get('priceChangePercentage', 0) or 0), 2)
            price_change_1h = round(float(events_data.get('1h', {}).get('priceChangePercentage', 0) or 0), 2)
            price_change_24h = round(float(events_data.get('24h', {}).get('priceChangePercentage', 0) or 0), 2)
            
            # Extract risk data
            rugged = bool(risk_data.get('rugged', False))
            risk_score = float(risk_data.get('score', 0) or 0)
            
            # Calculate total risk score with safety check
            risks = risk_data.get('risks', [])
            total_risk_score = float(sum(risk.get('score', 0) for risk in risks) if risks else 0)
            
            jupiter_verified = bool(risk_data.get('jupiterVerified', False))
            
            return {
                'mint': mint,
                'symbol': symbol,
                'twitter': twitter,
                'creator_site': creator_site,
                'has_file_metadata': has_file_metadata,
                'price': price,
                'market_cap_usd': market_cap_usd,
                'liquidity_usd': liquidity_usd,
                'txns_volume': txns_volume,
                'buysCount': buysCount,
                'txns_buys': txns_buys,
                'sellsCount': sellsCount,
                'txns_sells': txns_sells,
                'lpburn': lpburn,
                'price_change_1m': price_change_1m,
                'price_change_5m': price_change_5m,
                'price_change_1h': price_change_1h,
                'price_change_24h': price_change_24h,
                'rugged': rugged,
                'risk_score': risk_score,
                'total_risk_score': total_risk_score,
                'jupiter_verified': jupiter_verified
            }
            
        except Exception as e:
            logger.error(f"Error processing SolanaTracker data: {e}", exc_info=True)
            return TokenDataProcessor._get_default_solanatracker_data()
    
    @staticmethod
    def _get_default_solanatracker_data() -> Dict[str, Any]:
        """Return default data structure for SolanaTracker when processing fails."""
        return {
            'mint': '',
            'symbol': '',
            'twitter': '',
            'creator_site': '',
            'has_file_metadata': False,
            'price': 0.0,
            'market_cap_usd': 0.0,
            'liquidity_usd': 0.0,
            'txns_volume': 0.0,
            'buysCount': 0,
            'txns_buys': 0,
            'sellsCount': 0,
            'txns_sells': 0,
            'lpburn': 0.0,
            'price_change_1m': 0.0,
            'price_change_5m': 0.0,
            'price_change_1h': 0.0,
            'price_change_24h': 0.0,
            'rugged': False,
            'risk_score': 0.0,
            'total_risk_score': 0.0,
            'jupiter_verified': False
        }

    @staticmethod
    def merge_token_data(rugcheck_data: Dict[str, Any], solsniffer_data: Dict[str, Any], 
                        solanatracker_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merge data from multiple sources into a single token data dictionary.
        
        Args:
            rugcheck_data: Processed Rugcheck data
            solsniffer_data: Processed Solsniffer data
            solanatracker_data: Processed SolanaTracker data
            
        Returns:
            Merged token data dictionary
        """
        try:
            merged_data: Dict[str, Any] = {
                'rugcheck': rugcheck_data,
                'solsniffer': solsniffer_data,
                'solanatracker': solanatracker_data
            }
            
            # Add combined metrics
            merged_data['combined_score'] = (
                float(rugcheck_data.get('score', 100.0)) +
                float(solsniffer_data.get('score', 0.0)) +
                float(solanatracker_data.get('risk_score', 0.0))
            ) / 3.0
            
            merged_data['is_valid'] = (
                float(rugcheck_data.get('score', 100.0)) < 100.0 and
                float(solsniffer_data.get('score', 0.0)) >= 0.0 and
                bool(solsniffer_data.get('mint_disabled', False)) and
                bool(solsniffer_data.get('freeze_disabled', False)) and
                float(solanatracker_data.get('lpburn', 0.0)) >= 90.0 and
                not bool(solanatracker_data.get('rugged', False)) and
                float(solanatracker_data.get('risk_score', 0.0)) <= 5.0
            )
            
            return merged_data
            
        except Exception as e:
            logger.error(f"Error merging token data: {e}", exc_info=True)
            return {
                'rugcheck': rugcheck_data,
                'solsniffer': solsniffer_data,
                'solanatracker': solanatracker_data,
                'combined_score': 0.0,
                'is_valid': False
            }