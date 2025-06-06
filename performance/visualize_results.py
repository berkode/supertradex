import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.express as px
from scipy import stats
from datetime import datetime
import dash
from dash import dcc, html
from dash.dependencies import Input, Output
import json
from itertools import groupby

def calculate_metrics(historical_data: pd.DataFrame, results: pd.DataFrame) -> dict:
    """Calculate comprehensive performance metrics."""
    returns = historical_data['price'].pct_change().dropna()
    
    # Basic Returns
    total_return = (historical_data['price'].iloc[-1] / historical_data['price'].iloc[0] - 1) * 100
    annualized_return = ((1 + returns.mean()) ** 252 - 1) * 100
    
    # Risk Metrics
    volatility = returns.std() * np.sqrt(252) * 100
    sharpe_ratio = np.sqrt(252) * returns.mean() / returns.std()
    sortino_ratio = np.sqrt(252) * returns.mean() / returns[returns < 0].std()
    max_drawdown = ((historical_data['price'] / historical_data['price'].cummax() - 1) * 100).min()
    
    # Trade Statistics
    win_rate = (results['profit'] > 0).mean() * 100
    profit_factor = abs(results[results['profit'] > 0]['profit'].sum() / results[results['profit'] < 0]['profit'].sum())
    avg_trade_duration = (results['exit_time'] - results['entry_time']).dt.total_seconds().mean() / 3600
    
    # Advanced Metrics
    kelly_criterion = (results['profit'].mean() / results['profit'].std()) ** 2
    var_95 = np.percentile(returns, 5) * 100
    expected_shortfall = returns[returns <= np.percentile(returns, 5)].mean() * 100
    
    # Trade Analysis
    avg_win = results[results['profit'] > 0]['profit'].mean()
    avg_loss = results[results['profit'] < 0]['profit'].mean()
    largest_win = results['profit'].max()
    largest_loss = results['profit'].min()
    
    # Streak Analysis
    consecutive_wins = max(len(list(g)) for k, g in groupby(results['profit'] > 0) if k)
    consecutive_losses = max(len(list(g)) for k, g in groupby(results['profit'] < 0) if k)
    
    # Volume Analysis
    volume_trend = historical_data['volume'].pct_change().mean() * 100
    avg_volume = historical_data['volume'].mean()
    
    # Market Regime
    market_regime = "Bullish" if returns.mean() > 0 else "Bearish"
    
    metrics = {
        'Returns': {
            'Total Return (%)': round(total_return, 2),
            'Annualized Return (%)': round(annualized_return, 2),
            'Daily Return (%)': round(returns.mean() * 100, 2)
        },
        'Risk': {
            'Volatility (%)': round(volatility, 2),
            'Sharpe Ratio': round(sharpe_ratio, 2),
            'Sortino Ratio': round(sortino_ratio, 2),
            'Max Drawdown (%)': round(max_drawdown, 2),
            'VaR (95%) (%)': round(var_95, 2),
            'Expected Shortfall (%)': round(expected_shortfall, 2)
        },
        'Trading': {
            'Win Rate (%)': round(win_rate, 2),
            'Profit Factor': round(profit_factor, 2),
            'Kelly Criterion': round(kelly_criterion, 2),
            'Avg Trade Duration (hours)': round(avg_trade_duration, 2),
            'Consecutive Wins': consecutive_wins,
            'Consecutive Losses': consecutive_losses
        },
        'Trade Analysis': {
            'Average Win': round(avg_win, 2),
            'Average Loss': round(avg_loss, 2),
            'Largest Win': round(largest_win, 2),
            'Largest Loss': round(largest_loss, 2)
        },
        'Market': {
            'Volume Trend (%)': round(volume_trend, 2),
            'Average Volume': round(avg_volume, 2),
            'Market Regime': market_regime
        }
    }
    
    return metrics

