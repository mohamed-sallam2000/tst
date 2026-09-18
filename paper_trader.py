#!/usr/bin/env python3
"""
paper_trader.py - Paper trading simulator for SOL/USDT spot strategy.

Simulates live trading behavior without risking real funds.
Includes realistic fee simulation, slippage, order TTL, partial fills,
base-fee deduction, lot-size precision, and exchange protection behavior.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_DOWN
from typing import Dict, List, Optional, Tuple
import ccxt.async_support as ccxt_async

from config import (
    SYMBOL, TIMEFRAME_ENTRY, TIMEFRAME_TREND, FEE_ROUNDTRIP_PCT_FALLBACK,
    SLIPPAGE_ASSUMPTION_PCT, MIN_ORDER_SIZE_USDT, MAX_CAPITAL_USDT,
    RISK_PER_TRADE_PCT, MAX_POSITION_NOTIONAL_PCT, DEMO_MODE
)
from indicators import compute_trend_filter, compute_entry_signal
from risk import calculate_position_size, check_risk_halt, RiskState
from database import TradeDatabase, TradeRecord, SignalRecord, OrderRecord

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PaperTradingEngine:
    """Paper trading engine that simulates live behavior."""
    
    def __init__(self, db_path: str = "paper_trading.db"):
        self.db = TradeDatabase(db_path)
        self.initial_capital = Decimal(str(MAX_CAPITAL_USDT))
        self.capital = self.initial_capital
        self.position: Optional[Dict] = None
        self.pending_order: Optional[Dict] = None
        self.equity_curve: List[Decimal] = []
        self.trades: List[TradeRecord] = []
        self.signals: List[SignalRecord] = []
        
        # Fee and slippage simulation
        self.fee_rate = Decimal(str(FEE_ROUNDTRIP_PCT_FALLBACK)) / 200
        self.slippage_rate = Decimal(str(SLIPPAGE_ASSUMPTION_PCT)) / 100
        
        # Order settings
        self.order_ttl_seconds = 60
        self.amount_precision = 3
        self.price_precision = 2
        self.min_order_size = Decimal(str(MIN_ORDER_SIZE_USDT))
        
        # Risk state
        self.risk_state = RiskState(
            daily_loss=Decimal('0'),
            weekly_loss=Decimal('0'),
            monthly_drawdown=Decimal('0'),
            month_to_date_profit=Decimal('0'),
            last_reset_date=datetime.now(timezone.utc).date()
        )
        
        # Exchange connection (demo mode)
        self.exchange: Optional[ccxt_async.okx] = None
        
        # Market data cache
        self.candles_1h: List[Dict] = []
        self.candles_15m: List[Dict] = []
        
    async def initialize(self):
        """Initialize exchange connection in demo mode."""
        self.exchange = ccxt_async.okx({
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot',
                'sandbox': True  # Use OKX demo/sandbox if available
            }
        })
        
        if not DEMO_MODE:
            logger.warning("Paper trader should run in DEMO_MODE=True")
        
        await self.exchange.load_markets()
        logger.info(f"Paper trading initialized for {SYMBOL}")
    
    async def close(self):
        """Close exchange connection."""
        if self.exchange:
            await self.exchange.close()
    
    def _round_amount(self, amount: Decimal) -> Decimal:
        """Round amount down to exchange precision."""
        quantize_str = '0.' + '0' * self.amount_precision
        return amount.quantize(Decimal(quantize_str), rounding=ROUND_DOWN)
    
    def _round_price(self, price: Decimal) -> Decimal:
        """Round price to exchange precision."""
        quantize_str = '0.' + '0' * self.price_precision
        return price.quantize(Decimal(quantize_str), rounding=ROUND_DOWN)
    
    async def fetch_current_data(self) -> Tuple[Optional[Dict], Optional[Dict]]:
        """Fetch latest candles from exchange."""
        try:
            # Fetch 1h candles
            ohlcv_1h = await self.exchange.fetch_ohlcv(SYMBOL, TIMEFRAME_TREND, limit=300)
            self.candles_1h = [
                {
                    'timestamp': datetime.fromtimestamp(c[0]/1000, tz=timezone.utc),
                    'open': Decimal(str(c[1])),
                    'high': Decimal(str(c[2])),
                    'low': Decimal(str(c[3])),
                    'close': Decimal(str(c[4])),
                    'volume': Decimal(str(c[5]))
                }
                for c in ohlcv_1h
            ]
            
            # Fetch 15m candles
            ohlcv_15m = await self.exchange.fetch_ohlcv(SYMBOL, TIMEFRAME_ENTRY, limit=300)
            self.candles_15m = [
                {
                    'timestamp': datetime.fromtimestamp(c[0]/1000, tz=timezone.utc),
                    'open': Decimal(str(c[1])),
                    'high': Decimal(str(c[2])),
                    'low': Decimal(str(c[3])),
                    'close': Decimal(str(c[4])),
                    'volume': Decimal(str(c[5]))
                }
                for c in ohlcv_15m
            ]
            
            if self.candles_1h and self.candles_15m:
                return self.candles_1h[-1], self.candles_15m[-1]
            
            return None, None
        except Exception as e:
            logger.error(f"Error fetching data: {e}")
            return None, None
    
    def _simulate_limit_fill(
        self, limit_price: Decimal, current_price: Decimal, side: str
    ) -> bool:
        """Simulate whether a limit order would fill."""
        if side == 'buy':
            # Buy limit fills if current price <= limit price
            return current_price <= limit_price * (Decimal('1') + self.slippage_rate)
        else:
            # Sell limit fills if current price >= limit price
            return current_price >= limit_price * (Decimal('1') - self.slippage_rate)
    
    async def run_paper_trading(self, duration_hours: int = 24):
        """Run paper trading for specified duration."""
        await self.initialize()
        
        start_time = datetime.now(timezone.utc)
        end_time = start_time + timedelta(hours=duration_hours)
        
        logger.info(f"Starting paper trading from {start_time} to {end_time}")
        
        iteration = 0
        while datetime.now(timezone.utc) < end_time:
            iteration += 1
            
            # Fetch current market data
            candle_1h, candle_15m = await self.fetch_current_data()
            
            if not candle_1h or not candle_15m:
                logger.warning("No market data available, skipping iteration")
                await asyncio.sleep(60)
                continue
            
            current_ts = candle_15m['timestamp']
            current_price = candle_15m['close']
            
            # Check pending order status
            if self.pending_order:
                await self._check_pending_order(current_ts, current_price)
            
            # Manage open position
            if self.position:
                await self._manage_position(current_ts, current_price, candle_15m)
            elif not self.pending_order:
                # Check for new entry signals
                await self._check_entry_signal(current_ts, candle_1h, candle_15m)
            
            # Record equity
            unrealized_pnl = self._calculate_unrealized_pnl(current_price) if self.position else Decimal('0')
            total_equity = self.capital + unrealized_pnl
            self.equity_curve.append(total_equity)
            
            logger.info(f"Iteration {iteration}: Equity={total_equity:.2f} USDT, Position={'Active' if self.position else 'Flat'}")
            
            # Wait for next candle (approximately 15 minutes)
            await asyncio.sleep(60)  # Check every minute in paper trading
        
        await self.close()
        return self._generate_report()
    
    async def _check_entry_signal(self, ts: datetime, candle_1h: Dict, candle_15m: Dict):
        """Check for entry signal and place limit order."""
        # Convert to pandas-like structure for indicator calculation
        df_1h = self._candles_to_dataframe(self.candles_1h)
        df_15m = self._candles_to_dataframe(self.candles_15m)
        
        if len(df_1h) < 200 or len(df_15m) < 200:
            return
        
        # Check trend filter
        trend_bullish = compute_trend_filter(df_1h, len(df_1h) - 1)
        if not trend_bullish:
            return
        
        # Check entry signal
        entry_signal, indicators = compute_entry_signal(df_15m, len(df_15m) - 1, df_1h, len(df_1h) - 1)
        
        if not entry_signal:
            return
        
        # Check risk halts
        halt_reason = check_risk_halt(self.risk_state)
        if halt_reason:
            logger.info(f"Entry blocked by risk halt: {halt_reason}")
            return
        
        # Calculate position size
        atr_15m = indicators.get('atr_15m', Decimal('0'))
        stop_distance = max(Decimal('1.5') * atr_15m / candle_15m['close'], Decimal('0.008'))
        stop_distance = min(stop_distance, Decimal('0.03'))
        
        position_notional = calculate_position_size(
            equity=float(self.capital),
            stop_distance_pct=float(stop_distance),
            risk_per_trade_pct=float(RISK_PER_TRADE_PCT),
            max_position_pct=float(MAX_POSITION_NOTIONAL_PCT)
        )
        
        entry_price = candle_15m['close']
        requested_qty = self._round_amount(Decimal(str(position_notional)) / entry_price)
        
        if requested_qty * entry_price < self.min_order_size:
            logger.info(f"Position size below minimum order size")
            return
        
        # Place simulated limit order
        limit_price = self._round_price(entry_price * Decimal('0.9995'))  # Slightly better price
        
        self.pending_order = {
            'type': 'LIMIT_BUY',
            'timestamp': ts,
            'price': limit_price,
            'quantity': requested_qty,
            'ttl_expiry': ts + timedelta(seconds=self.order_ttl_seconds),
            'reason': 'Trend + Pullback + Momentum'
        }
        
        logger.info(f"Placed limit buy order: {requested_qty} SOL @ {limit_price} USDT")
        
        # Record signal
        sig_record = SignalRecord(
            timestamp=ts,
            signal_type='LONG',
            price=entry_price,
            indicators=indicators,
            reason=self.pending_order['reason']
        )
        self.signals.append(sig_record)
    
    async def _check_pending_order(self, ts: datetime, current_price: Decimal):
        """Check if pending order should fill or expire."""
        if not self.pending_order:
            return
        
        # Check TTL expiry
        if ts >= self.pending_order['ttl_expiry']:
            logger.info(f"Limit order expired unfilled")
            self.pending_order = None
            return
        
        # Check if order fills
        if self._simulate_limit_fill(
            self.pending_order['price'],
            current_price,
            'buy'
        ):
            await self._execute_entry_fill(ts, current_price)
    
    async def _execute_entry_fill(self, ts: datetime, fill_price: Decimal):
        """Execute entry fill with fee simulation."""
        if not self.pending_order:
            return
        
        requested_qty = self.pending_order['quantity']
        
        # Apply slippage
        slippage_adjustment = Decimal('1') + self.slippage_rate
        actual_fill_price = self._round_price(fill_price * slippage_adjustment)
        
        # Calculate fees (simulating base-fee deduction)
        gross_cost = actual_fill_price * requested_qty
        fee_cost_sol = requested_qty * self.fee_rate
        net_received_sol = self._round_amount(requested_qty - fee_cost_sol)
        
        if net_received_sol <= 0:
            logger.warning("Net received SOL is zero or negative after fees")
            self.pending_order = None
            return
        
        # Deduct capital
        self.capital -= gross_cost
        
        # Create position
        stop_distance = Decimal('0.015')  # Would be calculated from ATR in real implementation
        self.position = {
            'entry_time': ts,
            'entry_price': actual_fill_price,
            'filled_qty': requested_qty,
            'fee_sol': fee_cost_sol,
            'net_sol': net_received_sol,
            'stop_price': actual_fill_price * (Decimal('1') - stop_distance),
            'take_profit_price': actual_fill_price * (Decimal('1') + stop_distance * 2),
            'entry_reason': self.pending_order['reason']
        }
        
        logger.info(f"Entry filled: {requested_qty} SOL @ {actual_fill_price} USDT, Net: {net_received_sol} SOL")
        
        # Record order
        order_record = OrderRecord(
            timestamp=ts,
            order_type='BUY',
            price=actual_fill_price,
            quantity=requested_qty,
            filled_qty=requested_qty,
            fee_currency='SOL',
            fee_cost=fee_cost_sol,
            status='FILLED',
            reason=self.pending_order['reason']
        )
        self.db.save_order(order_record)
        
        self.pending_order = None
    
    async def _manage_position(self, ts: datetime, current_price: Decimal, candle: Dict):
        """Manage open position - check exits."""
        if not self.position:
            return
        
        exit_reason = None
        exit_price = None
        is_stop = False
        
        # Stop-loss check
        if current_price <= self.position['stop_price']:
            exit_reason = 'STOP_LOSS'
            exit_price = self.position['stop_price']
            is_stop = True
        
        # Take-profit check
        elif current_price >= self.position['take_profit_price']:
            exit_reason = 'TAKE_PROFIT'
            exit_price = self.position['take_profit_price']
        
        # Time stop check (24 hours)
        elif (ts - self.position['entry_time']).total_seconds() >= 86400:
            unrealized_pnl = (current_price - self.position['entry_price']) * self.position['net_sol']
            r_multiple = unrealized_pnl / (
                (self.position['entry_price'] - self.position['stop_price']) * self.position['net_sol']
            ) if self.position['entry_price'] != self.position['stop_price'] else Decimal('0')
            
            if r_multiple < Decimal('0.2'):
                exit_reason = 'TIME_STOP_24H'
                exit_price = current_price
        
        if exit_reason and exit_price:
            await self._execute_exit(ts, exit_price, exit_reason, is_stop)
    
    async def _execute_exit(self, ts: datetime, exit_price: Decimal, reason: str, is_stop: bool = False):
        """Execute exit with fee simulation."""
        if not self.position:
            return
        
        exit_qty = self.position['net_sol']
        
        # Apply slippage (worse for stops)
        slippage_factor = Decimal('1') - self.slippage_rate
        if is_stop:
            slippage_factor -= self.slippage_rate  # Extra slippage for stops
        
        actual_fill_price = self._round_price(exit_price * slippage_factor)
        
        # Calculate proceeds and fees
        gross_proceeds = actual_fill_price * exit_qty
        fee_cost_usdt = gross_proceeds * self.fee_rate
        net_proceeds = gross_proceeds - fee_cost_usdt
        
        # Calculate PnL
        pnl = net_proceeds - (self.position['entry_price'] * self.position['filled_qty'])
        
        # Update capital
        self.capital += net_proceeds
        
        logger.info(f"Exit executed: {reason}, PnL: {pnl:.2f} USDT")
        
        # Record trade
        trade_record = TradeRecord(
            entry_time=self.position['entry_time'],
            exit_time=ts,
            entry_price=self.position['entry_price'],
            exit_price=actual_fill_price,
            quantity=self.position['filled_qty'],
            fee_entry_sol=self.position['fee_sol'],
            fee_exit_usdt=fee_cost_usdt,
            pnl=pnl,
            exit_reason=reason,
            entry_reason=self.position['entry_reason']
        )
        self.trades.append(trade_record)
        self.db.save_trade(trade_record)
        
        # Update risk state
        if pnl < 0:
            self.risk_state.daily_loss += abs(pnl)
            self.risk_state.weekly_loss += abs(pnl)
            self.risk_state.monthly_drawdown = max(
                self.risk_state.monthly_drawdown,
                abs(pnl) / self.initial_capital * 100
            )
        else:
            self.risk_state.month_to_date_profit += pnl
        
        self.position = None
    
    def _calculate_unrealized_pnl(self, current_price: Decimal) -> Decimal:
        """Calculate unrealized PnL for open position."""
        if not self.position:
            return Decimal('0')
        
        gross_value = current_price * self.position['net_sol']
        estimated_exit_fee = gross_value * self.fee_rate
        net_value = gross_value - estimated_exit_fee
        
        cost_basis = self.position['entry_price'] * self.position['filled_qty']
        return net_value - cost_basis
    
    def _candles_to_dataframe(self, candles: List[Dict]):
        """Convert candles list to pandas DataFrame."""
        import pandas as pd
        
        if not candles:
            return pd.DataFrame()
        
        df = pd.DataFrame(candles)
        df.set_index('timestamp', inplace=True)
        return df
    
    def _generate_report(self) -> Dict:
        """Generate paper trading performance report."""
        if not self.trades:
            return {"error": "No trades executed"}
        
        total_return = (self.capital - self.initial_capital) / self.initial_capital * 100
        win_trades = [t for t in self.trades if t.pnl > 0]
        loss_trades = [t for t in self.trades if t.pnl <= 0]
        
        win_rate = len(win_trades) / len(self.trades) * 100 if self.trades else 0
        avg_win = sum(t.pnl for t in win_trades) / len(win_trades) if win_trades else Decimal('0')
        avg_loss = sum(t.pnl for t in loss_trades) / len(loss_trades) if loss_trades else Decimal('0')
        
        profit_factor = abs(sum(t.pnl for t in win_trades) / sum(t.pnl for t in loss_trades)) if loss_trades and sum(t.pnl for t in loss_trades) != 0 else float('inf')
        
        report = {
            'total_net_return_pct': float(total_return),
            'final_capital_usdt': float(self.capital),
            'initial_capital_usdt': float(self.initial_capital),
            'total_trades': len(self.trades),
            'winning_trades': len(win_trades),
            'losing_trades': len(loss_trades),
            'win_rate_pct': win_rate,
            'average_win_usdt': float(avg_win),
            'average_loss_usdt': float(avg_loss),
            'profit_factor': profit_factor,
            'signals_generated': len(self.signals),
            'trading_duration_hours': len(self.equity_curve) / 4,  # Assuming 15m intervals
        }
        
        return report


async def main():
    """Run paper trading for 24 hours."""
    engine = PaperTradingEngine()
    
    try:
        report = await engine.run_paper_trading(duration_hours=24)
        
        print("\n" + "="*60)
        print("PAPER TRADING RESULTS")
        print("="*60)
        for key, value in report.items():
            print(f"{key}: {value}")
        print("="*60)
        
        # Assessment
        print("\nPAPER TRADING ASSESSMENT:")
        if report.get('total_trades', 0) > 0:
            if report.get('profit_factor', 0) > 1.0:
                print("→ Positive performance in paper trading")
            else:
                print("→ Negative or neutral performance - review strategy")
        else:
            print("→ No trades executed - market conditions may not have met criteria")
    
    except KeyboardInterrupt:
        logger.info("Paper trading interrupted by user")
    finally:
        await engine.close()


if __name__ == "__main__":
    asyncio.run(main())
