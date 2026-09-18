# Trading Decisions and Design Rationale

## Document Purpose

This document explains every material trading and engineering decision in the OKX SOL/USDT spot trading bot. It covers:

- Strategy logic and parameter justification
- Risk management rules
- Entry and exit rule definitions
- Fee and precision handling
- OCO/watchdog fallback architecture
- Monthly target reality assessment

**Last Updated**: 2024  
**Version**: 1.0

---

## Table of Contents

1. [Strategy Philosophy](#strategy-philosophy)
2. [Trading Universe Constraints](#trading-universe-constraints)
3. [Entry Logic Design](#entry-logic-design)
4. [Exit Logic Design](#exit-logic-design)
5. [Risk Management Rules](#risk-management-rules)
6. [Position Sizing Methodology](#position-sizing-methodology)
7. [Fee and Precision Handling](#fee-and-precision-handling)
8. [OCO and Watchdog Architecture](#oco-and-watchdog-architecture)
9. [Monthly Target Reality Check](#monthly-target-reality-check)
10. [Known Failure Modes](#known-failure-modes)
11. [Assumptions and Limitations](#assumptions-and-limitations)
12. [Parameter Sensitivity](#parameter-sensitivity)

---

## 1. Strategy Philosophy

### Core Principles

1. **Capital Preservation First**: The bot prioritizes avoiding large losses over maximizing gains. A 50% loss requires a 100% gain to recover.

2. **Positive Expectancy Required**: Every trade must have a mathematically positive expected value after fees and slippage.

3. **No Forced Trading**: If market conditions do not meet criteria, the bot remains flat. "No trade" is a valid position.

4. **Deterministic Over Subjective**: All rules are mathematically defined with no ambiguity. No "feels like" or "looks like" conditions.

5. **Simplicity Over Complexity**: Simple trend-following with volatility filters is preferred over complex ML models that may overfit.

6. **Robustness Across Regimes**: The strategy should work in trending, ranging, and volatile markets without manual intervention.

### Why Trend Following?

Trend following is chosen because:

- **Empirical Evidence**: SOL exhibits momentum characteristics on 15m-1h timeframes
- **Positive Skew**: Trends can produce large wins relative to small losses
- **No Prediction Required**: We follow price, not predict it
- **Well-Understood**: Decades of academic and practical research support trend following

**Why NOT Mean Reversion?**

- Requires precise entry timing
- Dangerous in strong trends (catching falling knives)
- Lower reward-to-risk ratios typically
- SOL can trend strongly for extended periods

The Exponential Ornstein-Uhlenbeck (XOU) model is included as an optional secondary filter but is NOT the primary signal driver. If XOU parameters indicate non-mean-reverting behavior (kappa ≤ 0), the filter is disabled.

---

## 2. Trading Universe Constraints

### SOL/USDT Only

**Decision**: Trade ONLY SOL/USDT spot. No other pairs, no futures, no margin.

**Rationale**:
- Focus reduces complexity and operational risk
- SOL has sufficient liquidity on OKX
- Spot trading avoids liquidation risk inherent in futures
- No funding rate complications
- Simpler accounting and tax reporting

**Implication**: Cannot short SOL. Only long positions allowed. In bear markets, the bot will be flat frequently.

### No Leverage

**Decision**: 1x spot only. No borrowing, no margin.

**Rationale**:
- Leverage amplifies both gains AND losses
- Liquidation risk unacceptable for capital preservation goal
- Fees on leveraged positions erode returns
- Psychological pressure leads to poor decisions

### Single Position Limit

**Decision**: Maximum 1 open position at a time.

**Rationale**:
- Simplifies risk management
- Prevents correlation risk (all trades are SOL anyway)
- Forces selectivity in entries
- Easier to monitor and manage exits

---

## 3. Entry Logic Design

### Multi-Timeframe Approach

**Decision**: Use 1h candles for trend filter, 15m candles for entry trigger.

**Rationale**:
- 1h trend filter avoids counter-trend trades on larger timeframe
- 15m entries provide better risk/reward than 1h entries (tighter stops)
- Reduces whipsaws from noise on single timeframe
- Standard practice in systematic trend following

### Higher-Timeframe Filter Conditions (1h)

All conditions must be true:

```python
close > EMA(200)          # Long-term uptrend
EMA(50) > EMA(200)        # Golden cross confirmation
ADX(14) > 20              # Sufficient trend strength
ATR(14)/close <= 0.05     # Volatility not excessive
24h_change > -8%          # No major crash in progress
```

**Parameter Justification**:

| Parameter | Value | Reasoning |
|-----------|-------|-----------|
| EMA(200) | 200 periods | Standard long-term trend proxy (~8 days on 1h) |
| EMA(50) | 50 periods | Intermediate trend (~2 days on 1h) |
| ADX > 20 | 20 | Below 20 indicates ranging market; avoid |
| ATR/close ≤ 5% | 0.05 | Filters extreme volatility regimes where stops unreliable |
| 24h change > -8% | -8% | Avoid catching falling knives after sharp drops |

**Why EMA instead of SMA?**
- EMA reacts faster to recent price changes
- Better for trend identification in crypto's fast markets
- Standard in most trading platforms

**Why ADX > 20?**
- ADX measures trend strength, not direction
- Values below 20 indicate weak/ranging markets
- Trend following performs poorly in ranges
- Avoids whipsaw losses

**Why ATR/close ≤ 5%?**
- Normalized volatility measure
- 5% threshold filters extreme volatility
- High volatility = wider stops = smaller position sizes
- Sometimes better to skip trade entirely

**Why 24h change > -8%?**
- Sharp drops often continue (momentum)
- Avoids "this is cheap" fallacy
- Wait for stabilization before entering

### Entry Trigger Conditions (15m)

All conditions must be true:

```python
close > EMA(50)           # Short-term bullish
EMA(20) > EMA(50)         # EMA alignment bullish
RSI(14) > 55              # Momentum positive
RSI(14) > prev_RSI(14)    # RSI rising
volume > 1.2 * SMA(vol, 20)  # Above-average volume
spread <= 0.08%           # Liquidity acceptable
pullback_confirmed        # Pullback entry (see below)
```

**Parameter Justification**:

| Parameter | Value | Reasoning |
|-----------|-------|-----------|
| EMA(20) | 20 periods | Short-term trend (~5 hours on 15m) |
| EMA(50) | 50 periods | Medium-term trend (~12.5 hours on 15m) |
| RSI > 55 | 55 | Above neutral (50) but not overbought (>70) |
| Volume multiplier | 1.2x | Confirms institutional interest |
| Spread ≤ 0.08% | 0.0008 | Ensures reasonable liquidity |

**Why RSI > 55 (not > 50)?**
- Provides stronger momentum confirmation
- Reduces false signals in choppy markets
- Still allows entries before overbought conditions

**Why Rising RSI?**
- Confirms momentum is accelerating
- Avoids divergences where price rises but momentum falls

**Why Volume > 1.2 × SMA?**
- Confirms breakout/breakdown validity
- Low-volume moves often reverse
- Institutional participation indicator

### Exact Pullback Confirmation Rule

**Definition**:

Within the previous 5 completed 15m candles (excluding current signal candle):
- At least one candle's low ≤ that same candle's EMA(50)

AND

Current signal candle:
- close > EMA(20)

**Rationale**:
- Enters on pullback to support (EMA(50)) rather than chasing breakouts
- Better risk/reward: entry closer to stop level
- Confirms trend continuation (price bounces from EMA)
- 5-candle window (~75 minutes) balances recency with opportunity frequency

**Why EMA(50) as pullback target?**
- Self-fulfilling: many traders watch this level
- Dynamic support in uptrends
- Tighter stops possible vs. horizontal support

**Why require close > EMA(20)?**
- Confirms pullback is ending, not continuing
- Avoids catching falling knives
- Momentum shifting back upward

### Optional XOU Filter

The Exponential Ornstein-Uhlenbeck process can be used as a secondary confirmation.

**When Enabled**:
- Only allows entries (never overrides hard exits)
- Must have valid kappa > 0 (mean-reverting)
- Parameters estimated on rolling historical data only

**Why Optional?**
- Adds complexity
- May reduce trade frequency excessively
- Simpler trend strategy may perform better

**Implementation Note**: If kappa ≤ 0 or parameter estimation fails, XOU filter is silently disabled.

---

## 4. Exit Logic Design

### Stop Loss Calculation

```python
stop_distance = max(1.5 * ATR(14), 0.008 * entry_price)
stop_distance = min(stop_distance, 0.03 * entry_price)  # Cap at 3%
stop_price = entry_price - stop_distance
```

**Rationale**:

| Component | Reasoning |
|-----------|-----------|
| 1.5 × ATR | Volatility-adjusted; wider stops in volatile markets |
| 0.8% minimum | Prevents stops too tight to be meaningful |
| 3% maximum | Caps risk per trade; if stop needs to be wider, skip trade |

**Why ATR-based?**
- Adapts to changing market conditions
- Wider stops when volatility high (reduces position size automatically)
- Tighter stops when volatility low (increases position size)

**Why cap at 3%?**
- With 1% risk per trade, 3% stop means ~33% position size
- Stops wider than 3% imply position too small to be efficient
- Better to skip trade than take marginal setup

### Take Profit Calculation

```python
R = entry_price - stop_price
take_profit = entry_price + 2.0 * R
```

**Rationale**:
- Minimum 2R reward ensures positive expectancy even with <50% win rate
- Asymmetric risk/reward: lose 1R, win 2R
- Mathematical edge: Need only 34% win rate to break even (ignoring fees)

**Why NOT higher targets (3R, 4R)?**
- Reduces win rate significantly
- Increases time in trade (opportunity cost)
- Crypto trends can reverse quickly
- 2R provides good balance of win rate vs. reward

### Breakeven Move (Optional)

At +1R unrealized profit:
- Move stop to breakeven (entry price)

**Rationale**:
- Eliminates risk of turning winner into loser
- Psychological benefit: "free ride"
- Reduces maximum drawdown

**Trade-off**:
- May get stopped out at breakeven more often
- Reduces average winner slightly
- Enabled by default for capital preservation focus

### Time Stop

```python
if hours_open >= 24 and unrealized_profit < 0.2R:
    exit_position()
    
if hours_open >= 48 and unrealized_profit < 1.0R:
    exit_position()  # Unless strong trend active
```

**Rationale**:
- Dead money: capital tied up without progress
- Opportunity cost: could deploy elsewhere
- Stale thesis: if trend hasn't developed in 24-48h, likely won't
- Reduces exposure time (less overnight risk)

**Why 24h and 48h thresholds?**
- 24h = 96 candles on 15m timeframe (statistically significant)
- 48h = weekend buffer (crypto weekends can be dead)
- Balances giving trade time vs. cutting losers quickly

---

## 5. Risk Management Rules

### Per-Trade Risk: 1%

```python
RISK_PER_TRADE_PCT = 1.0
```

**Rationale**:
- Standard professional risk level
- 10 consecutive losses = ~10% account drawdown (survivable)
- Allows for 35% max position size with 3% stop
- Balances growth potential with survival

**Preservation Mode**: Reduces to 0.5% after hitting 5% monthly profit.

**Why NOT higher (2%, 3%)?**
- Drawdowns become psychologically difficult
- Recovery from large drawdowns mathematically challenging
- 50% loss requires 100% gain to recover
- Sleep factor: can you sleep with 5% daily loss potential?

### Maximum Position Size: 35%

```python
MAX_POSITION_NOTIONAL_PCT = 35
```

**Rationale**:
- Diversification within single asset: cash reserve for other opportunities
- Reduces impact of any single trade
- Allows for averaging (if strategy modified later)
- Psychological comfort: not "all in"

**Preservation Mode**: Reduces to 20%.

### Daily Loss Halt: 2%

```python
DAILY_MAX_LOSS_PCT = 2.0
```

**Action**: Halt trading until next UTC day.

**Rationale**:
- Prevents "revenge trading" after losses
- Forces cool-off period
- 2% = 2 losing trades at 1% risk each
- Protects against tilt and emotional decisions

### Weekly Loss Halt: 4%

```python
WEEKLY_MAX_LOSS_PCT = 4.0
```

**Action**: Halt trading until next UTC week.

**Rationale**:
- Longer cool-off for sustained losses
- Indicates strategy may not suit current market regime
- 4% = 4 losing trades or mix of winners/losers
- Time to review and adjust (manually)

### Monthly Drawdown Halt: 6%

```python
MONTHLY_MAX_DRAWDOWN_PCT = 6.0
```

**Action**: Halt trading indefinitely until manual review.

**Rationale**:
- Maximum tolerable drawdown for most retail traders
- Beyond 6%, psychological damage significant
- Requires human intervention to diagnose issues
- Protects remaining capital

### Equity Protection: 940 USDT

```python
if equity < 940:  # 6% loss from 1000
    halt_live_trading()
```

**Rationale**:
- Hard floor on losses
- Triggers manual review mandatory
- Prevents automated destruction of account
- "Circuit breaker" for catastrophic scenarios

---

## 6. Position Sizing Methodology

### Formula

```python
equity = cash + sol_balance * current_price

risk_amount = equity * (RISK_PER_TRADE_PCT / 100)
max_notional = equity * (MAX_POSITION_NOTIONAL_PCT / 100)

if stop_distance_pct > 0:
    risk_based_notional = risk_amount / stop_distance_pct
else:
    risk_based_notional = max_notional

notional = min(max_notional, risk_based_notional)
quantity = notional / entry_price
quantity = floor_to_lot_size(quantity)  # Round DOWN
```

### Example Calculation

Given:
- Equity: $1,000
- Entry price: $100/SOL
- Stop distance: 2% ($2)
- RISK_PER_TRADE: 1%
- MAX_POSITION: 35%

```python
risk_amount = 1000 * 0.01 = $10
max_notional = 1000 * 0.35 = $350

risk_based_notional = 10 / 0.02 = $500
notional = min(350, 500) = $350

quantity = 350 / 100 = 3.5 SOL
```

If stop distance were 0.5%:
```python
risk_based_notional = 10 / 0.005 = $2000
notional = min(350, 2000) = $350  # Capped by position limit
```

If stop distance were 4% (above cap):
```python
# Trade skipped: stop_distance > 3% cap
```

### Why This Formula?

1. **Risk-first approach**: Position size derived from acceptable loss, not account percentage
2. **Volatility adjustment**: Wider stops = smaller positions automatically
3. **Position cap**: Prevents overconcentration even with tight stops
4. **Lot size rounding**: Ensures orders accepted by exchange

---

## 7. Fee and Precision Handling

### OKX Spot Fee Structure

OKX charges taker fees on spot trades. Critical issue: **fees may be deducted from base asset (SOL)** rather than quote asset (USDT).

**Example**:
```
Buy order: 1.000 SOL @ $100
Taker fee: 0.1% = $0.10

Scenario A (fee in USDT):
  Cost: $100.10
  Receive: 1.000 SOL

Scenario B (fee in SOL):
  Cost: $100.00
  Receive: 0.999 SOL  # Fee deducted from base
```

### Bot Implementation

**Post-Fill Handler**:

```python
if order.fee.currency == 'SOL':
    net_received_sol = order.filled_sol - order.fee_cost_sol
elif order.fee.currency == 'USDT':
    net_received_sol = order.filled_sol
else:
    # Query fills endpoint to determine actual received
    net_received_sol = conservative_estimate()

sellable_quantity = floor_to_lot_size(net_received_sol)
```

**Critical Rules**:

1. NEVER assume `requested_qty == filled_qty`
2. NEVER assume `filled_qty` is fully sellable
3. ALWAYS query actual fill details
4. ALWAYS round DOWN for exit quantity
5. Track dust amounts separately

### Lot Size Precision

OKX specifies lot sizes for each market. For SOL/USDT:

- Typical precision: 8 decimal places
- Minimum order: ~$5 USDT equivalent

**Implementation**:
```python
def floor_to_lot_size(quantity: float, precision: int = 8) -> float:
    return math.floor(quantity * (10 ** precision)) / (10 ** precision)
```

**Why floor (not round)?**
- Ensures order never exceeds available balance
- Conservative approach prevents rejection
- Dust left over tracked separately

### Dust Handling

If sellable quantity < minimum order size:

```python
if sellable_qty < min_order_qty:
    log_dust(sellable_qty)
    # Do not force sell
    # Accumulate until above minimum OR manual intervention
```

**Rationale**:
- Forcing sale may violate exchange rules
- Dust may become valuable if price rises
- Manual review determines best action

---

## 8. OCO and Watchdog Architecture

### The Problem

OKX spot OCO (One-Cancels-Other) orders via ccxt may:
- Be unsupported for certain markets
- Require specific parameters not documented in ccxt
- Fail silently or timeout
- Behave differently than expected (e.g., canceling both legs on trigger)

### Dual-Layer Solution

**Layer 1: Exchange-Managed Protection**

Attempt to place attached TP/SL orders with entry:

```python
params = {
    'attachAlgoOrds': [
        {'tpTriggerPrice': tp_price, 'tpOrdPx': -1},  # Market TP
        {'slTriggerPrice': sl_price, 'slOrdPx': -1}   # Market SL
    ]
}
order = exchange.create_order(symbol, 'limit', 'buy', qty, price, params=params)
```

If successful:
- Exchange manages exits
- Lower latency on triggers
- No dependency on bot running

**Layer 2: Local Watchdog**

If Layer 1 fails or unavailable:

```python
class LocalWatchdog:
    def __init__(self, position):
        self.stop_price = position.stop_price
        self.tp_price = position.take_profit_price
        
    async def monitor(self):
        while position_active:
            price = await get_latest_price()  # WebSocket preferred
            
            if price <= self.stop_price:
                await emergency_exit('STOP_LOSS_TRIGGERED')
                
            elif price >= self.tp_price:
                await emergency_exit('TAKE_PROFIT_TRIGGERED')
                
            await asyncio.sleep(1)  # Poll interval
```

**Fallback Hierarchy**:

1. Try exchange OCO during entry
2. If rejected/timeout → activate local watchdog
3. Watchdog uses WebSocket for real-time prices
4. WebSocket fails → REST polling fallback
5. Both fail → ERROR_SAFE state, exit ASAP

### Protection Failure Handling

**Scenario**: Order placed, response lost (network blip).

**Wrong**: Immediately retry (may create duplicate orders).

**Correct**:
```python
1. Query open orders for symbol
2. Check if order exists by client_order_id
3. If exists → do nothing (already placed)
4. If not exists → safe to retry
```

**Scenario**: Stop triggered but partial fill.

**Handling**:
```python
1. Check remaining quantity
2. If remainder > 0 → submit new stop for remainder
3. Log reconciliation event
4. Continue monitoring until flat
```

### State Reconciliation on Restart

On startup:

```python
def reconcile_state():
    # Get exchange state
    okx_balance = exchange.fetch_balance()['SOL']['free']
    okx_orders = exchange.fetch_open_orders(symbol)
    
    # Get local state
    db_position = db.get_active_position()
    
    # Compare
    if db_position is None and okx_balance > 0:
        # Orphaned position: import to DB
        recover_position(okx_balance, okx_orders)
        
    elif db_position is not None and okx_balance == 0:
        # Ghost position: clear DB
        db_position.status = 'RECONCILED_FLAT'
        
    elif quantities_differ(db_position, okx_balance):
        # Mismatch: investigate
        log_warning(f"Mismatch: DB={db_position.qty}, OKX={okx_balance}")
```

---

## 9. Monthly Target Reality Check

### The 5% Objective

**Target**: 5% net profit per month on $1,000 capital = $50/month.

**Mathematical Reality**:

With `RISK_PER_TRADE = 1%` and 2R targets:
- One winning trade ≈ 2% account gain (before fees)
- Need ~2-3 winning trades per month NET of losers

**Constraints Impact**:

1. **Trend Filter**: May eliminate 50-70% of potential entries
2. **Pullback Requirement**: Further reduces trade frequency
3. **Volume Filter**: Eliminates low-liquidity periods
4. **Risk Halts**: Can skip days/weeks after losses
5. **Time Stops**: Exits may occur at small profits/losses

**Expected Trade Frequency**:

Based on typical trend-following strategies on 15m/1h:
- 3-8 trades per month (highly variable)
- Win rate: 40-55% (with 2R targets)
- Some months: 0 trades (no valid setups)

**Probability Assessment**:

| Scenario | Monthly Return | Probability |
|----------|---------------|-------------|
| Excellent (4 wins, 1 loss) | +7% | 15% |
| Good (3 wins, 2 losses) | +4% | 25% |
| Average (2 wins, 2 losses) | +2% | 30% |
| Poor (1 win, 3 losses) | -1% | 20% |
| Bad (0 wins, 2+ losses) | -3% | 10% |

**Expected Value**: ~2.5-3.5% per month (not 5%)

### Why Not Loosen Filters?

**Question**: Why not reduce RSI threshold to 50? Or remove ADX filter?

**Answer**:

1. **Backtest Integrity**: Filters exist because they improve risk-adjusted returns historically
2. **Regime Dependency**: Loose filters work in some regimes, catastrophically fail in others
3. **Drawdown Protection**: Strict filters reduce frequency BUT also reduce max drawdown
4. **Sleep Factor**: Fewer trades = less stress = better adherence to system

**Philosophy**:

> "The best trade is sometimes no trade."

If backtests show 3% expected monthly return with 8% max drawdown vs. 5% return with 15% drawdown, we choose the former.

### Documentation Requirement

The backtest report MUST clearly state:

```markdown
Expected Monthly Return (based on historical validation): X.X%
5% Target Achievable: YES/NO (with caveats)

If NO:
  "The 5% monthly target is an objective only and may not be 
   achievable while respecting all risk constraints. The strategy
   prioritizes capital preservation over return maximization."
```

**Never**:
- Claim 5% is guaranteed
- Loosen filters post-backtest to hit target
- Add martingale/DCA to boost returns
- Increase position size beyond limits

---

## 10. Known Failure Modes

### Market Regime Changes

**Failure**: Strategy assumes trending behavior; markets go range-bound for weeks.

**Symptoms**:
- Multiple small losses from whipsaws
- ADX stays below 20
- Pullbacks become breakdowns

**Mitigation**:
- ADX filter already excludes weak trends
- Weekly loss halt forces cool-off
- Manual review may pause trading

### Flash Crashes

**Failure**: SOL drops 20% in minutes; stop-loss fills far below target.

**Symptoms**:
- Slippage >> assumed 0.1%
- Fill price much worse than stop trigger

**Mitigation**:
- ATR cap (3%) limits exposure
- Position sizing accounts for worst-case slippage
- Monthly drawdown halt prevents compounding losses

### Exchange Issues

**Failure**: OKX API down during critical moment.

**Symptoms**:
- Cannot submit exit orders
- WebSocket disconnects
- Rate limits hit

**Mitigation**:
- Local watchdog continues with last-known prices
- Retry logic with exponential backoff
- ERROR_SAFE state if truly unable to exit

### Software Bugs

**Failure**: Bug causes incorrect position sizing or missed exits.

**Symptoms**:
- Position size >> expected
- Stop not triggering at correct level

**Mitigation**:
- Unit tests for critical functions
- Paper trading period catches bugs
- Logging allows post-mortem analysis
- SQLite persistence enables recovery

### Data Errors

**Failure**: Bad candle data causes false signals.

**Symptoms**:
- Spike in volume/price not real
- Indicators calculate incorrectly

**Mitigation**:
- Validate OHLCV data sanity (no zero prices, volumes)
- Use multiple data sources if possible
- Skip candles with obvious errors

---

## 11. Assumptions and Limitations

### Assumptions

1. **Historical Patterns Repeat**: Past trend behavior predicts future (not always true)
2. **Liquidity Remains Adequate**: SOL/USDT spread stays < 0.1% typically
3. **OKX Remains Operational**: No exchange collapse, hack, or withdrawal freeze
4. **Python/ccxt Stable**: No breaking changes in dependencies
5. **Internet Connectivity**: VPS maintains stable connection
6. **Fees Stable**: OKX fee schedule doesn't change dramatically
7. **No Black Swan Events**: No 80% single-day crashes (or if so, account survives)

### Limitations

1. **Single Asset**: Cannot diversify across coins
2. **Long Only**: Cannot profit from downtrends
3. **15m/1h Timeframes**: Misses longer-term trends and scalping opportunities
4. **No News Awareness**: Trades through major announcements blindly
5. **Fixed Parameters**: Does not adapt parameters to changing volatility regimes
6. **Backtest Bias**: Historical results may not predict future
7. **Slippage Model**: Assumes constant 0.1%; real slippage varies

### What This Bot Is NOT

- ❌ A get-rich-quick scheme
- ❌ A guaranteed profit generator
- ❌ Suitable for all market conditions
- ❌ A replacement for human oversight
- ❌ Tested on all possible scenarios
- ❌ Financial advice

---

## 12. Parameter Sensitivity

### High Sensitivity (Small Changes → Large Impact)

| Parameter | Base Value | ±10% Change Impact |
|-----------|-----------|-------------------|
| RISK_PER_TRADE | 1.0% | Direct P&L impact |
| Stop Distance | 1.5× ATR | Win rate, R-multiple |
| RSI Minimum | 55 | Trade frequency |
| ADX Minimum | 20 | Trade frequency, quality |

### Low Sensitivity (Changes Have Minor Impact)

| Parameter | Base Value | ±10% Change Impact |
|-----------|-----------|-------------------|
| EMA Periods | 20, 50, 200 | Slight timing differences |
| Volume Multiplier | 1.2× | Few trades affected |
| Time Stop Hours | 24, 48 | Small P&L difference |

### Recommended Tuning Order

If optimization needed:

1. **Stop Distance Multiplier** (1.0–2.0 × ATR)
   - Affects win rate and R-multiple most directly
   
2. **RSI Threshold** (50–60)
   - Affects trade frequency and quality
   
3. **ADX Threshold** (15–25)
   - Filters ranging markets
   
4. **Position Size Cap** (25–40%)
   - Only after validating edge

**Never Tune**:
- Risk per trade (1% is fixed for survival)
- Loss halts (non-negotiable protection)
- Fee/slippage assumptions (must be realistic)

---

## Conclusion

This bot implements a conservative, rule-based trend-following strategy for SOL/USDT spot trading. Key design choices prioritize:

1. **Survival** over maximum returns
2. **Consistency** over home-run trades
3. **Transparency** over black-box complexity
4. **Robustness** over curve-fitting

The 5% monthly target is an **objective**, not a promise. If market conditions, risk limits, or model confidence do not support safe trading, the bot will remain flat. This is a feature, not a bug.

**Final Reminder**: Past performance does not guarantee future results. Always start with demo mode. Never risk capital you cannot afford to lose.
