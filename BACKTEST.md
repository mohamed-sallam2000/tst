# Backtesting and Validation Methodology

## Document Purpose

This document describes the backtesting methodology, validation procedures, and go/no-go criteria for the OKX SOL/USDT trading bot.

**Important**: Backtest results are historical simulations only. They do NOT guarantee future performance. Live results will differ due to:
- Slippage variations
- Fee changes
- Market regime shifts
- Execution delays
- Software bugs

---

## Table of Contents

1. [Backtest Engine Overview](#backtest-engine-overview)
2. [Data Requirements](#data-requirements)
3. [Simulation Assumptions](#simulation-assumptions)
4. [Metrics Calculated](#metrics-calculated)
5. [Go/No-Go Criteria](#gono-go-criteria)
6. [Walk-Forward Validation](#walk-forward-validation)
7. [Paper Trading Transition](#paper-trading-transition)
8. [Results Template](#results-template)
9. [Checklists](#checklists)

---

## 1. Backtest Engine Overview

The backtest engine (`backtest.py`) simulates the exact trading logic that will run in live mode:

- Same entry signals (1h trend filter + 15m trigger)
- Same exit rules (stop-loss, take-profit, time-stop)
- Same risk management (position sizing, loss halts)
- Same fee and slippage assumptions
- Same lot-size precision handling

### Key Features

- **Vectorized Calculation**: Uses pandas/numpy for fast indicator computation
- **Event-Driven Simulation**: Processes candles sequentially (no lookahead bias)
- **Completed Candles Only**: Signals generated only after candle close
- **Fee Deduction Modeling**: Simulates base-asset fee deduction
- **Lot-Size Rounding**: Applies exchange precision rules
- **Risk Halt Tracking**: Records when daily/weekly/monthly limits hit

### What's NOT Simulated

- Order book depth impact (assumes infinite liquidity at best bid/ask)
- Network latency (assumes instant execution at close price)
- Partial fills on entries (assumes full fill or no fill)
- Exchange downtime (assumes continuous market access)
- Slippage variation (uses fixed 0.1% assumption)

These simplifications may make backtests **optimistic** vs. live results.

---

## 2. Data Requirements

### Minimum Data

- **Symbol**: SOL/USDT spot
- **Timeframes**: 15m (entry) and 1h (trend filter)
- **History**: Minimum 180 days (6 months), preferably 365+ days (1 year)
- **Fields**: timestamp, open, high, low, close, volume

### Data Source

Data fetched via ccxt from OKX:

```python
exchange = ccxt.okx({'enableRateLimit': True})
candles = exchange.fetch_ohlcv('SOL/USDT', '15m', since=timestamp_ms, limit=1500)
```

### Data Validation

Before backtesting, validate:

```python
def validate_data(df: pd.DataFrame) -> bool:
    # No zero prices
    assert (df['close'] > 0).all(), "Zero close prices found"
    assert (df['high'] > 0).all(), "Zero high prices found"
    assert (df['low'] > 0).all(), "Zero low prices found"
    
    # No negative volumes
    assert (df['volume'] >= 0).all(), "Negative volume found"
    
    # High >= Low >= Close relationships
    assert (df['high'] >= df['low']).all(), "High < Low"
    assert (df['high'] >= df['close']).all(), "High < Close"
    assert (df['low'] <= df['close']).all(), "Low > Close"
    
    # No duplicate timestamps
    assert df.index.is_unique, "Duplicate timestamps found"
    
    # Reasonable price movements (no 50% single-candle moves)
    returns = df['close'].pct_change().abs()
    assert (returns < 0.5).all(), "Extreme single-candle movement"
    
    return True
```

### Handling Gaps

If data has gaps (missing candles):

```python
# Forward-fill missing candles with previous values
df = df.reindex(full_date_range, method='ffill')

# OR skip gaps entirely (conservative)
# Gaps indicate illiquid periods; better to avoid trading then
```

---

## 3. Simulation Assumptions

### Fees

```python
FEE_ROUNDTRIP_PCT = 0.2  # 0.2% round trip
ENTRY_FEE = 0.001        # 0.1% entry
EXIT_FEE = 0.001         # 0.1% exit
```

**Rationale**: OKX standard taker fee is ~0.1% per side. May be lower with fee discounts.

**Base Asset Deduction**: Simulation assumes fees deducted from SOL received on buys.

### Slippage

```python
SLIPPAGE_PCT = 0.001  # 0.1% assumed on market orders (exits)
```

**Rationale**: SOL/USDT typically has tight spreads, but:
- Larger orders may slip more
- Volatile periods increase slippage
- Weekend/night liquidity thinner

**Entry Slippage**: Assumed zero for limit orders that fill (entered at limit price).

### Limit Order Fill Model

For entry limit orders:

```python
# Simplified fill model
if limit_price <= candle_low:
    # Order would have filled at some point during candle
    fill_price = limit_price  # Optimistic: fills at exact limit
    filled = True
else:
    # Price never reached limit
    filled = False
```

**Reality**: May not fill even if low touches limit (order book queue position unknown).

### Exit Execution

All exits simulated as market orders:

```python
exit_price = next_candle_open * (1 - slippage_pct)  # For sells
```

**Reality**: 
- Stop-losses may trigger on wicks (fill worse than expected)
- Take-profits may partially fill
- Time-stops executed at next candle open

### Position Sizing

Uses exact formula from live bot:

```python
risk_amount = equity * (RISK_PER_TRADE_PCT / 100)
max_notional = equity * (MAX_POSITION_NOTIONAL_PCT / 100)
notional = min(max_notional, risk_amount / stop_distance_pct)
quantity = floor_to_lot_size(notional / entry_price)
```

### Minimum Order Size

```python
MIN_ORDER_USDT = 5.0  # OKX typical minimum

if quantity * price < MIN_ORDER_USDT:
    skip_trade = True
```

---

## 4. Metrics Calculated

### Return Metrics

| Metric | Formula | Target |
|--------|---------|--------|
| Total Return % | `(Final - Initial) / Initial × 100` | > 0% |
| Monthly Return % | `Total / Months` | ~3-5% |
| Annualized Return % | `(1 + Total)^(12/Months) - 1` | > 20% |

### Risk Metrics

| Metric | Formula | Target |
|--------|---------|--------|
| Max Drawdown % | `Max peak-to-trough decline` | < 10% |
| Longest Drawdown Duration | `Days in max drawdown` | < 30 days |
| Daily Loss Halts | `Count of daily halt events` | Track only |
| Weekly Loss Halts | `Count of weekly halt events` | Track only |

### Trade Statistics

| Metric | Formula | Target |
|--------|---------|--------|
| Total Trades | `Count of completed trades` | ≥ 100 |
| Win Rate % | `Wins / Total × 100` | 40-55% |
| Avg Win (R) | `Mean R-multiple on winners` | ~2.0R |
| Avg Loss (R) | `Mean R-multiple on losers` | ~1.0R |
| Profit Factor | `Gross Wins / Gross Losses` | > 1.3 |
| Expectancy (R) | `(Win% × Avg Win) - (Loss% × Avg Loss)` | > 0.5R |

### Efficiency Metrics

| Metric | Formula | Target |
|--------|---------|--------|
| Sharpe Ratio | `Mean(returns) / Std(returns) × √(252×96)` | > 1.0 |
| Sortino Ratio | `Mean(returns) / Std(negative returns) × √(252×96)` | > 1.5 |
| Trades/Month | `Total trades / Months` | 3-8 |
| Avg Holding Time | `Mean trade duration` | 4-24 hours |
| Exposure Time % | `Time in market / Total time` | 20-50% |

### Robustness Metrics

| Metric | Description | Target |
|--------|-------------|--------|
| Parameter Sensitivity | P&L change with ±10% parameter shifts | < 30% degradation |
| Monthly Return Distribution | Standard deviation of monthly returns | Low variance |
| Worst Trade | Largest single loss | < 2% account |
| Best Trade | Largest single win | Track only |
| Consecutive Losses | Max losing streak | < 6 trades |

---

## 5. Go/No-Go Criteria

### Mandatory Criteria (ALL must pass)

The strategy proceeds to paper trading ONLY if:

```markdown
□ Positive net return after fees/slippage
   Result: $X,XXX.XX (must be > $0)

□ Profit factor > 1.3
   Result: X.XX (must be > 1.3)

□ Maximum drawdown < 10%
   Result: XX.X% (must be < 10%)

□ At least 100 simulated trades
   Result: XXX trades (must be ≥ 100)

□ No single trade contributes > 20% of total profit
   Result: XX% (must be < 20%)

□ Returns distributed across multiple months
   Result: X of Y months profitable (must be > 50%)

□ Strategy does not require breaching risk limits
   Result: All halts within acceptable frequency

□ 5% target assessment documented
   Result: Achievable YES/NO with caveats
```

### Advisory Criteria (Should pass)

```markdown
□ Sharpe ratio > 1.0
□ Sortino ratio > 1.5
□ Win rate between 40-55%
□ Average holding time < 48 hours
□ No month with > 5% loss
□ Maximum consecutive losses < 6
```

### Automatic Fail Conditions

If ANY of these occur, DO NOT proceed to paper trading:

```markdown
✗ Negative total return
✗ Profit factor < 1.0
✗ Maximum drawdown > 15%
✗ Single parameter setting drives all profits
✗ Requires loosening filters to achieve returns
✗ Martingale-like behavior detected (increasing size after losses)
```

---

## 6. Walk-Forward Validation

### Methodology

Instead of testing on entire dataset at once, use rolling windows:

```
Period 1: Months 1-6  → Train on 1-4, Test on 5-6
Period 2: Months 2-7  → Train on 2-5, Test on 6-7
Period 3: Months 3-8  → Train on 3-6, Test on 7-8
...
```

For this bot (no training/optimization), simpler approach:

```
Segment 1: Months 1-3  → Full backtest
Segment 2: Months 4-6  → Full backtest
Segment 3: Months 7-9  → Full backtest
Segment 4: Months 10-12 → Full backtest
```

### Validation Checks

For each segment, verify:

1. **Consistency**: Similar win rates, profit factors across segments
2. **No Degradation**: Later segments not significantly worse than early
3. **Regime Coverage**: At least one trending and one ranging segment

### Red Flags

```markdown
✗ First segment great, last segment terrible (overfitting to early data)
✗ One segment has 80% of total profit (concentration risk)
✗ Strategy fails completely in ranging market segments
✗ Performance highly dependent on single large trade
```

---

## 7. Paper Trading Transition

After backtests pass go/no-go criteria:

### Setup Paper Trading

```bash
# Edit .env
TRADING_MODE=demo

# Start bot
python main.py
```

### Paper Trading Duration

**Minimum**: 14 calendar days  
**Recommended**: 30 calendar days

### Paper Trading Validation

Compare paper results to backtest expectations:

| Metric | Backtest Expectation | Paper Actual | Variance |
|--------|---------------------|--------------|----------|
| Trade Frequency | X trades/month | X trades | ±20% OK |
| Win Rate | XX% | XX% | ±10% OK |
| Avg R-Multiple | X.XR | X.XR | ±0.5R OK |
| Max Drawdown | X% | X% | ±3% OK |

### Paper Trading Checklist

```markdown
Week 1:
□ Bot starts without errors
□ Indicators calculate correctly
□ Entry signals match manual verification
□ Position sizing matches expected values
□ Logs show correct fee deductions
□ SQLite persistence working

Week 2:
□ Exits trigger at correct levels
□ Stop-loss executes as expected
□ Take-profit executes as expected
□ Time-stop triggers appropriately
□ Risk halts work if triggered
□ State recovery works after restart

Week 3-4:
□ Trade frequency reasonable
□ No unexpected behavior
□ PnL tracking accurate
□ Equity curve matches expectations
□ No API rate limit issues
□ WebSocket monitoring stable

End of Period:
□ Total trades ≥ expected minimum
□ Win rate within expected range
□ No risk limit breaches
□ No critical errors in logs
□ Manual review of all trades completed
□ Ready for live consideration? YES/NO
```

### Paper Trading Go/No-Go

Proceed to live ONLY if:

```markdown
□ Paper trading completed ≥ 14 days
□ At least 5 trades executed (or explain why fewer)
□ No software bugs discovered
□ No risk limit breaches
□ Recovery tested successfully
□ All manual reviews passed
□ Emotional readiness confirmed (can handle real money?)
```

---

## 8. Results Template

### Backtest Report Template

```markdown
# Backtest Results: SOL/USDT Trend Following

## Test Parameters
- Period: YYYY-MM-DD to YYYY-MM-DD (X months)
- Initial Capital: $1,000
- Fee Assumption: 0.2% round trip
- Slippage Assumption: 0.1%

## Performance Summary
| Metric | Value |
|--------|-------|
| Final Capital | $X,XXX.XX |
| Total Return | XX.XX% |
| Monthly Return (avg) | X.XX% |
| Max Drawdown | X.XX% |
| Sharpe Ratio | X.XX |
| Sortino Ratio | X.XX |

## Trade Statistics
| Metric | Value |
|--------|-------|
| Total Trades | XXX |
| Winning Trades | XXX (XX%) |
| Losing Trades | XXX (XX%) |
| Avg Win (R) | X.XXR |
| Avg Loss (R) | X.XXR |
| Profit Factor | X.XX |
| Expectancy (R) | X.XXR |

## Risk Events
| Event Type | Count |
|------------|-------|
| Daily Loss Halts | X |
| Weekly Loss Halts | X |
| Monthly Drawdown Halts | X |
| Time Stop Exits | X |
| Stop-Loss Exits | X |
| Take-Profit Exits | X |

## Monthly Breakdown
| Month | Return % | Trades | Win Rate | Max DD |
|-------|----------|--------|----------|--------|
| Jan | +X.X% | XX | XX% | X.X% |
| Feb | -X.X% | XX | XX% | X.X% |
| ... | ... | ... | ... | ... |

## Go/No-Go Assessment
| Criterion | Required | Actual | Pass? |
|-----------|----------|--------|-------|
| Positive Return | > 0% | X.X% | ✓/✗ |
| Profit Factor | > 1.3 | X.XX | ✓/✗ |
| Max Drawdown | < 10% | X.X% | ✓/✗ |
| Min Trades | ≥ 100 | XXX | ✓/✗ |
| 5% Target Realistic | N/A | YES/NO | - |

## Conclusion
[ ] PROCEED TO PAPER TRADING
[ ] DO NOT PROCEED - Issues identified:
    - Issue 1
    - Issue 2

## Notes
[Any additional observations, concerns, or recommendations]
```

---

## 9. Checklists

### Pre-Backtest Checklist

```markdown
□ OHLCV data fetched for both timeframes (15m, 1h)
□ Data validated (no zeros, negatives, duplicates)
□ Date range sufficient (≥ 180 days)
□ Fee and slippage assumptions documented
□ Backtest engine code reviewed
□ Expected output format understood
```

### Post-Backtest Checklist

```markdown
□ Results exported and saved
□ All metrics calculated
□ Go/no-go criteria evaluated
□ Monthly breakdown reviewed
□ Worst trades analyzed
□ Parameter sensitivity checked
□ Decision documented (proceed/stop)
```

### Pre-Paper Trading Checklist

```markdown
□ Backtests passed all mandatory criteria
□ Code reviewed for bugs
□ Environment configured for demo mode
□ API keys set up (demo/testnet if available)
□ Logging enabled
□ Database initialized
□ Emergency stop procedure tested
□ Monitoring plan in place
```

### Post-Paper Trading Checklist

```markdown
□ Paper trading ran for ≥ 14 days
□ All trades manually reviewed
□ Results compared to backtest expectations
□ No critical bugs discovered
□ Recovery tested (restart bot, verify state)
□ Emotional readiness assessed
□ Decision documented (proceed to live/continue paper)
```

### Pre-Live Trading Checklist

```markdown
□ Paper trading completed successfully
□ Backtests show positive expectancy
□ All go/no-go criteria met
□ API keys configured with trade-only permissions
□ IP whitelisting enabled on OKX
□ Initial risk parameters reduced (0.25%, 15%)
□ Emergency contacts identified
□ Backup/recovery procedure documented
□ First 20 trades or 2 weeks monitoring plan ready
□ Mental preparation: can handle real losses?
```

---

## Final Warning

**BACKTESTS ARE NOT REALITY**

Even perfect backtests can fail in live trading because:

1. **Historical data ≠ Future data**: Market regimes change
2. **Simulation ≠ Reality**: Slippage, fees, execution vary
3. **Software can bug**: Code that works in backtest may fail live
4. **Psychology matters**: Paper trading doesn't test emotional resilience

Always start small. Always use stops. Always respect risk limits.

The 5% monthly target is an **objective**, not a guarantee. If market conditions don't allow safe trading, the bot will remain flat. This is correct behavior.

**Never risk capital you cannot afford to lose.**
