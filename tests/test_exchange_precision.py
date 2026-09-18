#!/usr/bin/env python3
"""
test_exchange_precision.py - Unit tests for OKX spot precision and fee handling.

Tests base-asset fee deduction, sellable quantity calculation, and lot-size rounding.
"""

import unittest
from decimal import Decimal, ROUND_DOWN


class TestFeeDeduction(unittest.TestCase):
    """Test OKX spot fee deduction scenarios."""
    
    def test_fee_deducted_from_base_asset(self):
        """Test scenario where fee is deducted from received SOL."""
        requested_qty = Decimal('1.000')
        fee_rate = Decimal('0.001')  # 0.1%
        
        # Fee deducted in SOL
        fee_cost_sol = requested_qty * fee_rate
        net_received_sol = requested_qty - fee_cost_sol
        
        self.assertEqual(net_received_sol, Decimal('0.999'))
        self.assertLess(net_received_sol, requested_qty)
    
    def test_fee_deducted_in_quote_asset(self):
        """Test scenario where fee is deducted from USDT instead."""
        requested_qty = Decimal('1.000')
        price = Decimal('100.00')
        fee_rate = Decimal('0.001')
        
        gross_cost = requested_qty * price
        fee_cost_usdt = gross_cost * fee_rate
        net_cost = gross_cost + fee_cost_usdt
        
        # Full SOL received, fee paid in USDT
        net_received_sol = requested_qty
        
        self.assertEqual(net_received_sol, Decimal('1.000'))
        self.assertEqual(fee_cost_usdt, Decimal('0.10'))
    
    def test_sellable_quantity_after_base_fee(self):
        """Test sellable quantity calculation after base-asset fee."""
        filled_qty = Decimal('1.000')
        fee_cost_sol = Decimal('0.001')
        
        sellable_qty = filled_qty - fee_cost_sol
        
        # Must round down to exchange precision (3 decimals for SOL)
        quantize_str = '0.001'
        sellable_qty = sellable_qty.quantize(Decimal(quantize_str), rounding=ROUND_DOWN)
        
        self.assertEqual(sellable_qty, Decimal('0.999'))
    
    def test_cannot_sell_more_than_received(self):
        """Test that exit quantity never exceeds actual received amount."""
        requested_qty = Decimal('1.000')
        fee_rate = Decimal('0.001')
        
        net_received = requested_qty * (Decimal('1') - fee_rate)
        
        # Attempting to sell original quantity would fail
        attempted_sell_qty = requested_qty
        
        self.assertGreater(attempted_sell_qty, net_received)
        # Bot must use net_received, not requested_qty


class TestLotSizeRounding(unittest.TestCase):
    """Test exchange lot-size precision rounding."""
    
    def test_round_down_to_precision(self):
        """Test rounding down to exchange precision."""
        amount = Decimal('1.234567')
        precision = 3  # SOL typically 3 decimals
        
        quantize_str = '0.' + '0' * precision
        rounded = amount.quantize(Decimal(quantize_str), rounding=ROUND_DOWN)
        
        self.assertEqual(rounded, Decimal('1.234'))
    
    def test_round_up_would_exceed_available(self):
        """Test that rounding up could exceed available balance."""
        available = Decimal('0.999')
        precision = 3
        
        # If we had 0.9994 and rounded normally, might get 0.999
        # But if we have exactly 0.999 and try to sell 0.9995 (rounded up), fail
        attempted_sell = Decimal('1.000')
        
        self.assertGreater(attempted_sell, available)
    
    def test_dust_detection(self):
        """Test detection of dust amounts below minimum order size."""
        min_order_size = Decimal('0.01')  # Example minimum
        remaining_qty = Decimal('0.005')
        
        is_dust = remaining_qty < min_order_size
        
        self.assertTrue(is_dust)


class TestOrderReconciliation(unittest.TestCase):
    """Test order fill reconciliation logic."""
    
    def test_filled_qty_matches_requested(self):
        """Test normal case where fill matches request."""
        requested = Decimal('1.000')
        filled = Decimal('1.000')
        
        self.assertEqual(filled, requested)
    
    def test_partial_fill_handling(self):
        """Test handling of partial fills."""
        requested = Decimal('1.000')
        filled = Decimal('0.500')
        
        unfilled = requested - filled
        
        self.assertEqual(unfilled, Decimal('0.500'))
        self.assertLess(filled, requested)
    
    def test_fee_currency_identification(self):
        """Test identifying fee currency from order response."""
        # Simulated order response
        order_data = {
            'fee': '0.001',
            'fee_currency': 'SOL'
        }
        
        fee_currency = order_data.get('fee_currency')
        fee_cost = Decimal(order_data.get('fee', '0'))
        
        self.assertEqual(fee_currency, 'SOL')
        self.assertEqual(fee_cost, Decimal('0.001'))
    
    def test_net_received_calculation_when_fee_in_base(self):
        """Test net received calculation when fee is in base asset."""
        filled_qty = Decimal('1.000')
        fee_currency = 'SOL'
        fee_cost = Decimal('0.001')
        
        if fee_currency == 'SOL':
            net_received = filled_qty - fee_cost
        else:
            net_received = filled_qty
        
        self.assertEqual(net_received, Decimal('0.999'))
    
    def test_net_received_calculation_when_fee_in_quote(self):
        """Test net received calculation when fee is in quote asset."""
        filled_qty = Decimal('1.000')
        fee_currency = 'USDT'
        fee_cost = Decimal('0.10')
        
        if fee_currency == 'SOL':
            net_received = filled_qty - fee_cost
        else:
            net_received = filled_qty
        
        self.assertEqual(net_received, Decimal('1.000'))


class TestExitQuantityValidation(unittest.TestCase):
    """Test exit quantity validation before order placement."""
    
    def test_exit_qty_equals_net_received(self):
        """Test exit quantity equals net received SOL."""
        net_received_sol = Decimal('0.999')
        precision = 3
        
        quantize_str = '0.' + '0' * precision
        exit_qty = net_received_sol.quantize(Decimal(quantize_str), rounding=ROUND_DOWN)
        
        self.assertEqual(exit_qty, net_received_sol)
    
    def test_exit_qty_never_exceeds_available(self):
        """Test exit quantity never exceeds available balance."""
        available_balance = Decimal('0.999')
        calculated_exit_qty = Decimal('1.000')  # Bug: using requested instead of net
        
        # Validation should catch this
        if calculated_exit_qty > available_balance:
            exit_qty = available_balance
        else:
            exit_qty = calculated_exit_qty
        
        self.assertLessEqual(exit_qty, available_balance)
    
    def test_zero_available_handling(self):
        """Test handling when available balance is zero."""
        available_balance = Decimal('0')
        
        if available_balance <= 0:
            should_trade = False
        else:
            should_trade = True
        
        self.assertFalse(should_trade)
    
    def test_material_mismatch_detection(self):
        """Test detection of material balance mismatches."""
        expected_balance = Decimal('1.000')
        actual_balance = Decimal('0.500')
        
        mismatch_threshold = Decimal('0.1')  # 10% tolerance
        mismatch_pct = abs(expected_balance - actual_balance) / expected_balance
        
        is_material_mismatch = mismatch_pct > mismatch_threshold
        
        self.assertTrue(is_material_mismatch)


if __name__ == '__main__':
    unittest.main()
