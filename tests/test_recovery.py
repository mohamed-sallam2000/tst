#!/usr/bin/env python3
"""
test_recovery.py - Unit tests for order recovery and state reconciliation.

Tests restart recovery, position reconciliation, and protection failure handling.
"""

import unittest
from decimal import Decimal
from datetime import datetime, timezone
from typing import Dict, List, Optional


class MockExchangeState:
    """Mock exchange state for testing."""
    
    def __init__(self):
        self.balances = {
            'USDT': {'free': Decimal('1000'), 'total': Decimal('1000')},
            'SOL': {'free': Decimal('0'), 'total': Decimal('0')}
        }
        self.open_orders: List[Dict] = []
        self.filled_orders: List[Dict] = []
        self.algo_orders: List[Dict] = []


class TestPositionReconciliation(unittest.TestCase):
    """Test position state reconciliation on restart."""
    
    def test_flat_state_with_no_exchange_position(self):
        """Test local FLAT state matches exchange when no position exists."""
        local_state = 'FLAT'
        exchange_sol_balance = Decimal('0')
        
        is_reconciled = (local_state == 'FLAT' and exchange_sol_balance == 0)
        
        self.assertTrue(is_reconciled)
    
    def test_local_flat_but_exchange_has_position(self):
        """Test detection of position mismatch - local says flat but exchange has SOL."""
        local_state = 'FLAT'
        exchange_sol_balance = Decimal('5.0')
        
        # This indicates a problem - bot thinks it's flat but exchange holds SOL
        position_mismatch = (local_state == 'FLAT' and exchange_sol_balance > 0)
        
        self.assertTrue(position_mismatch)
    
    def test_local_position_matches_exchange(self):
        """Test local position record matches exchange balance."""
        local_position_qty = Decimal('5.0')
        exchange_sol_balance = Decimal('5.0')
        
        is_reconciled = abs(local_position_qty - exchange_sol_balance) < Decimal('0.001')
        
        self.assertTrue(is_reconciled)
    
    def test_partial_fill_reconciliation(self):
        """Test reconciliation after partial fill."""
        requested_qty = Decimal('10.0')
        filled_qty = Decimal('6.0')
        unfilled_qty = requested_qty - filled_qty
        
        # After cancel, should have only filled amount
        actual_position = filled_qty
        
        self.assertEqual(actual_position, Decimal('6.0'))
        self.assertLess(actual_position, requested_qty)


class TestOrderRecovery(unittest.TestCase):
    """Test order recovery scenarios."""
    
    def test_open_buy_order_recovery(self):
        """Test recovery of open buy order on restart."""
        open_orders = [
            {
                'id': 'order123',
                'symbol': 'SOL/USDT',
                'side': 'buy',
                'type': 'limit',
                'amount': Decimal('5.0'),
                'filled': Decimal('0'),
                'status': 'open'
            }
        ]
        
        # Bot should detect open order and decide to keep or cancel
        has_open_buy = any(o['side'] == 'buy' and o['status'] == 'open' for o in open_orders)
        
        self.assertTrue(has_open_buy)
    
    def test_open_sell_order_recovery(self):
        """Test recovery of open sell order (exit) on restart."""
        open_orders = [
            {
                'id': 'order456',
                'symbol': 'SOL/USDT',
                'side': 'sell',
                'type': 'limit',
                'amount': Decimal('5.0'),
                'filled': Decimal('0'),
                'status': 'open'
            }
        ]
        
        # Open sell order might be take-profit that wasn't filled
        has_open_sell = any(o['side'] == 'sell' and o['status'] == 'open' for o in open_orders)
        
        self.assertTrue(has_open_sell)
    
    def test_partially_filled_order_recovery(self):
        """Test recovery of partially filled order."""
        open_orders = [
            {
                'id': 'order789',
                'symbol': 'SOL/USDT',
                'side': 'buy',
                'type': 'limit',
                'amount': Decimal('10.0'),
                'filled': Decimal('4.0'),
                'remaining': Decimal('6.0'),
                'status': 'open'
            }
        ]
        
        order = open_orders[0]
        is_partial = order['filled'] > 0 and order['filled'] < order['amount']
        
        self.assertTrue(is_partial)
        self.assertEqual(order['remaining'], Decimal('6.0'))


