import numpy as np
import pandas as pd
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("data_processing.log"),
        logging.StreamHandler()
    ]
)


class DataProcessing:
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
            logging.error("Input DataFrame is empty or None.")
            raise ValueError("The input DataFrame is empty or None.")
        logging.info(f"Validated DataFrame with {data.shape[0]} rows and {data.shape[1]} columns.")

    @staticmethod
    def handle_missing_values(data: pd.DataFrame, strategy: str = "mean", fill_value: float = None) -> pd.DataFrame:
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
        logging.info(f"Handling missing values using strategy: {strategy}")
        try:
            if strategy == "mean":
                return data.fillna(data.mean())
            elif strategy == "median":
                return data.fillna(data.median())
            elif strategy == "mode":
                return data.fillna(data.mode().iloc[0])
            elif strategy == "constant":
                if fill_value is None:
                    raise ValueError("`fill_value` must be provided for 'constant' strategy.")
                return data.fillna(fill_value)
            else:
                raise ValueError("Invalid strategy. Choose from 'mean', 'median', 'mode', or 'constant'.")
        except Exception as e:
            logging.error(f"Error handling missing values: {e}")
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
        logging.info(f"Removing outliers using method: {method}")
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
            logging.error(f"Error removing outliers: {e}")
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
        logging.info(f"Normalizing data using method: {method}")
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
            logging.error(f"Error normalizing data: {e}")
            raise
        return data

    @staticmethod
    def clean_data(data: pd.DataFrame, missing_strategy: str = "mean", outlier_columns: list = None,
                   outlier_method: str = "zscore", outlier_threshold: float = 3.0,
                   normalize_columns: list = None, normalize_method: str = "minmax") -> pd.DataFrame:
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
        logging.info("Cleaning data...")
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

            logging.info("Data cleaning complete.")
        except Exception as e:
            logging.error(f"Error cleaning data: {e}")
            raise
        return data


