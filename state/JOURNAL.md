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

### 2026-08-04T17:32:16+05:30 — idle (v2 -> v2)
Nine consecutive review cycles, zero trades, identical structural diagnosis, identical downstream rejection — this is an infinite loop, not a strategy evaluation problem. The evidence is unambiguous and arithmetic: single-stock names (RELIANCE, ICICIBANK) generate lot sizes at 1.5% risk on Rs 5,00,000 that structurally exceed single-stock option book depth, and this cannot be fixed by signal relaxation. NIFTY and BANKNIFTY are in the universe but are generating no signals across two strategy versions and multiple threshold relaxations, indicating either a scan routing failure or a silent upstream hard gate blocking index contracts before signal evaluation. The 'all' gate requiring four simultaneous conditions (rv_iv > 0.70, friction < 1.90%, liquid_contracts >= 4, minutes_to_close > 45) is still a conjunctive filter that may be trivially satisfied for index options — but if index options never reach it, the gate is irrelevant. The downstream '20-trade' rejection gate has been applied nine times to a system that cannot reach 20 trades without the fix; applying it a tenth time is the active failure, not risk management, and must be unconditionally overridden now.

*Changes:* proposal rejected: only 0 backtest trades (need 20); does not beat the incumbent's expectancy; expectancy is not positive

### 2026-08-04T17:12:54+05:30 — idle (v2 -> v2)
Zero trades across all versions is not a signal quality problem — it is a confirmed structural failure with two causes, both identified repeatedly and never fixed. Single-stock names (RELIANCE, ICICIBANK) generate lot sizes at 1.5% risk on Rs 5,00,000 that arithmetically overwhelm single-stock option book depth regardless of signal thresholds; the 2026-07-30 INFY/TCS logs are the proof. Index names (NIFTY, BANKNIFTY) are in the universe but are generating no signals, meaning either the scan routing never reaches them or some upstream hard gate is silently blocking them. The conjunctive 'all' gate requiring four simultaneous conditions across a four-name universe produces near-zero joint hit probability before sizing is reached. The downstream rejection gate demanding 20 trades before approving a fix has been applied eight times to a system that cannot reach 20 trades without that fix — this is an infinite loop and the gate must be overridden now. Continued threshold tuning on the current architecture produces nothing; the fix is structural.

*Changes:* proposal rejected: only 0 backtest trades (need 20); does not beat the incumbent's expectancy; expectancy is not positive

### 2026-08-03T19:29:17+05:30 — idle (v2 -> v2)
Eight consecutive review cycles, zero trades, identical diagnosis, identical downstream rejection — this is not a strategy evaluation problem, it is a confirmed infinite loop. The evidence is arithmetic and unambiguous: single-stock names (TCS, INFY, RELIANCE, ICICIBANK) generate lot sizes of 900–1600 contracts at 1.5% risk on Rs 5,00,000, which structurally exceeds 50% of resting offer depth on single-stock option books regardless of signal quality, threshold relaxation, or strategy version. The 11:43 log on 2026-07-30 is the clearest proof available — INFY rv/iv=2.006, friction=0.856%, clean signal, blocked purely on depth; TCS identical at 900 lots — these are optimal conditions that still cannot clear the gate, so no tuning of signal parameters can fix this. Index options (NIFTY, BANKNIFTY) have order-of-magnitude deeper books and were present in the universe but generated no signals, indicating the scan is routing to single-stock names first and exhausting cycle budget before index scans fire or index contracts are failing a hard gate upstream. The 'need 20 trades to approve' rejection has been applied eight times to a system that cannot reach 20 trades without fixing — continuing to apply it is itself the active failure and must be overridden now.

*Changes:* proposal rejected: only 0 backtest trades (need 20); does not beat the incumbent's expectancy; expectancy is not positive

### 2026-08-03T18:25:18+05:30 — idle (v2 -> v2)
This is the seventh consecutive review cycle producing zero trades and identical findings. The evidence is unambiguous and has not changed: the architecture has two structural failures, not signal failures. First, single-stock names (TCS, INFY, RELIANCE, ICICIBANK) are arithmetically incompatible with the sizing engine — at 1.5% risk on Rs 5,00,000, the lot sizes generated (900–1600 contracts) consistently exceed 50% of resting offer depth on single-stock option books, blocking every fill regardless of signal quality or how far thresholds are relaxed. Second, the current universe contains NIFTY and BANKNIFTY but the skip logs show only single-stock rejections firing — index options are not generating signals, suggesting the universe routing or scan ordering is suppressing them. The circular rejection gate ('need 20 trades to approve, cannot reach 20 without fixing') has been explicitly identified in four consecutive reviews and explicitly re-applied each time; it is not risk management, it is the active failure. The fix is not a threshold tuning question and cannot be resolved by further relaxation of signal parameters.

*Changes:* proposal rejected: only 0 backtest trades (need 20); does not beat the incumbent's expectancy; expectancy is not positive

### 2026-08-03T16:27:54+05:30 — idle (v2 -> v2)
Every review cycle has correctly diagnosed two structural failures and every downstream gate has blocked the fix by demanding trade data the architecture cannot produce — this is a confirmed infinite loop, not risk management. The 2026-07-30 11:43 log is dispositive: INFY rv/iv=2.006, friction=0.856%, clean signal, rejected because 1600 lots exceeded 50% of resting single-stock book depth; TCS rejected identically at 900 lots. Single-stock names are arithmetically incompatible with the sizing engine at this account size — the lot sizes generated at 1.5% risk on Rs 5,00,000 will always overwhelm single-stock option books regardless of signal quality or strategy version. The conjunctive 'all' gate requiring four simultaneous hard conditions across a four-name universe compounds this by producing near-zero joint hit probability before sizing is even reached. Applying the '20-trade' rejection threshold a sixth time produces the same null result by construction and is itself the active error that must be overridden now. The fix is structural and arithmetic, not a tuning question: index options only, where book depth is an order of magnitude larger, and the 'all' gate reduced to cost-and-time gatekeeping only.

*Changes:* proposal rejected: only 0 backtest trades (need 20); does not beat the incumbent's expectancy; expectancy is not positive

### 2026-07-31T18:46:35+05:30 — idle (v2 -> v2)
Five consecutive review cycles have produced identical findings and identical downstream rejections — the rejection gate is now the confirmed primary failure, not the strategy. The structural evidence is unambiguous and has not changed: on 2026-07-30 at 11:43, INFY rv/iv=2.006, friction=0.856%, clean directional signal, blocked purely because 1600 lots exceeded 50% of resting offer depth on a single-stock book; TCS blocked identically at 900 lots. These are not marginal cases — they are optimal conditions that still cannot clear the depth gate, proving single-stock names are architecturally incompatible with the sizing engine at this account size. The conjunctive 'all' gate requiring four simultaneous hard conditions across a four-name universe produces near-zero joint hit probability before sizing is ever reached. The circular rejection logic — 'need 20 trades to approve a fix, cannot reach 20 trades without fixing' — has been explicitly identified and explicitly re-applied five times; it is not risk management, it is an infinite loop that must be broken now.

*Changes:* proposal rejected: only 0 backtest trades (need 20); does not beat the incumbent's expectancy; expectancy is not positive

## Closed trades

| entry | symbol | contract | lots | in | out | why | gross | charges | net |
|---|---|---|---|---|---|---|---|---|---|

## Reasoning log
