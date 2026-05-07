"""
data_loader.py — Instrument Data Loading & Deduplication
=========================================================
Loads all CSV files from a data directory, deduplicates by symbol
(keeps longest history), and provides indexed access for backtesting.
"""

import os
import glob
import pandas as pd
from collections import defaultdict
from typing import Dict, Tuple


def load_instruments(data_dir: str,
                     min_bars: int = 1000
                     ) -> Tuple[Dict[str, pd.DataFrame], Dict[str, pd.DataFrame]]:
    """
    Load all CSVs, deduplicate by symbol, return both raw and indexed.

    Parameters
    ----------
    data_dir : path to directory containing subdirectories with CSV files
    min_bars : minimum rows required per instrument

    Returns
    -------
    instruments : dict of key → DataFrame (with Date column)
    inst_indexed : dict of key → DataFrame indexed by Date (for fast lookup)
    """
    csv_files = glob.glob(os.path.join(data_dir, '**', '*.csv'), recursive=True)
    raw = {}
    sym_keys = defaultdict(list)

    for f in sorted(csv_files):
        try:
            df = pd.read_csv(f)
            df['Date'] = pd.to_datetime(df['Date'])
            df = df.sort_values('Date').reset_index(drop=True)
            df = df.dropna(subset=['Close', 'High', 'Low'])
            df = df[df['Close'] > 0].reset_index(drop=True)

            sym = df['Symbol'].iloc[0].strip() if 'Symbol' in df.columns else \
                  os.path.basename(f).replace('.csv', '')
            subdir = os.path.basename(os.path.dirname(f))
            key = f"{sym}_{subdir}"

            if len(df) >= min_bars:
                raw[key] = df
                sym_keys[sym].append(key)
        except Exception:
            pass

    # Deduplicate: keep longest history per symbol
    instruments = {}
    for sym, keys in sym_keys.items():
        best = max(keys, key=lambda k: len(raw[k]))
        instruments[best] = raw[best]

    # Create date-indexed version for fast daily lookups
    inst_indexed = {}
    for key, df in instruments.items():
        inst_indexed[key] = df.set_index('Date')

    dupes = [s for s, ks in sym_keys.items() if len(ks) > 1]
    print(f"Loaded {len(raw)} files → {len(instruments)} unique instruments")
    if dupes:
        print(f"Deduplicated: {dupes}")

    return instruments, inst_indexed


def get_symbol(key: str, instruments: dict) -> str:
    """Extract clean symbol from instrument key."""
    df = instruments[key]
    if 'Symbol' in df.columns:
        return df['Symbol'].iloc[0].strip()
    return key.split('_')[0]


def build_trading_calendar(instruments: dict,
                            start_date: pd.Timestamp,
                            end_date: pd.Timestamp) -> list:
    """Build sorted list of all trading days across instruments."""
    all_dates = set()
    for df in instruments.values():
        all_dates.update(df['Date'].values)
    return sorted([pd.Timestamp(d) for d in all_dates
                   if start_date <= pd.Timestamp(d) <= end_date])