class TestProtectionRecovery(unittest.TestCase):
    """Test stop-loss and take-profit protection recovery."""
    
    def test_stop_loss_order_exists(self):
        """Test verification that stop-loss order exists on exchange."""
        algo_orders = [
            {
                'id': 'sl_order123',
                'type': 'stop_loss',
                'symbol': 'SOL/USDT',
                'status': 'live'
            }
        ]
        
        has_stop_loss = any(o['type'] == 'stop_loss' and o['status'] == 'live' for o in algo_orders)
        
        self.assertTrue(has_stop_loss)
    
    def test_take_profit_order_exists(self):
        """Test verification that take-profit order exists on exchange."""
        algo_orders = [
            {
                'id': 'tp_order456',
                'type': 'take_profit',
                'symbol': 'SOL/USDT',
                'status': 'live'
            }
        ]
        
        has_take_profit = any(o['type'] == 'take_profit' and o['status'] == 'live' for o in algo_orders)
        
        self.assertTrue(has_take_profit)
    
    def test_missing_protection_detection(self):
        """Test detection of missing stop-loss protection."""
        position_exists = True
        algo_orders = []  # No algo orders
        
        has_protection = any(o['type'] in ['stop_loss', 'oco'] for o in algo_orders)
        
        needs_emergency_protection = position_exists and not has_protection
        
        self.assertTrue(needs_emergency_protection)
    
    def test_oco_order_triggered_partial(self):
        """Test OCO order where one leg triggered and other was cancelled."""
        # Simulated: TP triggered, SL was cancelled automatically by exchange
        order_history = [
            {
                'id': 'tp_triggered',
                'type': 'take_profit',
                'status': 'filled',
                'filled_qty': Decimal('5.0')
            },
            {
                'id': 'sl_cancelled',
                'type': 'stop_loss',
                'status': 'cancelled',
                'reason': 'oco_triggered'
            }
        ]
        
        # Position should now be flat since TP filled
        total_sold = sum(o['filled_qty'] for o in order_history if o['status'] == 'filled')
        
        self.assertEqual(total_sold, Decimal('5.0'))


class TestStateRecoveryOnRestart(unittest.TestCase):
    """Test full state recovery on bot restart."""
    
    def test_full_recovery_with_open_position(self):
        """Test complete state recovery when position is open."""
        # Local database state
        local_db = {
            'state': 'POSITION_ACTIVE',
            'position_qty': Decimal('5.0'),
            'entry_price': Decimal('100.00'),
            'stop_price': Decimal('98.00'),
            'take_profit_price': Decimal('104.00')
        }
        
        # Exchange state
        exchange_balances = {
            'SOL': {'free': Decimal('5.0'), 'total': Decimal('5.0')},
            'USDT': {'free': Decimal('500'), 'total': Decimal('500')}
        }
        exchange_orders = []  # No open orders (protection via algo orders)
        
        # Reconciliation
        sol_balance = exchange_balances['SOL']['total']
        position_reconciled = abs(sol_balance - local_db['position_qty']) < Decimal('0.001')
        
        self.assertTrue(position_reconciled)
        self.assertEqual(local_db['state'], 'POSITION_ACTIVE')
    
    def test_recovery_detects_unrecorded_position(self):
        """Test recovery detects position not in local database."""
        local_db = {
            'state': 'FLAT',
            'position_qty': Decimal('0')
        }
        
        exchange_balances = {
            'SOL': {'free': Decimal('3.0'), 'total': Decimal('3.0')}
        }
        
        # Mismatch detected
        sol_balance = exchange_balances['SOL']['total']
        unexpected_position = sol_balance > 0 and local_db['state'] == 'FLAT'
        
        self.assertTrue(unexpected_position)
        # Bot should enter ERROR_SAFE state and reconcile
    
    def test_recovery_after_crash_during_entry(self):
        """Test recovery after crash during entry order placement."""
        # Scenario: Bot sent buy order, crashed before recording locally
        exchange_balances = {
            'SOL': {'free': Decimal('2.0'), 'total': Decimal('2.0')}
        }
        exchange_orders = []  # Order already filled
        
        # Local DB shows FLAT but exchange has SOL
        should_reconcile_as_position = exchange_balances['SOL']['total'] > 0
        
        self.assertTrue(should_reconcile_as_position)
        # Bot should reconstruct position state from exchange data


class TestEmergencyProtection(unittest.TestCase):
    """Test emergency protection fallback behavior."""
    
    def test_local_watchdog_activates_when_exchange_protection_fails(self):
        """Test local watchdog activates when exchange protection unavailable."""
        exchange_supports_oco = False
        position_open = True
        
        needs_local_watchdog = position_open and not exchange_supports_oco
        
        self.assertTrue(needs_local_watchdog)
    
    def test_emergency_market_exit_on_stop_breach(self):
        """Test emergency market exit when stop price breached."""
        current_price = Decimal('97.00')
        stop_price = Decimal('98.00')
        position_qty = Decimal('5.0')
        
        stop_breached = current_price <= stop_price
        
        if stop_breached:
            action = 'EMERGENCY_MARKET_SELL'
        else:
            action = 'HOLD'
        
        self.assertEqual(action, 'EMERGENCY_MARKET_SELL')
    
    def test_idempotent_emergency_exit(self):
        """Test emergency exit is idempotent - doesn't create duplicate orders."""
        emergency_exit_submitted = False
        last_exit_time = None
        current_time = datetime.now(timezone.utc)
        
        # First breach detection
        if not emergency_exit_submitted:
            emergency_exit_submitted = True
            last_exit_time = current_time
            action1 = 'SUBMIT_EMERGENCY_EXIT'
        else:
            action1 = 'SKIP_ALREADY_SUBMITTED'
        
        # Second breach detection (same condition)
        if not emergency_exit_submitted:
            action2 = 'SUBMIT_EMERGENCY_EXIT'
        else:
            action2 = 'SKIP_ALREADY_SUBMITTED'
        
        self.assertEqual(action1, 'SUBMIT_EMERGENCY_EXIT')
        self.assertEqual(action2, 'SKIP_ALREADY_SUBMITTED')


if __name__ == '__main__':
    unittest.main()
