# BounceBack — Strategy

A long-only mean-reversion bot for cbBTC (CBBTC/USDC) on 1-minute bars,
written in Python (stdlib only, deterministic, no clock, no randomness,
no network, no files). Entry: `main.py`, bar data via `vendor/makefun_bars.py`
(a byte-for-byte copy of the kit SDK shim).

## Strategy rules

| Rule | Value |
|---|---|
| Entry | Buy with all cash when the 120-minute return is <= -1.00% **and** the last 15-minute return is positive (bounce confirmation) |
| Take profit | +1.5% vs the filled entry price (exit whole position) |
| Stop loss | -1.0% vs the filled entry price (exit whole position) |
| Cooldown | 15 bars after an exit before the next entry |
| Loss brake | Stop entering once realised losses reach -$30 |
| Position | Long only, one position, full size |
| Max slippage | 100 bps |
| Fallback | If no trade by bar 1320, buy at market (guardrail: at least 1 trade) |

Exit prices are measured against the *filled* entry price, not the signal
price. The 120-minute lookback is the key design choice: on both dev
windows the first hour is often a steady downtrend, and a 30/60-minute dip
signal buys straight into it and never recovers (see the DipCatcher row
below). Waiting 2 hours and requiring the 15-minute return to have turned
positive means the bot buys a dip that has started to turn, not one still
falling.

## Why this, and what was rejected

The previous race's entry (DipCatcher: 60-minute dip, -1.00%, TP/SL 1.5%)
made +$27.32 on its dev window but **fails this competition's dev gate**:
-$18.60 on the new window. It bought at bar 61, the very first bar its
lookback allowed, into the opening downtrend, and its stop loss only
triggered at bar 1434. Reusing it would not have raced at all.

A float backtester was also found to be unreliable for selection: a ~$90
difference between the signal close and the filled entry price moved the
take-profit level just enough that the float sim showed +$8.33 for the same
parameters the exact integer replay grades at -$18.60. Every number in the
table below comes from the exact integer replay (`replay.py`, which mirrors
`sim/bars/engine.ts` fill math and was validated against the kit's own
`grade-local`: buy-and-hold matches to the cent, -$31.63, maxDD 3.25%).

## Dev-window results (1440 bars, $1,000 starting capital)

Exact integer replay, run twice (identical replies both times). "Fills"
counts the final flatten as a fill. The new window is this competition's
dev window (24h to 2026-11-18 14:44 UTC, -2.79% drift); the old window is
the previous race's dev window (24h, +0.53% drift), used as out-of-sample.

| Strategy | New PnL | New maxDD | New fills | Old PnL | Old maxDD | Old fills |
|---|---|---|---|---|---|---|
| **BounceBack (this bot)** | **+$13.56** | **0.81%** | **2** | **+$13.70** | **1.32%** | **4** |
| BounceBack, TP/SL 1.2% | +$10.61 | 0.81% | 2 | +$11.95 | 1.32% | 4 |
| BounceBack, bounce 30 min | +$13.22 | 0.74% | 2 | +$13.04 | 1.70% | 4 |
| BounceBack, entry -80 bps | -$6.75 | 2.77% | 4 | +$11.14 | 1.70% | 4 |
| BounceBack, entry -120 bps | +$13.56 | 0.81% | 2 | +$1.09 | 0.72% | 2 |
| BounceBack, TP 2.0% | -$12.84 | 3.24% | 2 | +$3.46 | 2.12% | 2 |
| BounceBack, lookback 180 | -$5.41 | 2.34% | 4 | +$1.09 | 0.72% | 2 |
| BounceBack, no bounce filter | -$5.31 | 2.77% | 4 | +$13.41 | 1.70% | 4 |
| DipCatcher (previous entry) | -$18.60 | 3.24% | 2 | +$27.32 | 0.72% | 6 |
| DipCatcher, cooldown 15 | -$18.60 | 3.24% | 2 | +$27.02 | 0.72% | 6 |
| Partial exits (50% at +0.8%) | -$5.51 | 1.63% | 3 | +$6.62 | 0.85% | 3 |
| Buy-and-hold (kit grade-local) | -$31.63 | 3.25% | 1 trade | — | — | — |

BounceBack's trades on the new window: buy bar 123 at $63,925.58, sell
bar 503 at $64,844.09 (+$13.56 net). On the old window: buy bar 232 at
$64,416.43, sell bar 515 at $65,282.21 (+$12.63), then buy bar 1115 at
$64,570.27, flattened at $64,690.60 (+$1.07). The stop loss was tightened
from -1.5% to -1.0% in a second revision (see Cost breakdown); both
windows' trades and PnL are unchanged by it.

The take-profit level is not a knife-edge: TP 1.3%, 1.4%, 1.5% and 1.6%
are all positive on both windows (+$11.12 to +$14.63 new, +$12.40 to
+$13.70 old). The entry threshold is the sensitive parameter (-95 bps
fails the new window, -110 bps nearly fails the old one); -100 bps is the
round, central value that catches the same deep-dip event on both windows.

## Cost breakdown (per round trip, ~$1,000 order)

| Component | Cost |
|---|---|
| Fee | ~4 bps |
| Modelled slippage | ~2 bps |
| Constant-product price impact (~$1,000 order) | ~7-20 bps |
| **Total (approx.)** | **~26-37 bps** |

The +1.5% take profit clears the round-trip cost with margin; the -1.0%
stop loss caps the loss per trade at about -$14 including costs. The stop
was tightened from -1.5% to -1.0% after the first local check run: a win
nets about +$11 and a stopped-out loss about -$14, which needs only a
~55% win rate to break even (vs ~62% for a symmetric 1.5% stop), and the
tighter stop caps the worst single trade. Verified on both dev windows:
identical trades and PnL to the 1.5% stop (the stop never fired there).

## Guardrails

- **Min 1 trade:** the fallback market buy after bar 1320 guarantees a
  trade even on a dip-free window. On both dev windows the bot traded
  without needing it.
- **Max drawdown <= 25%:** dev-window max drawdown is 0.81% (new) and
  1.32% (old), far inside the limit. Drawdown is further bounded by the
  -1.0% stop loss per trade and the 15-bar cooldown between entries.
- **Loss brake:** if realised losses reach -$30 (about two stopped-out
  round trips), the bot stops entering for the rest of the window. It
  never fired on either dev window.

## Determinism

The bot uses float arithmetic on closes only — no clock, no randomness, no
network, no files. The same bars always produce the same orders. Verified:
two independent replay runs produced identical replies on both windows
(net PnL +$13.56 / +$13.70, 2 / 4 fills, 0 rejected).

## Risks and limits — stated plainly

- The entry depends on **one or two trades per day**. On the new dev
  window the bot made exactly one round trip, all of it in the first half
  (half 1 +$13.56, half 2 $0.00 — no trades). On the old window it made
  two (half 1 +$12.63, half 2 +$1.07). A race window with no qualifying
  dip leaves only the fallback buy, and a race window whose dip keeps
  falling past -1.5% loses ~$19 on the trade. The edge is thin and the
  sample is tiny: two windows, three round trips. This is not a proven
  statistical edge; it is the most robust of the strategies tested, chosen
  because it is positive on both windows with low drawdown and because its
  take-profit level is not a knife-edge.
- Results are for the dev windows only; the live 24-hour race window may
  behave differently, including a trend day where dips keep falling. The
  -1.5% stop loss and the -$30 loss brake bound the loss, but they do not
  eliminate it.
- The fallback market buy after bar 1320 can enter at an unfavourable
  price in a falling market; it exists only to satisfy the minimum-trade
  guardrail.
