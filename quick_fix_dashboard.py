#!/usr/bin/env python3
"""
Quick Fix SuperTradeX Dashboard - Fixes HTML rendering issues
"""

from flask import Flask, render_template_string, jsonify, Markup
import json
import os
import glob
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

app = Flask(__name__)

def format_small_number(number: float) -> str:
    """Format small numbers with zero count indicator"""
    if number == 0:
        return "0"
    
    # Convert to string with enough precision
    num_str = f"{number:.15f}"
    
    # Find the position of the first non-zero digit after decimal
    decimal_part = num_str.split('.')[1] if '.' in num_str else ""
    
    # Count leading zeros after decimal point
    zero_count = 0
    for char in decimal_part:
        if char == '0':
            zero_count += 1
        else:
            break
    
    if zero_count > 3:  # If more than 3 zeros, show with count
        # Get the significant digits
        significant_part = decimal_part[zero_count:zero_count+4]
        return f"0.0{zero_count}{significant_part}"
    else:
        # Normal formatting for numbers with few zeros
        return f"{number:.8f}".rstrip('0').rstrip('.')

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
    """Quick fix dashboard"""
    
    template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SuperTradeX - Quick Fix Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    <style>
        body { background-color: #0d1117; color: #c9d1d9; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        .card { background-color: #161b22; border: 1px solid #30363d; margin-bottom: 20px; border-radius: 8px; }
        .card-header { background-color: #21262d; border-bottom: 1px solid #30363d; font-weight: 600; border-radius: 8px 8px 0 0; }
        .log-entry { padding: 10px; margin: 6px 0; border-radius: 6px; font-size: 13px; transition: all 0.2s ease; }
        .log-entry:hover { transform: translateX(2px); }
        .log-entry.new-token { background-color: rgba(40, 167, 69, 0.1); border-left: 4px solid #28a745; }
        .log-entry.price { background-color: rgba(0, 123, 255, 0.1); border-left: 4px solid #007bff; }
        .log-entry.trade { background-color: rgba(255, 193, 7, 0.1); border-left: 4px solid #ffc107; }
        .log-container { height: 400px; overflow-y: auto; background-color: #0d1117; border: 1px solid #30363d; padding: 10px; border-radius: 6px; }
        .stats-number { font-size: 2rem; font-weight: bold; color: #3b82f6; }
        .header { background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%); padding: 20px 0; margin-bottom: 30px; }
        
        .token-info { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
        .token-icon { 
            width: 28px; height: 28px; border-radius: 50%; 
            background: linear-gradient(45deg, #3b82f6, #8b5cf6); 
            display: flex; align-items: center; justify-content: center; 
            color: white; font-weight: bold; font-size: 12px; 
            box-shadow: 0 2px 4px rgba(0,0,0,0.3);
            flex-shrink: 0;
        }
        .copy-btn { 
            background: none; border: none; color: #8b949e; cursor: pointer; 
            padding: 4px 6px; border-radius: 4px; font-size: 12px; 
            transition: all 0.2s ease;
        }
        .copy-btn:hover { background-color: #30363d; color: #c9d1d9; transform: scale(1.1); }
        .mint-address { 
            font-family: 'Courier New', monospace; font-size: 11px; 
            color: #8b949e; background-color: rgba(139, 148, 158, 0.1); 
            padding: 2px 6px; border-radius: 3px; display: inline-block;
        }
        .price-formatted { font-family: 'Courier New', monospace; font-weight: 600; }
        .auto-refresh-indicator { 
            position: fixed; top: 20px; right: 20px; 
            background: rgba(40, 167, 69, 0.9); color: white; 
            padding: 8px 15px; border-radius: 20px; font-size: 12px; 
            z-index: 1000; box-shadow: 0 4px 8px rgba(0,0,0,0.3);
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0% { opacity: 1; }
            50% { opacity: 0.7; }
            100% { opacity: 1; }
        }
        .token-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
        .token-details { display: flex; flex-direction: column; gap: 4px; flex-grow: 1; }
        .token-symbol { font-weight: bold; font-size: 14px; }
        .blockchain-status { 
            background: rgba(220, 53, 69, 0.1); border: 1px solid #dc3545; 
            padding: 8px 12px; border-radius: 6px; margin-bottom: 15px; 
        }
    </style>
</head>
<body>
    <div class="auto-refresh-indicator">
        <i class="fas fa-sync-alt"></i> Auto-refresh: <span id="countdown">30</span>s
    </div>

    <div class="header">
        <div class="container">
            <h1><i class="fas fa-chart-line me-2"></i>SuperTradeX Quick Fix Dashboard</h1>
            <p class="mb-0">Fixed HTML rendering and working token icons</p>
        </div>
    </div>

    <div class="container-fluid">
        <div class="blockchain-status">
            <i class="fas fa-exclamation-triangle me-2"></i>
            <strong>Blockchain Connection Issue:</strong> WebSocket keepalive ping timeout detected. 
            System automatically switching to fallback endpoints.
        </div>

        <div class="row mb-4">
            <div class="col-md-3">
                <div class="card text-center p-3">
                    <div class="stats-number">{{ stats.total_tokens }}</div>
                    <div><i class="fas fa-coins me-1"></i>New Tokens</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card text-center p-3">
                    <div class="stats-number">{{ stats.total_trades }}</div>
                    <div><i class="fas fa-exchange-alt me-1"></i>Paper Trades</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card text-center p-3">
                    <div class="stats-number">{{ stats.price_updates }}</div>
                    <div><i class="fas fa-dollar-sign me-1"></i>Price Updates</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card text-center p-3">
                    <div class="stats-number">{{ stats.last_update }}</div>
                    <div><i class="fas fa-clock me-1"></i>Last Update</div>
                </div>
            </div>
        </div>

        <div class="row">
            <div class="col-md-4">
                <div class="card">
                    <div class="card-header">
                        <i class="fas fa-coins me-2"></i>New Tokens ({{ new_tokens|length }})
                    </div>
                    <div class="card-body p-0">
                        <div class="log-container">
                            {% for token in new_tokens %}
                            <div class="log-entry new-token">
                                <div class="token-info">
                                    <div class="token-icon">{{ token.symbol[0] if token.symbol else '?' }}</div>
                                    <div class="token-details">
                                        <div class="token-header">
                                            <span class="token-symbol">{{ token.symbol }}</span>
                                            <button class="copy-btn" onclick="copyToClipboard('{{ token.mint }}', 'Token address copied!')" title="Copy mint address">
                                                <i class="fas fa-copy"></i>
                                            </button>
                                        </div>
                                        <div class="mint-address">{{ token.mint[:8] }}...{{ token.mint[-8:] }}</div>
                                    </div>
                                </div>
                                <div class="token-stats">
                                    <small>
                                        Vol: ${{ "{:,.0f}".format(token.volume_24h or 0) }} | 
                                        MC: ${{ "{:,.0f}".format(token.market_cap or 0) }} | 
                                        RCS: {{ token.rugcheck_score or 'N/A' }}
                                    </small>
                                </div>
                                <div class="timestamp">
                                    <small class="text-muted"><i class="fas fa-clock me-1"></i>{{ token.timestamp[:19] }}</small>
                                </div>
                            </div>
                            {% endfor %}
                        </div>
                    </div>
                </div>
            </div>

            <div class="col-md-4">
                <div class="card">
                    <div class="card-header">
                        <i class="fas fa-dollar-sign me-2"></i>Price Updates ({{ price_updates|length }})
                    </div>
                    <div class="card-body p-0">
                        <div class="log-container">
                            {% for price in price_updates %}
                            <div class="log-entry price">
                                <div class="token-info">
                                    <div class="token-icon">{{ price.symbol[0] if price.symbol else '?' }}</div>
                                    <div class="token-details">
                                        <div class="token-header">
                                            <span class="token-symbol">{{ price.symbol }}</span>
                                            <button class="copy-btn" onclick="copyToClipboard('{{ price.mint }}', 'Token address copied!')" title="Copy mint address">
                                                <i class="fas fa-copy"></i>
                                            </button>
                                        </div>
                                        <div class="mint-address">{{ price.mint[:8] }}...{{ price.mint[-8:] }}</div>
                                    </div>
                                </div>
                                <div class="price-info">
                                    <div class="price-formatted">
                                        {{ format_price(price.price_sol) }} SOL
                                    </div>
                                    <div class="price-formatted">
                                        ${{ format_price(price.price_usd) }} USD
                                    </div>
                                </div>
                                <div class="source-info">
                                    <small class="text-muted">
                                        <i class="fas fa-link me-1"></i>{{ price.source }} | 
                                        <i class="fas fa-clock me-1"></i>{{ price.timestamp[:19] }}
                                    </small>
                                </div>
                            </div>
                            {% endfor %}
                        </div>
                    </div>
                </div>
            </div>

            <div class="col-md-4">
                <div class="card">
                    <div class="card-header">
                        <i class="fas fa-exchange-alt me-2"></i>Paper Trades ({{ trades|length }})
                    </div>
                    <div class="card-body p-0">
                        <div class="log-container">
                            {% for trade in trades %}
                            <div class="log-entry trade">
                                <div class="token-info">
                                    <div class="token-icon">{{ trade.symbol[0] if trade.symbol else '?' }}</div>
                                    <div class="token-details">
                                        <div class="token-header">
                                            <span class="token-symbol">{{ trade.symbol }}</span>
                                            <button class="copy-btn" onclick="copyToClipboard('{{ trade.mint }}', 'Token address copied!')" title="Copy mint address">
                                                <i class="fas fa-copy"></i>
                                            </button>
                                        </div>
                                        <div class="mint-address">{{ trade.mint[:8] }}...{{ trade.mint[-8:] }}</div>
                                    </div>
                                </div>
                                <div class="trade-info">
                                    <div>
                                        <strong class="{{ 'text-success' if trade.action == 'BUY' else 'text-danger' }}">
                                            <i class="fas fa-{{ 'arrow-up' if trade.action == 'BUY' else 'arrow-down' }} me-1"></i>{{ trade.action }}
                                        </strong>
                                    </div>
                                    <div class="price-formatted">
                                        {{ "{:.4f}".format(trade.amount_sol) }} SOL @ {{ format_price(trade.price_sol) }}
                                    </div>
                                    {% if trade.pnl_sol %}
                                    <div class="{{ 'text-success' if trade.pnl_sol > 0 else 'text-danger' }}">
                                        PnL: {{ "{:.4f}".format(trade.pnl_sol) }} SOL
                                    </div>
                                    {% endif %}
                                </div>
                                <div class="strategy-info">
                                    <small class="text-muted">
                                        <i class="fas fa-cog me-1"></i>{{ trade.strategy }} | 
                                        <i class="fas fa-clock me-1"></i>{{ trade.timestamp[:19] }}
                                    </small>
                                </div>
                            </div>
                            {% endfor %}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        function copyToClipboard(text, message) {
            navigator.clipboard.writeText(text).then(function() {
                showCopySuccess(message);
            }).catch(function(err) {
                const textArea = document.createElement('textarea');
                textArea.value = text;
                document.body.appendChild(textArea);
                textArea.select();
                document.execCommand('copy');
                document.body.removeChild(textArea);
                showCopySuccess(message);
            });
        }

        function showCopySuccess(message) {
            const successDiv = document.createElement('div');
            successDiv.style.cssText = 'position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); background: rgba(40, 167, 69, 0.95); color: white; padding: 10px 20px; border-radius: 8px; z-index: 2000;';
            successDiv.innerHTML = '<i class="fas fa-check me-2"></i>' + message;
            document.body.appendChild(successDiv);
            
            setTimeout(() => {
                document.body.removeChild(successDiv);
            }, 2000);
        }

        let refreshCountdown = 30;
        const countdownElement = document.getElementById('countdown');
        
        function updateCountdown() {
            countdownElement.textContent = refreshCountdown;
            refreshCountdown--;
            
            if (refreshCountdown < 0) {
                location.reload();
            }
        }
        
        setInterval(updateCountdown, 1000);
    </script>
</body>
</html>
    """
    
    try:
        log_files = get_latest_log_files()
        
        new_tokens = []
        price_updates = []
        trades = []
        
        if 'new_tokens' in log_files:
            new_tokens = read_json_log_file(log_files['new_tokens'], 20)
            
        if 'price_monitor' in log_files:
            price_updates = read_json_log_file(log_files['price_monitor'], 20)
            
        if 'trades' in log_files:
            trades = read_json_log_file(log_files['trades'], 20)
        
        stats = {
            'total_tokens': len(new_tokens),
            'total_trades': len(trades),
            'price_updates': len(price_updates),
            'last_update': datetime.now().strftime('%H:%M:%S') if log_files else '--'
        }
        
        def format_price(value):
            if value is None:
                return "0"
            return format_small_number(float(value))
        
        return render_template_string(template, 
                                    new_tokens=new_tokens,
                                    price_updates=price_updates,
                                    trades=trades,
                                    stats=stats,
                                    format_price=format_price)
        
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
            'timestamp': datetime.now().isoformat(),
            'features': ['fixed_icons', 'proper_formatting', 'copy_functionality', 'auto_refresh']
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("🚀 Starting Quick Fix SuperTradeX Dashboard")
    print("📊 Dashboard available at: http://localhost:5004")
    print("📁 Monitoring logs directory: ./logs/")
    print("✅ Fixed: Token icons, HTML rendering, number formatting")
    
    app.run(host='0.0.0.0', port=5004, debug=False) 