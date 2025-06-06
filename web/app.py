import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import os
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

# Import SupertradeX components
from config.settings import Settings
from data.token_database import TokenDatabase
from strategies.paper_trading import PaperTrading
from wallet.wallet_manager import WalletManager
from data.price_monitor import PriceMonitor
from utils.logger import get_logger

# Initialize logging
logger = get_logger(__name__)

class SupertradeXWebApp:
    def __init__(self):
        self.app = FastAPI(
            title="SupertradeX Dashboard",
            description="Real-time Solana trading dashboard",
            version="1.0.0"
        )
        
        # Initialize components
        self.settings = None
        self.db = None
        self.paper_trading = None
        self.wallet_manager = None
        self.price_monitor = None
        
        # Real-time data cache
        self.live_data = {
            'tokens': [],
            'positions': [],
            'trades': [],
            'stats': {},
            'last_update': None
        }
        
        self.setup_routes()
        self.setup_static_files()
        
    async def initialize_components(self):
        """Initialize SupertradeX components"""
        try:
            # Initialize settings
            self.settings = Settings()
            logger.info("Settings initialized")
            
            # Initialize database
            self.db = await TokenDatabase.create(self.settings.DATABASE_FILE_PATH, self.settings)
            logger.info("Token database initialized")
            
            # Initialize wallet manager
            self.wallet_manager = WalletManager(self.settings)
            logger.info("Wallet manager initialized")
            
            # Initialize price monitor
            self.price_monitor = PriceMonitor(self.settings, self.db)
            logger.info("Price monitor initialized")
            
            # Initialize paper trading
            self.paper_trading = PaperTrading(self.settings, self.db, self.wallet_manager, self.price_monitor)
            await self.paper_trading.load_persistent_state()
            logger.info("Paper trading initialized")
            
            logger.info("All components initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize components: {e}", exc_info=True)
            raise
    
    def setup_static_files(self):
        """Setup static file serving"""
        web_dir = Path(__file__).parent
        static_dir = web_dir / "static"
        templates_dir = web_dir / "templates"
        
        # Create directories if they don't exist
        static_dir.mkdir(exist_ok=True)
        templates_dir.mkdir(exist_ok=True)
        
        # Mount static files
        self.app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
        
        # Setup templates
        self.templates = Jinja2Templates(directory=str(templates_dir))
    
    def setup_routes(self):
        """Setup all API routes"""
        
        @self.app.on_event("startup")
        async def startup_event():
            await self.initialize_components()
        
        @self.app.get("/", response_class=HTMLResponse)
        async def dashboard(request: Request):
            """Main dashboard page"""
            return self.templates.TemplateResponse("dashboard.html", {"request": request})
        
        @self.app.get("/api/health")
        async def health_check():
            """System health check"""
            health_status = {
                "status": "healthy",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "components": {
                    "database": bool(self.db),
                    "paper_trading": bool(self.paper_trading),
                    "wallet_manager": bool(self.wallet_manager),
                    "price_monitor": bool(self.price_monitor)
                }
            }
            return health_status
        
        @self.app.get("/api/tokens")
        async def get_active_tokens():
            """Get list of active tokens for trading"""
            try:
                if not self.db:
                    raise HTTPException(status_code=503, detail="Database not available")
                
                tokens = await self.db.get_top_tokens_for_trading(limit=20)
                token_list = []
                
                for token in tokens:
                    # Get current price from API data
                    current_price_sol = 0.000001
                    if token.api_data and isinstance(token.api_data, dict):
                        current_price_sol = token.api_data.get('price_sol', current_price_sol)
                    elif token.price:
                        # Estimate SOL price (assuming ~$150/SOL)
                        current_price_sol = token.price / 150
                    
                    token_data = {
                        "mint": token.mint,
                        "symbol": token.symbol or 'UNKNOWN',
                        "name": token.name or '',
                        "price_sol": current_price_sol,
                        "price_usd": token.price or 0,
                        "volume_24h": token.volume_24h or 0,
                        "liquidity": token.liquidity or 0,
                        "dex_id": token.dex_id or '',
                        "rugcheck_score": token.rugcheck_score or 0,
                        "monitoring_status": token.monitoring_status or 'inactive',
                        "last_updated": token.last_updated.isoformat() if token.last_updated else None
                    }
                    token_list.append(token_data)
                
                return {"tokens": token_list, "count": len(token_list)}
                
            except Exception as e:
                logger.error(f"Error fetching tokens: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/paper/balance")
        async def get_paper_balance():
            """Get current paper trading balance"""
            try:
                if not self.db:
                    raise HTTPException(status_code=503, detail="Database not available")
                
                # Get SOL balance
                sol_balance_data = await self.db.get_paper_summary_value('paper_sol_balance')
                sol_balance = 0.0
                
                if sol_balance_data and sol_balance_data.get('value_float') is not None:
                    sol_balance = sol_balance_data['value_float']
                
                # Estimate USD value (rough conversion)
                usd_equivalent = sol_balance * 150  # Approximate SOL/USD rate
                
                return {
                    "sol_balance": sol_balance,
                    "usd_equivalent": usd_equivalent,
                    "last_updated": datetime.now(timezone.utc).isoformat()
                }
                
            except Exception as e:
                logger.error(f"Error fetching paper balance: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/paper/positions")
        async def get_paper_positions():
            """Get current paper trading positions"""
            try:
                if not self.db:
                    raise HTTPException(status_code=503, detail="Database not available")
                
                positions = await self.db.get_all_paper_positions()
                position_list = []
                
                for position in positions:
                    # Get token info for symbol
                    token_info = await self.db.get_token_by_mint(position.mint)
                    symbol = token_info.symbol if token_info else position.mint[:8]
                    
                    # Calculate current value and P&L
                    current_price_usd = token_info.price if token_info else position.average_price_usd
                    current_value = position.quantity * current_price_usd
                    unrealized_pnl = current_value - position.total_cost_usd
                    unrealized_pnl_pct = (unrealized_pnl / position.total_cost_usd * 100) if position.total_cost_usd > 0 else 0
                    
                    position_data = {
                        "mint": position.mint,
                        "symbol": symbol,
                        "quantity": position.quantity,
                        "average_price_usd": position.average_price_usd,
                        "total_cost_usd": position.total_cost_usd,
                        "current_price_usd": current_price_usd,
                        "current_value": current_value,
                        "unrealized_pnl": unrealized_pnl,
                        "unrealized_pnl_pct": unrealized_pnl_pct,
                        "last_updated": position.last_updated.isoformat() if position.last_updated else None
                    }
                    position_list.append(position_data)
                
                return {"positions": position_list, "count": len(position_list)}
                
            except Exception as e:
                logger.error(f"Error fetching paper positions: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/api/stats")
        async def get_platform_stats():
            """Get platform statistics"""
            try:
                if not self.db:
                    raise HTTPException(status_code=503, detail="Database not available")
                
                # Get basic statistics
                total_tokens = await self.db.count_tokens() if hasattr(self.db, 'count_tokens') else 0
                active_tokens = len(await self.db.get_top_tokens_for_trading(limit=100))
                
                # Get paper trading stats
                positions = await self.db.get_all_paper_positions()
                total_positions = len(positions)
                total_position_value = sum(pos.total_cost_usd for pos in positions)
                
                stats = {
                    "tokens": {
                        "total": total_tokens,
                        "active": active_tokens,
                        "monitoring": active_tokens
                    },
                    "paper_trading": {
                        "positions": total_positions,
                        "total_value_usd": total_position_value
                    },
                    "system": {
                        "uptime": "Running",
                        "last_update": datetime.now(timezone.utc).isoformat()
                    }
                }
                
                return stats
                
            except Exception as e:
                logger.error(f"Error fetching platform stats: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

# Create the web application instance
web_app = SupertradeXWebApp()
app = web_app.app

def run_server(host: str = "127.0.0.1", port: int = 8000):
    """Run the web server"""
    logger.info(f"Starting SupertradeX Dashboard on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")

if __name__ == "__main__":
    run_server()
