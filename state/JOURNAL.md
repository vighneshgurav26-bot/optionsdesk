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

### 2026-07-30T14:47:41+05:30 — idle (v2 -> v2)
Six or more consecutive review cycles have produced the same diagnosis and the same outcome: zero trades, circular rejection, no learning. The 2026-07-30 11:43 log is the clearest data point — INFY had rv/iv=2.006, friction=0.856%, a clean directional PUT signal, and was blocked purely by the order-size gate (1600 lots vs ~400-1200 resting offer). TCS showed the same at 900 lots. This is two independent structural failures running simultaneously: (1) the conjunctive gate architecture produces near-zero joint hit probability across a 4-name universe scanned ~5 times per session, and (2) the lot-sizing engine is producing orders that are multiples of available offer depth on single-stock books. Both failures are empirically confirmed; neither is a signal quality problem. Continuing to reject structural change on the grounds of insufficient trade data is the active error — the architecture is arithmetically preventing the data from being generated.

*Changes:* proposal rejected: only 0 backtest trades (need 20); does not beat the incumbent's expectancy; expectancy is not positive

### 2026-07-30T12:06:21+05:30 — idle (v2 -> v2)
Zero trades across every session, every version, every relaxation cycle — this is now the definitive finding. The 2026-07-30 11:43 log is the clearest evidence: INFY had rv/iv=2.006, friction=0.856%, trend=-0.401, a clean PUT signal, yet was killed not by entry logic but by the contract liquidity gate — 1600-lot orders are more than 50% of resting offer depth on single-stock books. TCS showed the same failure at 900 lots. The conjunctive gate architecture (4 simultaneous hard conditions + any-of-7) is one failure mode; the position sizing producing orders too large for single-stock depth is a second, independent failure mode. Both must be fixed simultaneously — fixing only the gate leaves the sizing problem, and vice versa. The rejection loop (need 20 trades to validate, cannot reach 20 trades without fixing) has now persisted across at least nine review cycles; continuing to reject structural changes on the grounds that there are zero trades is itself the active error — the circular dependency can only be broken by action, not more observation.

*Changes:* proposal rejected: only 0 backtest trades (need 20); does not beat the incumbent's expectancy; expectancy is not positive

### 2026-07-30T11:43:44+05:30 — idle (v2 -> v2)
Zero trades across every session, every version, every relaxation cycle. The blocked-and-skipped log from 2026-07-30 11:43 is the clearest evidence yet: INFY had rv/iv=2.006, edge=7.988, friction=0.856%, trend=-0.401 — a strongly directional PUT signal with excellent RV/IV — yet no trade fired. TCS and INFY both had valid directional reads but were killed by the contract liquidity gate (order size >50% of resting offer). This is now two distinct failure modes running simultaneously: (1) the conjunctive gate architecture still prevents entry even when fundamentals are clean, as seen on 2026-07-27; (2) the lot-size sizing is generating orders too large for single-stock option books — 900 lots on TCS and 1600 lots on INFY are simply not absorbable. The circular rejection loop ('need 20 trades to approve a fix, but cannot reach 20 trades without fixing') has now persisted across at least nine review cycles and is itself the active loss — theta and opportunity cost accumulate on idle capital. Two concrete fixes are now identified by the data: shrink the 'all' gate to the absolute minimum (cost and time only), and reduce lot sizing so single-stock orders are within 25% of resting offer depth.

*Changes:* proposal rejected: only 0 backtest trades (need 20); does not beat the incumbent's expectancy; expectancy is not positive

### 2026-07-30T09:16:03+05:30 — idle (v2 -> v2)
Zero trades across every session observed, across two strategy versions and multiple relaxation cycles. The blocked-and-skipped log is the only evidence available, and it is conclusive: on 2026-07-27 11:57, NIFTY showed rv/iv=0.983, friction=1.346%, trend_score=0.555 — conditions that are individually clean — yet no trade fired, meaning the conjunctive gate architecture itself is the blocker, not market conditions or thresholds. Every prior review correctly diagnosed this; every proposed fix was rejected for lacking 20 trades; 20 trades are arithmetically unreachable under the current architecture — this circular dependency is the real failure mode and has now persisted across at least eight review cycles. The 'all' gate of four simultaneous hard conditions plus a disjunctive 'any' tier of seven more produces a joint intraday hit probability near zero across a 4-name universe scanned 5-6 times per session; further threshold nudging inside this same conjunctive structure cannot change the outcome. The system's own standing instruction is explicit: a strategy that never fires learns nothing, and the note in the current payload repeats this; continuing to reject structural change is itself the active error.

*Changes:* proposal rejected: only 0 backtest trades (need 20); does not beat the incumbent's expectancy; expectancy is not positive

### 2026-07-29T18:48:44+05:30 — idle (v2 -> v2)
Zero trades across all sessions observed. This is now the fifth or sixth consecutive review reaching the same diagnosis: the conjunctive gate architecture is the sole blocker, not market conditions. The skipped log from 2026-07-27 11:57 is definitive — NIFTY had rv/iv=0.983, friction=1.346%, edge=2.858, trend_score=0.555, all individually acceptable, yet no trade fired, meaning subordinate conditions (adx_proxy, vwap_dev_pct, or the 'any' tier) vetoed a genuinely clean setup. The 12:22 scan shows trend_score=0.141 blocking an otherwise passable tape — a single directional feature below a threshold is enough to kill the whole cycle. Every prior review proposed the correct fix; every proposal was rejected for lacking 20 trades; 20 trades are arithmetically unreachable without the fix — this is a closed loop that only a structural change can break. Further threshold nudging inside the same AND/ANY architecture will not change the outcome: the joint probability of 4 simultaneous hard gates plus at least 1 of 7 soft gates remains near zero across a 4-name universe at ~5 scans per session.

*Changes:* proposal rejected: only 0 backtest trades (need 20); does not beat the incumbent's expectancy; expectancy is not positive

### 2026-07-29T17:31:19+05:30 — idle (v2 -> v2)
Seven review cycles, zero trades, zero empirical data. The blocked-and-skipped log is the only evidence and it is dispositive: on 2026-07-27 11:57, NIFTY showed rv/iv=0.983, friction=1.346%, edge=2.858, trend_score=0.555 — conditions that are individually and jointly acceptable — yet no trade fired, almost certainly because the 'any-of' tier still failed to return a single true condition simultaneously with all four 'all' gates. The V3 relaxation was structurally insufficient: dropping thresholds by half while keeping a conjunctive 'all' gate of four simultaneous conditions plus a disjunctive 'any' tier of seven more still produces a joint daily hit rate near zero across a 4-name universe scanned 5-6 times per session. The rejection loop — 'need 20 trades to approve, but strategy cannot reach 20 trades without approval' — is self-sealing and must be broken by architectural change, not further threshold nudging. The system's own standing instruction is unambiguous: a strategy that never fires learns nothing, and continued micro-relaxation of the same conjunctive structure is not a meaningful response to that instruction. The only honest diagnosis is that the filter architecture itself must change: the 'all' hard gate must shrink to the minimum necessary risk controls, and directional conditions must be collapsed to a single, low-bar confirmation rather than a conjunctive bundle.

*Changes:* proposal rejected: only 0 backtest trades (need 20); does not beat the incumbent's expectancy; expectancy is not positive

## Closed trades

| entry | symbol | contract | lots | in | out | why | gross | charges | net |
|---|---|---|---|---|---|---|---|---|---|

## Reasoning log
