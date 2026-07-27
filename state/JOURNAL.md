# Options Desk — Trading Journal

**Strategy v1 — V1_Liquid_RVoverIV_NextWeekly**

Calibrated on live NIFTY books, 24-Jul-2026. Three measurements drove it. (1) The front expiry with 2 sessions left bled 18.2% of premium per session versus 5.9% on the next weekly, so this avoids any expiry with under 3 sessions left. (2) Round-trip friction on liquid near-ATM index calls ran 0.96-1.29%, but jumped past 2% on sub-Rs60 premiums, so the premium floor does more work than any OI filter. (3) Five-day realised vol was 6.9% against 11.4% implied - RV/IV 0.60 - which is precisely the regime where a directional buyer is right on direction and still loses. So the binding condition is realised-versus-implied, not the signal.

## Performance

- **trades**: 0
- **note**: no trades generated

## Strategy versions

| v | name | status | created |
|---|---|---|---|
| 1 | V1_Liquid_RVoverIV_NextWeekly | ACTIVE | 2026-07-24T23:33:27+05:30 |

## Reviews

### 2026-07-27T19:25:28+05:30 — idle (v1 -> v1)
Five review cycles, zero trades, zero empirical data — the rejection loop is now fully self-sealing and must be broken by design. The blocked-and-skipped log is the only evidence available, and it is unambiguous: on the 11:57 scan NIFTY showed trend_score=0.555, rv/iv=0.983, edge=2.858, friction=1.346% — four heavy conditions clearing simultaneously on the most liquid index name in the universe, yet no trade fired, almost certainly because adx_proxy, vwap_dev_pct, and/or the 'any' clause did not simultaneously clear. The 12:22 scan confirms trend_score=0.141 as the active blocker on an otherwise clean tape; the directional filter alone is gating out sessions where vol, friction, and edge are all acceptable. Every past review correctly diagnosed conjunctive over-constraint; every proposed fix was rejected for lacking 20 trades; but the strategy structurally cannot reach 20 trades without relaxation — the validation criterion and the filter trap are arithmetically mutually exclusive. The note from the system itself states plainly: 'If the desk has not traded, the entry rules are too tight. A strategy that never fires learns nothing.' That is the authoritative instruction and it must be acted on now.

*Changes:* proposal rejected: only 0 backtest trades (need 20); does not beat the incumbent's expectancy; expectancy is not positive

### 2026-07-27T18:25:29+05:30 — idle (v1 -> v1)
Five review cycles, zero trades, zero empirical data — the rejection loop is now the dominant risk, not the strategy's signal logic. The blocked-and-skipped log is conclusive: on the 11:57 scan NIFTY showed trend_score=0.555 (passes 0.45), rv/iv=0.983 (passes 0.85), friction=1.346% (passes 1.45%), edge=2.858 (passes 1.3) — four of the ten 'all' conditions clearing simultaneously on a liquid index name, yet no trade fired. The 12:22 scan confirms trend_score=0.141 on NIFTY as the active blocker on an otherwise acceptable tape; BANKNIFTY trend=-0.231 blocks the put side. The conjunctive bundle of ten simultaneous 'all' conditions plus an 'any' clause across a universe of 2-4 names has a joint intraday probability that is structurally near zero — this is not bad luck, it is arithmetic. Four consecutive reviews correctly diagnosed this and proposed relaxation; each was rejected for lacking 20 trades, but the strategy will never accumulate 20 trades unless the filter is loosened — the rejection criterion and the filter trap are mutually reinforcing. The honest conclusion is that the strategy must be modified to fire, or it is not a trading strategy.

*Changes:* proposal rejected: only 0 backtest trades (need 20); does not beat the incumbent's expectancy; expectancy is not positive

### 2026-07-27T16:27:22+05:30 — idle (v1 -> v1)
Four scan cycles, zero trades, zero empirical data — the pattern is now unambiguous and the past three reviews have already diagnosed it correctly each time. The blocked-and-skipped log shows the market is not the problem: NIFTY rv/iv=0.98-0.99, edge=2.6-2.9, friction=1.27-1.35% are all acceptable, and on the 11:57 scan trend_score=0.555 already cleared the 0.45 threshold while rv/iv and friction also passed — yet no trade fired because the conjunctive 'all' block demands every one of ten conditions simultaneously true, plus the 'any' clause, across a universe of 2-4 names. The 12:22 scan shows the directional filter (trend_score=0.141 on NIFTY, -0.231 on BANKNIFTY) as the active blocker on an otherwise acceptable tape. The strategy has now consumed an entire trading session without a single observation; it cannot self-validate, cannot surface MFE/MAE data, and cannot prove or disprove any of its own assumptions. Three successive reviews proposed relaxation and were correctly rejected for lacking 20 trades — but the rejection loop itself is now the failure mode: the strategy will never reach 20 trades if the filter set is never loosened. The honest diagnosis is that the conjunctive bundle is structurally miscalibrated relative to the available universe size and intraday joint-probability reality.

