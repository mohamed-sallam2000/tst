"""
OKX Spot Trading Bot - Strategy Signal Engine
Deterministic multi-timeframe trend and volatility strategy for SOL/USDT.
"""

import logging
from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass

from indicators import (
    calculate_ema,
    calculate_rsi,
    calculate_adx,
    calculate_atr,
    calculate_sma,
    check_pullback_confirmation,
)

logger = logging.getLogger(__name__)


@dataclass
class SignalResult:
    """Represents a trading signal."""
    signal: str  # 'BUY', 'SELL', 'HOLD'
    confidence: float  # 0.0 to 1.0
    reason: str
    entry_price: Optional[float] = None
    stop_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    indicators: Optional[Dict[str, float]] = None


class StrategyEngine:
    """
    Deterministic strategy engine for SOL/USDT long-only spot trading.
    
    Uses multi-timeframe analysis:
    - 1h candles for trend filter
    - 15m candles for entry trigger
    """

    def __init__(self):
        self.symbol = 'SOL/USDT'
        
        # Strategy parameters (from spec)
        self.htf_timeframe = '1h'
        self.entry_timeframe = '15m'
        
        # HTF filter thresholds
        self.adx_threshold = 20.0
        self.atr_pct_threshold = 0.05
        self.solar_24h_change_threshold = -8.0
        
        # Entry thresholds
        self.rsi_entry_threshold = 55.0
        self.volume_multiplier = 1.2
        
        # Exit parameters
        self.stop_atr_multiplier = 1.5
        self.stop_min_pct = 0.008  # 0.8%
        self.stop_max_pct = 0.03   # 3.0%
        self.take_profit_r_multiple = 2.0

    def _extract_candle_data(self, candles: List[List]) -> Dict[str, List[float]]:
        """Extract OHLCV arrays from candle list."""
        if not candles:
            return {'time': [], 'open': [], 'high': [], 'low': [], 'close': [], 'volume': []}
        
        return {
            'time': [c[0] for c in candles],
            'open': [c[1] for c in candles],
            'high': [c[2] for c in candles],
            'low': [c[3] for c in candles],
            'close': [c[4] for c in candles],
            'volume': [c[5] for c in candles]
        }

    def check_higher_timeframe_filter(
        self,
        htf_candles: List[List],
        sol_24h_change: float
    ) -> Tuple[bool, Dict[str, float]]:
        """
        Check higher-timeframe (1h) trend filter.
        
        Returns: (is_bullish, indicator_values)
        
        Conditions for bullish:
        - close > EMA_200
        - EMA_50 > EMA_200
        - ADX_14 > 20.0
        - ATR_14 / close <= 0.05
        - SOL_24h_change > -8.0%
        """
        indicators = {}
        
        if len(htf_candles) < 200:
            logger.warning(f"Insufficient HTF candles: {len(htf_candles)} < 200")
            return False, indicators
        
        data = self._extract_candle_data(htf_candles)
        closes = data['close']
        highs = data['high']
        lows = data['low']
        opens = data['open']
        
        # Calculate indicators on completed candles only (exclude last forming candle)
        closes_completed = closes[:-1] if len(closes) > 0 else closes
        highs_completed = highs[:-1] if len(highs) > 0 else highs
        lows_completed = lows[:-1] if len(lows) > 0 else lows
        opens_completed = opens[:-1] if len(opens) > 0 else opens
        
        if len(closes_completed) < 200:
            logger.warning(f"Insufficient completed HTF candles: {len(closes_completed)} < 200")
            return False, indicators
        
        current_close = closes_completed[-1]
        
        # EMA calculations
        ema_200 = calculate_ema(closes_completed, period=200)
        ema_50 = calculate_ema(closes_completed, period=50)
        
        if ema_200 is None or ema_50 is None:
            logger.warning("Failed to calculate HTF EMAs")
            return False, indicators
        
        indicators['ema_200_htf'] = ema_200
        indicators['ema_50_htf'] = ema_50
        indicators['close_htf'] = current_close
        
        # Condition 1: close > EMA_200
        cond1 = current_close > ema_200
        
        # Condition 2: EMA_50 > EMA_200
        cond2 = ema_50 > ema_200
        
        # ADX calculation
        adx = calculate_adx(highs_completed, lows_completed, closes_completed, period=14)
        if adx is None:
            logger.warning("Failed to calculate HTF ADX")
            return False, indicators
        
        indicators['adx_htf'] = adx
        
        # Condition 3: ADX > 20.0
        cond3 = adx > self.adx_threshold
        
        # ATR calculation
        atr = calculate_atr(highs_completed, lows_completed, closes_completed, period=14)
        if atr is None:
            logger.warning("Failed to calculate HTF ATR")
            return False, indicators
        
        indicators['atr_htf'] = atr
        indicators['atr_pct_htf'] = atr / current_close if current_close > 0 else 999
        
        # Condition 4: ATR / close <= 0.05
        cond4 = (atr / current_close) <= self.atr_pct_threshold if current_close > 0 else False
        
        # Condition 5: SOL_24h_change > -8.0%
        cond5 = sol_24h_change > self.solar_24h_change_threshold
        
        indicators['sol_24h_change'] = sol_24h_change
        
        is_bullish = cond1 and cond2 and cond3 and cond4 and cond5
        
        logger.debug(
            f"HTF Filter: close>{ema_200:.2f}={cond1}, EMA50>EMA200={cond2}, "
            f"ADX>{self.adx_threshold}={cond3}, ATR%<={self.atr_pct_threshold}={cond4}, "
            f"24h_change>{self.solar_24h_change_threshold}={cond5}"
        )
        
        return is_bullish, indicators

    def check_entry_trigger(
        self,
        entry_candles: List[List],
        htf_bullish: bool
    ) -> Tuple[bool, Dict[str, float], Optional[str]]:
        """
        Check 15m entry trigger conditions.
        
        Returns: (should_enter, indicator_values, rejection_reason)
        
        Entry conditions:
        - HTF trend is bullish
        - close > EMA_50
        - EMA_20 > EMA_50
        - RSI_14 > 55.0
        - RSI_14 > RSI_14_previous
        - volume > 1.2 * SMA_volume_20
        - ask_bid_spread_pct <= 0.08%
        - pullback_confirmation == true
        """
        indicators = {}
        
        if not htf_bullish:
            return False, indicators, "HTF_FILTER_NOT_BULLISH"
        
        if len(entry_candles) < 55:  # Need at least 55 for EMA_50 + some history
            logger.warning(f"Insufficient entry candles: {len(entry_candles)} < 55")
            return False, indicators, "INSUFFICIENT_DATA"
        
        data = self._extract_candle_data(entry_candles)
        closes = data['close']
        highs = data['high']
        lows = data['low']
        volumes = data['volume']
        
        # Use completed candles only (exclude last forming candle)
        closes_completed = closes[:-1] if len(closes) > 0 else closes
        highs_completed = highs[:-1] if len(highs) > 0 else highs
        lows_completed = lows[:-1] if len(lows) > 0 else lows
        volumes_completed = volumes[:-1] if len(volumes) > 0 else volumes
        
        if len(closes_completed) < 55:
            logger.warning(f"Insufficient completed entry candles: {len(closes_completed)} < 55")
            return False, indicators, "INSUFFICIENT_COMPLETED_DATA"
        
        current_close = closes_completed[-1]
        current_low = lows_completed[-1]
        current_volume = volumes_completed[-1]
        
        # EMA calculations
        ema_50 = calculate_ema(closes_completed, period=50)
        ema_20 = calculate_ema(closes_completed, period=20)
        
        if ema_50 is None or ema_20 is None:
            logger.warning("Failed to calculate entry EMAs")
            return False, indicators, "EMA_CALCULATION_FAILED"
        
        indicators['ema_50_entry'] = ema_50
        indicators['ema_20_entry'] = ema_20
        indicators['close_entry'] = current_close
        
        # Condition 1: close > EMA_50
        cond1 = current_close > ema_50
        
        # Condition 2: EMA_20 > EMA_50
        cond2 = ema_20 > ema_50
        
        # RSI calculation
        rsi_current = calculate_rsi(closes_completed, period=14)
        rsi_previous = calculate_rsi(closes_completed[:-1], period=14) if len(closes_completed) > 14 else None
        
        if rsi_current is None:
            logger.warning("Failed to calculate RSI")
            return False, indicators, "RSI_CALCULATION_FAILED"
        
        indicators['rsi_current'] = rsi_current
        indicators['rsi_previous'] = rsi_previous
        
        # Condition 3: RSI > 55.0
        cond3 = rsi_current > self.rsi_entry_threshold
        
        # Condition 4: RSI > RSI_previous
        cond4 = rsi_previous is not None and rsi_current > rsi_previous
        
        # Volume calculation
        sma_volume_20 = calculate_sma(volumes_completed, period=20)
        
        if sma_volume_20 is None:
            logger.warning("Failed to calculate volume SMA")
            return False, indicators, "VOLUME_SMA_FAILED"
        
        indicators['volume_current'] = current_volume
        indicators['volume_sma_20'] = sma_volume_20
        
        # Condition 5: volume > 1.2 * SMA_volume_20
        cond5 = current_volume > (sma_volume_20 * self.volume_multiplier)
        
        # Note: ask_bid_spread_pct must be checked separately with live ticker data
        # We'll mark it as True here and let the caller verify
        indicators['spread_check_pending'] = True
        
        # Pullback confirmation
        # Check within previous 5 completed candles (excluding current signal candle)
        lookback_start = max(0, len(closes_completed) - 6)  # 5 candles before current
        lookback_closes = closes_completed[lookback_start:-1]  # Exclude current signal candle
        lookback_lows = lows_completed[lookback_start:-1]
        
        # Recalculate EMA_50 for each lookback candle
        pullback_confirmed = check_pullback_confirmation(
            closes_completed,
            lows_completed,
            window=5
        )
        
        indicators['pullback_confirmed'] = pullback_confirmed
        
        # Condition 6: pullback_confirmation == true
        cond6 = pullback_confirmed
        
        should_enter = cond1 and cond2 and cond3 and cond4 and cond5 and cond6
        
        if not should_enter:
            reasons = []
            if not cond1:
                reasons.append("CLOSE_NOT_ABOVE_EMA50")
            if not cond2:
                reasons.append("EMA20_NOT_ABOVE_EMA50")
            if not cond3:
                reasons.append("RSI_BELOW_THRESHOLD")
            if not cond4:
                reasons.append("RSI_NOT_RISING")
            if not cond5:
                reasons.append("VOLUME_TOO_LOW")
            if not cond6:
                reasons.append("NO_PULLBACK_CONFIRMATION")
            
            rejection_reason = ",".join(reasons) if reasons else "UNKNOWN"
        else:
            rejection_reason = None
        
        logger.debug(
            f"Entry Trigger: close>EMA50={cond1}, EMA20>EMA50={cond2}, "
            f"RSI>55={cond3}, RSI_rising={cond4}, volume_ok={cond5}, pullback={cond6}"
        )
        
        return should_enter, indicators, rejection_reason

    def calculate_exit_levels(
        self,
        entry_price: float,
        atr_15m: float,
        direction: str = 'long'
    ) -> Tuple[float, float]:
        """
        Calculate stop-loss and take-profit levels.
        
        Stop distance = max(1.5 * ATR, 0.8% of entry)
        Capped at 3.0% maximum.
        
        Take profit = entry + 2.0 * R (where R = entry - stop)
        
        Returns: (stop_price, take_profit_price)
        """
        if direction != 'long':
            raise ValueError("Only long positions supported")
        
        # Calculate stop distance
        atr_stop = self.stop_atr_multiplier * atr_15m
        pct_stop = entry_price * self.stop_min_pct
        stop_distance = max(atr_stop, pct_stop)
        
        # Cap at maximum
        max_stop_distance = entry_price * self.stop_max_pct
        stop_distance = min(stop_distance, max_stop_distance)
        
        stop_price = entry_price - stop_distance
        
        # Calculate R multiple
        r_value = entry_price - stop_price
        
        # Take profit at 2R
        take_profit_price = entry_price + (self.take_profit_r_multiple * r_value)
        
        logger.info(
            f"Exit levels: entry={entry_price:.4f}, stop={stop_price:.4f}, "
            f"tp={take_profit_price:.4f}, R={r_value:.4f}"
        )
        
        return stop_price, take_profit_price

    def check_time_exit(
        self,
        entry_time_ms: int,
        current_time_ms: int,
        unrealized_pnl_pct: float,
        r_value: float
    ) -> Tuple[bool, str]:
        """
        Check if time-based exit conditions are met.
        
        - If position open > 24h and unrealized PnL < +0.2R, exit
        - If position open > 48h and unrealized PnL < +1R, exit (unless strong trend)
        
        Returns: (should_exit, reason)
        """
        hours_open = (current_time_ms - entry_time_ms) / (1000 * 60 * 60)
        
        # 24-hour check
        if hours_open >= 24:
            threshold_pnl = 0.2 * r_value
            if unrealized_pnl_pct < threshold_pnl:
                return True, f"TIME_STOP_24H_PNL_{unrealized_pnl_pct:.4f}_BELOW_{threshold_pnl:.4f}"
        
        # 48-hour check
        if hours_open >= 48:
            threshold_pnl = 1.0 * r_value
            if unrealized_pnl_pct < threshold_pnl:
                return True, f"TIME_STOP_48H_PNL_{unrealized_pnl_pct:.4f}_BELOW_{threshold_pnl:.4f}"
        
        return False, ""

    def generate_signal(
        self,
        htf_candles: List[List],
        entry_candles: List[List],
        sol_24h_change: float,
        spread_pct: Optional[float] = None
    ) -> SignalResult:
        """
        Generate trading signal based on all conditions.
        
        Returns SignalResult with signal, confidence, and reasoning.
        """
        # Check HTF filter
        htf_bullish, htf_indicators = self.check_higher_timeframe_filter(
            htf_candles, sol_24h_change
        )
        
        if not htf_bullish:
            return SignalResult(
                signal='HOLD',
                confidence=0.0,
                reason="HTF trend filter not satisfied",
                indicators=htf_indicators
            )
        
        # Check entry trigger
        should_enter, entry_indicators, rejection_reason = self.check_entry_trigger(
            entry_candles, htf_bullish
        )
        
        # Merge indicators
        all_indicators = {**htf_indicators, **entry_indicators}
        
        # Check spread condition
        if spread_pct is not None:
            all_indicators['spread_pct'] = spread_pct
            if spread_pct > 0.08:  # 0.08%
                return SignalResult(
                    signal='HOLD',
                    confidence=0.0,
                    reason=f"Spread too wide: {spread_pct:.4f}% > 0.08%",
                    indicators=all_indicators
                )
        
        if not should_enter:
            return SignalResult(
                signal='HOLD',
                confidence=0.0,
                reason=f"Entry conditions not met: {rejection_reason}",
                indicators=all_indicators
            )
        
        # All conditions met - generate BUY signal
        current_price = entry_candles[-1][4] if entry_candles else None
        
        # Calculate exit levels if we have ATR
        atr_15m = calculate_atr(
            [c[2] for c in entry_candles[:-1]],
            [c[3] for c in entry_candles[:-1]],
            [c[4] for c in entry_candles[:-1]],
            period=14
        )
        
        stop_price = None
        tp_price = None
        
        if atr_15m is not None and current_price is not None:
            stop_price, tp_price = self.calculate_exit_levels(current_price, atr_15m)
            all_indicators['atr_15m'] = atr_15m
        
        return SignalResult(
            signal='BUY',
            confidence=1.0,
            reason="All entry conditions satisfied",
            entry_price=current_price,
            stop_price=stop_price,
            take_profit_price=tp_price,
            indicators=all_indicators
        )
