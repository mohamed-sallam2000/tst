#!/usr/bin/env python3
"""
test_risk.py - Unit tests for risk management module.

Tests position sizing, risk halts, daily/weekly/monthly loss limits,
preservation mode, and equity protection logic.
"""

import unittest
from decimal import Decimal
from datetime import datetime, timezone, timedelta

from risk import (
    calculate_position_size,
    check_risk_halt,
    update_daily_pnl,
    update_weekly_pnl,
    update_monthly_drawdown,
    check_profit_preservation_mode,
    RiskState
)


class TestPositionSizing(unittest.TestCase):
    """Test position sizing calculations."""
    
    def test_basic_position_sizing(self):
        """Test basic position size calculation with normal parameters."""
        equity = 1000.0
        stop_distance_pct = 0.015  # 1.5%
        risk_per_trade_pct = 1.0
        max_position_pct = 35.0
        
        position_size = calculate_position_size(
            equity=equity,
            stop_distance_pct=stop_distance_pct,
            risk_per_trade_pct=risk_per_trade_pct,
            max_position_pct=max_position_pct
        )
        
        # Risk amount = 1000 * 1% = 10 USDT
        # Position = min(350, 10 / 0.015) = min(350, 666.67) = 350
        self.assertAlmostEqual(position_size, 350.0, places=2)
    
    def test_tight_stop_increases_position(self):
        """Test that tighter stops allow larger positions up to max."""
        equity = 1000.0
        stop_distance_pct = 0.005  # 0.5% - very tight
        risk_per_trade_pct = 1.0
        max_position_pct = 35.0
        
        position_size = calculate_position_size(
            equity=equity,
            stop_distance_pct=stop_distance_pct,
            risk_per_trade_pct=risk_per_trade_pct,
            max_position_pct=max_position_pct
        )
        
        # Risk amount = 10 USDT
        # Position based on risk = 10 / 0.005 = 2000 USDT
        # But capped at max 35% = 350 USDT
        self.assertAlmostEqual(position_size, 350.0, places=2)
    
    def test_wide_stop_reduces_position(self):
        """Test that wider stops reduce position size below max."""
        equity = 1000.0
        stop_distance_pct = 0.03  # 3% - wide stop
        risk_per_trade_pct = 1.0
        max_position_pct = 35.0
        
        position_size = calculate_position_size(
            equity=equity,
            stop_distance_pct=stop_distance_pct,
            risk_per_trade_pct=risk_per_trade_pct,
            max_position_pct=max_position_pct
        )
        
        # Risk amount = 10 USDT
        # Position based on risk = 10 / 0.03 = 333.33 USDT
        # This is below max 350, so use 333.33
        self.assertAlmostEqual(position_size, 333.33, places=2)
    
    def test_zero_equity_returns_zero(self):
        """Test that zero equity returns zero position size."""
        position_size = calculate_position_size(
            equity=0.0,
            stop_distance_pct=0.015,
            risk_per_trade_pct=1.0,
            max_position_pct=35.0
        )
        self.assertEqual(position_size, 0.0)
    
    def test_large_stop_distance_returns_small_position(self):
        """Test that very large stop distance results in minimal position."""
        equity = 1000.0
        stop_distance_pct = 0.10  # 10% - extremely wide
        risk_per_trade_pct = 1.0
        max_position_pct = 35.0
        
        position_size = calculate_position_size(
            equity=equity,
            stop_distance_pct=stop_distance_pct,
            risk_per_trade_pct=risk_per_trade_pct,
            max_position_pct=max_position_pct
        )
        
        # Risk amount = 10 USDT
        # Position based on risk = 10 / 0.10 = 100 USDT
        self.assertAlmostEqual(position_size, 100.0, places=2)


class TestRiskHalt(unittest.TestCase):
    """Test risk halt conditions."""
    
    def test_no_halt_when_within_limits(self):
        """Test no halt when all metrics are within limits."""
        state = RiskState(
            daily_loss=Decimal('10'),  # 1% of 1000
            weekly_loss=Decimal('20'),  # 2% of 1000
            monthly_drawdown=Decimal('3'),  # 3%
            month_to_date_profit=Decimal('0'),
            last_reset_date=datetime.now(timezone.utc).date()
        )
        
        halt_reason = check_risk_halt(state)
        self.assertIsNone(halt_reason)
    
    def test_daily_loss_halt(self):
        """Test halt triggered by daily loss limit."""
        state = RiskState(
            daily_loss=Decimal('25'),  # 2.5% > 2% limit
            weekly_loss=Decimal('30'),
            monthly_drawdown=Decimal('4'),
            month_to_date_profit=Decimal('0'),
            last_reset_date=datetime.now(timezone.utc).date()
        )
        
        halt_reason = check_risk_halt(state)
        self.assertIsNotNone(halt_reason)
        self.assertIn('daily', halt_reason.lower())
    
    def test_weekly_loss_halt(self):
        """Test halt triggered by weekly loss limit."""
        state = RiskState(
            daily_loss=Decimal('10'),
            weekly_loss=Decimal('45'),  # 4.5% > 4% limit
            monthly_drawdown=Decimal('4'),
            month_to_date_profit=Decimal('0'),
            last_reset_date=datetime.now(timezone.utc).date()
        )
        
        halt_reason = check_risk_halt(state)
        self.assertIsNotNone(halt_reason)
        self.assertIn('weekly', halt_reason.lower())
    
    def test_monthly_drawdown_halt(self):
        """Test halt triggered by monthly drawdown limit."""
        state = RiskState(
            daily_loss=Decimal('5'),
            weekly_loss=Decimal('20'),
            monthly_drawdown=Decimal('7'),  # 7% > 6% limit
            month_to_date_profit=Decimal('0'),
            last_reset_date=datetime.now(timezone.utc).date()
        )
        
        halt_reason = check_risk_halt(state)
        self.assertIsNotNone(halt_reason)
        self.assertIn('monthly', halt_reason.lower())
    
    def test_equity_below_minimum_halt(self):
        """Test halt when equity falls below minimum threshold."""
        state = RiskState(
            daily_loss=Decimal('5'),
            weekly_loss=Decimal('20'),
            monthly_drawdown=Decimal('5'),
            month_to_date_profit=Decimal('0'),
            last_reset_date=datetime.now(timezone.utc).date(),
            current_equity=Decimal('930')  # Below 940 minimum
        )
        
        halt_reason = check_risk_halt(state, current_equity=Decimal('930'))
        self.assertIsNotNone(halt_reason)
        self.assertIn('equity', halt_reason.lower())


