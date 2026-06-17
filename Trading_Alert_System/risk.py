"""Position sizing from fixed-fractional risk. Output is informational."""
from __future__ import annotations


def size_signal(sig, risk, forex_cfg) -> None:
    """Fill sig.position_size in place."""
    risk_amount = risk.account_balance * risk.risk_per_trade
    stop_dist = abs(sig.entry - sig.stop)
    if stop_dist == 0:
        return

    if sig.market == "CRYPTO":
        units = risk_amount / stop_dist
        notional = units * sig.entry
        sig.position_size = (
            f"~{units:.4g} units (≈${notional:,.0f} notional) "
            f"risking ${risk_amount:,.0f} ({risk.risk_per_trade:.0%})"
        )
    else:  # FOREX
        # pip size: 0.01 for JPY pairs, else 0.0001
        pip = 0.01 if sig.symbol.endswith("JPY") else 0.0001
        pips = stop_dist / pip
        if pips > 0:
            lots = risk_amount / (pips * forex_cfg.pip_value_per_lot)
            sig.position_size = (
                f"~{lots:.2f} lots (stop ≈{pips:.0f} pips) "
                f"risking ${risk_amount:,.0f} ({risk.risk_per_trade:.0%}) "
                f"— verify pip value with your broker"
            )
