#!/usr/bin/env python3
"""
risk.py - Risk management module for OKX SOL/USDT trading bot.

Handles position sizing, risk halts, daily/weekly/monthly loss limits,
profit preservation mode, and equity protection.
"""

from decimal import Decimal
from datetime import datetime, timezone, date
from typing import Optional, Tuple
from dataclasses import dataclass, field

from config import (
    MAX_CAPITAL_USDT, MAX_POSITION_NOTIONAL_PCT, RISK_PER_TRADE_PCT,
    DAILY_MAX_LOSS_PCT, WEEKLY_MAX_LOSS_PCT, MONTHLY_MAX_DRAWDOWN_PCT,
    TARGET_MONTHLY_PROFIT_PCT, MIN_EQUITY_USDT,
    PRESERVATION_RISK_PER_TRADE_PCT, PRESERVATION_MAX_POSITION_PCT
)


@dataclass
class RiskState:
    """Current risk state of the trading bot."""
    
    daily_loss: Decimal = Decimal('0')
    weekly_loss: Decimal = Decimal('0')
    monthly_drawdown: Decimal = Decimal('0')
    month_to_date_profit: Decimal = Decimal('0')
    last_reset_date: date = field(default_factory=lambda: datetime.now(timezone.utc).date())
    current_equity: Optional[Decimal] = None
    
    # Halt flags
    daily_halt_active: bool = False
    weekly_halt_active: bool = False
    monthly_halt_active: bool = False
    equity_halt_active: bool = False
    
    # Preservation mode
    preservation_mode_active: bool = False


def calculate_position_size(
    equity: float,
    stop_distance_pct: float,
    risk_per_trade_pct: float = RISK_PER_TRADE_PCT,
    max_position_pct: float = MAX_POSITION_NOTIONAL_PCT
) -> float:
    """
    Calculate position size based on risk parameters.
    
    Position sizing formula:
        risk_amount_usdt = equity * risk_per_trade_pct / 100
        position_notional = min(
            equity * max_position_pct / 100,
            risk_amount_usdt / stop_distance_pct
        )
    
    Args:
        equity: Current account equity in USDT
        stop_distance_pct: Stop loss distance as percentage (e.g., 0.015 for 1.5%)
        risk_per_trade_pct: Risk per trade as percentage (default from config)
        max_position_pct: Maximum position as percentage of equity (default from config)
    
    Returns:
        Position notional value in USDT
    
    Note:
        If stop_distance_pct is zero or very small, position will be capped at max_position_pct.
        Returns 0 if equity is zero or negative.
    """
    if equity <= 0:
        return 0.0
    
    if stop_distance_pct <= 0:
        # Cannot calculate risk-based size without valid stop distance
        # Fall back to maximum allowed position
        return equity * (max_position_pct / 100)
    
    # Calculate risk amount
    risk_amount_usdt = equity * (risk_per_trade_pct / 100)
    
    # Calculate position based on risk
    risk_based_position = risk_amount_usdt / stop_distance_pct
    
    # Calculate maximum allowed position
    max_position = equity * (max_position_pct / 100)
    
    # Take minimum of risk-based and max position
    position_notional = min(risk_based_position, max_position)
    
    return position_notional


