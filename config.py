"""
config.py — Strategy Configuration
====================================
All parameters in one place. Edit here to tune the strategy.
"""

# ─── PORTFOLIO ───────────────────────────────────────────────
MAX_POSITIONS = 50           # Maximum concurrent open positions
SCAN_INTERVAL_DAYS = 63      # Quarterly re-scan for new opportunities
PROJECTION_DAYS = 252        # Look 1 year ahead for cycle windows

# ─── CYCLE DETECTION ─────────────────────────────────────────
MIN_HISTORY_BARS = 1000      # Minimum daily bars needed for analysis
MIN_WINDOW_DAYS = 15         # Minimum window length (~3 weeks)
MAX_WINDOWS_PER_SCAN = 2     # Max windows per instrument per scan

# ─── ENTRY PROTOCOL ──────────────────────────────────────────
USE_WEEK1_CONFIRMATION = True   # Enter 25% → confirm after 5 days → scale to 100%
CONFIRMATION_DAYS = 5           # Days to wait for directional confirmation
INITIAL_ALLOCATION_PCT = 25     # % of position at initial entry
FULL_ALLOCATION_PCT = 100       # % after confirmation

# ─── EXIT PROTOCOL ───────────────────────────────────────────
FIRST_TARGET_PCT = 5.0         # First take-profit level
FIRST_EXIT_PCT = 50            # % of position sold at first target
MID_EXIT_PCT = 25              # % sold at midpoint target
FINAL_EXIT_PCT = 25            # % sold at optimal target

# ─── TRAILING STOP (pre-target) ──────────────────────────────
USE_TRAILING_STOP = True       # Activate trailing stop once +3% reached
TRAILING_ACTIVATION_PCT = 3.0  # MFE threshold to activate trailing
TRAILING_RETENTION_PCT = 0.50  # Keep 50% of peak (trail at 50% of MFE)

# ─── STOP LOSS ────────────────────────────────────────────────
USE_STOP_LOSS = False          # No fixed stop loss (confirmed by backtests)
STOP_LOSS_PCT = -10.0          # If enabled: -10% stop

# ─── BREAKEVEN STOP (post-target) ────────────────────────────
# After first 5% target is hit, stop on remaining position moves to entry
BREAKEVEN_STOP_AFTER_TARGET = True

# ─── INSTRUMENT-SPECIFIC OPTIMAL TARGETS ─────────────────────
# Derived from P75 of Max Favorable Excursion during cycle windows
# Floor: 5.0%, Cap: 30.0%
OPTIMAL_TARGETS = {
    'AAPL': 13.8, 'ABBV': 16.4, 'ADBE': 20.4, 'AGG': 5.0,
    'AMAT': 28.5, 'AMD': 27.5, 'AMGN': 13.5, 'AMZN': 12.5,
    'AVGO': 30.0, 'BAC': 8.8, 'BND': 5.0, 'BRK B': 9.5,
    'CMCSA': 9.2, 'COST': 14.9, 'CRM': 10.5, 'CSCO': 9.8,
    'CVX': 8.0, 'DIA': 5.3, 'EEM': 5.4, 'EFA': 8.4,
    'EMB': 5.0, 'GILD': 18.1, 'GLD': 6.1, 'GOOGL': 13.7,
    'HD': 11.9, 'HON': 10.4, 'HYG': 5.0, 'IEF': 5.0,
    'INTU': 12.1, 'ISRG': 11.9, 'IWM': 8.7, 'JNJ': 5.8,
    'JNK': 5.0, 'JPM': 12.5, 'LLY': 10.3, 'LQD': 5.0,
    'MA': 11.4, 'META': 15.0, 'MSFT': 9.8, 'MUB': 5.0,
    'NFLX': 20.2, 'NVDA': 30.0, 'PEP': 5.7, 'PG': 6.7,
    'QCOM': 23.7, 'QQQ': 7.3, 'SBUX': 12.6, 'SHY': 5.0,
    'SLV': 24.8, 'SPY': 5.3, 'TIP': 5.0, 'TLT': 5.0,
    'TMUS': 6.3, 'TSLA': 30.0, 'TXN': 12.6, 'UNH': 8.0,
    'USO': 10.5, 'V': 8.9, 'VEA': 5.8, 'VOO': 5.8,
    'VTI': 5.0, 'VWO': 10.9, 'WMT': 9.8, 'XLE': 9.8,
    'XLF': 6.0, 'XLI': 6.4, 'XLK': 8.5, 'XLP': 5.0,
    'XLV': 6.8, 'XOM': 11.5,
}

# Default optimal target for instruments not in the table
DEFAULT_OPTIMAL_TARGET = 10.0
