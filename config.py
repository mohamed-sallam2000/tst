#!/usr/bin/env python3
"""
config.py - Configuration and environment variables for OKX SOL/USDT trading bot.

All configurable parameters are defined here. Sensitive credentials must be
provided via environment variables, never hardcoded.
"""

import os
from decimal import Decimal
from dotenv import load_dotenv

# Load environment variables from .env file if present
load_dotenv()

# =============================================================================
# TRADING MODE
# =============================================================================
# Default to demo mode. Live mode must be explicitly enabled.
DEMO_MODE = os.getenv('DEMO_MODE', 'true').lower() == 'true'

# API Credentials (NEVER hardcode these)
OKX_API_KEY = os.getenv('OKX_API_KEY', '')
OKX_SECRET_KEY = os.getenv('OKX_SECRET_KEY', '')
OKX_PASSPHRASE = os.getenv('OKX_PASSPHRASE', '')

# Validate credentials in live mode
if not DEMO_MODE:
    if not all([OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE]):
        raise ValueError(
            "LIVE MODE: Missing required API credentials. "
            "Set OKX_API_KEY, OKX_SECRET_KEY, and OKX_PASSPHRASE environment variables."
        )

# =============================================================================
# TRADING UNIVERSE
# =============================================================================
SYMBOL = 'SOL/USDT'
BASE_ASSET = 'SOL'
QUOTE_ASSET = 'USDT'

# Timeframes
TIMEFRAME_TREND = '1h'    # Higher timeframe for trend filter
TIMEFRAME_ENTRY = '15m'   # Trading timeframe for entry signals

# =============================================================================
# CAPITAL AND RISK PARAMETERS
# =============================================================================
MAX_CAPITAL_USDT = float(os.getenv('MAX_CAPITAL_USDT', '1000'))
MAX_POSITION_NOTIONAL_PCT = float(os.getenv('MAX_POSITION_NOTIONAL_PCT', '35'))
RISK_PER_TRADE_PCT = float(os.getenv('RISK_PER_TRADE_PCT', '1.0'))

# Loss limits (percentages)
DAILY_MAX_LOSS_PCT = float(os.getenv('DAILY_MAX_LOSS_PCT', '2.0'))
WEEKLY_MAX_LOSS_PCT = float(os.getenv('WEEKLY_MAX_LOSS_PCT', '4.0'))
MONTHLY_MAX_DRAWDOWN_PCT = float(os.getenv('MONTHLY_MAX_DRAWDOWN_PCT', '6.0'))

# Profit target (objective, not guaranteed)
TARGET_MONTHLY_PROFIT_PCT = float(os.getenv('TARGET_MONTHLY_PROFIT_PCT', '5.0'))

# Minimum equity threshold (halt if below)
MIN_EQUITY_USDT = float(os.getenv('MIN_EQUITY_USDT', '940'))

# =============================================================================
# PRESERVATION MODE PARAMETERS
# =============================================================================
# When MTD profit reaches TARGET_MONTHLY_PROFIT_PCT, reduce risk:
PRESERVATION_RISK_PER_TRADE_PCT = float(os.getenv('PRESERVATION_RISK_PER_TRADE_PCT', '0.5'))
PRESERVATION_MAX_POSITION_PCT = float(os.getenv('PRESERVATION_MAX_POSITION_PCT', '20'))

# =============================================================================
# ORDER AND EXECUTION PARAMETERS
# =============================================================================
# Limit order TTL in seconds
ORDER_TTL_SECONDS = int(os.getenv('ORDER_TTL_SECONDS', '60'))

# Fee assumptions (fallback if cannot fetch from exchange)
FEE_ROUNDTRIP_PCT_FALLBACK = float(os.getenv('FEE_ROUNDTRIP_PCT_FALLBACK', '0.2'))
SLIPPAGE_ASSUMPTION_PCT = float(os.getenv('SLIPPAGE_ASSUMPTION_PCT', '0.1'))

# Minimum order size in USDT (OKX spot minimum)
MIN_ORDER_SIZE_USDT = float(os.getenv('MIN_ORDER_SIZE_USDT', '5'))

# Maximum open positions (always 1 for this strategy)
MAX_OPEN_POSITIONS = 1

# =============================================================================
# STRATEGY PARAMETERS - HIGHER TIMEFRAME TREND FILTER (1h)
# =============================================================================
# Trend must be bullish: close > EMA_200
TREND_EMA_200_PERIOD = int(os.getenv('TREND_EMA_200_PERIOD', '200'))

# EMA_50 must be above EMA_200
TREND_EMA_50_PERIOD = int(os.getenv('TREND_EMA_50_PERIOD', '50'))

# ADX must be above this threshold (trend strength)
TREND_ADX_MIN = float(os.getenv('TREND_ADX_MIN', '20.0'))
TREND_ADX_PERIOD = int(os.getenv('TREND_ADX_PERIOD', '14'))

# ATR/Close must be below this (volatility filter)
TREND_ATR_RATIO_MAX = float(os.getenv('TREND_ATR_RATIO_MAX', '0.05'))
TREND_ATR_PERIOD = int(os.getenv('TREND_ATR_PERIOD', '14'))

# 24h price change must be above this (avoid severe crashes)
TREND_24H_CHANGE_MIN_PCT = float(os.getenv('TREND_24H_CHANGE_MIN_PCT', '-8.0'))

