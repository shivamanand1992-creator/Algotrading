import re
import sys
from pathlib import Path
from typing import List, Optional
from datetime import datetime

sys.path.append(str(Path(__file__).parent.parent.parent))

from backend.api.models.responses import PositionResponse, PortfolioSummary


def _parse_strike(symbol: str) -> int:
    """Extract strike price from option symbol, e.g. NIFTY27MAY24500CE → 24500."""
    m = re.search(r'(\d+)(CE|PE)$', symbol.upper())
    return int(m.group(1)) if m else 0


class PositionService:
    def __init__(self, position_manager, order_manager, config):
        self.position_manager = position_manager
        self.order_manager = order_manager
        self.config = config

    async def get_all_positions(self) -> List[PositionResponse]:
        # order_manager is the in-memory source of truth for both paper and live trades
        if self.order_manager:
            return self._from_order_manager()

        # Fallback: SQLite-backed position_manager (only populated in legacy CLI mode)
        if not self.position_manager:
            return []
        return self._from_position_manager()

    def _from_order_manager(self) -> List[PositionResponse]:
        result = []
        for pos in self.order_manager.get_open_positions():
            symbol      = pos.get('symbol', '')
            entry_price = float(pos.get('entry_price', 0.0))
            qty         = int(pos.get('qty', 0))
            unrealized  = float(pos.get('unrealized_pnl', 0.0))
            pnl_pct     = (unrealized / (entry_price * qty) * 100) if entry_price * qty > 0 else 0.0
            result.append(PositionResponse(
                order_id       = pos.get('order_id', ''),
                symbol         = symbol,
                strike         = _parse_strike(symbol),
                entry_price    = entry_price,
                current_price  = float(pos.get('current_price', entry_price)),
                qty            = qty,
                direction      = pos.get('direction', 'CE'),
                entry_time     = pos.get('entry_time', datetime.now()),
                exit_time      = pos.get('exit_time'),
                strategy       = pos.get('strategy', ''),
                regime         = pos.get('regime', ''),
                unrealized_pnl = unrealized,
                realized_pnl   = float(pos.get('realized_pnl', 0.0)),
                sl_price       = float(pos.get('sl_price', 0.0)),
                target_price   = float(pos.get('target_price', 0.0)),
                pnl_percentage = round(pnl_pct, 2),
            ))
        return result

    def _from_position_manager(self) -> List[PositionResponse]:
        result = []
        for pos_info in self.position_manager.get_open_positions():
            entry_price = pos_info.entry_price
            qty         = pos_info.qty
            pnl_pct     = (pos_info.unrealized_pnl / (entry_price * qty) * 100
                           if entry_price * qty > 0 else 0)
            result.append(PositionResponse(
                order_id       = pos_info.order_id,
                symbol         = pos_info.symbol,
                strike         = getattr(pos_info, 'strike', _parse_strike(pos_info.symbol)),
                entry_price    = entry_price,
                current_price  = pos_info.current_price,
                qty            = qty,
                direction      = pos_info.direction,
                entry_time     = pos_info.entry_time,
                exit_time      = pos_info.exit_time,
                strategy       = pos_info.strategy,
                regime         = pos_info.regime,
                unrealized_pnl = pos_info.unrealized_pnl,
                realized_pnl   = pos_info.realized_pnl,
                sl_price       = pos_info.sl_price,
                target_price   = pos_info.target_price,
                pnl_percentage = round(pnl_pct, 2),
            ))
        return result

    async def get_position(self, order_id: str) -> Optional[PositionResponse]:
        for pos in await self.get_all_positions():
            if pos.order_id == order_id:
                return pos
        return None

    async def close_position(self, order_id: str, reason: str = "manual_close") -> bool:
        if self.order_manager:
            pos_dict = next(
                (p for p in self.order_manager.get_open_positions()
                 if p.get('order_id') == order_id),
                None,
            )
            if pos_dict:
                self.order_manager.exit_position(pos_dict, reason=reason)
                return True
        return False

    async def get_portfolio_summary(self, angel_client=None) -> PortfolioSummary:
        import asyncio
        positions = await self.get_all_positions()

        total_unrealized = sum(p.unrealized_pnl for p in positions)
        used_capital     = sum(p.entry_price * p.qty for p in positions)

        # Use real broker balance when available; fall back to config
        total_capital = float(self.config.get('capital', 500000))
        available     = total_capital - used_capital

        if angel_client is not None:
            try:
                loop  = asyncio.get_event_loop()
                funds = await loop.run_in_executor(None, angel_client.get_funds)
                net   = float(
                    funds.get("availablecash")
                    or funds.get("net")
                    or funds.get("availablebalance")
                    or 0
                )
                if net > 0:
                    total_capital = net + used_capital   # net = cash still free; total = free + deployed
                    available     = net
            except Exception:
                pass  # keep config fallback silently

        total_pnl_pct = (total_unrealized / total_capital * 100) if total_capital > 0 else 0.0

        return PortfolioSummary(
            total_capital        = total_capital,
            used_capital         = used_capital,
            available_capital    = available,
            total_pnl            = total_unrealized,
            total_pnl_percentage = total_pnl_pct,
            open_positions_count = len(positions),
            daily_pnl            = total_unrealized,
            daily_pnl_percentage = total_pnl_pct,
        )
