"""The Signal object: everything the bot tells you about a potential move."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Signal:
    market: str            # "CRYPTO" or "FOREX"
    symbol: str            # e.g. "BTC/USDT"
    direction: str         # "LONG" or "SHORT"
    exec_tf: str           # entry timeframe, e.g. "5m"
    bias_tf: str           # higher-timeframe context, e.g. "1h"
    entry: float
    stop: float
    targets: list          # list of (label, price, r_multiple)
    atr: float
    confidence: int        # 0-6 score
    reasons: list          # human-readable list of what fired
    position_size: str = ""   # filled in by risk module
    session: str = ""         # forex only
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    @property
    def conf_label(self) -> str:
        return {6: "VERY HIGH", 5: "HIGH", 4: "MEDIUM"}.get(self.confidence, "LOW")

    @property
    def rr_first(self) -> float:
        risk = abs(self.entry - self.stop)
        if risk == 0:
            return 0.0
        first_target = self.targets[0][1]
        return round(abs(first_target - self.entry) / risk, 2)

    def to_telegram(self) -> str:
        arrow = "🟢 LONG" if self.direction == "LONG" else "🔴 SHORT"
        lines = [
            f"<b>{arrow}  {self.symbol}</b>  ({self.market})",
            f"Confidence: <b>{self.conf_label}</b> ({self.confidence}/6)",
            f"Bias TF {self.bias_tf}  |  Entry TF {self.exec_tf}",
        ]
        if self.session:
            lines.append(f"Session: {self.session}")
        lines += [
            "",
            f"Entry:  <code>{self.entry:.6g}</code>",
            f"Stop:   <code>{self.stop:.6g}</code>  (ATR {self.atr:.6g})",
        ]
        for label, price, r in self.targets:
            lines.append(f"{label}: <code>{price:.6g}</code>  ({r:.1f}R)")
        lines.append(f"R:R to first target: <b>{self.rr_first}</b>")
        if self.position_size:
            lines.append(f"Suggested size: {self.position_size}")
        lines += ["", "<b>Why:</b>"]
        lines += [f"• {r}" for r in self.reasons]
        lines += [
            "",
            f"<i>{self.timestamp}</i>",
            "<i>Signal only — not financial advice. Confirm on your own chart.</i>",
        ]
        return "\n".join(lines)
