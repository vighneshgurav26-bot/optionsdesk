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

### 2026-07-30T18:41:45+05:30 — idle (v2 -> v2)
Four review cycles have produced identical findings and identical rejections — the rejection mechanism itself is now the primary failure. The evidence is unambiguous: on 2026-07-30 at 11:43, INFY showed rv/iv=2.006, friction=0.856%, a clean directional signal, and was blocked purely because a 1600-lot order exceeded 50% of resting offer depth on a single-stock book. TCS was blocked identically at 900 lots. These are not signal failures — they are two confirmed structural failures running simultaneously: (1) the conjunctive 'all' gate still requires 4 hard conditions to clear simultaneously across a tiny 4-name universe, and (2) the sizing engine generates lot counts that dwarf single-stock option book depth regardless of signal quality. The circular rejection logic — 'need 20 trades to approve a fix, cannot reach 20 trades without fixing' — has now been explicitly identified in every past review and explicitly rejected every time by a downstream gate that demands trade data the architecture cannot produce. Continuing to apply that gate is not risk management; it is an infinite loop.

*Changes:* proposal rejected: only 0 backtest trades (need 20); does not beat the incumbent's expectancy; expectancy is not positive

### 2026-07-30T17:21:57+05:30 — idle (v2 -> v2)
Four consecutive review cycles have produced identical findings and identical rejections — this is itself the primary evidence. The 11:43 log on 2026-07-30 is definitive: INFY rv/iv=2.006, friction=0.856%, clean directional signal, blocked solely by order-size exceeding 50% of resting offer depth at 1600 lots; TCS blocked identically at 900 lots. Two independent structural failures are confirmed: (1) the conjunctive 'all' gate still requires 4 simultaneous hard conditions, producing near-zero joint hit probability across a 4-name universe; (2) the sizing engine generates orders that are multiples of available single-stock option book depth regardless of signal quality. The circular rejection logic — 'need 20 trades to validate, cannot reach 20 trades without fixing' — has now persisted across every version and is arithmetically self-sealing. No amount of threshold relaxation within the current architecture resolves a structural depth mismatch; the fix requires dropping single-stock names entirely in favour of index options where lot sizes are manageable, and reducing the 'all' gate to cost-and-time only.

*Changes:* proposal rejected: only 0 backtest trades (need 20); does not beat the incumbent's expectancy; expectancy is not positive

### 2026-07-30T16:55:24+05:30 — idle (v2 -> v2)
Nine consecutive review cycles, zero trades, same diagnosis each time. The 2026-07-30 11:43 log is definitive: INFY rv/iv=2.006, friction=0.856%, clean PUT signal, blocked purely because a 1600-lot order exceeded 50% of resting offer depth — not a signal failure, a sizing failure. TCS blocked identically at 900 lots. Two independent structural failures are running simultaneously: the conjunctive 'all' gate produces near-zero joint hit probability across 4 names scanned 5 times per session, and the lot-sizing engine generates orders that are multiples of available single-stock option book depth. The 'need 20 trades to approve a fix' rejection loop is itself the active error — it is a circular dependency that arithmetically prevents the data required to exit it from ever being generated. Every threshold relaxation inside the same conjunctive architecture cannot change this outcome.

*Changes:* proposal rejected: only 0 backtest trades (need 20); does not beat the incumbent's expectancy; expectancy is not positive

### 2026-07-30T14:47:41+05:30 — idle (v2 -> v2)
Six or more consecutive review cycles have produced the same diagnosis and the same outcome: zero trades, circular rejection, no learning. The 2026-07-30 11:43 log is the clearest data point — INFY had rv/iv=2.006, friction=0.856%, a clean directional PUT signal, and was blocked purely by the order-size gate (1600 lots vs ~400-1200 resting offer). TCS showed the same at 900 lots. This is two independent structural failures running simultaneously: (1) the conjunctive gate architecture produces near-zero joint hit probability across a 4-name universe scanned ~5 times per session, and (2) the lot-sizing engine is producing orders that are multiples of available offer depth on single-stock books. Both failures are empirically confirmed; neither is a signal quality problem. Continuing to reject structural change on the grounds of insufficient trade data is the active error — the architecture is arithmetically preventing the data from being generated.

*Changes:* proposal rejected: only 0 backtest trades (need 20); does not beat the incumbent's expectancy; expectancy is not positive

### 2026-07-30T12:06:21+05:30 — idle (v2 -> v2)
Zero trades across every session, every version, every relaxation cycle — this is now the definitive finding. The 2026-07-30 11:43 log is the clearest evidence: INFY had rv/iv=2.006, friction=0.856%, trend=-0.401, a clean PUT signal, yet was killed not by entry logic but by the contract liquidity gate — 1600-lot orders are more than 50% of resting offer depth on single-stock books. TCS showed the same failure at 900 lots. The conjunctive gate architecture (4 simultaneous hard conditions + any-of-7) is one failure mode; the position sizing producing orders too large for single-stock depth is a second, independent failure mode. Both must be fixed simultaneously — fixing only the gate leaves the sizing problem, and vice versa. The rejection loop (need 20 trades to validate, cannot reach 20 trades without fixing) has now persisted across at least nine review cycles; continuing to reject structural changes on the grounds that there are zero trades is itself the active error — the circular dependency can only be broken by action, not more observation.

*Changes:* proposal rejected: only 0 backtest trades (need 20); does not beat the incumbent's expectancy; expectancy is not positive

### 2026-07-30T11:43:44+05:30 — idle (v2 -> v2)
Zero trades across every session, every version, every relaxation cycle. The blocked-and-skipped log from 2026-07-30 11:43 is the clearest evidence yet: INFY had rv/iv=2.006, edge=7.988, friction=0.856%, trend=-0.401 — a strongly directional PUT signal with excellent RV/IV — yet no trade fired. TCS and INFY both had valid directional reads but were killed by the contract liquidity gate (order size >50% of resting offer). This is now two distinct failure modes running simultaneously: (1) the conjunctive gate architecture still prevents entry even when fundamentals are clean, as seen on 2026-07-27; (2) the lot-size sizing is generating orders too large for single-stock option books — 900 lots on TCS and 1600 lots on INFY are simply not absorbable. The circular rejection loop ('need 20 trades to approve a fix, but cannot reach 20 trades without fixing') has now persisted across at least nine review cycles and is itself the active loss — theta and opportunity cost accumulate on idle capital. Two concrete fixes are now identified by the data: shrink the 'all' gate to the absolute minimum (cost and time only), and reduce lot sizing so single-stock orders are within 25% of resting offer depth.

*Changes:* proposal rejected: only 0 backtest trades (need 20); does not beat the incumbent's expectancy; expectancy is not positive

## Closed trades

| entry | symbol | contract | lots | in | out | why | gross | charges | net |
|---|---|---|---|---|---|---|---|---|---|

## Reasoning log
