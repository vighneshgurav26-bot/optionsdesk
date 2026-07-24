"""The Claude layer: research -> debate -> verdict, plus strategy authoring
and self-review.

Two hard design rules:

1. The brain never sees or writes executable code. It emits JSON that conforms
   to the strategy schema and is clamped by strategy.clamp() before use.
2. The brain never gets to approve its own trade. Its verdict is an INPUT to
   the risk gate, which can and does veto it.

Anthropic API key comes from ANTHROPIC_API_KEY.
"""
from __future__ import annotations

import json
import os
import re

import requests

from . import features as feat_mod, strategy as strat

API = "https://api.anthropic.com/v1/messages"


class Brain:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.model = cfg["brain"]["model"]
        self.max_tokens = cfg["brain"]["max_tokens"]
        self.key = os.environ.get("ANTHROPIC_API_KEY", "")

    @property
    def available(self) -> bool:
        return bool(self.key)

    def _call(self, system: str, user: str, max_tokens: int | None = None) -> str:
        if not self.key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        r = requests.post(API, timeout=120, headers={
            "x-api-key": self.key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }, json={
            "model": self.model,
            "max_tokens": max_tokens or self.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        })
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json().get("content", [])
                       if b.get("type") == "text")

    @staticmethod
    def _json(text: str) -> dict | None:
        text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", text, re.S)
            if m:
                try:
                    return json.loads(m.group(0))
                except json.JSONDecodeError:
                    return None
        return None

    # ------------------------------------------------------------------
    DESK_CONTEXT = """You run an INTRADAY OPTION BUYING desk on NSE India.

Account: Rs 5,00,000 paper capital, Zerodha. Long options only, no shorts,
no overnight positions, everything flat by 15:15 IST. You may trade NSE index
options and options on NIFTY 50 large caps.

MANDATE: only volatile, only liquid. Both halves are enforced before your
rules ever run, and you cannot override either:
- A screening pass ranks underlyings on liquidity x volatility each cycle and
  hands you at most 4. If an underlying is missing, its book was too wide, its
  offer too thin, or its tape too quiet.
- Every contract is gated on minimum premium, spread, top-of-book depth,
  book-walk impact, OI and volume, then re-gated at your actual order size.

The economics you are fighting:
- Zerodha charges Rs 20 flat per executed order, plus STT on the sell side,
  exchange transaction charges on premium, stamp duty, GST. Because the Rs 20
  is FLAT, friction is a moving target: roughly 0.6% of premium on a Rs 11,000
  ticket, but ~2% on a Rs 3,000 ticket and worse below that. Small clips are
  taxed hardest. The exact number for the contract in front of you is given to
  you as friction_pct - use it, do not assume.
- Long options bleed theta on a BUSINESS clock. A weekly option can lose 5-9%
  of its premium in one session with the underlying unchanged.
- The tick is a fixed Rs 0.05. On a Rs 8 option one tick is 0.6%, so the
  narrowest quotable spread is already punitive. Real measured example: the
  same RELIANCE 1280 CE cost 1.26% round trip on the August expiry at Rs 33.67
  and 3.40% on the July expiry at Rs 7.72. Cheap options are a trap.
- Buying premium when realised volatility sits below implied means paying for
  movement the tape is not delivering. Watch rv_iv_ratio.
- The market's own ATM straddle is a fair quote for the day's range. If your
  expected capture is a large fraction of the straddle, your assumption is
  probably wrong.

Therefore: an intraday long option needs the underlying to move meaningfully
in your favour, fairly quickly, or you lose by default. Trade selectivity beats
trade frequency. Doing nothing is a valid and often correct output.

Rs 5,00,000 funds multiple lots, and that matters. The
Rs 20 is per ORDER, not per lot, so a 3-lot clip carries the same brokerage as
a 1-lot clip. Prefer fewer, larger, better-selected trades."""

    # ------------------------------------------------------------------
    def research_brief(self, feats_by_symbol: dict, snapshots: dict,
                       vix: float | None) -> str:
        payload = {
            "india_vix": vix,
            "symbols": {s: {
                "spot": snapshots[s]["spot"],
                "expected_move_pct": snapshots[s]["expected_move_pct"],
                "features": f,
            } for s, f in feats_by_symbol.items()},
        }
        sys = self.DESK_CONTEXT + """

You are the RESEARCH agent. Produce a compact brief: what regime each
underlying is in, where the volatility sits versus its own recent history,
what the option flow (PCR, OI change, skew, max pain) implies, and which
single underlying — if any — has the cleanest setup right now.

Be blunt about a bad tape. 200 words maximum. Plain prose, no headers."""
        return self._call(sys, json.dumps(payload, default=str), 900)

    def debate(self, symbol: str, brief: str, feats: dict, side_hint: str,
               contract: dict, spec: dict) -> dict:
        payload = {
            "symbol": symbol, "research_brief": brief, "features": feats,
            "proposed_side": side_hint,
            "contract": {k: contract.get(k) for k in (
                "tradingsymbol", "strike", "opt_type", "mid", "bid", "ask",
                "iv", "delta", "gamma", "vega", "theta_session", "theta_per_min",
                "vanna", "vomma", "charm", "breakeven_move_pct",
                "gamma_theta_ratio", "spread_pct", "oi", "premium_per_lot",
                "lot_size", "sessions_left")},
            "strategy_rules_that_fired": {
                "entry": spec.get(f"entry_long_{'call' if side_hint == 'CE' else 'put'}"),
                "exit": spec.get("exit"),
            },
        }
        sys = self.DESK_CONTEXT + """

You are the DEBATE layer: run a bull case and a bear case against this
specific proposed option purchase, then deliver a verdict.

BULL: why this contract, this strike, this moment. Be specific about the
greeks — is gamma per rupee of theta actually favourable, is the breakeven
move plausible within the holding period.

BEAR: attack it. Is the signal late? Is IV rich and about to crush? Is the
spread eating the target? Is the breakeven move larger than what this tape
delivers? Would this trade lose money even if the direction is right?

Then weigh them. Default to NO. Only approve when the bull case survives the
bear case on the numbers, not on the narrative.

Reply with ONLY this JSON:
{"bull":"...","bear":"...","verdict":"TAKE"|"SKIP",
 "confidence":0.0-1.0,"thesis":"one sentence",
 "invalidation":"what would prove this wrong","key_risk":"..."}"""
        out = self._json(self._call(sys, json.dumps(payload, default=str), 1600))
        if not out or out.get("verdict") not in ("TAKE", "SKIP"):
            return {"verdict": "SKIP", "confidence": 0.0,
                    "thesis": "brain returned unusable output",
                    "bull": "", "bear": "", "key_risk": "parse failure"}
        return out

    # ------------------------------------------------------------------
    def author_strategy(self, context: dict) -> dict | None:
        sys = self.DESK_CONTEXT + f"""

You are the STRATEGY author. Write the next version of the desk's intraday
strategy as JSON.

You may ONLY reference these features in rules:
{json.dumps(feat_mod.FEATURE_DOC, indent=1)}

Operators for a condition: {list(strat.OPS)}
A condition is {{"feature": name, "op": op, "value": number or [lo,hi]}}
Rule blocks are {{"all":[...], "any":[...], "none":[...]}}

Schema you must return (no extra keys, no prose outside the JSON):
{{
 "name": "short_snake_case_name",
 "rationale": "2-4 sentences: what edge you believe exists and why the costs
                do not eat it",
 "universe": ["NIFTY", ...],
 "session": {{"start":"HH:MM","no_new_after":"HH:MM","force_exit":"HH:MM"}},
 "selection": {{"expiry":"nearest"|"skip_expiry_day"|"next",
                "delta_band":[lo,hi], "max_spread_pct":x, "min_oi":n,
                "max_premium_per_lot":n}},
 "entry_long_call": {{...rules...}},
 "entry_long_put": {{...rules...}},
 "exit": {{"target_pct":x,"stop_pct":x,"trail_after_pct":x,
           "trail_giveback_pct":x,"time_stop_min":n,"iv_crush_exit_pct":x,
           "underlying_invalidation":{{"feature":"...","flip":true}}}},
 "sizing": {{"risk_per_trade_pct":x,"max_lots":n,"max_premium_pct":x}},
 "risk": {{"daily_loss_pct":x,"max_trades_day":n,"max_concurrent":n,
           "cooldown_min_after_loss":n}}
}}

Constraints you cannot escape: risk_per_trade_pct <= 2, daily_loss_pct <= 3,
max_lots <= 3, max_concurrent <= 3, max_trades_day <= 6. Values above these
are silently clamped, so setting them high buys you nothing.

Design guidance:
- Entry rules MUST include at least one cost-aware condition (edge_ratio,
  atm_total_friction_pct, atm_breakeven_move_pct, atm_one_tick_pct) and at
  least one volatility-regime condition (rv_iv_ratio, atr_pct,
  expected_move_pct). A rule set that ignores either will lose.
- max_lots above 1 is usually right at this capital. Check the sizing that
  actually happened in the trade log before assuming otherwise.
- Prefer few high-quality conditions over many. Six conditions that each
  filter something real beat twelve that overfit.
- If the evidence says the previous version traded too much, tighten. If it
  says the previous version never traded at all, loosen — a strategy that
  never fires generates no information and is a failure too.
- Change a SMALL number of things per version and say which, so the next
  review can attribute the effect.

Return ONLY the JSON."""
        out = self._json(self._call(sys, json.dumps(context, default=str)[:60000],
                                    4000))
        if not out or "entry_long_call" not in out:
            return None
        return out

    def review(self, context: dict) -> dict | None:
        sys = self.DESK_CONTEXT + """

You are the REVIEW agent. You are looking at the desk's own closed trades,
its equity curve, and the strategy version that produced them.

Do this honestly. Your job is not to defend the previous version.

Look for:
- Where the money actually went. Compare gross P&L to charges — if charges are
  a large fraction of gross, the trade size or frequency is wrong, not the signal.
- MFE vs MAE: were targets too far, stops too tight, or exits too slow?
- Exit reason mix. Mostly TIME_STOP means the entries had no urgency. Mostly
  STOP means entries were late or stops were inside the noise. Mostly
  SESSION_CLOSE means no exit logic is binding.
- Theta paid versus move captured on losers.
- Whether a small number of trades is doing all the work (fragile) or the
  result is broad (real).
- Sample size. With fewer than ~20 trades, say so and prefer a small change.

Reply with ONLY this JSON:
{"lessons":"what the evidence actually shows, 3-6 sentences",
 "diagnosis":"the single biggest problem",
 "action":"KEEP"|"TWEAK"|"REPLACE",
 "changes":"specific changes you want, plain English",
 "confidence":0.0-1.0}"""
        return self._json(self._call(sys, json.dumps(context, default=str)[:60000],
                                     2000))