class TestProfitPreservationMode(unittest.TestCase):
    """Test profit preservation mode activation."""
    
    def test_preservation_mode_activates_at_target(self):
        """Test preservation mode activates when MTD profit reaches target."""
        state = RiskState(
            daily_loss=Decimal('0'),
            weekly_loss=Decimal('0'),
            monthly_drawdown=Decimal('0'),
            month_to_date_profit=Decimal('55'),  # 5.5% of 1000
            last_reset_date=datetime.now(timezone.utc).date()
        )
        
        is_preservation, reduced_risk, reduced_position = check_profit_preservation_mode(
            state, initial_capital=Decimal('1000')
        )
        
        self.assertTrue(is_preservation)
        self.assertAlmostEqual(reduced_risk, 0.5, places=2)  # Reduced from 1.0%
        self.assertAlmostEqual(reduced_position, 20.0, places=2)  # Reduced from 35%
    
    def test_preservation_mode_not_active_below_target(self):
        """Test preservation mode not active when below target."""
        state = RiskState(
            daily_loss=Decimal('0'),
            weekly_loss=Decimal('0'),
            monthly_drawdown=Decimal('0'),
            month_to_date_profit=Decimal('45'),  # 4.5% < 5% target
            last_reset_date=datetime.now(timezone.utc).date()
        )
        
        is_preservation, reduced_risk, reduced_position = check_profit_preservation_mode(
            state, initial_capital=Decimal('1000')
        )
        
        self.assertFalse(is_preservation)
        self.assertIsNone(reduced_risk)
        self.assertIsNone(reduced_position)
    
    def test_preservation_mode_exact_target(self):
        """Test preservation mode activates at exactly 5% target."""
        state = RiskState(
            daily_loss=Decimal('0'),
            weekly_loss=Decimal('0'),
            monthly_drawdown=Decimal('0'),
            month_to_date_profit=Decimal('50'),  # Exactly 5% of 1000
            last_reset_date=datetime.now(timezone.utc).date()
        )
        
        is_preservation, reduced_risk, reduced_position = check_profit_preservation_mode(
            state, initial_capital=Decimal('1000')
        )
        
        self.assertTrue(is_preservation)


class TestDailyPnlUpdate(unittest.TestCase):
    """Test daily PnL tracking and reset."""
    
    def test_daily_loss_accumulates(self):
        """Test daily loss accumulates correctly."""
        state = RiskState(
            daily_loss=Decimal('10'),
            weekly_loss=Decimal('20'),
            monthly_drawdown=Decimal('3'),
            month_to_date_profit=Decimal('0'),
            last_reset_date=datetime.now(timezone.utc).date()
        )
        
        new_state = update_daily_pnl(state, Decimal('-15'))  # 15 USDT loss
        
        self.assertEqual(new_state.daily_loss, Decimal('25'))
    
    def test_daily_profit_reduces_loss(self):
        """Test daily profit reduces accumulated loss."""
        state = RiskState(
            daily_loss=Decimal('20'),
            weekly_loss=Decimal('30'),
            monthly_drawdown=Decimal('4'),
            month_to_date_profit=Decimal('10'),
            last_reset_date=datetime.now(timezone.utc).date()
        )
        
        new_state = update_daily_pnl(state, Decimal('15'))  # 15 USDT profit
        
        # Daily loss should reduce but not go negative
        self.assertEqual(new_state.daily_loss, Decimal('5'))
        self.assertEqual(new_state.month_to_date_profit, Decimal('25'))
    
    def test_daily_reset_on_new_day(self):
        """Test daily loss resets on new UTC day."""
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        state = RiskState(
            daily_loss=Decimal('20'),
            weekly_loss=Decimal('30'),
            monthly_drawdown=Decimal('4'),
            month_to_date_profit=Decimal('10'),
            last_reset_date=yesterday
        )
        
        new_state = update_daily_pnl(state, Decimal('0'), force_reset=True)
        
        self.assertEqual(new_state.daily_loss, Decimal('0'))
        self.assertEqual(new_state.last_reset_date, datetime.now(timezone.utc).date())


if __name__ == '__main__':
    unittest.main()
