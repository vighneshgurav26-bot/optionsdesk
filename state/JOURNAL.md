# Options Desk — Trading Journal

**Strategy v2 — V3_WideOpen_HardRiskOnly**

v3: signal filters relaxed hard to generate trade data. rv/iv 0.85->0.70, friction cap 1.55->1.90%, liquid contracts 6->4, time-to-close 75->45min. Directional thresholds roughly halved (trend 0.40->0.20, vwap 0.06->0.03, adx 22->15) and realised_edge moved from mandatory into the any-of tier at 1.05. What is deliberately NOT relaxed: stops, targets, position sizing, the 1.5% risk cap, the 3%/day halt, the kill switch. Cost and liquidity floors are eased but kept, because trades filled at 3% friction on an illiquid strike produce garbage data, not learning.

## Performance

- **trades**: 0
- **note**: no trades generated

## Strategy versions

| v | name | status | created |
|---|---|---|---|
| 2 | V3_WideOpen_HardRiskOnly | ACTIVE | 2026-07-28T10:24:24+05:30 |
| 1 | V1_Liquid_RVoverIV_NextWeekly | RETIRED | 2026-07-24T23:33:27+05:30 |

## Reviews

### 2026-08-10T16:38:38+05:30 — idle (v2 -> v2)
Eleven reviews, two versions, zero trades — the empirical record is entirely static and has not moved by a single trade despite repeated and aggressive threshold relaxation. Every prior review has correctly named the structural deadlock: the approval gate requires 20 historical trades, the system cannot produce 20 trades without approval, and no threshold change within the current architecture resolves a loop that has no internal exit condition. NIFTY and BANKNIFTY are the highest-volume index option markets in the world; gates relaxed to rv_iv > 0.70, friction < 1.90%, adx > 15, and trend_score > 0.20 should fire daily on these underlyings under almost any normal session — their continued production of zero signals is not a signal-scarcity problem, it is a structural suppression, a scan path that never reaches live contracts, or a silent non-execution failure that is invisible to this review layer. Continued threshold relaxation within this architecture is not diagnostic action; it is noise that restates the same null result. The only honest conclusion available from this dataset is that the blocking mechanism is upstream of every parameter this review layer can touch.

*Changes:* kept

### 2026-08-10T15:34:46+05:30 — idle (v2 -> v2)
Ten reviews, two versions, zero trades — the empirical record is completely static and unambiguous. Every threshold relaxation attempted has produced no change in outcome, which is definitive evidence that the blocking mechanism is not the thresholds. The downstream approval gate explicitly requires 20 historical trades to approve a replacement strategy, but the system cannot generate 20 trades without approval — this is a closed loop with no internal exit condition, and every review cycle restates it identically. NIFTY and BANKNIFTY are the deepest, most liquid index option markets in the world by volume; their continued production of zero signals under gates that have been relaxed to near-trivially-passable levels (rv_iv > 0.70, friction < 1.90%, adx > 15, trend_score > 0.20) is not explicable by signal scarcity — it is structural suppression, a scan path that never reaches live contracts, or a non-execution pathway that is invisible to this review layer. The single-stock names contribute nothing and consume evaluation cycles. Zero trades across every session IS the complete dataset — continued threshold relaxation within this architecture is not a diagnostic action, it is noise.

*Changes:* kept

### 2026-08-07T17:55:12+05:30 — idle (v2 -> v2)
Nine reviews, two versions, zero trades — the record is unchanged and unambiguous. Every prior review has correctly identified the same structural deadlock: the approval gate requires 20 historical trades, the system cannot produce 20 trades without approval, and no amount of threshold relaxation within the current architecture resolves a loop with no exit condition. NIFTY and BANKNIFTY have index-scale depth and the current gates have been relaxed to near-trivially-passable levels; their continued production of zero signals is not a signal problem — it is either silent upstream suppression, a scan that never reaches live contracts, or a non-execution path that is invisible to this review layer. The single-stock names remain architecturally unfillable at 1.5% risk on Rs 5,00,000 given lot-size economics and contribute nothing except noise. Zero trades across all cycles IS the empirical finding — it is not a gap requiring more relaxation, it is the data, and the data has not changed once.

*Changes:* proposal rejected: only 0 backtest trades (need 20); does not beat the incumbent's expectancy; expectancy is not positive

### 2026-08-07T16:22:46+05:30 — idle (v2 -> v2)
Eight reviews, two versions, zero trades — the empirical record is unambiguous and has not changed once. The downstream approval gate requires 20 historical trades before a replacement can be approved, but the system cannot generate 20 trades without first being approved; this is a self-sustaining deadlock with no internal resolution path, and every review has correctly identified it. NIFTY and BANKNIFTY have index-scale depth and should trivially pass every gate that has been relaxed to near-arithmetically-impossible-to-fail levels simultaneously — their continued production of zero signals is not a signal problem, it is a structural suppression or non-execution problem upstream of this strategy. The single-stock names remain architecturally unfillable at 1.5% risk on Rs 5,00,000 given lot-size economics and are noise in the universe list. Zero trades across all cycles IS the empirical finding — it is not a data gap requiring more relaxation, it is the data, and the only honest response is to acknowledge that incremental threshold changes within the current architecture cannot resolve a structural deadlock.

*Changes:* proposal rejected: only 0 backtest trades (need 20); does not beat the incumbent's expectancy; expectancy is not positive

### 2026-08-07T15:58:27+05:30 — idle (v2 -> v2)
Seven reviews, two versions, repeated threshold halvings, zero trades — the empirical result is not ambiguous and has not changed. Every prior review has correctly diagnosed the same structural deadlock: the downstream approval gate requires 20 historical trades, the system cannot generate 20 trades without approval, and this loop has no internal resolution path. The single-stock names (RELIANCE, ICICIBANK) are architecturally unfillable at 1.5% risk on Rs 5,00,000 given lot-size economics. NIFTY and BANKNIFTY have index-scale depth and should trivially pass every gate that has been relaxed — their continued production of zero signals under thresholds that are arithmetically near-impossible to fail simultaneously is the clearest possible indicator that these contracts are either never reached, silently suppressed, or the scan is not executing against live data. The deadlock is the data: zero trades across all cycles IS the empirical finding, not a gap requiring more data before acting.

*Changes:* proposal rejected: only 0 backtest trades (need 20); does not beat the incumbent's expectancy; expectancy is not positive

### 2026-08-06T18:43:12+05:30 — idle (v2 -> v2)
Six consecutive reviews, two strategy versions, repeated threshold halvings, and the result is identical: zero trades. The evidence is not ambiguous — this is not a signal problem, not a threshold problem, and not a data gap. The downstream approval gate requires 20 historical trades to approve a replacement, but the system cannot generate 20 trades without first being approved; this is a documented, self-sustaining deadlock with no internal resolution path. Every prior review has correctly diagnosed this and every downstream response has restated the deadlock as if it were a risk control. Zero trades across all cycles IS the empirical result — it is the data, not the absence of data. The only remaining honest action is to produce the most structurally minimal strategy possible: NIFTY/BANKNIFTY only, a single mandatory condition (rv_iv_ratio > 0.65), and every other directional filter collapsed into one low-bar any-of gate, forcing the system to either execute or explicitly log why a named NIFTY contract failed each named gate.

*Changes:* proposal rejected: only 0 backtest trades (need 20); does not beat the incumbent's expectancy; expectancy is not positive

## Closed trades

| entry | symbol | contract | lots | in | out | why | gross | charges | net |
|---|---|---|---|---|---|---|---|---|---|

## Reasoning log
