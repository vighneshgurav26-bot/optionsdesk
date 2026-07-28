"""
kite_resample.py

Turns raw Kite historical_data() candles into a clean, gap-safe
lookback window for Kronos forecasting.

Written so the comments explain themselves in plain English.
"""
from datetime import time

# NSE trades 9:15 -> 15:30. Anything before/after is "off session".
SESSION_START = time(9, 15)
SESSION_END = time(15, 30)


def is_in_session(dt):
    t = dt.time()
    return SESSION_START <= t <= SESSION_END


def clean_and_flag_gaps(raw_candles, max_gap_minutes=15):
    """
    raw_candles: list of dicts from kite.historical_data(), each with
        'date' (datetime), 'open', 'high', 'low', 'close', 'volume'

    Returns: list of dicts, same fields + 'gap' (True/False) marking
    any candle that starts a new trading day or follows a big pause
    (like a data outage or a missed tick).

    Why this matters: Kronos was NOT trained on NSE's 9:15-15:30
    session pattern with its overnight and weekend gaps. If we just
    hand it raw candles back-to-back, it can mistake a "Friday close
    -> Monday open" jump for a real intraday move and hallucinate
    momentum that never happened. Flagging gaps lets us cut the
    window cleanly instead.
    """
    cleaned = []
    prev_dt = None
    for c in raw_candles:
        dt = c["date"]
        if not is_in_session(dt):
            continue  # throw away anything outside 9:15-15:30
        gap = False
        if prev_dt is not None:
            minutes_since_last = (dt - prev_dt).total_seconds() / 60
            if minutes_since_last > max_gap_minutes or dt.date() != prev_dt.date():
                gap = True
        cleaned.append({**c, "gap": gap})
        prev_dt = dt
    return cleaned


def latest_unbroken_window(cleaned_candles, window_size=400):
    """
    Kronos wants one continuous stretch of candles with no gaps in it.
    This walks backward from the most recent candle and stops at the
    first gap it finds, so we never hand Kronos a session-jump
    pretending to be a normal 5-minute move.

    Returns up to `window_size` candles, oldest first, gap-free.
    """
    if not cleaned_candles:
        return []
    end = len(cleaned_candles)
    start = 0
    for i in range(end - 1, -1, -1):
        if cleaned_candles[i]["gap"] and i != end - 1:
            start = i + 1
            break
    window = cleaned_candles[start:end]
    return window[-window_size:]
