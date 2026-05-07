"""
cycle_engine.py — Core Cycle Detection & Projection Engine
============================================================
FFT spectral analysis with Bartels significance testing.
Detects anchor (200-900d), medium (50-200d), and timing (15-50d) cycles.
Projects composite cycle forward to identify multi-week directional windows.

Used by: scanner.py, daily_bot.py
"""

import numpy as np
import pandas as pd
from scipy.fft import fft, fftfreq
from scipy.signal import detrend
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class DetectedCycle:
    period_days: float
    amplitude: float
    phase: float
    spectral_power: float
    bartels_p: float          # lower = more significant
    harmonic_score: float = 0.0
    category: str = ''        # anchor / medium / timing

    @property
    def quality(self) -> float:
        """Composite quality score 0–100."""
        sig = max(0, 1 - self.bartels_p) * 40
        hrm = self.harmonic_score * 30
        amp = min(self.amplitude / 0.03, 1.0) * 30
        return sig + hrm + amp


def detect_cycles(close: np.ndarray, min_bars: int = 1000) -> List[DetectedCycle]:
    """
    Detect dominant cycles in a price series using FFT.

    Parameters
    ----------
    close : array of close prices
    min_bars : minimum bars required

    Returns
    -------
    List of DetectedCycle, sorted by quality descending.
    """
    if len(close) < min_bars:
        return []

    log_p = np.log(close[close > 0])
    if len(log_p) < min_bars:
        return []

    detr = detrend(log_p, type='linear')
    N = len(detr)
    window = np.hanning(N)
    windowed = detr * window

    yf = fft(windowed)
    xf = fftfreq(N, d=1.0)
    pos = xf > 0
    freqs = xf[pos]
    power = np.abs(yf[pos]) ** 2
    phases = np.angle(yf[pos])
    periods = 1.0 / freqs

    if power.max() == 0:
        return []
    power_norm = power / power.max()

    # Extract top peaks per category
    RANGES = {
        'anchor': (200, 900, 2),
        'medium': (50, 200, 3),
        'timing': (15, 50, 2),
    }

    cycles = []
    for cat, (lo, hi, n_peaks) in RANGES.items():
        mask = (periods >= lo) & (periods <= hi)
        if not mask.any():
            continue
        cp = power_norm[mask]
        cper = periods[mask]
        cph = phases[mask]
        n = min(n_peaks, len(cp))
        idx = np.argsort(cp)[-n:]
        for i in idx:
            amp = np.sqrt(cp[i]) * 2 / N
            cycles.append(DetectedCycle(
                period_days=round(cper[i], 1),
                amplitude=amp,
                phase=cph[i],
                spectral_power=float(cp[i]),
                bartels_p=1.0,
                category=cat,
            ))

    # Bartels significance test
    returns = np.diff(close) / close[:-1]
    for cyc in cycles:
        period = int(round(cyc.period_days))
        if period < 5 or len(close) // period < 3:
            cyc.bartels_p = 0.5
            continue
        ph = np.arange(len(returns)) % period / period * 2 * np.pi
        n_bins = min(12, max(4, period // 5))
        edges = np.linspace(0, 2 * np.pi, n_bins + 1)
        bmeans = []
        for b in range(n_bins):
            m = (ph >= edges[b]) & (ph < edges[b + 1])
            bmeans.append(returns[m].mean() if m.sum() > 5 else 0)
        bvar = np.var(bmeans)
        evar = np.var(returns) / max(1, len(returns) / n_bins)
        f = bvar / (evar + 1e-12)
        cyc.bartels_p = 1.0 / (1.0 + f)

    # Filter significant cycles
    valid = [c for c in cycles if c.bartels_p < 0.20 or
             (c.category == 'anchor' and c.bartels_p < 0.30)]
    if len(valid) < 3:
        valid = sorted(cycles, key=lambda c: c.bartels_p)[:5]

    # Harmonic scoring
    anchors = [c for c in valid if c.category == 'anchor']
    if anchors:
        anchor = max(anchors, key=lambda c: c.spectral_power)
        for c in valid:
            if c.category == 'anchor':
                c.harmonic_score = 1.0
                continue
            ratio = anchor.period_days / c.period_days
            nearest = round(ratio)
            if nearest > 0:
                dev = abs(ratio - nearest) / nearest
                c.harmonic_score = max(0, 1.0 - dev * 5)

    return sorted(valid, key=lambda c: c.quality, reverse=True)


def project_composite(cycles: List[DetectedCycle],
                      total_history_days: int,
                      n_forward_days: int) -> np.ndarray:
    """
    Build composite cycle projection forward.

    Returns array of daily 'bullish strength' values.
    Positive = bullish (near troughs, expecting up), negative = bearish.
    """
    if not cycles:
        return np.zeros(n_forward_days)

    composite = np.zeros(n_forward_days)
    total_weight = 0

    for cyc in cycles:
        w = cyc.quality / 100.0
        period = cyc.period_days
        phase_at_end = (total_history_days % period) / period * 2 * np.pi + cyc.phase

        for d in range(n_forward_days):
            future_phase = (phase_at_end + (d + 1) / period * 2 * np.pi) % (2 * np.pi)
            # +1 at trough (buy), -1 at peak (avoid)
            bullish = -np.cos(future_phase)
            composite[d] += w * bullish

        total_weight += w

    if total_weight > 0:
        composite /= total_weight

    return composite


def find_directional_windows(composite: np.ndarray,
                              start_date: pd.Timestamp,
                              min_window_days: int = 15,
                              max_windows: int = 2) -> List[dict]:
    """
    Find sustained bullish windows (composite > 0 for ≥ min_window_days).

    Returns list of window dicts sorted by score descending.
    """
    n = len(composite)
    dates = pd.bdate_range(start=start_date + pd.Timedelta(days=1), periods=n)

    smoothed = pd.Series(composite).rolling(5, center=True).mean().fillna(0).values

    windows = []
    in_window = False
    ws = 0

    for d in range(n):
        if smoothed[d] > 0:
            if not in_window:
                in_window = True
                ws = d
        else:
            if in_window and (d - ws) >= min_window_days:
                avg_str = composite[ws:d].mean()
                peak_str = composite[ws:d].max()
                windows.append({
                    'window_start': dates[ws],
                    'window_end': dates[min(d - 1, n - 1)],
                    'optimal_entry': dates[ws],
                    'window_days': d - ws,
                    'avg_strength': float(avg_str),
                    'peak_strength': float(peak_str),
                    'score': float(avg_str * np.log(d - ws + 1) * peak_str * 100),
                })
            in_window = False

    if in_window and (n - ws) >= min_window_days:
        avg_str = composite[ws:n].mean()
        peak_str = composite[ws:n].max()
        windows.append({
            'window_start': dates[ws],
            'window_end': dates[n - 1],
            'optimal_entry': dates[ws],
            'window_days': n - ws,
            'avg_strength': float(avg_str),
            'peak_strength': float(peak_str),
            'score': float(avg_str * np.log(n - ws + 1) * peak_str * 100),
        })

    windows.sort(key=lambda w: w['score'], reverse=True)
    return windows[:max_windows]
