#!/usr/bin/env python3
"""
Simple SuperTradeX Real-Time Monitoring Dashboard
Standalone Flask app to display live logs from the controlled main script
"""

from flask import Flask, render_template_string, jsonify, Markup
import json
import os
import glob
from datetime import datetime
from pathlib import Path
import threading
import time
from typing import Dict, List, Optional

app = Flask(__name__)

def get_latest_log_files():
    """Get the most recent log files"""
    logs_dir = Path("logs")
    if not logs_dir.exists():
        return {}
        
    log_files = {}
    
    # Get the most recent files for each type
    for log_type in ['new_tokens', 'price_monitor', 'trades', 'main_execution']:
        pattern = f"{log_type}_*.json" if log_type != 'main_execution' else f"{log_type}_*.log"
        files = list(logs_dir.glob(pattern))
        
        if files:
            latest_file = max(files, key=lambda f: f.stat().st_mtime)
            log_files[log_type] = latest_file
            
    return log_files

def read_json_log_file(file_path: Path, limit: int = 50) -> List[Dict]:
    """Read and parse JSON log file"""
    try:
        if not file_path.exists():
            return []
            
        with open(file_path, 'r') as f:
            data = json.load(f)
            
        if isinstance(data, list):
            return data[-limit:] if len(data) > limit else data
        else:
            return [data]
            
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return []

def read_text_log_file(file_path: Path, limit: int = 20) -> List[str]:
    """Read text log file"""
    try:
        if not file_path.exists():
            return []
            
        with open(file_path, 'r') as f:
            lines = f.readlines()
            
        return lines[-limit:] if len(lines) > limit else lines
        
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return []

