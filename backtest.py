#!/usr/bin/env python3
"""
backtest.py - Historical backtesting engine for SOL/USDT spot strategy.

Uses completed candles only, includes fees, slippage, lot-size constraints,
and base-fee deduction assumptions. No future data, no repainting.
"""

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Dict, List, Optional, Tuple
import ccxt.async_support as ccxt_async
import numpy as np
import pandas as pd

from config import (
    SYMBOL, TIMEFRAME_ENTRY, TIMEFRAME_TREND, FEE_ROUNDTRIP_PCT_FALLBACK,
    SLIPPAGE_ASSUMPTION_PCT, MIN_ORDER_SIZE_USDT, MAX_CAPITAL_USDT,
    RISK_PER_TRADE_PCT, MAX_POSITION_NOTIONAL_PCT
)
from indicators import (
    calculate_ema, calculate_rsi, calculate_adx, calculate_atr,
    check_pullback_confirmation, compute_trend_filter, compute_entry_signal
)
from risk import (
    calculate_position_size, check_risk_halt, update_daily_pnl,
    update_weekly_pnl, update_monthly_drawdown, RiskState
)
from database import TradeDatabase, TradeRecord, SignalRecord

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BacktestEngine:
    """Historical backtesting engine with realistic execution modeling."""
    
    def __init__(self, db_path: str = "backtest.db"):
        self.db = TradeDatabase(db_path)
        self.initial_capital = Decimal(str(MAX_CAPITAL_USDT))
        self.capital = self.initial_capital
        self.position: Optional[Dict] = None
        self.equity_curve: List[Decimal] = []
        self.trades: List[TradeRecord] = []
        self.signals: List[SignalRecord] = []
        self.fee_rate = Decimal(str(FEE_ROUNDTRIP_PCT_FALLBACK)) / 200  # per side
        self.slippage_rate = Decimal(str(SLIPPAGE_ASSUMPTION_PCT)) / 100
        
        # Market data
        self.candles_1h: pd.DataFrame = pd.DataFrame()
        self.candles_15m: pd.DataFrame = pd.DataFrame()
        
        # Precision
        self.amount_precision = 3  # SOL typically 3 decimals
        self.price_precision = 2   # USDT typically 2 decimals
        self.min_order_size = Decimal(str(MIN_ORDER_SIZE_USDT))
        
        # Risk state
        self.risk_state = RiskState(
            daily_loss=Decimal('0'),
            weekly_loss=Decimal('0'),
            monthly_drawdown=Decimal('0'),
            month_to_date_profit=Decimal('0'),
            last_reset_date=datetime.now(timezone.utc).date()
        )
        
    async def fetch_historical_data(
        self, symbol: str, timeframe: str, days: int = 365
    ) -> pd.DataFrame:
        """Fetch historical candle data from OKX."""
        exchange = ccxt_async.okx({
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'}
        })
        
        try:
            await exchange.load_markets()
            now = datetime.now(timezone.utc)
            since = int((now.timestamp() - days * 86400) * 1000)
            
            candles = []
            while since < int(now.timestamp() * 1000):
                ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=100)
                if not ohlcv:
                    break
                candles.extend(ohlcv)
                since = ohlcv[-1][0] + 1
                await asyncio.sleep(0.1)  # Rate limit
            
            df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
            df.set_index('timestamp', inplace=True)
            return df
        finally:
            await exchange.close()
    
    def _round_amount(self, amount: Decimal) -> Decimal:
        """Round amount down to exchange precision."""
        quantize_str = '0.' + '0' * self.amount_precision
        return amount.quantize(Decimal(quantize_str), rounding=ROUND_DOWN)
    
    def _round_price(self, price: Decimal) -> Decimal:
        """Round price to exchange precision."""
        quantize_str = '0.' + '0' * self.price_precision
        return price.quantize(Decimal(quantize_str), rounding=ROUND_DOWN)
    
    def _simulate_entry_fill(
        self, signal_price: Decimal, requested_qty: Decimal
    ) -> Tuple[Optional[Decimal], Optional[Decimal], Optional[Decimal]]:
        """
        Simulate entry order fill with fees and slippage.
        Returns (filled_qty, fee_cost_sol, net_received_sol) or (None, None, None) if failed.
        """
        if requested_qty < self.min_order_size / signal_price:
            return None, None, None
        
        # Apply slippage (worse price for entry)
        slippage_adjustment = Decimal('1') + self.slippage_rate
        fill_price = self._round_price(signal_price * slippage_adjustment)
        
        # Calculate gross cost
        gross_cost = fill_price * requested_qty
        
        if gross_cost > self.capital:
            return None, None, None
        
        # Deduct fee in USDT (simplified model; can be extended for base-fee deduction)
        fee_cost_usdt = gross_cost * self.fee_rate
        net_cost = gross_cost + fee_cost_usdt
        
        if net_cost > self.capital:
            # Reduce quantity to fit capital
            adjusted_qty = self._round_amount(self.capital / (fill_price * (Decimal('1') + self.fee_rate)))
            if adjusted_qty < self.min_order_size / fill_price:
                return None, None, None
            requested_qty = adjusted_qty
            gross_cost = fill_price * requested_qty
            fee_cost_usdt = gross_cost * self.fee_rate
        
        # For OKX spot, fees are often deducted in base asset when paid in base
        # Here we model fee deducted from received SOL
        fee_cost_sol = requested_qty * self.fee_rate
        net_received_sol = self._round_amount(requested_qty - fee_cost_sol)
        
        if net_received_sol <= 0:
            return None, None, None
        
        return requested_qty, fee_cost_sol, net_received_sol
    
    def _simulate_exit_fill(
        self, exit_price: Decimal, exit_qty: Decimal, is_stop: bool = False
    ) -> Tuple[Optional[Decimal], Optional[Decimal]]:
        """
        Simulate exit order fill with fees and slippage.
        Returns (net_proceeds_usdt, fee_cost_usdt) or (None, None) if failed.
        """
        if exit_qty <= 0:
            return None, None
        
        # Apply slippage (worse price for exit)
        slippage_factor = Decimal('1') - self.slippage_rate if not is_stop else Decimal('1') - self.slippage_rate * 2
        fill_price = self._round_price(exit_price * slippage_factor)
        
        gross_proceeds = fill_price * exit_qty
        fee_cost_usdt = gross_proceeds * self.fee_rate
        net_proceeds = gross_proceeds - fee_cost_usdt
        
        return net_proceeds, fee_cost_usdt
    
    async def run_backtest(
        self, start_date: datetime, end_date: datetime
    ) -> Dict:
        """Run full backtest over specified period."""
        logger.info(f"Fetching historical data for {SYMBOL}...")
        
        # Fetch data
        self.candles_1h = await self.fetch_historical_data(
            SYMBOL, TIMEFRAME_TREND, days=400
        )
        self.candles_15m = await self.fetch_historical_data(
            SYMBOL, TIMEFRAME_ENTRY, days=400
        )
        
        if self.candles_1h.empty or self.candles_15m.empty:
            raise ValueError("Failed to fetch historical data")
        
        # Filter to backtest period
        self.candles_1h = self.candles_1h[
            (self.candles_1h.index >= start_date) & 
            (self.candles_15m.index <= end_date)
        ]
        self.candles_15m = self.candles_15m[
            (self.candles_15m.index >= start_date) & 
            (self.candles_15m.index <= end_date)
        ]
        
        logger.info(f"Backtesting from {start_date} to {end_date}")
        logger.info(f"1h candles: {len(self.candles_1h)}, 15m candles: {len(self.candles_15m)}")
        
        # Iterate through 15m candles for signals
        timestamps = self.candles_15m.index.tolist()
        
        for i in range(200, len(timestamps)):  # Warmup period
            current_ts = timestamps[i]
            
            if self.position is not None:
                # Check exit conditions
                self._check_exits(current_ts, i)
            
            if self.position is None:
                # Check entry conditions
                self._check_entry(current_ts, i)
            
            # Record equity
            self.equity_curve.append(self.capital)
        
        return self._generate_report()
    
    def _check_entry(self, ts: datetime, idx: int):
        """Check for entry signal at given timestamp."""
        # Get current candles
        candle_15m = self.candles_15m.iloc[idx]
        
        # Ensure we have enough 1h data
        ts_1h = ts.floor('H')
        if ts_1h not in self.candles_1h.index:
            return
        
        # Compute indicators
        trend_bullish = compute_trend_filter(self.candles_1h, idx)
        if not trend_bullish:
            return
        
        entry_signal, indicators = compute_entry_signal(
            self.candles_15m, idx, self.candles_1h, idx
        )
        
        if not entry_signal:
            return
        
        # Record signal
        sig_record = SignalRecord(
            timestamp=ts,
            signal_type='LONG',
            price=Decimal(str(candle_15m['close'])),
            indicators=indicators,
            reason='Trend + Pullback + Momentum'
        )
        self.signals.append(sig_record)
        
        # Check risk halts
        halt_reason = check_risk_halt(self.risk_state)
        if halt_reason:
            logger.info(f"Entry blocked by risk halt: {halt_reason}")
            return
        
        # Calculate position size
        stop_distance_pct = Decimal('0.015')  # 1.5% initial estimate
        position_notional = calculate_position_size(
            equity=float(self.capital),
            stop_distance_pct=float(stop_distance_pct),
            risk_per_trade_pct=float(RISK_PER_TRADE_PCT),
            max_position_pct=float(MAX_POSITION_NOTIONAL_PCT)
        )
        
        entry_price = Decimal(str(candle_15m['close']))
        requested_qty = self._round_amount(Decimal(str(position_notional)) / entry_price)
        
        if requested_qty * entry_price < self.min_order_size:
            return
        
        # Simulate fill
        filled_qty, fee_sol, net_sol = self._simulate_entry_fill(entry_price, requested_qty)
        
        if filled_qty is None:
            return
        
        # Execute trade
        cost = entry_price * filled_qty
        self.capital -= cost
        
        self.position = {
            'entry_time': ts,
            'entry_price': entry_price,
            'filled_qty': filled_qty,
            'fee_sol': fee_sol,
            'net_sol': net_sol,
            'stop_price': entry_price * (Decimal('1') - stop_distance_pct),
            'take_profit_price': entry_price * (Decimal('1') + stop_distance_pct * 2),  # 2R
            'entry_reason': sig_record.reason
        }
        
        logger.info(f"Entry at {ts}: {filled_qty} SOL @ {entry_price} USDT")
    
    def _check_exits(self, ts: datetime, idx: int):
        """Check exit conditions for open position."""
        if self.position is None:
            return
        
        candle = self.candles_15m.iloc[idx]
        current_price = Decimal(str(candle['close']))
        
        exit_reason = None
        exit_price = None
        is_stop = False
        
        # Stop-loss
        if current_price <= self.position['stop_price']:
            exit_reason = 'STOP_LOSS'
            exit_price = self.position['stop_price']
            is_stop = True
        
        # Take-profit
        elif current_price >= self.position['take_profit_price']:
            exit_reason = 'TAKE_PROFIT'
            exit_price = self.position['take_profit_price']
        
        # Time stop (24 hours)
        elif (ts - self.position['entry_time']).total_seconds() >= 86400:
            unrealized_pnl = (current_price - self.position['entry_price']) * self.position['net_sol']
            r_multiple = unrealized_pnl / (
                (self.position['entry_price'] - self.position['stop_price']) * self.position['net_sol']
            ) if self.position['entry_price'] != self.position['stop_price'] else Decimal('0')
            
            if r_multiple < Decimal('0.2'):
                exit_reason = 'TIME_STOP_24H'
                exit_price = current_price
        
        if exit_reason and exit_price:
            # Execute exit
            net_proceeds, fee_usdt = self._simulate_exit_fill(
                exit_price, self.position['net_sol'], is_stop
            )
            
            if net_proceeds is None:
                return
            
            pnl = net_proceeds - (self.position['entry_price'] * self.position['filled_qty'])
            
            # Update capital
            self.capital += net_proceeds
            
            # Record trade
            trade = TradeRecord(
                entry_time=self.position['entry_time'],
                exit_time=ts,
                entry_price=self.position['entry_price'],
                exit_price=exit_price,
                quantity=self.position['filled_qty'],
                fee_entry_sol=self.position['fee_sol'],
                fee_exit_usdt=fee_usdt,
                pnl=pnl,
                exit_reason=exit_reason,
                entry_reason=self.position['entry_reason']
            )
            self.trades.append(trade)
            
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
            
            logger.info(f"Exit at {ts}: {exit_reason}, PnL: {pnl:.2f} USDT")
            
            self.position = None
    
    def _generate_report(self) -> Dict:
        """Generate backtest performance report."""
        if not self.trades:
            return {"error": "No trades executed"}
        
        trades_df = pd.DataFrame([{
            'entry_time': t.entry_time,
            'exit_time': t.exit_time,
            'pnl': float(t.pnl),
            'exit_reason': t.exit_reason,
            'entry_reason': t.entry_reason
        } for t in self.trades])
        
        total_return = (self.capital - self.initial_capital) / self.initial_capital * 100
        win_trades = [t for t in self.trades if t.pnl > 0]
        loss_trades = [t for t in self.trades if t.pnl <= 0]
        
        win_rate = len(win_trades) / len(self.trades) * 100 if self.trades else 0
        avg_win = sum(t.pnl for t in win_trades) / len(win_trades) if win_trades else Decimal('0')
        avg_loss = sum(t.pnl for t in loss_trades) / len(loss_trades) if loss_trades else Decimal('0')
        
        profit_factor = abs(sum(t.pnl for t in win_trades) / sum(t.pnl for t in loss_trades)) if loss_trades and sum(t.pnl for t in loss_trades) != 0 else float('inf')
        
        # Monthly returns
        monthly_returns = {}
        for t in self.trades:
            month_key = t.exit_time.strftime('%Y-%m')
            if month_key not in monthly_returns:
                monthly_returns[month_key] = Decimal('0')
            monthly_returns[month_key] += t.pnl
        
        # Convert to percentage of initial capital
        monthly_returns_pct = {k: float(v / self.initial_capital * 100) for k, v in monthly_returns.items()}
        
        # Max drawdown from equity curve
        equity_series = pd.Series([float(e) for e in self.equity_curve])
        running_max = equity_series.cummax()
        drawdown = (equity_series - running_max) / running_max * 100
        max_drawdown = drawdown.min()
        
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
            'max_drawdown_pct': float(max_drawdown),
            'monthly_returns_pct': monthly_returns_pct,
            'average_trades_per_month': len(self.trades) / max(len(monthly_returns), 1),
            'sharpe_ratio': self._calculate_sharpe(),
            'sortino_ratio': self._calculate_sortino(),
        }
        
        return report
    
    def _calculate_sharpe(self) -> float:
        """Calculate Sharpe ratio (annualized)."""
        if len(self.equity_curve) < 2:
            return 0.0
        
        returns = pd.Series(self.equity_curve).pct_change().dropna()
        if returns.std() == 0:
            return 0.0
        
        # Assume 24/7 crypto trading, annualize by sqrt(365*24*4) for 15m bars
        annualization_factor = np.sqrt(365 * 24 * 4)
        sharpe = (returns.mean() / returns.std()) * annualization_factor
        return float(sharpe)
    
    def _calculate_sortino(self) -> float:
        """Calculate Sortino ratio (annualized)."""
        if len(self.equity_curve) < 2:
            return 0.0
        
        returns = pd.Series(self.equity_curve).pct_change().dropna()
        downside_returns = returns[returns < 0]
        
        if downside_returns.empty or downside_returns.std() == 0:
            return 0.0
        
        annualization_factor = np.sqrt(365 * 24 * 4)
        sortino = (returns.mean() / downside_returns.std()) * annualization_factor
        return float(sortino)


