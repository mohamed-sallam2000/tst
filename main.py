"""
OKX Spot Trading Bot - Main Runtime Loop
State machine, watchdog coordination, risk checks, and graceful shutdown.
"""

import asyncio
import signal
import logging
import time
import sys
from typing import Optional, Dict, Any
from datetime import datetime, timezone

from config import (
    TRADING_MODE,
    SYMBOL,
    CHECK_INTERVAL_SECONDS,
    MAX_OPEN_POSITIONS,
    LOG_LEVEL,
)
from database import DBManager, BotState
from exchange import ExchangeManager
from strategy import StrategyEngine, SignalResult
from risk import RiskManager, RiskState

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class TradingBot:
    """Main trading bot orchestrator."""

    def __init__(self):
        self.db = DBManager()
        self.exchange = ExchangeManager(self.db)
        self.strategy = StrategyEngine()
        self.risk_manager = RiskManager(self.db)
        
        self.state = BotState.FLAT
        self.shutdown_requested = False
        self.watchdog_active = False
        self.current_position_id: Optional[int] = None
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.shutdown_requested = True

    async def initialize(self) -> bool:
        """Initialize all components."""
        logger.info(f"Initializing bot in {TRADING_MODE} mode...")
        
        # Initialize database
        self.db.initialize()
        logger.info("Database initialized")
        
        # Recover any existing state
        await self._recover_state()
        
        # Initialize exchange
        if not await self.exchange.initialize():
            logger.error("Failed to initialize exchange")
            return False
        
        # Initialize risk manager
        if not self.risk_manager.initialize():
            logger.error("Failed to initialize risk manager")
            return False
        
        logger.info("Bot initialization complete")
        return True

    async def _recover_state(self):
        """Recover state from database and reconcile with exchange."""
        logger.info("Attempting state recovery...")
        
        # Check for active position in database
        active_pos = self.db.get_active_position()
        
        if active_pos:
            logger.info(f"Found active position in database: {active_pos}")
            self.current_position_id = active_pos['id']
            
            # Reconcile with exchange
            report = await self.exchange.reconcile_state()
            
            if report['exchange_has_position']:
                logger.info("Exchange confirms position exists")
                self.state = BotState.POSITION_ACTIVE
                
                # Check if protection orders exist
                if report['algo_orders']:
                    logger.info(f"Found {len(report['algo_orders'])} algo orders")
                    self.watchdog_active = False
                else:
                    logger.warning("No protection orders found, activating local watchdog")
                    self.watchdog_active = True
            else:
                logger.warning("Database shows position but exchange shows none")
                logger.warning("Entering ERROR_SAFE state for manual review")
                self.state = BotState.ERROR_SAFE
                self.db.update_bot_state(BotState.ERROR_SAFE)
                
        else:
            # Check for open orders that need handling
            open_orders = await self.exchange.get_open_orders()
            
            if open_orders:
                logger.warning(f"Found {len(open_orders)} open orders without position record")
                # Cancel orphaned orders
                for order in open_orders:
                    logger.info(f"Cancelling orphaned order: {order['id']}")
                    await self.exchange.cancel_order(order['id'])
            
            self.state = BotState.FLAT
            self.db.update_bot_state(BotState.FLAT)
        
        # Check for halt conditions
        risk_state = self.risk_manager.get_current_risk_state()
        if risk_state == RiskState.HALT:
            logger.warning("Risk manager indicates HALT state")
            self.state = BotState.HALT
            self.db.update_bot_state(BotState.HALT)

    async def run_entry_cycle(self):
        """Run one entry evaluation cycle."""
        if self.state != BotState.FLAT:
            return
        
        # Check risk limits
        if not self.risk_manager.can_enter_trade():
            logger.info("Risk manager prohibits new entries")
            return
        
        # Fetch market data
        try:
            htf_candles = await self.exchange.get_ohlcvc('1h', limit=250)
            entry_candles = await self.exchange.get_ohlcvc('15m', limit=100)
            ticker = await self.exchange.get_ticker()
            
            # Calculate 24h change
            daily_candles = await self.exchange.get_ohlcvc('1d', limit=2)
            if len(daily_candles) >= 2:
                sol_24h_change = ((daily_candles[-1][4] - daily_candles[-2][4]) / daily_candles[-2][4]) * 100
            else:
                sol_24h_change = 0.0
            
            spread_pct = ticker.get('spread_pct', 999)
            
        except Exception as e:
            logger.error(f"Failed to fetch market data: {e}")
            return
        
        # Generate signal
        signal_result = self.strategy.generate_signal(
            htf_candles=htf_candles,
            entry_candles=entry_candles,
            sol_24h_change=sol_24h_change,
            spread_pct=spread_pct
        )
        
        # Log indicators
        if signal_result.indicators:
            logger.debug(f"Signal indicators: {signal_result.indicators}")
        
        if signal_result.signal != 'BUY':
            logger.debug(f"No entry signal: {signal_result.reason}")
            return
        
        logger.info(f"Entry signal generated: {signal_result.reason}")
        
        # Calculate position size
        equity = self.risk_manager.get_current_equity()
        stop_distance_pct = (signal_result.entry_price - signal_result.stop_price) / signal_result.entry_price
        
        position_size = self.risk_manager.calculate_position_size(
            equity=equity,
            stop_distance_pct=stop_distance_pct
        )
        
        if position_size <= 0:
            logger.warning("Position size calculation returned zero or negative")
            return
        
        # Check minimum order size
        min_size = self.exchange.get_min_order_size()
        if position_size < min_size:
            logger.warning(f"Position size {position_size} below minimum {min_size}")
            return
        
        # Place entry order
        client_oid = f"entry_{int(time.time() * 1000)}"
        
        # Calculate limit price (slightly above current for better fill chance)
        entry_price = ticker['ask'] if ticker['ask'] else signal_result.entry_price
        limit_price = self.exchange.get_precision_price(entry_price * 1.001)  # 0.1% above
        
        logger.info(
            f"Placing entry order: {position_size} SOL @ {limit_price:.4f} USDT, "
            f"stop={signal_result.stop_price:.4f}, tp={signal_result.take_profit_price:.4f}"
        )
        
        order = await self.exchange.place_limit_order(
            side='buy',
            amount=position_size,
            price=limit_price,
            client_order_id=client_oid
        )
        
        if not order:
            logger.error("Failed to place entry order")
            return
        
        # Update state
        self.state = BotState.ENTRY_PENDING
        self.db.update_bot_state(BotState.ENTRY_PENDING)
        
        # Wait for fill
        filled_order = await self.exchange.wait_for_fill(order['id'])
        
        if not filled_order or filled_order.get('status') != 'closed':
            logger.info("Entry order did not fill")
            self.state = BotState.FLAT
            self.db.update_bot_state(BotState.FLAT)
            return
        
        # Reconcile fill
        filled_qty, fee_cost, fee_currency, net_received = await self.exchange.reconcile_fill(filled_order)
        
        if filled_qty <= 0:
            logger.error("Order filled but quantity is zero")
            self.state = BotState.ERROR_SAFE
            self.db.update_bot_state(BotState.ERROR_SAFE)
            return
        
        # Record position
        entry_price_filled = filled_order.get('average', filled_order.get('price', limit_price))
        
        position_id = self.db.create_position(
            symbol=SYMBOL,
            side='long',
            entry_price=entry_price_filled,
            requested_qty=position_size,
            filled_qty=filled_qty,
            fee_currency=fee_currency,
            fee_cost=fee_cost,
            net_received=net_received,
            stop_price=signal_result.stop_price,
            take_profit_price=signal_result.take_profit_price,
            entry_reason=signal_result.reason,
            indicators=signal_result.indicators
        )
        
        self.current_position_id = position_id
        logger.info(f"Position opened: ID={position_id}, qty={filled_qty}, net={net_received}")
        
        # Attempt to place protection
        stop_success, tp_success = await self.exchange.attach_protection(
            entry_order_id=order['id'],
            stop_price=signal_result.stop_price,
            take_profit_price=signal_result.take_profit_price,
            position_qty=net_received
        )
        
        if not stop_success or not tp_success:
            logger.warning("Exchange protection not fully established, activating local watchdog")
            self.watchdog_active = True
        else:
            self.watchdog_active = False
        
        # Update state
        self.state = BotState.POSITION_ACTIVE
        self.db.update_bot_state(BotState.POSITION_ACTIVE)

    async def run_exit_cycle(self):
        """Run one exit evaluation cycle for active position."""
        if self.state != BotState.POSITION_ACTIVE:
            return
        
        if self.current_position_id is None:
            logger.error("Position active but no position ID tracked")
            self.state = BotState.ERROR_SAFE
            return
        
        # Get position details
        position = self.db.get_position(self.current_position_id)
        
        if not position:
            logger.error("Position record not found")
            self.state = BotState.ERROR_SAFE
            return
        
        # Get current price
        try:
            ticker = await self.exchange.get_ticker()
            current_price = ticker['last']
        except Exception as e:
            logger.error(f"Failed to fetch ticker: {e}")
            return
        
        # Calculate unrealized PnL
        entry_price = position['entry_price']
        net_received = position['net_received']
        
        unrealized_pnl = (current_price - entry_price) * net_received
        unrealized_pnl_pct = (current_price - entry_price) / entry_price
        
        # Get R value
        stop_price = position['stop_price']
        r_value = entry_price - stop_price
        
        # Check stop-loss breach
        if current_price <= stop_price:
            logger.warning(f"Stop-loss breached: {current_price} <= {stop_price}")
            await self._execute_exit('STOP_LOSS_HIT', current_price, net_received)
            return
        
        # Check take-profit reached
        take_profit = position['take_profit_price']
        if current_price >= take_profit:
            logger.info(f"Take-profit reached: {current_price} >= {take_profit}")
            await self._execute_exit('TAKE_PROFIT_HIT', current_price, net_received)
            return
        
        # Check time-based exit
        should_time_exit, time_reason = self.strategy.check_time_exit(
            entry_time_ms=position['entry_time'],
            current_time_ms=int(time.time() * 1000),
            unrealized_pnl_pct=unrealized_pnl_pct,
            r_value=r_value
        )
        
        if should_time_exit:
            logger.info(f"Time-based exit triggered: {time_reason}")
            await self._execute_exit(time_reason, current_price, net_received)
            return
        
        # Monitor via watchdog if active
        if self.watchdog_active:
            await self._run_watchdog_monitoring(position, current_price, stop_price, take_profit)

    async def _run_watchdog_monitoring(
        self,
        position: Dict[str, Any],
        current_price: float,
        stop_price: float,
        take_profit_price: float
    ):
        """Local watchdog monitoring when exchange protection is missing."""
        # This is a safety fallback - check more frequently
        if current_price <= stop_price * 0.995:  # 0.5% buffer
            logger.critical(f"WATCHDOG: Stop price breached! {current_price} <= {stop_price}")
            await self._execute_exit('WATCHDOG_STOP', current_price, position['net_received'])
        elif current_price >= take_profit_price * 0.995:
            logger.info(f"WATCHDOG: Take profit near, preparing exit")
            # Could implement partial exit here if desired

    async def _execute_exit(self, reason: str, exit_price: float, exit_qty: float):
        """Execute position exit."""
        logger.info(f"Executing exit: reason={reason}, qty={exit_qty}, price={exit_price}")
        
        # Update state
        self.state = BotState.EXIT_PENDING
        self.db.update_bot_state(BotState.EXIT_PENDING)
        
        # Place market sell order
        client_oid = f"exit_{int(time.time() * 1000)}"
        
        order = await self.exchange.place_market_order(
            side='sell',
            amount=exit_qty,
            client_order_id=client_oid
        )
        
        if not order:
            logger.error("Failed to place exit order")
            self.state = BotState.ERROR_SAFE
            return
        
        # Wait for fill
        filled_order = await self.exchange.wait_for_fill(order['id'], ttl_seconds=30)
        
        if not filled_order or filled_order.get('status') != 'closed':
            logger.error("Exit order did not fill properly")
            self.state = BotState.ERROR_SAFE
            return
        
        # Reconcile
        filled_qty, fee_cost, fee_currency, _ = await self.exchange.reconcile_fill(filled_order)
        exit_price_actual = filled_order.get('average', filled_order.get('price', exit_price))
        
        # Update position record
        self.db.update_position_exit(
            exit_reason=reason,
            exit_price=exit_price_actual,
            exit_qty=filled_qty,
            fee_cost=fee_cost,
            fee_currency=fee_currency
        )
        
        # Calculate realized PnL
        position = self.db.get_position(self.current_position_id)
        if position:
            pnl = self.risk_manager.calculate_realized_pnl(
                entry_price=position['entry_price'],
                exit_price=exit_price_actual,
                qty=filled_qty,
                entry_fee=position['fee_cost'],
                exit_fee=fee_cost
            )
            logger.info(f"Trade closed: realized PnL = {pnl:.4f} USDT")
            
            # Update risk manager
            self.risk_manager.record_trade(pnl)
        
        # Reset state
        self.state = BotState.FLAT
        self.db.update_bot_state(BotState.FLAT)
        self.current_position_id = None
        self.watchdog_active = False

    async def run(self):
        """Main runtime loop."""
        logger.info("Starting main loop...")
        
        while not self.shutdown_requested:
            try:
                # Run entry cycle if flat
                if self.state == BotState.FLAT:
                    await self.run_entry_cycle()
                
                # Run exit cycle if position active
                elif self.state == BotState.POSITION_ACTIVE:
                    await self.run_exit_cycle()
                
                # Handle error states
                elif self.state == BotState.ERROR_SAFE:
                    logger.warning("Bot in ERROR_SAFE state, attempting reconciliation...")
                    await self._recover_state()
                    
                    if self.state == BotState.ERROR_SAFE:
                        logger.error("Still in ERROR_SAFE after reconciliation, waiting...")
                        await asyncio.sleep(60)  # Wait longer before retry
                
                # Handle halt state
                elif self.state == BotState.HALT:
                    logger.info("Bot in HALT state, checking if can resume...")
                    if self.risk_manager.can_resume_trading():
                        logger.info("Risk conditions cleared, resuming")
                        self.state = BotState.FLAT
                        self.db.update_bot_state(BotState.FLAT)
                    else:
                        await asyncio.sleep(300)  # Check every 5 minutes
                
                else:
                    await asyncio.sleep(CHECK_INTERVAL_SECONDS)
                
            except Exception as e:
                logger.exception(f"Error in main loop: {e}")
                self.state = BotState.ERROR_SAFE
                await asyncio.sleep(10)
        
        logger.info("Shutdown complete")

    async def shutdown(self):
        """Clean shutdown."""
        logger.info("Shutting down bot...")
        
        # Cancel any open orders if in error state
        if self.state == BotState.ERROR_SAFE:
            logger.warning("Shutting down from ERROR_SAFE, canceling open orders")
            open_orders = await self.exchange.get_open_orders()
            for order in open_orders:
                await self.exchange.cancel_order(order['id'])
        
        # Close exchange connection
        await self.exchange.close()
        
        logger.info("Bot shutdown complete")


async def main():
    """Entry point."""
    bot = TradingBot()
    
    if not await bot.initialize():
        logger.error("Failed to initialize bot")
        sys.exit(1)
    
    try:
        await bot.run()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        await bot.shutdown()


if __name__ == '__main__':
    asyncio.run(main())
