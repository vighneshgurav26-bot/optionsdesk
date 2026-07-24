"""Option pricing and greeks for NSE index/stock options.

We price on the FORWARD (Black-76), not the spot. NSE index options are
European and cash-settled, and the market's own forward already contains the
dividend and repo effects — so backing the forward out of put-call parity at
the ATM strike is more faithful than guessing a dividend yield.

    F = K_atm + (C_atm - P_atm) * e^{rT}

Everything downstream (IV, delta, gamma, vega, theta, and the second-order
greeks that actually decide whether an intraday long option makes money) is
computed off that forward.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict

SQRT_2PI = math.sqrt(2.0 * math.pi)


def _n(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT_2PI


def _N(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


@dataclass
class Greeks:
    price: float = 0.0
    iv: float = 0.0
    delta: float = 0.0
    gamma: float = 0.0
    vega: float = 0.0            # per 1 vol point (1%)
    theta_cal: float = 0.0       # rupees/day, calendar clock
    theta_session: float = 0.0   # rupees/session, business clock
    theta_per_min: float = 0.0   # rupees/min of live market
    rho: float = 0.0
    vanna: float = 0.0           # d delta / d vol
    vomma: float = 0.0           # d vega / d vol
    charm: float = 0.0           # d delta / d time (per day)
    speed: float = 0.0           # d gamma / d spot
    d1: float = 0.0
    d2: float = 0.0
    moneyness: float = 0.0       # ln(F/K) / (sigma*sqrt(T))
    breakeven_move_pct: float = 0.0
    gamma_theta_ratio: float = 0.0

    def to_dict(self) -> dict:
        return {k: (round(v, 6) if isinstance(v, float) else v)
                for k, v in asdict(self).items()}


def forward_from_parity(spot: float, atm_strike: float, call_mid: float,
                        put_mid: float, r: float, t: float) -> float:
    """Synthetic forward from the ATM call/put pair. Falls back to carry."""
    if call_mid > 0 and put_mid > 0 and atm_strike > 0:
        f = atm_strike + (call_mid - put_mid) * math.exp(r * t)
        # sanity: forward should sit within 3% of spot for intraday horizons
        if spot > 0 and abs(f / spot - 1.0) < 0.03:
            return f
    return spot * math.exp(r * t)


def black76(F: float, K: float, t: float, sigma: float, r: float,
            is_call: bool) -> float:
    if t <= 0 or sigma <= 0 or F <= 0 or K <= 0:
        intrinsic = max(F - K, 0.0) if is_call else max(K - F, 0.0)
        return intrinsic * math.exp(-r * max(t, 0.0))
    v = sigma * math.sqrt(t)
    d1 = (math.log(F / K) + 0.5 * v * v) / v
    d2 = d1 - v
    df = math.exp(-r * t)
    if is_call:
        return df * (F * _N(d1) - K * _N(d2))
    return df * (K * _N(-d2) - F * _N(-d1))


def implied_vol(price: float, F: float, K: float, t: float, r: float,
                is_call: bool, lo: float = 0.005, hi: float = 5.0) -> float:
    """Brent-free bisection + Newton hybrid. Robust on wide/illiquid quotes."""
    if price <= 0 or t <= 0 or F <= 0 or K <= 0:
        return 0.0
    df = math.exp(-r * t)
    intrinsic = df * (max(F - K, 0.0) if is_call else max(K - F, 0.0))
    if price <= intrinsic + 1e-8:
        return 0.0
    cap = df * (F if is_call else K)
    if price >= cap:
        return hi

    sigma = 0.35
    for _ in range(24):                       # Newton with vega
        p = black76(F, K, t, sigma, r, is_call)
        v = sigma * math.sqrt(t)
        d1 = (math.log(F / K) + 0.5 * v * v) / v
        vega = df * F * _n(d1) * math.sqrt(t)
        if vega < 1e-9:
            break
        step = (p - price) / vega
        new = sigma - step
        if new <= lo or new >= hi or not math.isfinite(new):
            break
        if abs(step) < 1e-7:
            return new
        sigma = new
    else:
        return sigma

    a, b = lo, hi                              # bisection fallback
    for _ in range(80):
        mid = 0.5 * (a + b)
        if black76(F, K, t, mid, r, is_call) > price:
            b = mid
        else:
            a = mid
    return 0.5 * (a + b)


def compute(price: float, F: float, K: float, t_cal: float, t_bus: float,
            r: float, is_call: bool, lot_size: int = 1,
            sessions_left: float = 1.0) -> Greeks:
    """Full greek surface for one contract, scaled per SHARE (not per lot)."""
    g = Greeks(price=price)
    sigma = implied_vol(price, F, K, t_cal, r, is_call)
    g.iv = sigma
    if sigma <= 0 or t_cal <= 0:
        g.delta = 1.0 if (is_call and F > K) else (-1.0 if (not is_call and F < K) else 0.0)
        return g

    v = sigma * math.sqrt(t_cal)
    d1 = (math.log(F / K) + 0.5 * v * v) / v
    d2 = d1 - v
    df = math.exp(-r * t_cal)
    nd1 = _n(d1)

    g.d1, g.d2 = d1, d2
    g.moneyness = math.log(F / K) / v

    g.delta = df * (_N(d1) if is_call else _N(d1) - 1.0)
    g.gamma = df * nd1 / (F * v)
    g.vega = df * F * nd1 * math.sqrt(t_cal) / 100.0     # per 1 vol point

    # Black-76 theta, per YEAR, then converted to the two clocks.
    theta_year = -(df * F * nd1 * sigma) / (2.0 * math.sqrt(t_cal))
    if is_call:
        theta_year += -r * df * (F * _N(d1) - K * _N(d2))
    else:
        theta_year += -r * df * (K * _N(-d2) - F * _N(-d1))

    g.theta_cal = theta_year / 365.0
    # Business-clock theta: the same total decay compressed into open sessions.
    sessions_left = max(sessions_left, 0.05)
    total_decay = -theta_year * t_cal            # rupees left to bleed
    g.theta_session = -total_decay / sessions_left
    g.theta_per_min = g.theta_session / 375.0

    g.rho = (K * t_cal * df * _N(d2) / 100.0) if is_call \
        else (-K * t_cal * df * _N(-d2) / 100.0)

    g.vanna = -df * nd1 * d2 / sigma / 100.0
    g.vomma = g.vega * d1 * d2 / sigma
    g.charm = (-df * nd1 * (2 * r * t_cal - d2 * v) / (2 * t_cal * v)) / 365.0
    g.speed = -g.gamma / F * (d1 / v + 1.0)

    # How far the underlying must travel today just to pay for one session of
    # theta. This single number kills more bad intraday longs than any filter.
    if abs(g.delta) > 1e-6:
        move = abs(g.theta_session) / abs(g.delta)
        g.breakeven_move_pct = 100.0 * move / F
    g.gamma_theta_ratio = (g.gamma * F * F * 0.0001) / abs(g.theta_session) \
        if abs(g.theta_session) > 1e-9 else 0.0

    return g