*Changes:* proposal rejected: only 0 backtest trades (need 20); does not beat the incumbent's expectancy; expectancy is not positive

### 2026-07-27T13:12:41+05:30 — idle (v1 -> v1)
Three scan cycles, zero trades, zero empirical data — the strategy is not a trading strategy yet, it is a filter set that is permanently in standby. The blocked-and-skipped log shows the market is not junk: NIFTY at rv/iv=0.98-0.99, edge=2.6-2.9, friction=1.27-1.35% are all acceptable readings, and on the 11:57 scan trend_score=0.555 was already above the 0.45 threshold. The active gatekeepers are the conjunctive bundle: trend_score, vwap_dev_pct, adx_proxy, realised_edge_ratio, AND the 'any' clause must all be true simultaneously across a universe of only 2-4 names — joint probability of that conjunction is structurally too low for intraday options where conditions rarely align perfectly across every dimension at once. Two past reviews already identified this and proposed changes that were correctly rejected for having zero backtest trades; the correct response now is a minimal surgical relaxation of the tightest conjunctive conditions to allow the first trades to exist, not a wholesale redesign. Without a single closed trade there is no MFE, MAE, exit reason mix, or theta-versus-move evidence to review — the only honest diagnosis is structural overfitting of the filter logic before any live observation.

*Changes:* proposal rejected: only 0 backtest trades (need 20); does not beat the incumbent's expectancy; expectancy is not positive

### 2026-07-27T12:22:20+05:30 — idle (v1 -> v1)
The strategy has generated zero trades across two full scan cycles despite the market showing borderline-passing readings on multiple dimensions simultaneously — NIFTY rv/iv=0.98-0.99, trend=0.14-0.56, friction=1.28-1.35%, edge=2.6-2.9. The conjunctive 'all' block requiring every one of ten conditions to be true at once is the structural problem: each condition is individually reasonable but their joint probability is too low for the available universe of 2-4 names. The second scan shows NIFTY trend_score=0.141 failing the 0.45 threshold while BANKNIFTY trend=-0.231 fails the put side threshold of -0.45, meaning the directional filter is the active gatekeeper on otherwise acceptable vol/friction readings. There is no empirical base — no MFE, no MAE, no exit reason distribution, no theta-versus-move data — so any verdict on signal quality is inference from near-misses, not evidence. The strategy cannot self-correct or validate with zero observations; the primary obligation now is to generate enough trades to produce a real performance record without materially increasing risk.

*Changes:* proposal rejected: only 0 backtest trades (need 20); does not beat the incumbent's expectancy; expectancy is not positive

### 2026-07-27T11:57:08+05:30 — idle (v1 -> v1)
Zero trades have been generated, which means the entry ruleset is not calibrated to actual market conditions — it is a hypothesis that has never been tested. The single logged scan shows NIFTY with edge=2.86, rv/iv=0.98, trend=0.56, friction=1.35% and BANKNIFTY with rv/iv=1.19, trend=-0.46: these are not junk readings, they are borderline or near-passing on several dimensions simultaneously, which suggests the conjunctive 'all' block is too tight as a bundle rather than any single condition being wildly wrong. With zero trades there is no MFE/MAE, no exit reason mix, no theta-versus-move data — the review has no empirical base to stand on, and any strong claim about signal quality would be fabricated. The RV/IV threshold of 0.85 is structurally sensible but on the day of the scan NIFTY was at 0.98 (passing) while BANKNIFTY was at 1.19 (passing), yet neither fired — meaning the blocking conditions are the conjunctive bundle of trend_score, vwap_dev_pct, adx_proxy, realised_edge_ratio, AND the 'any' clause all having to be true simultaneously. The strategy cannot learn, adjust, or validate itself with zero observations; the note in the payload explicitly flags this and it is correct.

*Changes:* proposal rejected: only 0 backtest trades (need 20); does not beat the incumbent's expectancy; expectancy is not positive

## Closed trades

| entry | symbol | contract | lots | in | out | why | gross | charges | net |
|---|---|---|---|---|---|---|---|---|---|

## Reasoning log
