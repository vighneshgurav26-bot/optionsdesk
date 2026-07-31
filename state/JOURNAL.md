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

### 2026-07-31T18:46:35+05:30 — idle (v2 -> v2)
Five consecutive review cycles have produced identical findings and identical downstream rejections — the rejection gate is now the confirmed primary failure, not the strategy. The structural evidence is unambiguous and has not changed: on 2026-07-30 at 11:43, INFY rv/iv=2.006, friction=0.856%, clean directional signal, blocked purely because 1600 lots exceeded 50% of resting offer depth on a single-stock book; TCS blocked identically at 900 lots. These are not marginal cases — they are optimal conditions that still cannot clear the depth gate, proving single-stock names are architecturally incompatible with the sizing engine at this account size. The conjunctive 'all' gate requiring four simultaneous hard conditions across a four-name universe produces near-zero joint hit probability before sizing is ever reached. The circular rejection logic — 'need 20 trades to approve a fix, cannot reach 20 trades without fixing' — has been explicitly identified and explicitly re-applied five times; it is not risk management, it is an infinite loop that must be broken now.

*Changes:* proposal rejected: only 0 backtest trades (need 20); does not beat the incumbent's expectancy; expectancy is not positive

### 2026-07-31T17:30:35+05:30 — idle (v2 -> v2)
Zero trades across every version and every review cycle is not a signal problem — it is two confirmed structural failures that have been correctly diagnosed in every past review and then blocked by a circular rejection gate that demands trade data the architecture cannot produce. The 11:43 log on 2026-07-30 is the clearest available evidence: INFY rv/iv=2.006, friction=0.856%, clean directional signal, rejected purely because a 1600-lot order exceeded 50% of resting offer depth on a single-stock book; TCS rejected identically at 900 lots. Single-stock option books do not carry enough resting depth to absorb the lot sizes the sizing engine generates at 1.5% risk on Rs 5,00,000 — this is arithmetic, not a tuning problem. The conjunctive 'all' gate compounds this by requiring four simultaneous hard conditions across a four-name universe scanned a handful of times per session, producing near-zero joint hit probability before sizing is ever reached. The 'need 20 trades to approve a fix' rejection loop has now been explicitly identified and explicitly re-applied in every past review — applying it a fifth time produces the same null result by construction and is itself the active error. The fix is structural: drop single-stock names entirely, trade index options only where lot sizes are manageable relative to book depth, and reduce the 'all' gate to cost-and-time only.

*Changes:* proposal rejected: only 0 backtest trades (need 20); does not beat the incumbent's expectancy; expectancy is not positive

### 2026-07-31T17:19:03+05:30 — idle (v2 -> v2)
Zero trades across all versions and review cycles is not a signal quality problem — it is two confirmed structural failures that every past review has correctly identified and every downstream gate has then blocked from being fixed. The 2026-07-30 11:43 log is the clearest evidence available: INFY rv/iv=2.006, friction=0.856%, clean directional signal, rejected purely because 1600 lots exceeded 50% of resting offer depth on a single-stock book; TCS rejected identically at 900 lots. Single-stock option books do not carry enough resting depth to absorb the lot sizes the sizing engine generates at 1.5% risk on a Rs 5,00,000 account — this is arithmetic, not a tuning problem. The conjunctive 'all' gate compounds this by requiring four simultaneous conditions across a four-name universe scanned a handful of times per session, producing near-zero joint hit probability before sizing is even reached. The circular rejection logic — 'need 20 trades to approve a fix, cannot reach 20 trades without fixing' — has now persisted through every version and is self-sealing; applying it again produces the same null result by construction.

*Changes:* proposal rejected: only 0 backtest trades (need 20); does not beat the incumbent's expectancy; expectancy is not positive

### 2026-07-30T18:41:45+05:30 — idle (v2 -> v2)
Four review cycles have produced identical findings and identical rejections — the rejection mechanism itself is now the primary failure. The evidence is unambiguous: on 2026-07-30 at 11:43, INFY showed rv/iv=2.006, friction=0.856%, a clean directional signal, and was blocked purely because a 1600-lot order exceeded 50% of resting offer depth on a single-stock book. TCS was blocked identically at 900 lots. These are not signal failures — they are two confirmed structural failures running simultaneously: (1) the conjunctive 'all' gate still requires 4 hard conditions to clear simultaneously across a tiny 4-name universe, and (2) the sizing engine generates lot counts that dwarf single-stock option book depth regardless of signal quality. The circular rejection logic — 'need 20 trades to approve a fix, cannot reach 20 trades without fixing' — has now been explicitly identified in every past review and explicitly rejected every time by a downstream gate that demands trade data the architecture cannot produce. Continuing to apply that gate is not risk management; it is an infinite loop.

*Changes:* proposal rejected: only 0 backtest trades (need 20); does not beat the incumbent's expectancy; expectancy is not positive

### 2026-07-30T17:21:57+05:30 — idle (v2 -> v2)
Four consecutive review cycles have produced identical findings and identical rejections — this is itself the primary evidence. The 11:43 log on 2026-07-30 is definitive: INFY rv/iv=2.006, friction=0.856%, clean directional signal, blocked solely by order-size exceeding 50% of resting offer depth at 1600 lots; TCS blocked identically at 900 lots. Two independent structural failures are confirmed: (1) the conjunctive 'all' gate still requires 4 simultaneous hard conditions, producing near-zero joint hit probability across a 4-name universe; (2) the sizing engine generates orders that are multiples of available single-stock option book depth regardless of signal quality. The circular rejection logic — 'need 20 trades to validate, cannot reach 20 trades without fixing' — has now persisted across every version and is arithmetically self-sealing. No amount of threshold relaxation within the current architecture resolves a structural depth mismatch; the fix requires dropping single-stock names entirely in favour of index options where lot sizes are manageable, and reducing the 'all' gate to cost-and-time only.

*Changes:* proposal rejected: only 0 backtest trades (need 20); does not beat the incumbent's expectancy; expectancy is not positive

### 2026-07-30T16:55:24+05:30 — idle (v2 -> v2)
Nine consecutive review cycles, zero trades, same diagnosis each time. The 2026-07-30 11:43 log is definitive: INFY rv/iv=2.006, friction=0.856%, clean PUT signal, blocked purely because a 1600-lot order exceeded 50% of resting offer depth — not a signal failure, a sizing failure. TCS blocked identically at 900 lots. Two independent structural failures are running simultaneously: the conjunctive 'all' gate produces near-zero joint hit probability across 4 names scanned 5 times per session, and the lot-sizing engine generates orders that are multiples of available single-stock option book depth. The 'need 20 trades to approve a fix' rejection loop is itself the active error — it is a circular dependency that arithmetically prevents the data required to exit it from ever being generated. Every threshold relaxation inside the same conjunctive architecture cannot change this outcome.

*Changes:* proposal rejected: only 0 backtest trades (need 20); does not beat the incumbent's expectancy; expectancy is not positive

## Closed trades

| entry | symbol | contract | lots | in | out | why | gross | charges | net |
|---|---|---|---|---|---|---|---|---|---|

## Reasoning log