@app.route('/')
def dashboard():
    """Main monitoring dashboard"""
    
    # HTML template embedded in Python
    template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SuperTradeX - Monitoring Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    <style>
        body { background-color: #0d1117; color: #c9d1d9; }
        .card { background-color: #161b22; border: 1px solid #30363d; margin-bottom: 20px; }
        .card-header { background-color: #21262d; border-bottom: 1px solid #30363d; font-weight: 600; }
        .log-entry { padding: 8px; margin: 4px 0; border-radius: 4px; font-family: monospace; font-size: 12px; }
        .log-entry.new-token { background-color: rgba(40, 167, 69, 0.1); border-left: 3px solid #28a745; }
        .log-entry.price { background-color: rgba(0, 123, 255, 0.1); border-left: 3px solid #007bff; }
        .log-entry.trade { background-color: rgba(255, 193, 7, 0.1); border-left: 3px solid #ffc107; }
        .log-container { height: 400px; overflow-y: auto; background-color: #0d1117; border: 1px solid #30363d; padding: 10px; }
        .stats-number { font-size: 2rem; font-weight: bold; color: #3b82f6; }
        .header { background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%); padding: 20px 0; margin-bottom: 30px; }
        
        /* New styles for enhanced features */
        .token-info { display: flex; align-items: center; gap: 8px; }
        .token-icon { width: 24px; height: 24px; border-radius: 50%; background: linear-gradient(45deg, #3b82f6, #8b5cf6); display: flex; align-items: center; justify-content: center; color: white; font-weight: bold; font-size: 10px; }
        .copy-btn { background: none; border: none; color: #8b949e; cursor: pointer; padding: 2px 4px; border-radius: 3px; font-size: 12px; }
        .copy-btn:hover { background-color: #30363d; color: #c9d1d9; }
        .mint-address { font-family: monospace; font-size: 11px; color: #8b949e; }
        .price-formatted { font-family: monospace; }
        .zero-count { color: #8b949e; font-size: 10px; vertical-align: super; }
        .auto-refresh-indicator { position: fixed; top: 10px; right: 10px; background: rgba(40, 167, 69, 0.8); color: white; padding: 5px 10px; border-radius: 15px; font-size: 12px; z-index: 1000; }
        .token-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px; }
        .token-details { display: flex; flex-direction: column; gap: 2px; }
    </style>
</head>
<body>
    <div class="header">
        <div class="container">
            <h1><i class="fas fa-chart-line me-2"></i>SuperTradeX Monitoring Dashboard</h1>
            <p class="mb-0">Real-time monitoring of token discovery, prices, and trades</p>
        </div>
    </div>

    <div class="container-fluid">
        <!-- Stats Row -->
        <div class="row mb-4">
            <div class="col-md-3">
                <div class="card text-center p-3">
                    <div class="stats-number">{{ stats.total_tokens }}</div>
                    <div>New Tokens</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card text-center p-3">
                    <div class="stats-number">{{ stats.total_trades }}</div>
                    <div>Paper Trades</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card text-center p-3">
                    <div class="stats-number">{{ stats.price_updates }}</div>
                    <div>Price Updates</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card text-center p-3">
                    <div class="stats-number">{{ stats.last_update }}</div>
                    <div>Last Update</div>
                </div>
            </div>
        </div>

        <!-- Main Content Row -->
        <div class="row">
            <!-- New Tokens -->
            <div class="col-md-4">
                <div class="card">
                    <div class="card-header">
                        <i class="fas fa-coins me-2"></i>New Tokens ({{ new_tokens|length }})
                    </div>
                    <div class="card-body p-0">
                        <div class="log-container">
                            {% for token in new_tokens %}
                            <div class="log-entry new-token">
                                <strong>{{ token.symbol }}</strong> ({{ token.mint[:8] }}...)
                                <br><small>Vol: ${{ "{:,.0f}".format(token.volume_24h or 0) }} | 
                                MC: ${{ "{:,.0f}".format(token.market_cap or 0) }} | 
                                RCS: {{ token.rugcheck_score or 'N/A' }}</small>
                                <br><small class="text-muted">{{ token.timestamp[:19] }}</small>
                            </div>
                            {% endfor %}
                        </div>
                    </div>
                </div>
            </div>

            <!-- Price Updates -->
            <div class="col-md-4">
                <div class="card">
                    <div class="card-header">
                        <i class="fas fa-dollar-sign me-2"></i>Price Updates ({{ price_updates|length }})
                    </div>
                    <div class="card-body p-0">
                        <div class="log-container">
                            {% for price in price_updates %}
                            <div class="log-entry price">
                                <strong>{{ price.symbol }}</strong>
                                <br><small>{{ "{:.10f}".format(price.price_sol) }} SOL | 
                                ${{ "{:.6f}".format(price.price_usd) }} USD</small>
                                <br><small class="text-muted">{{ price.source }} | {{ price.timestamp[:19] }}</small>
                            </div>
                            {% endfor %}
                        </div>
                    </div>
                </div>
            </div>

            <!-- Trades -->
            <div class="col-md-4">
                <div class="card">
                    <div class="card-header">
                        <i class="fas fa-exchange-alt me-2"></i>Paper Trades ({{ trades|length }})
                    </div>
                    <div class="card-body p-0">
                        <div class="log-container">
                            {% for trade in trades %}
                            <div class="log-entry trade">
                                <strong class="{{ 'text-success' if trade.action == 'BUY' else 'text-danger' }}">{{ trade.action }}</strong> 
                                <strong>{{ trade.symbol }}</strong>
                                <br><small>{{ "{:.4f}".format(trade.amount_sol) }} SOL @ {{ "{:.8f}".format(trade.price_sol) }}</small>
                                <br><small class="text-muted">{{ trade.strategy }} | {{ trade.timestamp[:19] }}</small>
                            </div>
                            {% endfor %}
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- System Logs -->
        <div class="row mt-4">
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <i class="fas fa-terminal me-2"></i>System Logs
                        <button class="btn btn-sm btn-outline-light float-end" onclick="location.reload()">
                            <i class="fas fa-sync"></i> Refresh
                        </button>
                    </div>
                    <div class="card-body p-0">
                        <div class="log-container" style="height: 300px;">
                            {% for log in system_logs %}
                            <div class="log-entry">{{ log.strip() }}</div>
                            {% endfor %}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        // Auto-refresh every 30 seconds
        setTimeout(function() {
            location.reload();
        }, 30000);
    </script>
</body>
</html>
    """
    
    try:
        log_files = get_latest_log_files()
        
        # Read data from log files
        new_tokens = []
        price_updates = []
        trades = []
        system_logs = []
        
        if 'new_tokens' in log_files:
            new_tokens = read_json_log_file(log_files['new_tokens'], 20)
            
        if 'price_monitor' in log_files:
            price_updates = read_json_log_file(log_files['price_monitor'], 20)
            
        if 'trades' in log_files:
            trades = read_json_log_file(log_files['trades'], 20)
            
        if 'main_execution' in log_files:
            system_logs = read_text_log_file(log_files['main_execution'], 20)
        
        # Calculate stats
        stats = {
            'total_tokens': len(new_tokens),
            'total_trades': len(trades),
            'price_updates': len(price_updates),
            'last_update': datetime.now().strftime('%H:%M:%S') if log_files else '--'
        }
        
        return render_template_string(template, 
                                    new_tokens=new_tokens,
                                    price_updates=price_updates,
                                    trades=trades,
                                    system_logs=system_logs,
                                    stats=stats)
        
    except Exception as e:
        return f"<h1>Error loading dashboard: {e}</h1>"

@app.route('/api/status')
def api_status():
    """API endpoint for status"""
    try:
        log_files = get_latest_log_files()
        return jsonify({
            'status': 'ok',
            'log_files_found': len(log_files),
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("🚀 Starting Simple SuperTradeX Monitoring Dashboard")
    print("📊 Dashboard available at: http://localhost:5001")
    print("📁 Monitoring logs directory: ./logs/")
    print("🔄 Auto-refresh every 30 seconds")
    
    app.run(host='0.0.0.0', port=5001, debug=False) 