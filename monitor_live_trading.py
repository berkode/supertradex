#!/usr/bin/env python3
"""
Real-time Live Trading Monitor
Monitors the live trading system logs and displays real-time activity
"""
import time
import os
import re
from datetime import datetime
from collections import defaultdict

class LiveTradingMonitor:
    def __init__(self):
        self.log_files = {
            'main': './outputs/supertradex.log',
            'price': './outputs/price_updates.log',
            'blockchain': './outputs/blockchain_listener.log'
        }
        self.last_positions = {}
        self.tokens_being_evaluated = set()
        self.price_updates = defaultdict(list)
        self.trading_activity = []
        self.top_tokens = {}  # Track top 3 tokens with their symbols
        self.trading_events = []  # Track detailed trading events
        
    def get_file_size(self, filepath):
        """Get current file size"""
        try:
            return os.path.getsize(filepath)
        except:
            return 0
    
    def read_new_lines(self, filepath, last_size):
        """Read new lines from file since last check"""
        try:
            current_size = self.get_file_size(filepath)
            if current_size <= last_size:
                return [], current_size
            
            with open(filepath, 'r') as f:
                f.seek(last_size)
                new_lines = f.readlines()
            
            return new_lines, current_size
        except:
            return [], last_size
    
    def parse_price_update(self, line):
        """Parse price update from log line"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Parse Jupiter API price format: "💰 JUPITER_API price: FgAEC3Tq... = 0.00000002 SOL ($0.000004)"
        jupiter_match = re.search(r'💰 JUPITER_API price: ([A-Za-z0-9]+)\.+ = ([\d.]+) SOL \(\$?([\d.]+)\)', line)
        if jupiter_match:
            token_short = jupiter_match.group(1)
            price_sol = float(jupiter_match.group(2))
            price_usd = float(jupiter_match.group(3))
            symbol = self.get_token_symbol(token_short)
            
            return {
                'token': token_short + '...',
                'symbol': symbol,
                'price_sol': price_sol,
                'price_usd': price_usd,
                'source': 'jupiter_api',
                'timestamp': timestamp
            }
        
        # Parse Helius price format: "🎯 Helius Pump price update: 0.00000049 SOL (decimals: 6) [helius_api]"
        helius_match = re.search(r'🎯 Helius Pump price update: ([\d.]+) SOL.*\[([^\]]+)\]', line)
        if helius_match:
            price_sol = float(helius_match.group(1))
            source = helius_match.group(2)
            
            # Try to find token in the context (this is a limitation - we'd need more context)
            # For now, we'll use a placeholder
            return {
                'token': 'HELIUS...',
                'symbol': 'HLUS',
                'price_sol': price_sol,
                'price_usd': None,
                'source': source,
                'timestamp': timestamp
            }
        
        # Parse general price patterns with source indicators
        sol_match = re.search(r'([\d.]+) SOL', line)
        usd_match = re.search(r'\$([\d.]+)', line)
        token_match = re.search(r'([A-Za-z0-9]{8,})', line)
        
        # Look for source indicators
        source = "unknown"
        if "helius_api" in line or "helius" in line.lower():
            source = "helius_api"
        elif "jupiter" in line.lower():
            source = "jupiter_api"
        elif "raydium" in line.lower():
            source = "raydium_api"
        elif "blockchain" in line.lower():
            source = "blockchain"
        
        if sol_match and token_match:
            token_id = token_match.group(1)
            symbol = self.get_token_symbol(token_id)
            
            return {
                'token': token_id[:8] + '...',
                'symbol': symbol,
                'price_sol': float(sol_match.group(1)),
                'price_usd': float(usd_match.group(1)) if usd_match else None,
                'source': source,
                'timestamp': timestamp
            }
        
        return None
    
    def get_token_symbol(self, mint):
        """Get token symbol from mint address (placeholder - could be enhanced with API calls)"""
        # For now, return first 4 chars as symbol
        return mint[:4].upper()
    
    def parse_strategy_evaluation(self, line):
        """Parse strategy evaluation from log line"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        if 'StrategyEvaluator starting evaluation' in line:
            token_match = re.search(r'token: ([A-Za-z0-9]+)', line)
            if token_match:
                full_mint = token_match.group(1)
                symbol = self.get_token_symbol(full_mint)
                self.tokens_being_evaluated.add(full_mint)
                self.top_tokens[full_mint] = symbol
                
                # Add detailed trading event
                self.trading_events.append({
                    'timestamp': timestamp,
                    'type': 'evaluation_start',
                    'token': full_mint,
                    'symbol': symbol,
                    'description': f"Started evaluation for {symbol}"
                })
                
                return f"🎯 Evaluating: {symbol} | {full_mint[:8]}..."
        
        if 'Evaluating trading conditions' in line:
            token_match = re.search(r'mint ([A-Za-z0-9]+)', line)
            if token_match:
                full_mint = token_match.group(1)
                symbol = self.get_token_symbol(full_mint)
                self.top_tokens[full_mint] = symbol
                
                # Add detailed trading event
                self.trading_events.append({
                    'timestamp': timestamp,
                    'type': 'conditions_check',
                    'token': full_mint,
                    'symbol': symbol,
                    'description': f"Checking trading conditions for {symbol}"
                })
                
                return f"📊 Trading conditions check: {symbol} | {full_mint[:8]}..."
        
        return None
    
    def parse_trading_activity(self, line):
        """Parse trading activity from log line"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Look for paper trading activity
        if 'paper trading' in line.lower() or 'simulated' in line.lower():
            if any(keyword in line.upper() for keyword in ['BUY', 'SELL', 'ENTER', 'EXIT']):
                self.trading_events.append({
                    'timestamp': timestamp,
                    'type': 'paper_trade',
                    'description': line.strip()
                })
                return f"💰 PAPER: {line.strip()}"
        
        # Look for actual trading signals
        if any(keyword in line.lower() for keyword in ['buy signal', 'sell signal', 'entry signal', 'exit signal']):
            token_match = re.search(r'([A-Za-z0-9]{8,})', line)
            if token_match:
                full_mint = token_match.group(1)
                symbol = self.get_token_symbol(full_mint)
                self.trading_events.append({
                    'timestamp': timestamp,
                    'type': 'signal',
                    'token': full_mint,
                    'symbol': symbol,
                    'description': line.strip()
                })
                return f"🎯 SIGNAL: {symbol} | {line.strip()}"
        
        # Look for position changes
        if 'position' in line.lower():
            if any(keyword in line.lower() for keyword in ['entered', 'exited', 'opened', 'closed']):
                self.trading_events.append({
                    'timestamp': timestamp,
                    'type': 'position',
                    'description': line.strip()
                })
                return f"📈 POSITION: {line.strip()}"
        
        # Look for trade execution
        if any(keyword in line.lower() for keyword in ['trade executed', 'order filled', 'transaction']):
            self.trading_events.append({
                'timestamp': timestamp,
                'type': 'execution',
                'description': line.strip()
            })
            return f"⚡ EXECUTED: {line.strip()}"
        
        return None
    
    def display_status(self):
        """Display current trading status"""
        os.system('clear')
        print("🚀 SUPERTRADEX LIVE TRADING MONITOR")
        print("=" * 80)
        print(f"⏰ Time: {datetime.now().strftime('%H:%M:%S')} | Monitoring: Main System + Paper Trading")
        print("=" * 80)
        
        # Show TOP 3 TOKENS being evaluated
        if self.top_tokens:
            print("🎯 TOP 3 TOKENS UNDER EVALUATION:")
            top_3 = list(self.top_tokens.items())[-3:]  # Get last 3 tokens
            for mint, symbol in top_3:
                print(f"   • {symbol} | {mint[:8]}...{mint[-8:]}")
            print()
        
        # Show recent price updates with symbols
        if self.price_updates:
            print("📊 RECENT PRICE UPDATES (with sources):")
            recent_prices = []
            for token, updates in self.price_updates.items():
                if updates:
                    latest = updates[-1]
                    recent_prices.append(latest)
            
            # Sort by timestamp and show last 5
            recent_prices.sort(key=lambda x: x['timestamp'], reverse=True)
            for price in recent_prices[:5]:
                usd_str = f" (${price['price_usd']:.6f})" if price['price_usd'] else ""
                symbol = price.get('symbol', price['token'])
                source = price.get('source', 'unknown')
                print(f"   {price['timestamp']} | {symbol} | {price['token']} | {price['price_sol']:.8f} SOL{usd_str} [{source}]")
            print()
        
        # Show detailed trading events
        if self.trading_events:
            print("🎯 DETAILED TRADING EVENTS:")
            for event in self.trading_events[-8:]:  # Show last 8 events
                event_type = event['type'].upper()
                symbol = event.get('symbol', '')
                symbol_display = f"{symbol} | " if symbol else ""
                print(f"   {event['timestamp']} | [{event_type}] {symbol_display}{event['description']}")
            print()
        
        # Show trading activity summary
        if self.trading_activity:
            print("💰 RECENT TRADING ACTIVITY:")
            for activity in self.trading_activity[-6:]:  # Show last 6
                print(f"   {activity}")
            print()
        
        print("📈 SYSTEM STATUS:")
        print(f"   • Top Tokens Tracked: {len(self.top_tokens)}")
        print(f"   • Price Updates: {sum(len(updates) for updates in self.price_updates.values())}")
        print(f"   • Trading Events: {len(self.trading_events)}")
        print(f"   • Activity Log Entries: {len(self.trading_activity)}")
        print()
        print("Press Ctrl+C to stop monitoring...")
    
    def monitor(self):
        """Main monitoring loop"""
        print("🔍 Starting Live Trading Monitor...")
        
        # Initialize file sizes
        file_sizes = {}
        for name, filepath in self.log_files.items():
            file_sizes[name] = self.get_file_size(filepath)
        
        try:
            while True:
                # Check each log file for new content
                for name, filepath in self.log_files.items():
                    new_lines, new_size = self.read_new_lines(filepath, file_sizes[name])
                    file_sizes[name] = new_size
                    
                    for line in new_lines:
                        # Parse different types of events
                        if name == 'main':
                            # Strategy evaluation
                            strategy_event = self.parse_strategy_evaluation(line)
                            if strategy_event:
                                self.trading_activity.append(f"{datetime.now().strftime('%H:%M:%S')} | {strategy_event}")
                            
                            # Trading activity
                            trade_event = self.parse_trading_activity(line)
                            if trade_event:
                                self.trading_activity.append(f"{datetime.now().strftime('%H:%M:%S')} | {trade_event}")
                            
                            # Price updates (also in main log)
                            price_update = self.parse_price_update(line)
                            if price_update:
                                token = price_update['token']
                                self.price_updates[token].append(price_update)
                                # Keep only last 10 updates per token
                                if len(self.price_updates[token]) > 10:
                                    self.price_updates[token] = self.price_updates[token][-10:]
                        
                        elif name == 'price':
                            # Price updates (if separate log exists)
                            price_update = self.parse_price_update(line)
                            if price_update:
                                token = price_update['token']
                                self.price_updates[token].append(price_update)
                                # Keep only last 10 updates per token
                                if len(self.price_updates[token]) > 10:
                                    self.price_updates[token] = self.price_updates[token][-10:]
                
                # Update display
                self.display_status()
                
                # Sleep before next check
                time.sleep(2)
                
        except KeyboardInterrupt:
            print("\n🛑 Monitoring stopped by user")
        except Exception as e:
            print(f"\n❌ Error in monitoring: {e}")

if __name__ == "__main__":
    monitor = LiveTradingMonitor()
    monitor.monitor() 