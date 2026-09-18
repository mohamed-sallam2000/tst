# OKX SOL/USDT Spot Trading Bot

## ⚠️ Critical Risk Warnings

**READ THIS BEFORE USING THIS SOFTWARE:**

1. **NO PROFIT GUARANTEE**: This bot does NOT guarantee profits. The 5% monthly return target is an **objective only**, not a promise. Market conditions may prevent achieving this target while respecting risk limits.

2. **CAPITAL LOSS RISK**: Cryptocurrency trading involves substantial risk. You can lose money even with stop-losses due to slippage, gaps, and exchange issues.

3. **DEMO MODE DEFAULT**: The bot runs in demo/paper mode by default. Do NOT enable live trading until you have:
   - Successfully run backtests
   - Completed at least 14 days of paper trading
   - Verified all risk controls work correctly
   - Read and understood all documentation

4. **NOT FINANCIAL ADVICE**: This software is for educational and research purposes only. Consult a qualified financial advisor before trading real money.

5. **API KEY SECURITY**: Never commit API keys to Git or share them. Use environment variables or AWS Secrets Manager only.

---

## Table of Contents

1. [Overview](#overview)
2. [Features](#features)
3. [System Requirements](#system-requirements)
4. [Installation](#installation)
5. [Configuration](#configuration)
6. [Usage](#usage)
7. [Trading Strategy](#trading-strategy)
8. [Risk Management](#risk-management)
9. [Backtesting](#backtesting)
10. [Paper Trading](#paper-trading)
11. [Live Trading](#live-trading)
12. [Monitoring & Operations](#monitoring--operations)
13. [Troubleshooting](#troubleshooting)
14. [File Structure](#file-structure)

---

## Overview

This is a production-grade, conservative spot trading bot for **SOL/USDT only** on OKX. It implements:

- Multi-timeframe trend-following strategy (1h trend filter, 15m entry)
- Strict risk management with daily/weekly/monthly loss limits
- Dual-layer exit architecture (exchange OCO + local watchdog)
- SQLite persistence for crash recovery
- Demo and live trading modes
- Comprehensive backtesting engine

**Starting Capital**: 1,000 USDT (configurable)  
**Target**: 5% net monthly profit (objective, not guaranteed)  
**Priority**: Capital preservation over profit maximization

---

## Features

### Trading
- ✅ SOL/USDT spot trading only (no futures, margin, or shorts)
- ✅ Deterministic, rule-based entry signals
- ✅ Volatility-adjusted stop losses (ATR-based)
- ✅ 2R take-profit targets minimum
- ✅ Time-stop exits for stale positions
- ✅ Profit preservation mode after hitting targets

### Risk Management
- ✅ Maximum 1% risk per trade (reduces to 0.5% in preservation mode)
- ✅ Maximum 35% position size (reduces to 20% in preservation mode)
- ✅ Daily loss halt at 2%
- ✅ Weekly loss halt at 4%
- ✅ Monthly drawdown halt at 6%
- ✅ Equity protection halt below 940 USDT

### Technical
- ✅ OKX integration via ccxt
- ✅ SQLite persistence for all trades, orders, and state
- ✅ Crash recovery with state reconciliation
- ✅ Dual-layer exits (exchange + local watchdog)
- ✅ Fee deduction handling (base asset fees)
- ✅ Lot-size precision and minimum order checks
- ✅ WebSocket price monitoring (with REST fallback)
- ✅ Structured JSON logging

### Safety
- ✅ Demo mode by default
- ✅ Singleton process lock
- ✅ API key via environment variables only
- ✅ No keys in logs or database
- ✅ Graceful shutdown handling

---

## System Requirements

### Minimum
- Python 3.11+
- 1 GB RAM
- 10 GB disk space
- Stable internet connection
- UTC timezone

### Recommended (AWS EC2)
- Instance: t3.micro or t3.small
- Ubuntu 22.04 LTS or Amazon Linux 2023
- Python 3.11+
- 2 GB RAM
- 20 GB SSD
- CloudWatch Logs (optional)

---

## Installation

### Local Development

```bash
# Clone repository
git clone <repository-url>
cd okx-sol-bot

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env

# Edit .env with your configuration
nano .env
```

### AWS EC2 Deployment

See `AWS_EC2_DEPLOYMENT.md` for complete instructions.

Quick start:

```bash
# SSH into EC2
ssh -i your-key.pem ubuntu@your-ec2-ip

# Update system
sudo apt update && sudo apt upgrade -y

# Install Python
sudo apt install -y python3.11 python3.11-venv python3-pip

# Clone repo
git clone <repository-url>
cd okx-sol-bot

# Setup virtual environment
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp .env.example .env
nano .env  # Add API credentials

# Install systemd service
sudo cp okx_sol_bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable okx_sol_bot
```

---

## Configuration

### Environment Variables (.env)

```bash
# Required: Trading Mode
TRADING_MODE=demo  # 'demo' or 'live' - MUST be 'demo' initially

# Required: OKX API Credentials (NEVER commit these)
OKX_API_KEY=your_api_key
OKX_API_SECRET=your_api_secret
OKX_PASSPHRASE=your_passphrase

# Optional: Risk Parameters (defaults shown)
MAX_CAPITAL_USDT=1000
RISK_PER_TRADE_PCT=1.0
MAX_POSITION_NOTIONAL_PCT=35
DAILY_MAX_LOSS_PCT=2.0
WEEKLY_MAX_LOSS_PCT=4.0
MONTHLY_MAX_DRAWDOWN_PCT=6.0

# Optional: Strategy Parameters
EMA_SHORT_PERIOD=20
EMA_LONG_PERIOD=50
RSI_PERIOD=14
RSI_MIN=55.0
ADX_MIN=20.0
ATR_MULTIPLIER=1.5

# Optional: Logging
LOG_LEVEL=INFO
LOG_TO_FILE=true
LOG_DIR=./logs
```

### OKX API Key Setup

1. Go to OKX → Profile → API Management
2. Create new API key with:
   - **Permissions**: Trade ONLY (no withdrawal, no transfer)
   - **IP Whitelist**: Add your EC2 IP or development IP
   - **Passphrase**: Record securely
3. Store credentials in `.env` or AWS Secrets Manager

**Security Best Practices**:
- ❌ NEVER commit `.env` to Git
- ❌ NEVER log API credentials
- ✅ Use IP whitelisting
- ✅ Use trade-only permissions
- ✅ Rotate keys periodically

---

## Usage

### Run Backtest

```bash
source venv/bin/activate
python backtest.py
```

This will:
1. Fetch 180 days of historical SOL/USDT data
2. Calculate all indicators
3. Simulate trades with fees and slippage
4. Generate performance report

### Run Paper Trading

```bash
# Set mode to demo in .env
TRADING_MODE=demo

# Start bot
python main.py

# Or as background service
sudo systemctl start okx_sol_bot
```

Paper trading runs indefinitely, simulating live behavior without real funds.

### Run Live Trading

**PREREQUISITES**:
- ✅ Backtests show positive expectancy
- ✅ 14+ days successful paper trading
- ✅ All risk controls verified
- ✅ Emergency stop procedure tested

```bash
# Change .env
TRADING_MODE=live

# Restart bot
sudo systemctl restart okx_sol_bot
```

**Initial Live Settings** (first 20 trades or 2 weeks):
```bash
RISK_PER_TRADE_PCT=0.25
MAX_POSITION_NOTIONAL_PCT=15
```

---

## Trading Strategy

### Entry Conditions (ALL must be true)

#### Higher-Timeframe Trend Filter (1h)
- Close > EMA(200)
- EMA(50) > EMA(200)
- ADX(14) > 20.0
- ATR(14)/Close ≤ 5%
- 24h price change > -8%

#### Entry Trigger (15m)
- Close > EMA(50)
- EMA(20) > EMA(50)
- RSI(14) > 55.0
- RSI(14) > Previous RSI(14)
- Volume > 1.2 × SMA(Volume, 20)
- Pullback confirmed (see below)
- Bid-ask spread ≤ 0.08%

#### Pullback Confirmation
Within the previous 5 completed 15m candles:
- At least one candle's low ≤ that candle's EMA(50)
- Current signal candle's close > EMA(20)

### Exit Conditions

#### Stop Loss
- Distance = max(1.5 × ATR(14), 0.8% of entry)
- Capped at 3.0% maximum
- Hard exit (market order if needed)

#### Take Profit
- Target = Entry + 2.0 × (Entry - Stop)
- Minimum 2R reward

#### Time Stop
- 24 hours: Exit if unrealized profit < 0.2R
- 48 hours: Exit unless strong trend active

---

## Risk Management

### Position Sizing

```python
risk_amount = equity × (RISK_PER_TRADE_PCT / 100)
max_notional = equity × (MAX_POSITION_NOTIONAL_PCT / 100)
position_size = min(max_notional, risk_amount / stop_distance_pct)
```

### Loss Limits

| Period | Max Loss | Action |
|--------|----------|--------|
| Daily | 2% | Halt until next UTC day |
| Weekly | 4% | Halt until next UTC week |
| Monthly | 6% | Halt until manual review |
| Equity | < 940 USDT | Immediate halt |

### Profit Preservation

When month-to-date profit ≥ 5%:
- Risk per trade: 1.0% → 0.5%
- Max position: 35% → 20%
- Continues until next calendar month

### Risk Priority

1. Protect capital
2. Prevent uncontrolled loss
3. Maintain accurate state
4. Trade only valid setups
5. Pursue return objective
6. Stay flat when uncertain

---

## Backtesting

Run the backtest engine:

```bash
python backtest.py
```

### Go/No-Go Criteria

Strategy proceeds to paper trading ONLY if:

- ✅ Positive net return after fees/slippage
- ✅ Profit factor > 1.3
- ✅ Maximum drawdown < 10%
- ✅ At least 100 simulated trades
- ✅ No single parameter drives all profits
- ✅ Returns distributed across months
- ✅ Does not require breaching risk limits

If expected monthly return < 5% while respecting all rules, the bot clearly states this in the report. **Do not loosen filters to force more trades.**

See `BACKTEST.md` for detailed methodology.

---

## Paper Trading

### Requirements

Before live trading:

1. Run paper trading for **minimum 14 days**
2. Verify:
   - Entry signals match backtest expectations
   - Exit orders execute correctly
   - Risk halts trigger appropriately
   - Recovery works after restarts
   - Fees and balances reconcile
3. No risk limit breaches
4. No critical errors or lost states

### Monitoring Paper Trades

```bash
# View recent logs
tail -f logs/bot.log

# Check current position
sqlite3 trading.db "SELECT * FROM positions WHERE status='ACTIVE';"

# View trade history
sqlite3 trading.db "SELECT * FROM trades ORDER BY exit_time DESC LIMIT 10;"
```

### Paper Trading Checklist

See `BACKTEST.md` for complete checklist.

---

## Live Trading

### Pre-Live Checklist

- [ ] Backtests pass all go/no-go criteria
- [ ] 14+ days paper trading completed successfully
- [ ] Emergency stop procedure tested
- [ ] API keys configured with trade-only permissions
- [ ] IP whitelisting enabled
- [ ] Initial risk reduced (0.25% per trade, 15% max position)
- [ ] Monitoring/alerting configured
- [ ] Backup/recovery procedure documented

### Starting Live Mode

```bash
# Edit .env
TRADING_MODE=live
RISK_PER_TRADE_PCT=0.25
MAX_POSITION_NOTIONAL_PCT=15

# Restart
sudo systemctl restart okx_sol_bot

# Monitor closely
tail -f logs/bot.log
```

### After 20 Trades or 2 Weeks

If no issues:

```bash
# Increase to normal risk
RISK_PER_TRADE_PCT=1.0
MAX_POSITION_NOTIONAL_PCT=35

# Restart
sudo systemctl restart okx_sol_bot
```

---

## Monitoring & Operations

### Check Service Status

```bash
sudo systemctl status okx_sol_bot
```

### View Logs

```bash
# Real-time
tail -f logs/bot.log

# Last 100 lines
tail -n 100 logs/bot.log

# Search for errors
grep ERROR logs/bot.log
```

### Check Current State

```bash
# Active position
sqlite3 trading.db "SELECT * FROM positions WHERE status='ACTIVE';"

# Today's PnL
sqlite3 trading.db "SELECT SUM(net_pnl_usdt) FROM trades WHERE DATE(exit_time) = DATE('now');"

# Current risk state
sqlite3 trading.db "SELECT * FROM risk_state ORDER BY timestamp DESC LIMIT 1;"
```

### Emergency Stop

**Method 1: Systemd**
```bash
sudo systemctl stop okx_sol_bot
```

**Method 2: Kill Switch File**
```bash
touch /tmp/okx_bot_killswitch
sudo systemctl restart okx_sol_bot
```

**Method 3: Environment Variable**
```bash
# Edit .env
TRADING_MODE=halt

sudo systemctl restart okx_sol_bot
```

### Restart Procedure

```bash
# Graceful restart
sudo systemctl restart okx_sol_bot

# Verify recovery
tail -f logs/bot.log
sqlite3 trading.db "SELECT * FROM recovery_log ORDER BY timestamp DESC LIMIT 5;"
```

### Backup Database

```bash
# Compressed backup
sqlite3 trading.db ".backup 'backups/trading_backup_$(date +%Y%m%d_%H%M%S).db'"

# Encrypt (if using encryption)
gpg -c backups/trading_backup_*.db
```

---

## Troubleshooting

### Common Issues

#### "No trades executing"
- Check if trend filter conditions are met
- Verify pullback confirmation logic
- Check if risk halts are active
- Review logs for rejection reasons

#### "Order rejected: Insufficient balance"
- Verify fee deduction handling
- Check lot-size rounding
- Ensure sellable quantity ≤ actual balance

#### "Stop-loss not triggering"
- Check WebSocket connection
- Verify watchdog is running
- Review exchange OCO status

#### "State mismatch after restart"
- Check recovery logs
- Run manual reconciliation
- Compare SQLite state with OKX balances

### Getting Help

1. Check logs first: `tail -f logs/bot.log`
2. Review `DECISIONS.md` for design rationale
3. Check `BACKTEST.md` for expected behavior
4. Open GitHub issue with logs attached

---

## File Structure

```
okx-sol-bot/
├── config.py              # Configuration and constants
├── indicators.py          # Technical indicator calculations
├── risk.py               # Risk management engine
├── database.py           # SQLite schema and persistence
├── exchange.py           # OKX/ccxt integration
├── strategy.py           # Entry/exit signal logic
├── main.py               # Main runtime loop
├── backtest.py           # Backtesting engine
├── paper_trader.py       # Paper trading simulator
├── requirements.txt      # Python dependencies
├── .env.example          # Environment template
├── okx_sol_bot.service   # Systemd unit file
├── README.md            # This file
├── DECISIONS.md         # Design decisions
├── BACKTEST.md          # Backtest methodology
├── AWS_EC2_DEPLOYMENT.md # Deployment guide
├── logs/                # Log files
├── backups/             # Database backups
└── tests/
    ├── test_risk.py
    ├── test_indicators.py
    ├── test_exchange_precision.py
    └── test_recovery.py
```

---

## License

This software is provided for educational and research purposes only. Use at your own risk.

## Disclaimer

Cryptocurrency trading involves substantial risk of loss. Past performance does not guarantee future results. The 5% monthly return target is an objective only and may not be achieved. Never trade with money you cannot afford to lose.
