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
