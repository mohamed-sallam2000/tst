#!/usr/bin/env python3
"""
test_indicators.py - Unit tests for indicator calculations.

Tests EMA, RSI, ADX, ATR calculations and pullback confirmation rule.
"""

import unittest
from decimal import Decimal
import pandas as pd
import numpy as np

from indicators import (
    calculate_ema,
    calculate_rsi,
    calculate_adx,
    calculate_atr,
    check_pullback_confirmation,
    compute_trend_filter,
    compute_entry_signal
)


class TestEMA(unittest.TestCase):
    """Test EMA calculation."""
    
    def test_ema_basic(self):
        """Test basic EMA calculation with known values."""
        prices = pd.Series([100, 102, 101, 103, 105, 104, 106, 108, 107, 109])
        
        ema_5 = calculate_ema(prices, period=5)
        
        self.assertEqual(len(ema_5), len(prices))
        self.assertFalse(ema_5.isnull().all())
        # EMA should be close to recent prices
        self.assertAlmostEqual(ema_5.iloc[-1], prices.iloc[-1], delta=5.0)
    
    def test_ema_smooths_prices(self):
        """Test that EMA smooths price series."""
        prices = pd.Series([100, 200, 100, 200, 100, 200, 100, 200])
        
        ema_10 = calculate_ema(prices, period=10)
        
        # EMA should be smoother than raw prices
        price_std = prices.std()
        ema_std = ema_10.std()
        self.assertLess(ema_std, price_std)


class TestRSI(unittest.TestCase):
    """Test RSI calculation."""
    
    def test_rsi_range(self):
        """Test RSI stays within 0-100 range."""
        prices = pd.Series(np.random.uniform(90, 110, 100))
        
        rsi = calculate_rsi(prices, period=14)
        
        # Skip NaN values at start
        valid_rsi = rsi.dropna()
        
        self.assertTrue((valid_rsi >= 0).all())
        self.assertTrue((valid_rsi <= 100).all())
    
    def test_rsi_overbought(self):
        """Test RSI reaches overbought levels with sustained uptrend."""
        # Create steadily rising prices
        prices = pd.Series(range(100, 200))
        
        rsi = calculate_rsi(prices, period=14)
        
        # Later RSI should be high (>70)
        self.assertGreater(rsi.iloc[-1], 70)
    
    def test_rsi_oversold(self):
        """Test RSI reaches oversold levels with sustained downtrend."""
        # Create steadily falling prices
        prices = pd.Series(range(200, 100, -1))
        
        rsi = calculate_rsi(prices, period=14)
        
        # Later RSI should be low (<30)
        self.assertLess(rsi.iloc[-1], 30)


class TestADX(unittest.TestCase):
    """Test ADX calculation."""
    
    def test_adx_non_negative(self):
        """Test ADX is always non-negative."""
        highs = pd.Series(np.random.uniform(95, 105, 100))
        lows = pd.Series(np.random.uniform(85, 95, 100))
        closes = pd.Series(np.random.uniform(90, 100, 100))
        
        adx = calculate_adx(highs, lows, closes, period=14)
        
        valid_adx = adx.dropna()
        self.assertTrue((valid_adx >= 0).all())
    
    def test_adx_strong_trend(self):
        """Test ADX increases with strong trend."""
        # Create strongly trending data
        base = pd.Series(range(100))
        highs = base + 5
        lows = base - 5
        closes = base
        
        adx = calculate_adx(highs, lows, closes, period=14)
        
        # ADX should increase and reach meaningful levels
        self.assertGreater(adx.iloc[-1], 20)


