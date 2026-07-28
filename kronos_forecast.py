"""
kronos_forecast.py

Asks the Kronos AI model "what do you think happens next?" for one
underlying (like NIFTY or RELIANCE), using the last few hundred
candles as its only input.

SAFETY RULE built into this file, on purpose:
If ANYTHING goes wrong (model missing, internet hiccup, weird data,
not enough history, whatever) this file NEVER crashes the bot and
NEVER blocks a trade. It just returns "neutral, confidence 0" and
the rest of the bot carries on exactly as if Kronos wasn't there.
Kronos is one extra opinion in the room, never a gatekeeper.
"""
import sys
import os

MIN_BARS_NEEDED = 64  # Kronos wants a real lookback; below this we skip it

NEUTRAL_RESULT = {
    "available": False,
    "direction": "neutral",
    "confidence": 0.0,
    "pred_vol": None,
    "note": "kronos not used",
}

_PREDICTOR = None
_LOAD_ERROR = None
_LOAD_ATTEMPTED = False


def _load_kronos():
    """
    Loads the Kronos model + tokenizer once. Returns (predictor, None)
    on success, or (None, error_message) on any failure.
    """
    try:
        kronos_lib_path = os.path.join(os.path.dirname(__file__), "kronos_lib")
        if kronos_lib_path not in sys.path:
            sys.path.insert(0, kronos_lib_path)
        from model import Kronos, KronosTokenizer, KronosPredictor  # noqa: E402

        tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
        model = Kronos.from_pretrained("NeoQuasar/Kronos-small")
        predictor = KronosPredictor(model, tokenizer, device="cpu", max_context=512)
        return predictor, None
    except Exception as e:  # pragma: no cover - safety net
        return None, f"{type(e).__name__}: {e}"


def get_kronos_signal(window, lookahead_bars=6):
    """
    window: list of dicts (from kite_resample.latest_unbroken_window),
            each with date/open/high/low/close/volume, oldest first.

    Returns a dict:
        available   - True only if Kronos actually produced a forecast
        direction   - "bullish" / "bearish" / "neutral"
        confidence  - 0.0 to 1.0 (how sure Kronos is, based on how big
                      the predicted move is relative to its own spread
                      of Monte-Carlo outcomes)
        pred_vol    - Kronos's rough near-term volatility guess (or None)
        note        - human-readable one-liner for the journal/log
    """
    global _PREDICTOR, _LOAD_ERROR, _LOAD_ATTEMPTED

    if len(window) < MIN_BARS_NEEDED:
        return {**NEUTRAL_RESULT, "note": f"only {len(window)} clean bars, need {MIN_BARS_NEEDED}+"}

    if not _LOAD_ATTEMPTED:
        _LOAD_ATTEMPTED = True
        _PREDICTOR, _LOAD_ERROR = _load_kronos()

    if _PREDICTOR is None:
        return {**NEUTRAL_RESULT, "note": f"kronos unavailable: {_LOAD_ERROR}"}

    try:
        import pandas as pd

        df = pd.DataFrame(window)
        df = df.rename(columns=str.lower)
        x_df = df[["open", "high", "low", "close", "volume"]]
        x_timestamp = pd.to_datetime(df["date"])
        last_ts = x_timestamp.iloc[-1]
        y_timestamp = pd.date_range(start=last_ts, periods=lookahead_bars + 1, freq="5min")[1:]

        pred_df = _PREDICTOR.predict(
            df=x_df,
            x_timestamp=x_timestamp,
            y_timestamp=y_timestamp,
            pred_len=lookahead_bars,
            T=1.0,
            top_p=0.9,
            sample_count=20,  # Monte-Carlo runs -> a spread of outcomes, not one guess
        )

        last_close = float(df["close"].iloc[-1])
        pred_close_mean = float(pred_df["close"].mean())
        pred_close_std = float(pred_df["close"].std())

        move_pct = (pred_close_mean - last_close) / last_close
        confidence = 0.0
        if pred_close_std > 0:
            confidence = min(abs(move_pct) / (pred_close_std / last_close), 1.0)

        direction = "neutral"
        if move_pct > 0.001 and confidence > 0.2:
            direction = "bullish"
        elif move_pct < -0.001 and confidence > 0.2:
            direction = "bearish"

        pred_vol = pred_close_std / last_close  # rough proxy only, not a true IV number

        return {
            "available": True,
            "direction": direction,
            "confidence": round(confidence, 3),
            "pred_vol": round(pred_vol, 5),
            "note": f"predicted move {move_pct * 100:.2f}% over next {lookahead_bars} bars",
        }
    except Exception as e:  # pragma: no cover - safety net
        return {**NEUTRAL_RESULT, "note": f"kronos inference error: {type(e).__name__}: {e}"}
