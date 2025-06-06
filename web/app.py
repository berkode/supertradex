from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy
import os
from dotenv import load_dotenv
from typing import Dict, List, Optional
import threading
import time
from datetime import datetime
import pandas as pd
from performance.run_strategy import MemeTokenStrategy
from performance.fetch_historical_data import SolanaDataFetcher
from performance.visualize_results import create_dashboard
from performance.metrics import calculate_metrics
from data.token_database import TokenDatabase
from data.models import db, User, Token, Strategy, Trade, Alert
from views import views
import logging
from config.settings import Settings, initialize_settings

# Initialize settings
initialize_settings()

# Get settings instance
settings = Settings()

# Import the encrypted env loader
try:
    from utils.env_loader import load_encrypted_env
    # Try to load encrypted environment variables first
    encrypted_env_path = os.environ.get('ENCRYPTED_ENV_PATH', 'config/.env')
    if os.path.exists(encrypted_env_path):
        load_encrypted_env(encrypted_env_path)
    else:
        # Fall back to regular .env if encrypted file doesn't exist
        load_dotenv()
except ImportError:
    # Fall back to regular .env if module not found
    load_dotenv()

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = settings.SECRET_KEY or 'fallback_secret_key'
    db_path = settings.DATABASE_URL
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)

    from .views import views
    from .routes import routes

    app.register_blueprint(views, url_prefix='/')
    app.register_blueprint(routes, url_prefix='/app')

    # Global state
    active_strategies: Dict[str, MemeTokenStrategy] = {}
    update_intervals = {
        '1s': 1,
        '5s': 5,
        '15s': 15,
        '1m': 60,
        '5m': 300,
        '15m': 900,
        '1h': 3600,
        '6h': 21600,
        '24h': 86400
    }

    @app.route('/')
    def index():
        """Render the main dashboard."""
        return render_template('index.html')

    @app.route('/backtest')
    def backtest():
        """Render the backtest analysis dashboard."""
        return render_template('backtest.html')

    @app.route('/api/tokens')
    def get_tokens():
        """Get list of available tokens for backtesting."""
        try:
            db = TokenDatabase()
            tokens = db.get_all_tokens()
            return jsonify({'status': 'success', 'tokens': tokens})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)})

    @app.route('/api/strategy_params/<strategy>')
    def get_strategy_params(strategy):
        """Get parameters for a specific strategy."""
        try:
            params = {
                'ma_crossover': [
                    {'name': 'short_window', 'label': 'Short MA Period', 'type': 'number', 'default': 10},
                    {'name': 'long_window', 'label': 'Long MA Period', 'type': 'number', 'default': 50}
                ],
                'rsi': [
                    {'name': 'rsi_period', 'label': 'RSI Period', 'type': 'number', 'default': 14},
                    {'name': 'overbought', 'label': 'Overbought Level', 'type': 'number', 'default': 70},
                    {'name': 'oversold', 'label': 'Oversold Level', 'type': 'number', 'default': 30}
                ],
                'macd': [
                    {'name': 'fast_period', 'label': 'Fast EMA Period', 'type': 'number', 'default': 12},
                    {'name': 'slow_period', 'label': 'Slow EMA Period', 'type': 'number', 'default': 26},
                    {'name': 'signal_period', 'label': 'Signal Period', 'type': 'number', 'default': 9}
                ]
            }
            return jsonify({'status': 'success', 'params': params.get(strategy, [])})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)})

    @app.route('/scan_tokens', methods=['POST'])
    def scan_tokens():
        """Scan tokens and save to database."""
        try:
            # TODO: Implement token scanning logic
            return jsonify({'status': 'success', 'message': 'Token scanning started'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)})

    @app.route('/start_trading', methods=['POST'])
    def start_trading():
        """Start live trading."""
        try:
            data = request.json
            token_address = data.get('token_address')
            interval = data.get('interval', '1h')
            
            if not token_address:
                return jsonify({'status': 'error', 'message': 'Token address required'})
                
            strategy = MemeTokenStrategy(token_address)
            
            def handle_price_update(data):
                socketio.emit('price_update', {
                    'token': token_address,
                    'data': data,
                    'timestamp': datetime.now().isoformat()
                })
                
            strategy.start_realtime_monitoring(handle_price_update)
            active_strategies[token_address] = strategy
            
            return jsonify({'status': 'success', 'message': 'Trading started'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)})

    @app.route('/start_paper_trading', methods=['POST'])
    def start_paper_trading():
        """Start paper trading on testnet."""
        try:
            data = request.json
            token_address = data.get('token_address')
            interval = data.get('interval', '1h')
            
            if not token_address:
                return jsonify({'status': 'error', 'message': 'Token address required'})
                
            # TODO: Implement paper trading logic using testnet
            return jsonify({'status': 'success', 'message': 'Paper trading started'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)})

    @app.route('/start_backtesting', methods=['POST'])
    def start_backtesting():
        """Start backtesting on historical data."""
        try:
            data = request.json
            token_address = data.get('token_address')
            strategy = data.get('strategy')
            timeframe = data.get('timeframe', '1h')
            start_date = data.get('start_date')
            end_date = data.get('end_date')
            params = data.get('params', {})
            
            if not all([token_address, strategy, start_date, end_date]):
                return jsonify({'status': 'error', 'message': 'Missing required parameters'})

            # Start backtest in a separate thread
            thread = threading.Thread(
                target=run_backtest,
                args=(token_address, strategy, timeframe, start_date, end_date, params)
            )
            thread.daemon = True
            thread.start()
            
            return jsonify({'status': 'success', 'message': 'Backtest started'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)})

    def run_backtest(token_address: str, strategy: str, timeframe: str, 
                    start_date: str, end_date: str, params: Dict):
        """Run backtest and emit results via WebSocket."""
        try:
            # Fetch historical data
            data_fetcher = SolanaDataFetcher()
            historical_data = data_fetcher.fetch_data(
                token_address=token_address,
                interval=timeframe,
                start_date=start_date,
                end_date=end_date
            )
            
            # Initialize strategy
            strategy_instance = MemeTokenStrategy(token_address)
            strategy_instance.set_parameters(params)
            
            # Run backtest
            results = strategy_instance.backtest(historical_data)
            
            # Calculate metrics
            metrics = calculate_metrics(results)
            
            # Create visualizations
            charts = create_dashboard(historical_data, results)
            
            # Emit results via WebSocket
            socketio.emit('backtest_update', {
                'metrics': metrics,
                'charts': charts,
                'trades': results['trades'].to_dict('records')
            })
            
        except Exception as e:
            socketio.emit('backtest_error', {'message': str(e)})

    @app.route('/stop_trading', methods=['POST'])
    def stop_trading():
        """Stop trading for a specific token."""
        try:
            data = request.json
            token_address = data.get('token_address')
            
            if token_address in active_strategies:
                active_strategies[token_address].stop_realtime_monitoring()
                del active_strategies[token_address]
                
            return jsonify({'status': 'success', 'message': 'Trading stopped'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)})

    @app.route('/update_interval', methods=['POST'])
    def update_interval():
        """Update the data refresh interval."""
        try:
            data = request.json
            interval = data.get('interval')
            
            if interval not in update_intervals:
                return jsonify({'status': 'error', 'message': 'Invalid interval'})
                
            # TODO: Implement interval update logic
            return jsonify({'status': 'success', 'message': f'Interval updated to {interval}'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)})

    return app

def main():
    app = create_app()
    # Configuration for running the app, e.g., debug mode
    debug_mode = True # Set based on arguments or environment variables if needed
    app.run(debug=debug_mode, host='0.0.0.0')

if __name__ == '__main__':
    main() 