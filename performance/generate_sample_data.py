import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os

def generate_sample_data():
    """Generate sample data for testing the visualization dashboard."""
    # Create outputs directory if it doesn't exist
    os.makedirs('synthron/outputs', exist_ok=True)
    
    # Generate historical data
    start_date = datetime.now() - timedelta(days=30)
    dates = pd.date_range(start=start_date, periods=720, freq='h')  # 30 days of hourly data
    
    # Generate price data with some randomness and trend
    np.random.seed(42)
    base_price = 100
    price_returns = np.random.normal(0.0001, 0.01, len(dates))
    price = base_price * (1 + price_returns).cumprod()
    
    # Generate volume data
    volume = np.random.lognormal(mean=8, sigma=0.5, size=len(dates))
    
    # Create historical data DataFrame
    historical_data = pd.DataFrame({
        'timestamp': dates,
        'price': price,
        'volume': volume
    })
    
    # Generate backtest results
    # Simulate some trades
    num_trades = 50
    trade_indices = np.random.choice(range(24, len(dates)-24), num_trades, replace=False)  # Avoid edges
    trade_durations = np.random.randint(1, 24, num_trades)  # 1-24 hours
    
    results = []
    for i in range(num_trades):
        entry_time = dates[trade_indices[i]]
        exit_time = entry_time + pd.Timedelta(hours=int(trade_durations[i]))
        
        # Get actual prices from historical data
        entry_price = historical_data[historical_data['timestamp'] == entry_time]['price'].values[0]
        exit_price = historical_data[historical_data['timestamp'] == exit_time]['price'].values[0]
        
        # Calculate profit
        profit = exit_price - entry_price
        
        results.append({
            'timestamp': entry_time,
            'entry_time': entry_time,
            'exit_time': exit_time,
            'profit': profit
        })
    
    # Create results DataFrame
    results_df = pd.DataFrame(results)
    
    # Save data
    historical_data.to_csv('synthron/outputs/historical_data.csv', index=False)
    results_df.to_csv('synthron/outputs/backtest_results.csv', index=False)
    
    print("Sample data generated successfully!")
    print(f"Historical data saved to: synthron/outputs/historical_data.csv")
    print(f"Backtest results saved to: synthron/outputs/backtest_results.csv")
    print("\nYou can now run the visualization with:")
    print("python synthron/performance/visualize_results.py")

if __name__ == "__main__":
    generate_sample_data() 