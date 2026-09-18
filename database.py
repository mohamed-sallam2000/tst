#!/usr/bin/env python3
"""
database.py - SQLite persistence layer for OKX SOL/USDT trading bot.

Handles all database operations including orders, positions, fills, fees,
risk events, and state recovery.
"""

import sqlite3
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict
from pathlib import Path

from config import DB_PATH

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class TradeRecord:
    """Trade record with entry and exit details."""
    entry_time: datetime
    exit_time: datetime
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    fee_entry_sol: Decimal
    fee_exit_usdt: Decimal
    pnl: Decimal
    exit_reason: str
    entry_reason: str
    
    def to_dict(self) -> Dict:
        return {
            'entry_time': self.entry_time.isoformat(),
            'exit_time': self.exit_time.isoformat(),
            'entry_price': str(self.entry_price),
            'exit_price': str(self.exit_price),
            'quantity': str(self.quantity),
            'fee_entry_sol': str(self.fee_entry_sol),
            'fee_exit_usdt': str(self.fee_exit_usdt),
            'pnl': str(self.pnl),
            'exit_reason': self.exit_reason,
            'entry_reason': self.entry_reason
        }


@dataclass
class SignalRecord:
    """Trading signal record."""
    timestamp: datetime
    signal_type: str  # 'LONG', 'SHORT' (though we only do LONG)
    price: Decimal
    indicators: Dict[str, Any]
    reason: str
    
    def to_dict(self) -> Dict:
        return {
            'timestamp': self.timestamp.isoformat(),
            'signal_type': self.signal_type,
            'price': str(self.price),
            'indicators': json.dumps(self.indicators),
            'reason': self.reason
        }


@dataclass
class OrderRecord:
    """Order record with fill details."""
    timestamp: datetime
    order_type: str  # 'BUY', 'SELL'
    price: Decimal
    quantity: Decimal
    filled_qty: Decimal
    fee_currency: str
    fee_cost: Decimal
    status: str  # 'PENDING', 'FILLED', 'CANCELLED', 'REJECTED'
    reason: str
    order_id: Optional[str] = None
    client_order_id: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            'timestamp': self.timestamp.isoformat(),
            'order_type': self.order_type,
            'price': str(self.price),
            'quantity': str(self.quantity),
            'filled_qty': str(self.filled_qty),
            'fee_currency': self.fee_currency,
            'fee_cost': str(self.fee_cost),
            'status': self.status,
            'reason': self.reason,
            'order_id': self.order_id,
            'client_order_id': self.client_order_id
        }


@dataclass
class RiskEventRecord:
    """Risk event record (halts, preservation mode, etc.)."""
    timestamp: datetime
    event_type: str  # 'DAILY_HALT', 'WEEKLY_HALT', 'MONTHLY_HALT', 'EQUITY_HALT', 'PRESERVATION_MODE'
    details: Dict[str, Any]
    resolved: bool = False
    
    def to_dict(self) -> Dict:
        return {
            'timestamp': self.timestamp.isoformat(),
            'event_type': self.event_type,
            'details': json.dumps(self.details),
            'resolved': self.resolved
        }


