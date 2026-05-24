"""
Real-time terminal dashboard using Rich.
Shows live P&L, positions, signals, and system status.
"""

import time
from datetime import datetime
from typing import Optional
import pytz

from rich.console import Console
from rich.table import Table
from rich.layout import Layout
from rich.panel import Panel
from rich.live import Live
from rich.text import Text
from rich.align import Align
from rich import box
from loguru import logger


IST = pytz.timezone("Asia/Kolkata")
console = Console()


def _color_pnl(value: float) -> str:
    if value > 0:
        return f"[green]+₹{value:,.0f}[/green]"
    elif value < 0:
        return f"[red]-₹{abs(value):,.0f}[/red]"
    return f"₹{value:,.0f}"


def _color_regime(regime: str) -> str:
    colors = {
        "trending_up": "[bold green]",
        "trending_down": "[bold red]",
        "ranging": "[bold yellow]",
        "high_volatility": "[bold magenta]",
    }
    c = colors.get(regime, "")
    return f"{c}{regime.upper().replace('_', ' ')}[/]"


class TradingDashboard:
    def __init__(self, config: dict):
        self.config = config
        self.capital = config["risk"]["total_capital"]
        self._state = {
            "positions": [],
            "daily_pnl": 0.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "regime": "unknown",
            "regime_confidence": 0.0,
            "signal": "NO_TRADE",
            "signal_confidence": 0.0,
            "nifty_spot": 0.0,
            "trades_today": 0,
            "wins_today": 0,
            "losses_today": 0,
            "status": "STARTING",
            "last_update": datetime.now(IST),
            "errors": [],
            "daily_loss_limit": self.capital * config["risk"]["daily_loss_limit_pct"],
            "daily_target": self.capital * config["risk"]["daily_profit_target_pct"],
        }

    def update(self, **kwargs):
        self._state.update(kwargs)
        self._state["last_update"] = datetime.now(IST)

    def _build_header(self) -> Panel:
        now = datetime.now(IST).strftime("%d %b %Y  %H:%M:%S IST")
        status = self._state["status"]
        status_color = "green" if status == "RUNNING" else "yellow" if status == "STARTING" else "red"
        title = Text()
        title.append(" NIFTY50 AI OPTIONS TRADING SYSTEM ", style="bold white on blue")
        title.append(f"  [{status_color}]{status}[/{status_color}]  ")
        title.append(f"  {now}", style="dim")
        return Panel(Align.center(title), box=box.DOUBLE_EDGE)

    def _build_market_panel(self) -> Panel:
        spot = self._state["nifty_spot"]
        regime = self._state["regime"]
        conf = self._state["regime_confidence"]
        signal = self._state["signal"]
        sig_conf = self._state["signal_confidence"]

        content = Table.grid(padding=1)
        content.add_column(style="bold cyan", min_width=20)
        content.add_column(min_width=25)
        content.add_row("Nifty Spot", f"[bold white]{spot:,.2f}[/bold white]")
        content.add_row("Market Regime", f"{_color_regime(regime)}  ({conf:.0%} confidence)")
        content.add_row("AI Signal", f"[bold]{signal}[/bold]  ({sig_conf:.0%} confidence)")
        return Panel(content, title="[bold]Market Intelligence[/bold]", border_style="blue")

    def _build_pnl_panel(self) -> Panel:
        pnl = self._state["daily_pnl"]
        realized = self._state["realized_pnl"]
        unrealized = self._state["unrealized_pnl"]
        limit = self._state["daily_loss_limit"]
        target = self._state["daily_target"]
        pct = pnl / self.capital * 100

        limit_used = abs(min(0, pnl)) / limit * 100 if limit > 0 else 0
        limit_color = "red" if limit_used > 80 else "yellow" if limit_used > 50 else "green"

        content = Table.grid(padding=1)
        content.add_column(style="bold cyan", min_width=22)
        content.add_column(min_width=22)
        content.add_row("Daily P&L", f"{_color_pnl(pnl)} ({pct:+.2f}%)")
        content.add_row("Realized", _color_pnl(realized))
        content.add_row("Unrealized", _color_pnl(unrealized))
        content.add_row("Loss Limit", f"[{limit_color}]{limit_used:.0f}% used[/{limit_color}] (₹{limit:,.0f})")
        content.add_row("Daily Target", f"₹{target:,.0f}")
        content.add_row("Capital", f"₹{self.capital:,.0f}")
        return Panel(content, title="[bold]P&L Summary[/bold]", border_style="green" if pnl >= 0 else "red")

    def _build_trades_panel(self) -> Panel:
        trades = self._state["trades_today"]
        wins = self._state["wins_today"]
        losses = self._state["losses_today"]
        win_rate = wins / trades * 100 if trades > 0 else 0

        content = Table.grid(padding=1)
        content.add_column(style="bold cyan", min_width=20)
        content.add_column(min_width=15)
        content.add_row("Trades Today", str(trades))
        content.add_row("Wins", f"[green]{wins}[/green]")
        content.add_row("Losses", f"[red]{losses}[/red]")
        content.add_row("Win Rate", f"[{'green' if win_rate > 50 else 'red'}]{win_rate:.1f}%[/]")
        return Panel(content, title="[bold]Trade Stats[/bold]", border_style="cyan")

    def _build_positions_table(self) -> Panel:
        positions = self._state["positions"]
        table = Table(
            "Symbol", "Strike", "Type", "Qty", "Entry", "LTP", "P&L", "SL", "Target", "Strategy",
            box=box.SIMPLE_HEAVY,
            show_header=True,
            header_style="bold magenta",
        )
        if not positions:
            table.add_row(*["—"] * 10)
        for p in positions:
            pnl_val = p.get("unrealized_pnl", 0)
            pnl_str = _color_pnl(pnl_val)
            table.add_row(
                p.get("symbol", ""),
                str(p.get("strike", "")),
                p.get("option_type", ""),
                str(p.get("qty", "")),
                f"₹{p.get('entry_price', 0):.2f}",
                f"₹{p.get('current_price', 0):.2f}",
                pnl_str,
                f"₹{p.get('sl_price', 0):.2f}",
                f"₹{p.get('target_price', 0):.2f}",
                p.get("strategy", ""),
            )
        return Panel(table, title="[bold]Open Positions[/bold]", border_style="yellow")

    def _build_errors_panel(self) -> Panel:
        errors = self._state["errors"][-5:]
        content = "\n".join(f"[red]{e}[/red]" for e in errors) if errors else "[green]No errors[/green]"
        return Panel(content, title="[bold]System Alerts[/bold]", border_style="red" if errors else "green")

    def render(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(self._build_header(), size=3),
            Layout(name="middle"),
            Layout(self._build_positions_table(), size=12),
            Layout(self._build_errors_panel(), size=5),
        )
        layout["middle"].split_row(
            Layout(self._build_market_panel()),
            Layout(self._build_pnl_panel()),
            Layout(self._build_trades_panel()),
        )
        return layout

    def run_live(self, refresh_seconds: float = 1.0):
        """Run the live dashboard. Call update() from your trading loop to push new state."""
        import sys
        if not sys.stdout.isatty():
            # Non-interactive environment (Railway/server): print periodic snapshots to logs
            while True:
                try:
                    self.print_snapshot()
                    time.sleep(30)
                except KeyboardInterrupt:
                    break
            return
        with Live(self.render(), console=console, refresh_per_second=1 / refresh_seconds, screen=True) as live:
            while True:
                try:
                    live.update(self.render())
                    time.sleep(refresh_seconds)
                except KeyboardInterrupt:
                    break

    def print_snapshot(self):
        """Print a static snapshot (for non-interactive use)."""
        console.print(self.render())
