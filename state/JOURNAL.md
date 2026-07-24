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

## Closed trades

| entry | symbol | contract | lots | in | out | why | gross | charges | net |
|---|---|---|---|---|---|---|---|---|---|

## Reasoning log
