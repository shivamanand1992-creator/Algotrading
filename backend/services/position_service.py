import sys
from pathlib import Path
from typing import List, Optional
from datetime import datetime

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from backend.api.models.responses import PositionResponse, PortfolioSummary


class PositionService:
    def __init__(self, position_manager, config):
        self.position_manager = position_manager
        self.config = config

    async def get_all_positions(self) -> List[PositionResponse]:
        """Get all open positions"""
        positions = self.position_manager.get_all_positions()

        result = []
        for pos_id, pos_info in positions.items():
            pnl_pct = (pos_info.unrealized_pnl / (pos_info.entry_price * pos_info.qty) * 100
                       if pos_info.entry_price * pos_info.qty > 0 else 0)

            result.append(PositionResponse(
                order_id=pos_info.order_id,
                symbol=pos_info.symbol,
                strike=pos_info.strike,
                entry_price=pos_info.entry_price,
                current_price=pos_info.current_price,
                qty=pos_info.qty,
                direction=pos_info.direction,
                entry_time=pos_info.entry_time,
                exit_time=pos_info.exit_time,
                strategy=pos_info.strategy,
                regime=pos_info.regime,
                unrealized_pnl=pos_info.unrealized_pnl,
                realized_pnl=pos_info.realized_pnl,
                sl_price=pos_info.sl_price,
                target_price=pos_info.target_price,
                pnl_percentage=pnl_pct
            ))

        return result

    async def get_position(self, order_id: str) -> Optional[PositionResponse]:
        """Get specific position details"""
        positions = await self.get_all_positions()
        for pos in positions:
            if pos.order_id == order_id:
                return pos
        return None

    async def close_position(self, order_id: str, reason: str = "manual_close") -> bool:
        """Close a position"""
        # TODO: Implement position closing via order manager
        # For now, just return success
        return True

    async def get_portfolio_summary(self) -> PortfolioSummary:
        """Get portfolio summary"""
        total_capital = self.config.get('capital', 500000)
        positions = await self.get_all_positions()

        # Calculate metrics
        total_unrealized_pnl = sum(pos.unrealized_pnl for pos in positions)
        used_capital = sum(pos.entry_price * pos.qty for pos in positions)
        available_capital = total_capital - used_capital

        # TODO: Get daily P&L from database
        daily_pnl = 0
        daily_pnl_pct = (daily_pnl / total_capital * 100) if total_capital > 0 else 0

        total_pnl_pct = (total_unrealized_pnl / total_capital * 100) if total_capital > 0 else 0

        return PortfolioSummary(
            total_capital=total_capital,
            used_capital=used_capital,
            available_capital=available_capital,
            total_pnl=total_unrealized_pnl,
            total_pnl_percentage=total_pnl_pct,
            open_positions_count=len(positions),
            daily_pnl=daily_pnl,
            daily_pnl_percentage=daily_pnl_pct
        )