# =============================================================================
# STRATEGY PARAMETERS - ENTRY TIMEFRAME (15m)
# =============================================================================
# Price must be above EMA_50
ENTRY_EMA_50_PERIOD = int(os.getenv('ENTRY_EMA_50_PERIOD', '50'))

# EMA_20 must be above EMA_50
ENTRY_EMA_20_PERIOD = int(os.getenv('ENTRY_EMA_20_PERIOD', '20'))

# RSI must be above this (momentum)
ENTRY_RSI_MIN = float(os.getenv('ENTRY_RSI_MIN', '55.0'))
ENTRY_RSI_PERIOD = int(os.getenv('ENTRY_RSI_PERIOD', '14'))

# RSI must be rising (current > previous)
ENTRY_RSI_MOMENTUM_REQUIRED = os.getenv('ENTRY_RSI_MOMENTUM_REQUIRED', 'true').lower() == 'true'

# Volume must be above SMA_20 by this factor
ENTRY_VOLUME_SMA_PERIOD = int(os.getenv('ENTRY_VOLUME_SMA_PERIOD', '20'))
ENTRY_VOLUME_MULTIPLIER = float(os.getenv('ENTRY_VOLUME_MULTIPLIER', '1.2'))

# Bid-ask spread must be below this (percent)
ENTRY_SPREAD_MAX_PCT = float(os.getenv('ENTRY_SPREAD_MAX_PCT', '0.08'))

# Pullback confirmation lookback candles
ENTRY_PULLBACK_LOOKBACK = int(os.getenv('ENTRY_PULLBACK_LOOKBACK', '5'))

# =============================================================================
# EXIT PARAMETERS
# =============================================================================
# Stop-loss distance: max(1.5 * ATR, 0.8% of entry)
EXIT_STOP_ATR_MULTIPLIER = float(os.getenv('EXIT_STOP_ATR_MULTIPLIER', '1.5'))
EXIT_STOP_MIN_PCT = float(os.getenv('EXIT_STOP_MIN_PCT', '0.8'))
EXIT_STOP_MAX_PCT = float(os.getenv('EXIT_STOP_MAX_PCT', '3.0'))

# Take-profit: 2R minimum
EXIT_TP_R_MULTIPLE = float(os.getenv('EXIT_TP_R_MULTIPLE', '2.0'))

# Time stop: exit after this many hours if profit < threshold
EXIT_TIME_STOP_HOURS = int(os.getenv('EXIT_TIME_STOP_HOURS', '24'))
EXIT_TIME_STOP_MIN_R = float(os.getenv('EXIT_TIME_STOP_MIN_R', '0.2'))

# Optional: move stop to breakeven at +1R
EXIT_BREAKEVEN_AT_R = float(os.getenv('EXIT_BREAKEVEN_AT_R', '1.0'))

# =============================================================================
# DATABASE AND PERSISTENCE
# =============================================================================
DB_PATH = os.getenv('DB_PATH', 'okx_sol_bot.db')
LOCK_FILE = os.getenv('LOCK_FILE', '/tmp/okx_sol_bot.lock')

# =============================================================================
# LOGGING
# =============================================================================
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
LOG_FILE = os.getenv('LOG_FILE', 'okx_sol_bot.log')

# =============================================================================
# AWS / DEPLOYMENT
# =============================================================================
USE_AWS_SECRETS = os.getenv('USE_AWS_SECRETS', 'false').lower() == 'true'
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
SECRET_NAME = os.getenv('SECRET_NAME', 'okx_trading_bot_credentials')

# =============================================================================
# VALIDATION
# =============================================================================
def validate_config():
    """Validate configuration parameters."""
    errors = []
    
    if MAX_CAPITAL_USDT <= 0:
        errors.append("MAX_CAPITAL_USDT must be positive")
    
    if not (0 < MAX_POSITION_NOTIONAL_PCT <= 100):
        errors.append("MAX_POSITION_NOTIONAL_PCT must be between 0 and 100")
    
    if not (0 < RISK_PER_TRADE_PCT <= 100):
        errors.append("RISK_PER_TRADE_PCT must be between 0 and 100")
    
    if DAILY_MAX_LOSS_PCT <= 0:
        errors.append("DAILY_MAX_LOSS_PCT must be positive")
    
    if WEEKLY_MAX_LOSS_PCT <= 0:
        errors.append("WEEKLY_MAX_LOSS_PCT must be positive")
    
    if MONTHLY_MAX_DRAWDOWN_PCT <= 0:
        errors.append("MONTHLY_MAX_DRAWDOWN_PCT must be positive")
    
    if MIN_EQUITY_USDT >= MAX_CAPITAL_USDT:
        errors.append("MIN_EQUITY_USDT must be less than MAX_CAPITAL_USDT")
    
    if PRESERVATION_RISK_PER_TRADE_PCT >= RISK_PER_TRADE_PCT:
        errors.append("PRESERVATION_RISK_PER_TRADE_PCT should be less than RISK_PER_TRADE_PCT")
    
    if EXIT_STOP_MIN_PCT >= EXIT_STOP_MAX_PCT:
        errors.append("EXIT_STOP_MIN_PCT must be less than EXIT_STOP_MAX_PCT")
    
    if errors:
        raise ValueError(f"Configuration errors: {'; '.join(errors)}")
    
    return True


# Run validation on import
validate_config()