class TradeDatabase:
    """SQLite database handler for trading bot persistence."""
    
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = Path(db_path)
        self._init_database()
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection with row factory."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn
    
    def _init_database(self):
        """Initialize database schema."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Trades table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_time TEXT NOT NULL,
                exit_time TEXT NOT NULL,
                entry_price TEXT NOT NULL,
                exit_price TEXT NOT NULL,
                quantity TEXT NOT NULL,
                fee_entry_sol TEXT NOT NULL,
                fee_exit_usdt TEXT NOT NULL,
                pnl TEXT NOT NULL,
                exit_reason TEXT NOT NULL,
                entry_reason TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Signals table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                price TEXT NOT NULL,
                indicators TEXT,
                reason TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Orders table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                order_type TEXT NOT NULL,
                price TEXT NOT NULL,
                quantity TEXT NOT NULL,
                filled_qty TEXT NOT NULL,
                fee_currency TEXT NOT NULL,
                fee_cost TEXT NOT NULL,
                status TEXT NOT NULL,
                reason TEXT,
                order_id TEXT,
                client_order_id TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Risk events table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS risk_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                details TEXT,
                resolved INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Bot state table (singleton)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bot_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                mode TEXT NOT NULL,  -- 'demo' or 'live'
                state TEXT NOT NULL,  -- 'FLAT', 'ENTRY_PENDING', etc.
                position_qty TEXT,
                entry_price TEXT,
                stop_price TEXT,
                take_profit_price TEXT,
                net_received_sol TEXT,
                sellable_sol TEXT,
                dust_amount TEXT,
                last_update TEXT NOT NULL,
                daily_loss TEXT DEFAULT '0',
                weekly_loss TEXT DEFAULT '0',
                monthly_drawdown TEXT DEFAULT '0',
                month_to_date_profit TEXT DEFAULT '0',
                preservation_mode INTEGER DEFAULT 0,
                halt_flags TEXT  -- JSON of active halts
            )
        ''')
        
        # Position tracking table (for reconciliation)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS position_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,  -- 'ENTRY', 'EXIT', 'FEE', 'RECONCILIATION'
                sol_change TEXT NOT NULL,
                usdt_change TEXT,
                balance_after TEXT NOT NULL,
                reference_id TEXT,  -- order_id or trade_id
                notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Performance metrics table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS performance_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL UNIQUE,
                starting_equity TEXT,
                ending_equity TEXT,
                realized_pnl TEXT,
                unrealized_pnl TEXT,
                num_trades INTEGER DEFAULT 0,
                win_rate REAL,
                max_drawdown TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info(f"Database initialized at {self.db_path}")
    
    def save_trade(self, trade: TradeRecord):
        """Save a completed trade to database."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO trades (
                entry_time, exit_time, entry_price, exit_price, quantity,
                fee_entry_sol, fee_exit_usdt, pnl, exit_reason, entry_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            trade.entry_time.isoformat(),
            trade.exit_time.isoformat(),
            str(trade.entry_price),
            str(trade.exit_price),
            str(trade.quantity),
            str(trade.fee_entry_sol),
            str(trade.fee_exit_usdt),
            str(trade.pnl),
            trade.exit_reason,
            trade.entry_reason
        ))
        
        conn.commit()
        conn.close()
        logger.info(f"Trade saved: {trade.exit_reason}, PnL={trade.pnl}")
    
    def save_signal(self, signal: SignalRecord):
        """Save a trading signal to database."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO signals (timestamp, signal_type, price, indicators, reason)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            signal.timestamp.isoformat(),
            signal.signal_type,
            str(signal.price),
            json.dumps(signal.indicators),
            signal.reason
        ))
        
        conn.commit()
        conn.close()
    
    def save_order(self, order: OrderRecord):
        """Save an order record to database."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO orders (
                timestamp, order_type, price, quantity, filled_qty,
                fee_currency, fee_cost, status, reason, order_id, client_order_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            order.timestamp.isoformat(),
            order.order_type,
            str(order.price),
            str(order.quantity),
            str(order.filled_qty),
            order.fee_currency,
            str(order.fee_cost),
            order.status,
            order.reason,
            order.order_id,
            order.client_order_id
        ))
        
        conn.commit()
        conn.close()
    
    def save_risk_event(self, event: RiskEventRecord):
        """Save a risk event to database."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO risk_events (timestamp, event_type, details, resolved)
            VALUES (?, ?, ?, ?)
        ''', (
            event.timestamp.isoformat(),
            event.event_type,
            json.dumps(event.details),
            1 if event.resolved else 0
        ))
        
        conn.commit()
        conn.close()
        logger.warning(f"Risk event saved: {event.event_type}")
    
    def save_bot_state(
        self,
        mode: str,
        state: str,
        position_qty: Optional[Decimal] = None,
        entry_price: Optional[Decimal] = None,
        stop_price: Optional[Decimal] = None,
        take_profit_price: Optional[Decimal] = None,
        net_received_sol: Optional[Decimal] = None,
        sellable_sol: Optional[Decimal] = None,
        dust_amount: Optional[Decimal] = None,
        daily_loss: Decimal = Decimal('0'),
        weekly_loss: Decimal = Decimal('0'),
        monthly_drawdown: Decimal = Decimal('0'),
        month_to_date_profit: Decimal = Decimal('0'),
        preservation_mode: bool = False,
        halt_flags: Optional[Dict] = None
    ):
        """Save current bot state (singleton record)."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO bot_state (
                id, mode, state, position_qty, entry_price, stop_price,
                take_profit_price, net_received_sol, sellable_sol, dust_amount,
                last_update, daily_loss, weekly_loss, monthly_drawdown,
                month_to_date_profit, preservation_mode, halt_flags
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            mode,
            state,
            str(position_qty) if position_qty else None,
            str(entry_price) if entry_price else None,
            str(stop_price) if stop_price else None,
            str(take_profit_price) if take_profit_price else None,
            str(net_received_sol) if net_received_sol else None,
            str(sellable_sol) if sellable_sol else None,
            str(dust_amount) if dust_amount else None,
            datetime.now(timezone.utc).isoformat(),
            str(daily_loss),
            str(weekly_loss),
            str(monthly_drawdown),
            str(month_to_date_profit),
            1 if preservation_mode else 0,
            json.dumps(halt_flags) if halt_flags else None
        ))
        
        conn.commit()
        conn.close()
    
    def load_bot_state(self) -> Optional[Dict]:
        """Load current bot state from database."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM bot_state WHERE id = 1')
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        state = dict(row)
        
        # Convert string decimals back to Decimal
        decimal_fields = [
            'position_qty', 'entry_price', 'stop_price', 'take_profit_price',
            'net_received_sol', 'sellable_sol', 'dust_amount',
            'daily_loss', 'weekly_loss', 'monthly_drawdown', 'month_to_date_profit'
        ]
        
        for field in decimal_fields:
            if state.get(field):
                state[field] = Decimal(state[field])
        
        # Parse JSON fields
        if state.get('halt_flags'):
            state['halt_flags'] = json.loads(state['halt_flags'])
        
        state['preservation_mode'] = bool(state.get('preservation_mode', 0))
        
        return state
    
    def get_recent_trades(self, limit: int = 10) -> List[TradeRecord]:
        """Get recent trades from database."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM trades ORDER BY exit_time DESC LIMIT ?
        ''', (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        trades = []
        for row in rows:
            trade = TradeRecord(
                entry_time=datetime.fromisoformat(row['entry_time']),
                exit_time=datetime.fromisoformat(row['exit_time']),
                entry_price=Decimal(row['entry_price']),
                exit_price=Decimal(row['exit_price']),
                quantity=Decimal(row['quantity']),
                fee_entry_sol=Decimal(row['fee_entry_sol']),
                fee_exit_usdt=Decimal(row['fee_exit_usdt']),
                pnl=Decimal(row['pnl']),
                exit_reason=row['exit_reason'],
                entry_reason=row['entry_reason']
            )
            trades.append(trade)
        
        return trades
    
    def get_total_realized_pnl(self) -> Decimal:
        """Get total realized PnL from all trades."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT SUM(pnl) as total_pnl FROM trades')
        row = cursor.fetchone()
        conn.close()
        
        if row and row['total_pnl']:
            return Decimal(row['total_pnl'])
        
        return Decimal('0')
    
    def log_position_ledger_entry(
        self,
        event_type: str,
        sol_change: Decimal,
        balance_after: Decimal,
        usdt_change: Optional[Decimal] = None,
        reference_id: Optional[str] = None,
        notes: Optional[str] = None
    ):
        """Log an entry to the position ledger for reconciliation."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO position_ledger (
                timestamp, event_type, sol_change, usdt_change,
                balance_after, reference_id, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            datetime.now(timezone.utc).isoformat(),
            event_type,
            str(sol_change),
            str(usdt_change) if usdt_change else None,
            str(balance_after),
            reference_id,
            notes
        ))
        
        conn.commit()
        conn.close()
    
    def get_position_ledger(self, limit: int = 50) -> List[Dict]:
        """Get recent position ledger entries."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM position_ledger ORDER BY timestamp DESC LIMIT ?
        ''', (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def save_daily_performance(
        self,
        date_str: str,
        starting_equity: Decimal,
        ending_equity: Decimal,
        realized_pnl: Decimal,
        num_trades: int,
        max_drawdown: Decimal
    ):
        """Save daily performance metrics."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        win_rate = 0.0
        if num_trades > 0:
            cursor.execute('''
                SELECT COUNT(*) as wins FROM trades 
                WHERE DATE(exit_time) = ? AND pnl > 0
            ''', (date_str,))
            wins = cursor.fetchone()['wins']
            win_rate = wins / num_trades if num_trades > 0 else 0.0
        
        cursor.execute('''
            INSERT OR REPLACE INTO performance_metrics (
                date, starting_equity, ending_equity, realized_pnl,
                num_trades, win_rate, max_drawdown, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            date_str,
            str(starting_equity),
            str(ending_equity),
            str(realized_pnl),
            num_trades,
            win_rate,
            str(max_drawdown),
            datetime.now(timezone.utc).isoformat()
        ))
        
        conn.commit()
        conn.close()
    
    def close(self):
        """Close database connections (cleanup)."""
        # In a more complex setup, we'd manage connection pools here
        pass