def check_risk_halt(state: RiskState, current_equity: Optional[Decimal] = None) -> Optional[str]:
    """
    Check if any risk halt conditions are triggered.
    
    Halt conditions:
    - Daily loss >= DAILY_MAX_LOSS_PCT of equity
    - Weekly loss >= WEEKLY_MAX_LOSS_PCT of equity
    - Monthly drawdown >= MONTHLY_MAX_DRAWDOWN_PCT
    - Current equity < MIN_EQUITY_USDT
    
    Args:
        state: Current RiskState
        current_equity: Optional current equity override
    
    Returns:
        Halt reason string if halted, None if trading allowed
    """
    equity = current_equity if current_equity is not None else (state.current_equity or Decimal(str(MAX_CAPITAL_USDT)))
    
    # Check equity floor first
    if equity < Decimal(str(MIN_EQUITY_USDT)):
        state.equity_halt_active = True
        return f"Equity {equity} USDT below minimum {MIN_EQUITY_USDT} USDT"
    
    # Check daily loss limit (2% of equity)
    daily_limit = equity * Decimal(str(DAILY_MAX_LOSS_PCT)) / Decimal('100')
    if state.daily_loss >= daily_limit:
        state.daily_halt_active = True
        return f"Daily loss {state.daily_loss} USDT exceeds limit {daily_limit} USDT ({DAILY_MAX_LOSS_PCT}%)"
    
    # Check weekly loss limit (4% of equity)
    weekly_limit = equity * Decimal(str(WEEKLY_MAX_LOSS_PCT)) / Decimal('100')
    if state.weekly_loss >= weekly_limit:
        state.weekly_halt_active = True
        return f"Weekly loss {state.weekly_loss} USDT exceeds limit {weekly_limit} USDT ({WEEKLY_MAX_LOSS_PCT}%)"
    
    # Check monthly drawdown limit (6%)
    if state.monthly_drawdown >= Decimal(str(MONTHLY_MAX_DRAWDOWN_PCT)):
        state.monthly_halt_active = True
        return f"Monthly drawdown {state.monthly_drawdown}% exceeds limit {MONTHLY_MAX_DRAWDOWN_PCT}%"
    
    # Check if any halt flags are still active from previous periods
    # (In production, these would be reset based on UTC day/week/month boundaries)
    if state.daily_halt_active:
        return "Daily halt still active (requires UTC day reset)"
    
    if state.weekly_halt_active:
        return "Weekly halt still active (requires UTC week reset)"
    
    if state.monthly_halt_active:
        return "Monthly halt still active (requires manual review)"
    
    if state.equity_halt_active:
        return "Equity halt still active (requires manual review)"
    
    return None


def update_daily_pnl(
    state: RiskState,
    pnl: Decimal,
    force_reset: bool = False
) -> RiskState:
    """
    Update daily PnL tracking.
    
    Args:
        state: Current RiskState
        pnl: Realized PnL from trade (positive for profit, negative for loss)
        force_reset: Force daily reset (used for testing or manual reset)
    
    Returns:
        Updated RiskState
    """
    today = datetime.now(timezone.utc).date()
    
    # Check if new day (UTC)
    if force_reset or state.last_reset_date < today:
        state.daily_loss = Decimal('0')
        state.last_reset_date = today
        state.daily_halt_active = False
    
    if pnl < 0:
        # Accumulate losses
        state.daily_loss += abs(pnl)
    else:
        # Profits reduce accumulated daily loss (but don't go negative)
        state.daily_loss = max(Decimal('0'), state.daily_loss - pnl)
        state.month_to_date_profit += pnl
    
    return state


def update_weekly_pnl(state: RiskState, pnl: Decimal) -> RiskState:
    """
    Update weekly PnL tracking.
    
    Args:
        state: Current RiskState
        pnl: Realized PnL from trade
    
    Returns:
        Updated RiskState
    """
    if pnl < 0:
        state.weekly_loss += abs(pnl)
    else:
        state.weekly_loss = max(Decimal('0'), state.weekly_loss - pnl)
    
    # Reset weekly halt if losses have been recovered
    weekly_limit = (state.current_equity or Decimal(str(MAX_CAPITAL_USDT))) * Decimal(str(WEEKLY_MAX_LOSS_PCT)) / Decimal('100')
    if state.weekly_loss < weekly_limit:
        state.weekly_halt_active = False
    
    return state


def update_monthly_drawdown(state: RiskState, current_equity: Decimal, peak_equity: Decimal) -> RiskState:
    """
    Update monthly drawdown tracking.
    
    Args:
        state: Current RiskState
        current_equity: Current account equity
        peak_equity: Peak equity for the month
    
    Returns:
        Updated RiskState
    """
    if peak_equity > 0:
        drawdown_pct = ((peak_equity - current_equity) / peak_equity) * Decimal('100')
        state.monthly_drawdown = max(state.monthly_drawdown, drawdown_pct)
    
    # Check if drawdown has recovered
    if state.monthly_drawdown >= Decimal(str(MONTHLY_MAX_DRAWDOWN_PCT)):
        current_dd = ((peak_equity - current_equity) / peak_equity) * Decimal('100') if peak_equity > 0 else Decimal('0')
        if current_dd < Decimal(str(MONTHLY_MAX_DRAWDOWN_PCT)):
            state.monthly_halt_active = False
            state.monthly_drawdown = current_dd
    
    state.current_equity = current_equity
    return state


