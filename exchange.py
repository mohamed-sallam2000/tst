"""
OKX Spot Trading Bot - Exchange Integration Layer
Handles OKX/CCXT integration, market data, order management, and protection.
"""

import time
import logging
from typing import Dict, Any, Optional, Tuple, List
from decimal import Decimal, ROUND_DOWN
import ccxt.async_support as ccxt_async
import asyncio

from config import (
    OKX_API_KEY,
    OKX_SECRET,
    OKX_PASSPHRASE,
    OKX_SANDBOX,
    TRADING_MODE,
    SYMBOL,
    DEFAULT_TTL_SECONDS,
    FEE_ROUNDTRIP_PCT_FALLBACK,
)
from database import (
    DBManager,
    OrderRecord,
    PositionRecord,
    RiskEvent,
)

logger = logging.getLogger(__name__)


class ExchangeManager:
    """Manages OKX connection, orders, and position tracking."""

    def __init__(self, db: DBManager):
        self.db = db
        self.exchange: Optional[ccxt_async.okx] = None
        self.symbol = SYMBOL
        self.market_info: Optional[Dict[str, Any]] = None
        self._initialized = False
        self._watchdog_active = False

    async def initialize(self) -> bool:
        """Initialize exchange connection and load market info."""
        try:
            self.exchange = ccxt_async.okx({
                'apiKey': OKX_API_KEY if TRADING_MODE == 'live' else None,
                'secret': OKX_SECRET if TRADING_MODE == 'live' else None,
                'password': OKX_PASSPHRASE if TRADING_MODE == 'live' else None,
                'sandbox': OKX_SANDBOX,
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'spot',
                    'adjustForTimeDifference': True,
                }
            })
            
            # Load markets
            await self.exchange.load_markets()
            
            # Get market info for SOL/USDT
            if self.symbol not in self.exchange.markets:
                logger.error(f"Symbol {self.symbol} not found on OKX")
                return False
            
            self.market_info = self.exchange.market(self.symbol)
            self._initialized = True
            
            logger.info(f"Exchange initialized: {self.symbol}")
            logger.info(f"Min order size: {self.market_info['limits']['amount']['min']}")
            logger.info(f"Price precision: {self.market_info['precision']['price']}")
            logger.info(f"Amount precision: {self.market_info['precision']['amount']}")
            
            # Check OCO/attached order support
            has_oco = self.exchange.has.get('stopLossPrice', False) or \
                      self.exchange.has.get('takeProfitPrice', False)
            logger.info(f"Exchange OCO support detected: {has_oco}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize exchange: {e}")
            return False

    async def close(self):
        """Close exchange connection."""
        if self.exchange:
            await self.exchange.close()
            self._initialized = False

    def get_precision_amount(self, amount: float) -> float:
        """Round amount down to exchange precision."""
        if not self.market_info:
            raise ValueError("Market info not loaded")
        
        precision = self.market_info['precision']['amount']
        # Round DOWN to ensure we don't exceed available balance
        if isinstance(precision, int):
            factor = 10 ** precision
            return float(Decimal(str(amount)).quantize(
                Decimal(10) ** -precision, rounding=ROUND_DOWN
            ))
        else:
            # Handle string precision like "0.0001"
            return float(Decimal(str(amount)).quantize(
                Decimal(str(precision)), rounding=ROUND_DOWN
            ))

    def get_precision_price(self, price: float) -> float:
        """Round price to exchange precision."""
        if not self.market_info:
            raise ValueError("Market info not loaded")
        
        precision = self.market_info['precision']['price']
        if isinstance(precision, int):
            factor = 10 ** precision
            return float(Decimal(str(price)).quantize(
                Decimal(10) ** -precision, rounding=ROUND_DOWN
            ))
        else:
            return float(Decimal(str(price)).quantize(
                Decimal(str(precision)), rounding=ROUND_DOWN
            ))

    def get_min_order_size(self) -> float:
        """Get minimum order size in base currency."""
        if not self.market_info:
            raise ValueError("Market info not loaded")
        return self.market_info['limits']['amount']['min']

    async def get_balance(self, currency: str) -> float:
        """Fetch available balance for currency."""
        if not self._initialized:
            raise RuntimeError("Exchange not initialized")
        
        try:
            balance = await self.exchange.fetch_balance()
            if currency in balance['free']:
                return float(balance['free'][currency])
            return 0.0
        except Exception as e:
            logger.error(f"Failed to fetch balance for {currency}: {e}")
            raise

    async def get_ticker(self) -> Dict[str, float]:
        """Fetch current ticker."""
        if not self._initialized:
            raise RuntimeError("Exchange not initialized")
        
        try:
            ticker = await self.exchange.fetch_ticker(self.symbol)
            return {
                'bid': ticker['bid'],
                'ask': ticker['ask'],
                'last': ticker['last'],
                'spread_pct': (ticker['ask'] - ticker['bid']) / ticker['last'] * 100
                if ticker['bid'] and ticker['ask'] else None
            }
        except Exception as e:
            logger.error(f"Failed to fetch ticker: {e}")
            raise

    async def get_ohlcvc(self, timeframe: str, limit: int = 500) -> List[List]:
        """Fetch OHLCV candles."""
        if not self._initialized:
            raise RuntimeError("Exchange not initialized")
        
        try:
            candles = await self.exchange.fetch_ohlcv(self.symbol, timeframe, limit=limit)
            return candles
        except Exception as e:
            logger.error(f"Failed to fetch OHLCV: {e}")
            raise

    async def get_fees(self) -> Dict[str, float]:
        """Fetch trading fees."""
        if not self._initialized:
            raise RuntimeError("Exchange not initialized")
        
        try:
            fees = await self.exchange.fetch_trading_fees()
            # OKX returns maker/taker fees
            maker = fees.get('maker', 0.0008)  # Default fallback
            taker = fees.get('taker', 0.0010)
            return {'maker': maker, 'taker': taker}
        except Exception as e:
            logger.warning(f"Failed to fetch fees, using fallback: {e}")
            return {'maker': FEE_ROUNDTRIP_PCT_FALLBACK / 200, 
                    'taker': FEE_ROUNDTRIP_PCT_FALLBACK / 200}

    async def place_limit_order(
        self,
        side: str,
        amount: float,
        price: float,
        client_order_id: str
    ) -> Optional[Dict[str, Any]]:
        """Place a limit order with client order ID."""
        if not self._initialized:
            raise RuntimeError("Exchange not initialized")
        
        # Precision adjustments
        amount = self.get_precision_amount(amount)
        price = self.get_precision_price(price)
        
        # Check minimum order size
        min_size = self.get_min_order_size()
        if amount < min_size:
            logger.error(f"Order amount {amount} below minimum {min_size}")
            return None
        
        try:
            params = {'clientOrderId': client_order_id}
            
            order = await self.exchange.create_limit_order(
                symbol=self.symbol,
                side=side,
                amount=amount,
                price=price,
                params=params
            )
            
            logger.info(f"Placed {side} limit order: {order['id']} @ {price}")
            
            # Persist order intent
            self.db.insert_order(OrderRecord(
                order_id=order['id'],
                client_order_id=client_order_id,
                symbol=self.symbol,
                side=side,
                type='limit',
                amount=amount,
                price=price,
                status=order['status'],
                filled=order.get('filled', 0.0),
                remaining=order.get('remaining', amount),
                fee_currency=None,
                fee_cost=0.0,
                created_at=int(time.time() * 1000)
            ))
            
            return order
            
        except Exception as e:
            logger.error(f"Failed to place limit order: {e}")
            return None

    async def place_market_order(
        self,
        side: str,
        amount: float,
        client_order_id: str
    ) -> Optional[Dict[str, Any]]:
        """Place a market order (for emergency exits)."""
        if not self._initialized:
            raise RuntimeError("Exchange not initialized")
        
        amount = self.get_precision_amount(amount)
        
        min_size = self.get_min_order_size()
        if amount < min_size:
            logger.error(f"Order amount {amount} below minimum {min_size}")
            return None
        
        try:
            params = {'clientOrderId': client_order_id}
            
            order = await self.exchange.create_market_order(
                symbol=self.symbol,
                side=side,
                amount=amount,
                params=params
            )
            
            logger.info(f"Placed {side} market order: {order['id']}")
            
            return order
            
        except Exception as e:
            logger.error(f"Failed to place market order: {e}")
            return None

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an order by ID."""
        if not self._initialized:
            raise RuntimeError("Exchange not initialized")
        
        try:
            await self.exchange.cancel_order(order_id, self.symbol)
            logger.info(f"Cancelled order: {order_id}")
            return True
        except Exception as e:
            logger.warning(f"Failed to cancel order {order_id}: {e}")
            return False

    async def fetch_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Fetch order details."""
        if not self._initialized:
            raise RuntimeError("Exchange not initialized")
        
        try:
            order = await self.exchange.fetch_order(order_id, self.symbol)
            return order
        except Exception as e:
            logger.error(f"Failed to fetch order {order_id}: {e}")
            return None

    async def wait_for_fill(
        self,
        order_id: str,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        check_interval: float = 2.0
    ) -> Optional[Dict[str, Any]]:
        """Wait for order to fill or expire."""
        start_time = time.time()
        
        while time.time() - start_time < ttl_seconds:
            order = await self.fetch_order(order_id)
            if not order:
                logger.error(f"Order {order_id} not found")
                return None
            
            status = order.get('status', 'open')
            
            if status == 'closed':
                logger.info(f"Order {order_id} filled")
                return order
            elif status == 'canceled' or status == 'rejected':
                logger.info(f"Order {order_id} {status}")
                return order
            elif status == 'expired':
                logger.info(f"Order {order_id} expired")
                return order
            
            await asyncio.sleep(check_interval)
        
        # TTL expired, cancel if still open
        logger.info(f"TTL expired for order {order_id}, canceling")
        await self.cancel_order(order_id)
        return await self.fetch_order(order_id)

    async def reconcile_fill(self, order: Dict[str, Any]) -> Tuple[float, float, str, float]:
        """
        Reconcile actual filled quantity after fees.
        Returns: (filled_qty, fee_cost, fee_currency, net_received)
        """
        order_id = order['id']
        side = order['side']
        
        # Fetch detailed fills if available
        try:
            trades = await self.exchange.fetch_my_trades(
                self.symbol, 
                params={'orderId': order_id}
            )
        except Exception:
            trades = []
        
        total_filled = 0.0
        total_fee_cost = 0.0
        fee_currency = 'USDT'  # Default assumption
        
        if trades:
            for trade in trades:
                total_filled += trade.get('amount', 0.0)
                fee_info = trade.get('fee', {})
                if fee_info:
                    total_fee_cost += fee_info.get('cost', 0.0)
                    fee_currency = fee_info.get('currency', 'USDT')
        else:
            # Fallback to order data
            total_filled = order.get('filled', 0.0)
            fee_info = order.get('fee', {})
            if fee_info:
                total_fee_cost = fee_info.get('cost', 0.0)
                fee_currency = fee_info.get('currency', 'USDT')
        
        # Calculate net received based on fee currency
        if side == 'buy':
            if fee_currency == 'SOL':
                # Fee deducted from base asset
                net_received = total_filled - total_fee_cost
            else:
                # Fee in quote currency (USDT)
                net_received = total_filled
        else:
            # Sell side - fee typically in USDT or SOL
            if fee_currency == 'SOL':
                net_received = total_filled - total_fee_cost
            else:
                net_received = total_filled
        
        # Ensure non-negative
        net_received = max(0.0, net_received)
        
        logger.info(
            f"Reconciled fill: filled={total_filled}, fee={total_fee_cost} {fee_currency}, "
            f"net_received={net_received}"
        )
        
        return total_filled, total_fee_cost, fee_currency, net_received

    async def attach_protection(
        self,
        entry_order_id: str,
        stop_price: float,
        take_profit_price: float,
        position_qty: float
    ) -> Tuple[bool, bool]:
        """
        Attempt to attach stop-loss and take-profit protection.
        Returns: (stop_success, tp_success)
        
        Note: OKX spot OCO support varies. This attempts native attachment
        but callers must implement local watchdog fallback.
        """
        if not self._initialized:
            return False, False
        
        stop_success = False
        tp_success = False
        
        try:
            # Try OKX's attachAlgoOrds parameter (if supported by ccxt version)
            # This is OKX-specific and may not work in all ccxt versions
            params = {
                'attachAlgoOrds': [
                    {
                        'tdMode': 'cash',
                        'side': 'sell',
                        'posSide': 'net',
                        'ordType': 'conditional',
                        'sz': str(position_qty),
                        'triggerPx': str(stop_price),
                        'triggerPxType': 'last',
                        'algoPx': '-1',  # Market order on trigger
                    },
                    {
                        'tdMode': 'cash',
                        'side': 'sell',
                        'posSide': 'net',
                        'ordType': 'conditional',
                        'sz': str(position_qty),
                        'triggerPx': str(take_profit_price),
                        'triggerPxType': 'last',
                        'algoPx': '-1',  # Market order on trigger
                    }
                ]
            }
            
            # Note: This may fail if ccxt doesn't support this parameter
            # The caller must handle failure and use local watchdog
            logger.info("Attempting to attach protection orders...")
            
            # Since we can't modify the already-placed entry order,
            # we'd need to place separate algo orders
            # For now, return False to trigger local watchdog
            logger.warning("Native OCO attachment not fully supported via ccxt. Using local watchdog.")
            
        except Exception as e:
            logger.error(f"Failed to attach protection: {e}")
        
        return stop_success, tp_success

    async def place_conditional_order(
        self,
        side: str,
        trigger_price: float,
        amount: float,
        order_type: str = 'stop_loss'
    ) -> Optional[str]:
        """
        Place a conditional/stop order separately.
        Returns order ID if successful, None otherwise.
        """
        if not self._initialized:
            return None
        
        try:
            # OKX algo order parameters
            params = {
                'tdMode': 'cash',
                'side': side,
                'posSide': 'net',
                'ordType': 'conditional',
                'sz': str(self.get_precision_amount(amount)),
                'triggerPx': str(self.get_precision_price(trigger_price)),
                'triggerPxType': 'last',
                'algoPx': '-1',  # Market on trigger
            }
            
            # Use ccxt's create_stop_order if available
            if order_type == 'stop_loss':
                order = await self.exchange.create_stop_order(
                    symbol=self.symbol,
                    side=side,
                    amount=amount,
                    trigger=trigger_price,
                    params=params
                )
            else:
                # Take profit
                order = await self.exchange.create_stop_order(
                    symbol=self.symbol,
                    side=side,
                    amount=amount,
                    trigger=trigger_price,
                    params={**params, 'ordType': 'conditional'}
                )
            
            logger.info(f"Placed {order_type} conditional order: {order.get('id')}")
            return order.get('id')
            
        except Exception as e:
            logger.error(f"Failed to place conditional order: {e}")
            return None

    async def get_open_orders(self) -> List[Dict[str, Any]]:
        """Fetch all open orders for the symbol."""
        if not self._initialized:
            raise RuntimeError("Exchange not initialized")
        
        try:
            orders = await self.exchange.fetch_open_orders(self.symbol)
            return orders
        except Exception as e:
            logger.error(f"Failed to fetch open orders: {e}")
            return []

    async def get_algo_orders(self) -> List[Dict[str, Any]]:
        """Fetch open algo/conditional orders."""
        if not self._initialized:
            raise RuntimeError("Exchange not initialized")
        
        try:
            # OKX-specific: fetch algo orders
            # This may require direct API call if ccxt doesn't support it
            response = await self.exchange.private_get_trade_orders_algo_pending({
                'ordType': 'conditional'
            })
            if response.get('code') == '0' and response.get('data'):
                return response['data']
            return []
        except Exception as e:
            logger.warning(f"Failed to fetch algo orders: {e}")
            return []

    async def cancel_algo_order(self, algo_id: str) -> bool:
        """Cancel an algo/conditional order."""
        if not self._initialized:
            return False
        
        try:
            await self.exchange.private_post_trade_cancel_algo_order({
                'algoId': algo_id
            })
            logger.info(f"Cancelled algo order: {algo_id}")
            return True
        except Exception as e:
            logger.warning(f"Failed to cancel algo order {algo_id}: {e}")
            return False

    async def reconcile_state(self) -> Dict[str, Any]:
        """
        Reconcile local state with exchange state.
        Returns reconciliation report.
        """
        report = {
            'local_flat': True,
            'exchange_has_position': False,
            'exchange_balances': {},
            'open_orders': [],
            'algo_orders': [],
            'discrepancies': []
        }
        
        # Fetch exchange balances
        try:
            balance = await self.exchange.fetch_balance()
            report['exchange_balances'] = {
                'SOL': balance['free'].get('SOL', 0.0),
                'USDT': balance['free'].get('USDT', 0.0)
            }
            
            # Check if we have SOL balance (indicates position)
            if report['exchange_balances']['SOL'] > 0:
                report['exchange_has_position'] = True
                
        except Exception as e:
            logger.error(f"Failed to fetch balance during reconciliation: {e}")
        
        # Fetch open orders
        try:
            open_orders = await self.get_open_orders()
            report['open_orders'] = open_orders
            if open_orders:
                report['discrepancies'].append(f"Found {len(open_orders)} open orders")
        except Exception as e:
            logger.error(f"Failed to fetch open orders during reconciliation: {e}")
        
        # Fetch algo orders
        try:
            algo_orders = await self.get_algo_orders()
            report['algo_orders'] = algo_orders
            if algo_orders:
                report['discrepancies'].append(f"Found {len(algo_orders)} open algo orders")
        except Exception as e:
            logger.error(f"Failed to fetch algo orders during reconciliation: {e}")
        
        # Check local state
        active_position = self.db.get_active_position()
        if active_position:
            report['local_flat'] = False
        
        return report

    async def emergency_exit(self, reason: str) -> bool:
        """
        Emergency market exit of entire position.
        Used when protection fails or critical error occurs.
        """
        try:
            # Get actual SOL balance
            sol_balance = await self.get_balance('SOL')
            
            if sol_balance <= 0:
                logger.info("No SOL balance to exit")
                return True
            
            # Round down to precision
            exit_qty = self.get_precision_amount(sol_balance)
            
            # Check minimum
            min_size = self.get_min_order_size()
            if exit_qty < min_size:
                logger.warning(f"Exit quantity {exit_qty} below minimum {min_size}, skipping")
                # Record dust
                self.db.record_risk_event(
                    event_type='DUST_POSITION',
                    details=f"Dust position {exit_qty} SOL cannot be sold"
                )
                return True
            
            client_oid = f"emergency_{int(time.time() * 1000)}"
            
            # Place market sell
            order = await self.place_market_order('sell', exit_qty, client_oid)
            
            if order:
                logger.critical(f"EMERGENCY EXIT executed: {order['id']} - Reason: {reason}")
                
                # Wait for fill
                filled_order = await self.wait_for_fill(order['id'], ttl_seconds=30)
                
                if filled_order and filled_order.get('status') == 'closed':
                    # Reconcile
                    filled, fee_cost, fee_curr, net = await self.reconcile_fill(filled_order)
                    
                    # Update position record
                    self.db.update_position_exit(
                        exit_reason=f'EMERGENCY_{reason}',
                        exit_price=filled_order.get('average', filled_order.get('price', 0)),
                        exit_qty=filled,
                        fee_cost=fee_cost,
                        fee_currency=fee_curr
                    )
                    
                    return True
                
            logger.error("Emergency exit failed")
            return False
            
        except Exception as e:
            logger.critical(f"Emergency exit exception: {e}")
            return False
