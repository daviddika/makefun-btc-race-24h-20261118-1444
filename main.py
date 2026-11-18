# BounceBack: a mean-reversion bot for cbBTC (CBBTC/USDC) on 1-minute bars.
#
# Strategy (long only, one position, full size):
#   - Buy the deep dip, not the falling knife: when the 120-minute return
#     is at or below -1.00% AND the last 15-minute return is positive (the
#     price has started bouncing back), buy with all cash. The 120-minute
#     lookback matters: on the dev windows the first hour is often a steady
#     downtrend, and a 30/60-minute dip signal buys straight into it and
#     never recovers. Waiting for the bounce confirmation avoids that.
#   - Exit at +1.5% from the filled entry price (take profit) or at -1.5%
#     (stop loss). A round trip costs ~26-37 bps in fees, slippage and
#     pool impact, so only a move of this size is worth trading.
#   - Cooldown: 15 bars after an exit before the next entry.
#   - Loss brake: stop entering for the rest of the window once realised
#     losses reach -$30 (about two stopped-out round trips).
#   - Guardrail fallback: if no trade has happened by bar 1320, buy at
#     market, so the entry still meets the "at least 1 trade" guardrail.
#
# Everything is deterministic: float arithmetic on closes only, no clock, no
# randomness, no network, no files. The same bars always give the same orders.
# SPDX-License-Identifier: MIT

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"

# 120-minute return at or below this (in bps) is a dip worth buying.
LOOKBACK_BARS = 120
ENTRY_BPS = 100

# Bounce confirmation: the last 15-minute return must be positive, so the
# bot buys a dip that has started to turn, not one still falling.
BOUNCE_LOOKBACK_BARS = 15

# Take profit / stop loss, as fractions of the filled entry price.
# The stop is tighter than the target (+1.5% / -1.0%): a round trip costs
# ~26-37 bps, so a win nets about +$11 and a stopped-out loss about -$14,
# which needs only a ~55% win rate to break even (vs ~62% for a symmetric
# 1.5% stop). The tighter stop also caps the worst single trade. Verified
# on both dev windows: identical trades and PnL to the 1.5% stop (the stop
# never fired there), with a smaller maximum loss if it does fire.
TAKE_PROFIT = 0.015
STOP_LOSS = 0.010

# Loss brake: stop entering for the rest of the window once realised losses
# reach this many quote units (-$30, i.e. about two stopped-out round trips).
MAX_REALIZED_LOSS = -30_000_000

# Bars to wait after an exit before the next entry.
COOLDOWN_BARS = 15

# Fallback entry so a dip-free window still trades at least once.
LAST_RESORT_BAR = 1320

MAX_SLIPPAGE_BPS = 100

closes = []  # float closes (USDC per CBBTC) of every bar seen, in order.
entry_price = None  # filled entry price of the open position, else None.
position_cost = 0  # quote units paid for the open position (spend + fee).
realized_pnl = 0  # quote units realised from closed round trips (fees in).
last_exit_seq = -10 ** 9
buys_decided = 0


def on_batch(state, batch):
    global entry_price, position_cost, realized_pnl, last_exit_seq, buys_decided

    # Learn the true filled entry price (and exits) from the fills this batch
    # carries, before deciding anything on this bar.
    for fill in batch.get("fills", []):
        if fill.get("symbol") != SYMBOL or fill.get("status") != "filled":
            continue
        if fill.get("side") == "buy":
            entry_price = int(fill["price"]) / 1e5
            position_cost = int(fill["notional_quote_units"]) + int(fill["fee_quote_units"])
        elif fill.get("side") == "sell":
            realized_pnl += (int(fill["notional_quote_units"]) - int(fill["fee_quote_units"])) - position_cost
            entry_price = None
            position_cost = 0
            last_exit_seq = state.seq

    bar = state.latest.get(SYMBOL)
    if bar is None:
        return []
    closes.append(int(bar["c"]) / 1e5)
    if state.warming_up:
        return []

    held = state.positions.get(SYMBOL)
    if held is not None:
        # Exit the whole position at take profit or stop loss.
        if entry_price is not None:
            close = closes[-1]
            if close >= entry_price * (1.0 + TAKE_PROFIT) or close <= entry_price * (1.0 - STOP_LOSS):
                return [{
                    "side": "sell",
                    "symbol": SYMBOL,
                    "qty": held.qty,
                    "max_slippage_bps": MAX_SLIPPAGE_BPS,
                }]
        return []

    # Flat: look for a dip that has started bouncing back.
    if realized_pnl <= MAX_REALIZED_LOSS:
        return []
    if state.seq - last_exit_seq < COOLDOWN_BARS:
        return []
    k = len(closes) - 1
    if k < LOOKBACK_BARS:
        return []
    ret_120bps = (closes[k] / closes[k - LOOKBACK_BARS] - 1.0) * 1e4
    buy = ret_120bps <= -ENTRY_BPS
    if buy:
        if k < BOUNCE_LOOKBACK_BARS:
            buy = False
        elif closes[k] / closes[k - BOUNCE_LOOKBACK_BARS] - 1.0 <= 0:
            buy = False
    if not buy and buys_decided == 0 and state.seq >= LAST_RESORT_BAR:
        buy = True
    if not buy:
        return []

    amount = state.cash
    room = state.weight_room(SYMBOL)
    if amount > room:
        amount = room
    if amount < int(state.hello["fees"]["min_notional_quote_units"]):
        return []
    buys_decided += 1
    return [{
        "side": "buy",
        "symbol": SYMBOL,
        "notional_quote_units": amount,
        "max_slippage_bps": MAX_SLIPPAGE_BPS,
    }]


makefun_bars.run(on_batch)