def check_profit_preservation_mode(
    state: RiskState,
    initial_capital: Decimal = Decimal(str(MAX_CAPITAL_USDT))
) -> Tuple[bool, Optional[float], Optional[float]]:
    """
    Check if profit preservation mode should be activated.
    
    When month-to-date net realized profit reaches or exceeds TARGET_MONTHLY_PROFIT_PCT (5%),
    reduce risk parameters:
    - RISK_PER_TRADE_PCT reduced to PRESERVATION_RISK_PER_TRADE_PCT (0.5%)
    - MAX_POSITION_NOTIONAL_PCT reduced to PRESERVATION_MAX_POSITION_PCT (20%)
    
    Args:
        state: Current RiskState
        initial_capital: Initial capital for percentage calculation
    
    Returns:
        Tuple of (is_preservation_mode, reduced_risk_pct, reduced_position_pct)
    """
    mtd_profit_pct = (state.month_to_date_profit / initial_capital) * Decimal('100')
    
    if mtd_profit_pct >= Decimal(str(TARGET_MONTHLY_PROFIT_PCT)):
        state.preservation_mode_active = True
        return (
            True,
            PRESERVATION_RISK_PER_TRADE_PCT,
            PRESERVATION_MAX_POSITION_PCT
        )
    
    return False, None, None


def get_effective_risk_params(state: RiskState) -> Tuple[float, float]:
    """
    Get effective risk parameters considering preservation mode.
    
    Args:
        state: Current RiskState
    
    Returns:
        Tuple of (effective_risk_per_trade_pct, effective_max_position_pct)
    """
    if state.preservation_mode_active:
        return PRESERVATION_RISK_PER_TRADE_PCT, PRESERVATION_MAX_POSITION_PCT
    
    return RISK_PER_TRADE_PCT, MAX_POSITION_NOTIONAL_PCT


def reset_daily_limits(state: RiskState) -> RiskState:
    """Reset daily loss tracking (called at UTC midnight)."""
    state.daily_loss = Decimal('0')
    state.daily_halt_active = False
    state.last_reset_date = datetime.now(timezone.utc).date()
    return state


def reset_weekly_limits(state: RiskState) -> RiskState:
    """Reset weekly loss tracking (called at start of UTC week)."""
    state.weekly_loss = Decimal('0')
    state.weekly_halt_active = False
    return state


def require_manual_review_reset(state: RiskState) -> RiskState:
    """
    Reset monthly/equity halts after manual review.
    
    WARNING: Should only be called after human operator reviews account state.
    """
    state.monthly_halt_active = False
    state.equity_halt_active = False
    state.monthly_drawdown = Decimal('0')
    return state


def validate_trade_against_risk(
    state: RiskState,
    proposed_position_usdt: float,
    stop_distance_pct: float,
    equity: float
) -> Tuple[bool, Optional[str]]:
    """
    Validate a proposed trade against all risk rules.
    
    Args:
        state: Current RiskState
        proposed_position_usdt: Proposed position notional value
        stop_distance_pct: Stop loss distance as percentage
        equity: Current equity
    
    Returns:
        Tuple of (is_valid, rejection_reason)
        is_valid=True if trade passes all checks, rejection_reason=None
        is_valid=False if trade violates rules, rejection_reason explains why
    """
    # Check for active halts
    halt_reason = check_risk_halt(state)
    if halt_reason:
        return False, f"Risk halt active: {halt_reason}"
    
    # Check position size limit
    max_position = equity * (MAX_POSITION_NOTIONAL_PCT / 100)
    if proposed_position_usdt > max_position:
        return False, f"Position {proposed_position_usdt} exceeds max {max_position} ({MAX_POSITION_NOTIONAL_PCT}% of equity)"
    
    # Check risk-based sizing
    risk_amount = proposed_position_usdt * stop_distance_pct
    max_risk_amount = equity * (RISK_PER_TRADE_PCT / 100)
    
    if risk_amount > max_risk_amount:
        return False, f"Risk amount {risk_amount} exceeds limit {max_risk_amount} ({RISK_PER_TRADE_PCT}% of equity)"
    
    # Check minimum order size (imported from config)
    from config import MIN_ORDER_SIZE_USDT
    if proposed_position_usdt < MIN_ORDER_SIZE_USDT:
        return False, f"Position {proposed_position_usdt} below minimum order size {MIN_ORDER_SIZE_USDT}"
    
    return True, None