def create_dashboard(historical_data: pd.DataFrame, results: pd.DataFrame, metrics: dict):
    """Create an interactive dashboard using Dash."""
    app = dash.Dash(__name__)
    
    # Create layout
    app.layout = html.Div([
        html.H1("Backtest Analysis Dashboard", style={'textAlign': 'center'}),
        
        # Metrics Summary
        html.Div([
            html.H2("Performance Metrics"),
            html.Div([
                html.Div([
                    html.H3(category),
                    html.Table([
                        html.Tbody([
                            html.Tr([
                                html.Td(metric),
                                html.Td(str(value))
                            ]) for metric, value in metrics[category].items()
                        ])
                    ], style={'width': '100%'})
                ], style={'margin': '10px', 'padding': '10px', 'border': '1px solid #ddd'})
                for category in metrics.keys()
            ], style={'display': 'flex', 'flexWrap': 'wrap'})
        ]),
        
        # Interactive Plots
        html.Div([
            html.H2("Interactive Analysis"),
            dcc.Tabs([
                dcc.Tab(label='Price & Volume', children=[
                    dcc.Graph(
                        figure=create_price_volume_plot(historical_data)
                    )
                ]),
                dcc.Tab(label='Returns Analysis', children=[
                    dcc.Graph(
                        figure=create_returns_analysis(historical_data)
                    )
                ]),
                dcc.Tab(label='Trade Analysis', children=[
                    dcc.Graph(
                        figure=create_trade_analysis(results)
                    )
                ]),
                dcc.Tab(label='Risk Analysis', children=[
                    dcc.Graph(
                        figure=create_risk_analysis(historical_data)
                    )
                ])
            ])
        ]),
        
        # Export Controls
        html.Div([
            html.H2("Export Data"),
            html.Button("Export Metrics to JSON", id="export-metrics"),
            html.Button("Export Trade History to CSV", id="export-trades"),
            dcc.Download(id="download-metrics"),
            dcc.Download(id="download-trades")
        ])
    ])
    
    # Export callbacks
    @app.callback(
        Output("download-metrics", "data"),
        Input("export-metrics", "n_clicks"),
        prevent_initial_call=True
    )
    def export_metrics(n_clicks):
        return dict(content=json.dumps(metrics, indent=2), filename="metrics.json")
    
    @app.callback(
        Output("download-trades", "data"),
        Input("export-trades", "n_clicks"),
        prevent_initial_call=True
    )
    def export_trades(n_clicks):
        return dict(content=results.to_csv(index=False), filename="trade_history.csv")
    
    return app