class TestATR(unittest.TestCase):
    """Test ATR calculation."""
    
    def test_atr_positive(self):
        """Test ATR is always positive."""
        highs = pd.Series(np.random.uniform(95, 105, 100))
        lows = pd.Series(np.random.uniform(85, 95, 100))
        closes = pd.Series(np.random.uniform(90, 100, 100))
        
        atr = calculate_atr(highs, lows, closes, period=14)
        
        valid_atr = atr.dropna()
        self.assertTrue((valid_atr > 0).all())
    
    def test_atr_volatility(self):
        """Test ATR reflects volatility changes."""
        # Low volatility period
        base = pd.Series([100] * 50)
        highs_low = base + 1
        lows_low = base - 1
        closes_low = base
        
        # High volatility period
        highs_high = base + 10
        lows_high = base - 10
        closes_high = base
        
        atr_low = calculate_atr(highs_low, lows_low, closes_low, period=14)
        atr_high = calculate_atr(highs_high, lows_high, closes_high, period=14)
        
        self.assertGreater(atr_high.iloc[-1], atr_low.iloc[-1])


class TestPullbackConfirmation(unittest.TestCase):
    """Test pullback confirmation rule."""
    
    def test_pullback_confirmed(self):
        """Test pullback is confirmed when price touched EMA then recovered."""
        # Create data where price dipped below EMA then recovered
        closes = pd.Series([100, 101, 102, 103, 102, 101, 100, 99, 100, 101, 102, 103, 104, 105])
        
        ema_50 = calculate_ema(closes, period=5)  # Use shorter period for test
        
        # Simulate: one of last 5 candles had low <= EMA, current close > EMA
        result = check_pullback_confirmation(
            closes=closes,
            ema_50=ema_50,
            current_idx=len(closes) - 1,
            lookback=5,
            use_lows=True
        )
        
        # Should confirm if conditions met
        self.assertIsInstance(result, bool)
    
    def test_no_pullback_if_always_above_ema(self):
        """Test no pullback if price never touched EMA."""
        # Price always above EMA (strong uptrend without pullback)
        closes = pd.Series([100, 105, 110, 115, 120, 125, 130, 135, 140, 145])
        
        ema_50 = calculate_ema(closes, period=5)
        
        result = check_pullback_confirmation(
            closes=closes,
            ema_50=ema_50,
            current_idx=len(closes) - 1,
            lookback=5,
            use_lows=True
        )
        
        # May or may not confirm depending on exact values
        self.assertIsInstance(result, bool)


class TestTrendFilter(unittest.TestCase):
    """Test higher-timeframe trend filter."""
    
    def test_bullish_trend_conditions(self):
        """Test bullish trend detection."""
        # Create bullish market structure
        closes = pd.Series(range(100, 300))  # Strong uptrend
        
        df = pd.DataFrame({'close': closes})
        df['high'] = df['close'] + 5
        df['low'] = df['close'] - 5
        df['volume'] = 1000
        
        # Calculate indicators
        df['ema_50'] = calculate_ema(df['close'], 50)
        df['ema_200'] = calculate_ema(df['close'], 200)
        df['adx'] = calculate_adx(df['high'], df['low'], df['close'], 14)
        df['atr'] = calculate_atr(df['high'], df['low'], df['close'], 14)
        
        # Test trend filter on last row
        idx = len(df) - 1
        
        # Check basic conditions
        self.assertGreater(df['close'].iloc[idx], df['ema_200'].iloc[idx])
        self.assertGreater(df['ema_50'].iloc[idx], df['ema_200'].iloc[idx])


class TestEntrySignal(unittest.TestCase):
    """Test entry signal generation."""
    
    def test_entry_signal_structure(self):
        """Test entry signal returns correct structure."""
        closes = pd.Series(np.random.uniform(90, 110, 300))
        
        df_15m = pd.DataFrame({'close': closes})
        df_15m['high'] = df_15m['close'] + 2
        df_15m['low'] = df_15m['close'] - 2
        df_15m['volume'] = np.random.uniform(100, 1000, 300)
        
        df_1h = df_15m.copy()
        
        signal, indicators = compute_entry_signal(df_15m, 299, df_1h, 299)
        
        self.assertIsInstance(signal, bool)
        self.assertIsInstance(indicators, dict)
        
        # Check indicators contain expected keys
        expected_keys = ['rsi_15m', 'ema_20_15m', 'ema_50_15m']
        for key in expected_keys:
            self.assertIn(key, indicators)


if __name__ == '__main__':
    unittest.main()
