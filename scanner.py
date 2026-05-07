"""
scanner.py — Opportunity Scanner
==================================
Scans all instruments for upcoming cycle confluence windows.
Returns a deduplicated, ranked list of LONG opportunities.

Used by: backtest.py, daily_bot.py
"""

import pandas as pd
from typing import List, Dict
from cycle_engine import detect_cycles, project_composite, find_directional_windows
from data_loader import get_symbol
import config as cfg


def scan_opportunities(instruments: dict,
                        inst_indexed: dict,
                        as_of_date: pd.Timestamp) -> List[dict]:
    """
    Scan all instruments for upcoming LONG cycle windows.

    Parameters
    ----------
    instruments : dict of key → DataFrame (raw)
    inst_indexed : dict of key → DataFrame indexed by Date
    as_of_date : scan as of this date (only use data up to here)

    Returns
    -------
    List of opportunity dicts, sorted by score, deduplicated by symbol.
    """
    opps = []

    for key in instruments:
        idf = inst_indexed.get(key)
        if idf is None:
            continue

        available = idf.index[idf.index <= as_of_date]
        if len(available) < cfg.MIN_HISTORY_BARS:
            continue

        close = idf.loc[available, 'Close'].values
        cycles = detect_cycles(close, min_bars=cfg.MIN_HISTORY_BARS)
        if len(cycles) < 3:
            continue

        composite = project_composite(cycles, len(close), cfg.PROJECTION_DAYS)
        windows = find_directional_windows(
            composite, as_of_date,
            min_window_days=cfg.MIN_WINDOW_DAYS,
            max_windows=cfg.MAX_WINDOWS_PER_SCAN
        )

        sym = get_symbol(key, instruments)
        for w in windows:
            if w['window_start'] >= as_of_date:
                opps.append({
                    'key': key,
                    'symbol': sym,
                    'window_start': w['window_start'],
                    'window_end': w['window_end'],
                    'window_days': w['window_days'],
                    'score': w['score'],
                    'avg_strength': w['avg_strength'],
                    'peak_strength': w['peak_strength'],
                })

    # Sort by score, deduplicate by symbol (keep best)
    opps.sort(key=lambda o: o['score'], reverse=True)
    seen = set()
    deduped = []
    for o in opps:
        if o['symbol'] not in seen:
            deduped.append(o)
            seen.add(o['symbol'])

    return deduped