def create_price_volume_plot(data: pd.DataFrame) -> go.Figure:
    """Create interactive price and volume plot."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    
    fig.add_trace(
        go.Scatter(x=data['timestamp'], y=data['price'],
                  name='Price', line=dict(color='blue')),
        secondary_y=False
    )
    
    fig.add_trace(
        go.Bar(x=data['timestamp'], y=data['volume'],
               name='Volume', opacity=0.3),
        secondary_y=True
    )
    
    fig.update_layout(
        title='Price and Volume Analysis',
        xaxis_title='Time',
        yaxis_title='Price',
        yaxis2_title='Volume',
        hovermode='x unified'
    )
    
    return fig

def create_returns_analysis(data: pd.DataFrame) -> go.Figure:
    """Create interactive returns analysis plot."""
    returns = data['price'].pct_change().dropna()
    
    fig = make_subplots(rows=2, cols=1)
    
    fig.add_trace(
        go.Histogram(x=returns, nbinsx=50, name='Returns Distribution',
                    histnorm='probability'),
        row=1, col=1
    )
    
    fig.add_trace(
        go.Scatter(x=data['timestamp'][1:], y=returns.cumsum(),
                  name='Cumulative Returns', line=dict(color='green')),
        row=2, col=1
    )
    
    fig.update_layout(
        title='Returns Analysis',
        height=800
    )
    
    return fig

def create_trade_analysis(results: pd.DataFrame) -> go.Figure:
    """Create interactive trade analysis plot."""
    # Create figure with mixed subplot types
    fig = make_subplots(
        rows=2, cols=2,
        specs=[[{"type": "box"}, {"type": "pie"}],
               [{"type": "scatter"}, {"type": "scatter"}]],
        subplot_titles=('Profit Distribution', 'Win/Loss Ratio',
                       'Trade Duration vs Profit', 'Trade Timeline')
    )
    
    # Profit Distribution
    fig.add_trace(
        go.Box(y=results['profit'], name='Profit Distribution'),
        row=1, col=1
    )
    
    # Win/Loss Ratio
    win_loss = results['profit'] > 0
    fig.add_trace(
        go.Pie(labels=['Wins', 'Losses'],
               values=win_loss.value_counts().values),
        row=1, col=2
    )
    
    # Trade Duration vs Profit
    results['duration'] = (results['exit_time'] - results['entry_time']).dt.total_seconds() / 3600
    fig.add_trace(
        go.Scatter(x=results['duration'], y=results['profit'],
                  mode='markers', name='Trade Duration vs Profit'),
        row=2, col=1
    )
    
    # Trade Timeline
    fig.add_trace(
        go.Scatter(x=results['entry_time'], y=results['profit'],
                  mode='markers', name='Trade Timeline'),
        row=2, col=2
    )
    
    fig.update_layout(height=800, title='Trade Analysis')
    
    return fig

def create_risk_analysis(data: pd.DataFrame) -> go.Figure:
    """Create interactive risk analysis plot."""
    returns = data['price'].pct_change().dropna()
    
    fig = make_subplots(rows=2, cols=1)
    
    # Rolling Sharpe Ratio
    rolling_returns = returns.rolling(window=24).mean()
    rolling_std = returns.rolling(window=24).std()
    rolling_sharpe = np.sqrt(24) * (rolling_returns / rolling_std)
    
    fig.add_trace(
        go.Scatter(x=data['timestamp'][23:], y=rolling_sharpe,
                  name='Rolling Sharpe Ratio'),
        row=1, col=1
    )
    
    # Drawdown
    drawdown = (data['price'] - data['price'].cummax()) / data['price'].cummax() * 100
    fig.add_trace(
        go.Scatter(x=data['timestamp'], y=drawdown,
                  fill='tozeroy', name='Drawdown'),
        row=2, col=1
    )
    
    fig.update_layout(height=800, title='Risk Analysis')
    
    return fig

def visualize_results(historical_data_path: str, results_path: str):
    """
    Create interactive dashboard for backtesting results.
    
    Args:
        historical_data_path: Path to historical data CSV
        results_path: Path to backtest results CSV
    """
    try:
        # Load data
        historical_data = pd.read_csv(historical_data_path)
        results = pd.read_csv(results_path)
        
        # Convert timestamps
        historical_data['timestamp'] = pd.to_datetime(historical_data['timestamp'])
        results['timestamp'] = pd.to_datetime(results['timestamp'])
        results['entry_time'] = pd.to_datetime(results['entry_time'])
        results['exit_time'] = pd.to_datetime(results['exit_time'])
        
        # Calculate metrics
        metrics = calculate_metrics(historical_data, results)
        
        # Create and run dashboard
        app = create_dashboard(historical_data, results, metrics)
        app.run(debug=True)
    except FileNotFoundError as e:
        print(f"Error: Required data files not found.")
        print(f"Please ensure the following files exist:")
        print(f"1. {historical_data_path}")
        print(f"2. {results_path}")
        print("\nTo generate sample data for testing, run:")
        print("python synthron/performance/generate_sample_data.py")
    except Exception as e:
        print(f"Error: {str(e)}")
        print("\nPlease check that your data files are properly formatted.")
        print("Required columns for historical_data.csv:")
        print("- timestamp: datetime")
        print("- price: float")
        print("- volume: float")
        print("\nRequired columns for backtest_results.csv:")
        print("- timestamp: datetime")
        print("- entry_time: datetime")
        print("- exit_time: datetime")
        print("- profit: float")

if __name__ == "__main__":
    # Use default paths if none provided
    historical_data_path = 'synthron/outputs/historical_data.csv'
    results_path = 'synthron/outputs/backtest_results.csv'
    visualize_results(historical_data_path, results_path) 