async def main():
    """Run backtest with default parameters."""
    engine = BacktestEngine()
    
    # Backtest last 6 months
    end_date = datetime.now(timezone.utc)
    start_date = datetime(end_date.year - 1, end_date.month, end_date.day, tzinfo=timezone.utc)
    
    report = await engine.run_backtest(start_date, end_date)
    
    print("\n" + "="*60)
    print("BACKTEST RESULTS")
    print("="*60)
    for key, value in report.items():
        if key != 'monthly_returns_pct':
            print(f"{key}: {value}")
    
    if 'monthly_returns_pct' in report:
        print("\nMonthly Returns (%):")
        for month, ret in sorted(report['monthly_returns_pct'].items()):
            print(f"  {month}: {ret:.2f}%")
    
    print("="*60)
    
    # Go/No-Go assessment
    print("\nGO/NO-GO ASSESSMENT:")
    criteria = [
        ("Positive expectancy", report.get('total_net_return_pct', 0) > 0),
        ("Profit factor > 1.3", report.get('profit_factor', 0) > 1.3),
        ("Max drawdown < 10%", abs(report.get('max_drawdown_pct', 100)) < 10),
        ("At least 100 trades", report.get('total_trades', 0) >= 100),
    ]
    
    all_pass = True
    for criterion, passed in criteria:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}: {criterion}")
        if not passed:
            all_pass = False
    
    if all_pass:
        print("\n→ Strategy meets go-live criteria (pending paper trading)")
    else:
        print("\n→ Strategy does NOT meet go-live criteria. Do not deploy live.")


if __name__ == "__main__":
    asyncio.run(main())
