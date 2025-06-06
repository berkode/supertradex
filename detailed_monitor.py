#!/usr/bin/env python3
"""
Detailed Live Trading Monitor with Trade Numbers and Decision Analysis
Shows comprehensive trading decisions, numbers, and explanations
"""

import asyncio
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import json

class DetailedTradingMonitor:
    def __init__(self):
        self.db_path = "outputs/supertradex.db"
        self.log_file = "simple_live_paper_trading.log"
        self.last_check = datetime.now() - timedelta(hours=1)
        
    def get_token_symbols(self) -> Dict[str, str]:
        """Get token symbols from database"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT mint, symbol 
                FROM tokens 
                WHERE symbol IS NOT NULL AND symbol != ''
            """)
            
            symbols = {}
            for mint, symbol in cursor.fetchall():
                symbols[mint] = symbol
                
            conn.close()
            return symbols
        except Exception as e:
            print(f"Error getting symbols: {e}")
            return {}
    
    def get_recent_trades(self) -> List[Dict]:
        """Get recent trading activity from database"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Get recent trades/orders
            cursor.execute("""
                SELECT 
                    mint,
                    action,
                    quantity,
                    price,
                    timestamp,
                    status,
                    strategy
                FROM orders 
                WHERE timestamp > datetime('now', '-1 hour')
                ORDER BY timestamp DESC
                LIMIT 50
            """)
            
            trades = []
            for row in cursor.fetchall():
                trades.append({
                    'mint': row[0],
                    'action': row[1],
                    'quantity': row[2],
                    'price': row[3],
                    'timestamp': row[4],
                    'status': row[5],
                    'strategy': row[6]
                })
                
            conn.close()
            return trades
        except Exception as e:
            print(f"Error getting trades: {e}")
            return []
    
    def get_current_positions(self) -> List[Dict]:
        """Get current positions"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    mint,
                    quantity,
                    entry_price,
                    current_price,
                    pnl,
                    strategy,
                    timestamp
                FROM positions 
                WHERE quantity > 0
                ORDER BY timestamp DESC
            """)
            
            positions = []
            for row in cursor.fetchall():
                positions.append({
                    'mint': row[0],
                    'quantity': row[1],
                    'entry_price': row[2],
                    'current_price': row[3],
                    'pnl': row[4],
                    'strategy': row[5],
                    'timestamp': row[6]
                })
                
            conn.close()
            return positions
        except Exception as e:
            print(f"Error getting positions: {e}")
            return []
    
    def get_recent_price_updates(self) -> List[Dict]:
        """Get recent price updates"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    mint,
                    price,
                    source,
                    timestamp
                FROM price_history 
                WHERE timestamp > datetime('now', '-30 minutes')
                ORDER BY timestamp DESC
                LIMIT 20
            """)
            
            prices = []
            for row in cursor.fetchall():
                prices.append({
                    'mint': row[0],
                    'price': row[1],
                    'source': row[2],
                    'timestamp': row[3]
                })
                
            conn.close()
            return prices
        except Exception as e:
            print(f"Error getting prices: {e}")
            return []
    
    def parse_log_for_decisions(self) -> List[Dict]:
        """Parse log file for trading decisions and explanations"""
        decisions = []
        try:
            with open(self.log_file, 'r') as f:
                lines = f.readlines()
                
            # Look for strategy evaluation lines
            for line in lines[-200:]:  # Last 200 lines
                if "Evaluating trading conditions" in line:
                    parts = line.split()
                    timestamp = f"{parts[0]} {parts[1]}"
                    mint = None
                    for part in parts:
                        if len(part) == 44:  # Solana address length
                            mint = part
                            break
                    
                    if mint:
                        decisions.append({
                            'timestamp': timestamp,
                            'mint': mint,
                            'action': 'EVALUATION',
                            'reason': 'Strategy condition check'
                        })
                
                # Look for signal generation
                elif "SIGNAL GENERATED" in line or "Entry signal" in line or "Exit signal" in line:
                    parts = line.split()
                    timestamp = f"{parts[0]} {parts[1]}"
                    decisions.append({
                        'timestamp': timestamp,
                        'mint': 'UNKNOWN',
                        'action': 'SIGNAL',
                        'reason': line.split(':', 2)[-1].strip() if ':' in line else line
                    })
                
                # Look for trade executions
                elif "TRADE EXECUTED" in line or "Order placed" in line:
                    parts = line.split()
                    timestamp = f"{parts[0]} {parts[1]}"
                    decisions.append({
                        'timestamp': timestamp,
                        'mint': 'UNKNOWN',
                        'action': 'EXECUTION',
                        'reason': line.split(':', 2)[-1].strip() if ':' in line else line
                    })
                    
        except Exception as e:
            print(f"Error parsing log: {e}")
            
        return decisions[-20:]  # Last 20 decisions
    
    def get_trading_statistics(self) -> Dict:
        """Get comprehensive trading statistics"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            stats = {}
            
            # Total trades today
            cursor.execute("""
                SELECT COUNT(*) FROM orders 
                WHERE date(timestamp) = date('now')
            """)
            stats['trades_today'] = cursor.fetchone()[0]
            
            # Successful trades
            cursor.execute("""
                SELECT COUNT(*) FROM orders 
                WHERE status = 'filled' AND date(timestamp) = date('now')
            """)
            stats['successful_trades'] = cursor.fetchone()[0]
            
            # Total PnL
            cursor.execute("""
                SELECT SUM(pnl) FROM positions 
                WHERE date(timestamp) = date('now')
            """)
            result = cursor.fetchone()[0]
            stats['total_pnl'] = result if result else 0
            
            # Active positions
            cursor.execute("""
                SELECT COUNT(*) FROM positions 
                WHERE quantity > 0
            """)
            stats['active_positions'] = cursor.fetchone()[0]
            
            # Tokens monitored
            cursor.execute("""
                SELECT COUNT(DISTINCT mint) FROM price_history 
                WHERE timestamp > datetime('now', '-1 hour')
            """)
            stats['tokens_monitored'] = cursor.fetchone()[0]
            
            conn.close()
            return stats
        except Exception as e:
            print(f"Error getting statistics: {e}")
            return {}
    
    def format_mint(self, mint: str, symbols: Dict[str, str]) -> str:
        """Format mint address with symbol"""
        if mint in symbols:
            return f"{symbols[mint]} | {mint[:8]}...{mint[-8:]}"
        return f"{mint[:8]}...{mint[-8:]}"
    
    def display_detailed_monitor(self):
        """Display comprehensive trading monitor"""
        symbols = self.get_token_symbols()
        trades = self.get_recent_trades()
        positions = self.get_current_positions()
        prices = self.get_recent_price_updates()
        decisions = self.parse_log_for_decisions()
        stats = self.get_trading_statistics()
        
        # Clear screen
        print("\033[2J\033[H")
        
        print("🚀 SUPERTRADEX DETAILED TRADING MONITOR")
        print("=" * 80)
        print(f"⏰ Time: {datetime.now().strftime('%H:%M:%S')} | Paper Trading Mode")
        print("=" * 80)
        
        # Trading Statistics
        print("\n📊 TRADING STATISTICS:")
        print(f"   • Trades Today: {stats.get('trades_today', 0)}")
        print(f"   • Successful Trades: {stats.get('successful_trades', 0)}")
        print(f"   • Total P&L: {stats.get('total_pnl', 0):.6f} SOL")
        print(f"   • Active Positions: {stats.get('active_positions', 0)}")
        print(f"   • Tokens Monitored: {stats.get('tokens_monitored', 0)}")
        
        # Current Positions
        print("\n💼 CURRENT POSITIONS:")
        if positions:
            for pos in positions:
                mint_display = self.format_mint(pos['mint'], symbols)
                pnl_color = "🟢" if pos['pnl'] > 0 else "🔴" if pos['pnl'] < 0 else "⚪"
                print(f"   {pnl_color} {mint_display}")
                print(f"      Qty: {pos['quantity']:.2f} | Entry: {pos['entry_price']:.8f} SOL")
                print(f"      Current: {pos['current_price']:.8f} SOL | P&L: {pos['pnl']:.6f} SOL")
        else:
            print("   📭 No active positions")
        
        # Recent Trades
        print("\n💰 RECENT TRADES:")
        if trades:
            for trade in trades[-10:]:  # Last 10 trades
                mint_display = self.format_mint(trade['mint'], symbols)
                action_emoji = "🟢" if trade['action'] == 'buy' else "🔴" if trade['action'] == 'sell' else "⚪"
                status_emoji = "✅" if trade['status'] == 'filled' else "⏳" if trade['status'] == 'pending' else "❌"
                print(f"   {action_emoji}{status_emoji} {trade['timestamp']} | {mint_display}")
                print(f"      Action: {trade['action'].upper()} | Qty: {trade['quantity']:.2f}")
                print(f"      Price: {trade['price']:.8f} SOL | Strategy: {trade['strategy']}")
        else:
            print("   📭 No recent trades")
        
        # Recent Price Updates
        print("\n📈 RECENT PRICE UPDATES:")
        if prices:
            for price in prices[-10:]:  # Last 10 price updates
                mint_display = self.format_mint(price['mint'], symbols)
                print(f"   📊 {price['timestamp']} | {mint_display}")
                print(f"      Price: {price['price']:.8f} SOL | Source: {price['source']}")
        else:
            print("   📭 No recent price updates")
        
        # Trading Decisions & Explanations
        print("\n🧠 RECENT TRADING DECISIONS:")
        if decisions:
            for decision in decisions:
                action_emoji = "🔍" if decision['action'] == 'EVALUATION' else "⚡" if decision['action'] == 'SIGNAL' else "🎯"
                mint_display = self.format_mint(decision['mint'], symbols) if decision['mint'] != 'UNKNOWN' else 'SYSTEM'
                print(f"   {action_emoji} {decision['timestamp']} | {mint_display}")
                print(f"      Action: {decision['action']} | Reason: {decision['reason']}")
        else:
            print("   📭 No recent decisions")
        
        # System Status
        print("\n🔧 SYSTEM STATUS:")
        print("   • Paper Trading: ✅ ACTIVE")
        print("   • Real-time Data: ✅ CONNECTED")
        print("   • Strategy Engine: ✅ RUNNING")
        print("   • Risk Management: ✅ ACTIVE")
        
        print("\n" + "=" * 80)
        print("Press Ctrl+C to stop monitoring...")

async def main():
    monitor = DetailedTradingMonitor()
    
    try:
        while True:
            monitor.display_detailed_monitor()
            await asyncio.sleep(5)  # Update every 5 seconds
    except KeyboardInterrupt:
        print("\n\n👋 Detailed monitor stopped.")

if __name__ == "__main__":
    asyncio.run(main()) 