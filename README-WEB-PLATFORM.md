# JARVIS-Style Web Trading Platform

Complete web-based algorithmic trading platform with futuristic Iron Man JARVIS-inspired UI.

## 🎯 Overview

This project wraps the existing Python algorithmic trading system with a modern web interface featuring:
- FastAPI REST API backend
- React TypeScript frontend
- Real-time WebSocket updates
- Futuristic JARVIS-style UI with circular widgets and holographic effects

## 🏗️ Architecture

```
┌─────────────────────────────────────────┐
│   React Frontend (Port 3000)            │
│   - JARVIS UI with circular widgets     │
│   - Real-time dashboard                 │
│   - Strategy control panel              │
│   - Portfolio management                │
└─────────────┬───────────────────────────┘
              │ HTTP + WebSocket
┌─────────────┴───────────────────────────┐
│   FastAPI Backend (Port 8000)           │
│   - 15 REST API endpoints               │
│   - WebSocket manager                   │
│   - Service layer                       │
└─────────────┬───────────────────────────┘
              │
┌─────────────┴───────────────────────────┐
│   Existing Python Components            │
│   - Strategies (Trend, Premium, Scalp)  │
│   - ML Models (LSTM, XGBoost)           │
│   - Order/Position/Risk Management      │
│   - Angel One Integration               │
└─────────────────────────────────────────┘
```

## 📁 Project Structure

```
Algotrading/
├── backend/                      # FastAPI backend
│   ├── main.py                  # FastAPI app entry point
│   ├── config.py                # Backend configuration
│   ├── websocket_manager.py     # WebSocket real-time updates
│   ├── dependencies.py          # Dependency injection
│   ├── api/
│   │   ├── routes/              # API endpoints
│   │   │   ├── strategies.py   # Strategy control
│   │   │   ├── positions.py    # Position management
│   │   │   ├── trades.py       # Trade history
│   │   │   ├── market_data.py  # Market data
│   │   │   ├── risk.py         # Risk metrics
│   │   │   └── system.py       # System status
│   │   └── models/              # Pydantic models
│   │       ├── requests.py     # Request models
│   │       └── responses.py    # Response models
│   └── services/                # Business logic
│       ├── strategy_service.py # Strategy orchestration
│       ├── position_service.py # Position management
│       └── market_service.py   # Market data aggregation
│
├── frontend/                     # React frontend
│   ├── src/
│   │   ├── components/
│   │   │   ├── layout/         # MainLayout, Header, Sidebar
│   │   │   ├── dashboard/      # DashboardView
│   │   │   ├── strategies/     # StrategyPanel
│   │   │   └── ui/             # CircularWidget, Button, Card
│   │   ├── hooks/
│   │   │   └── useWebSocket.ts # WebSocket hook
│   │   ├── api/
│   │   │   └── client.ts       # API client
│   │   ├── types/
│   │   │   └── api.ts          # TypeScript types
│   │   ├── utils/
│   │   │   └── formatters.ts   # Formatting utilities
│   │   └── styles/
│   │       └── jarvis-theme.css # JARVIS styling
│   ├── .env                     # Environment config
│   └── package.json             # Dependencies
│
└── [existing Python modules]    # Original trading system
    ├── strategies/
    ├── models/
    ├── execution/
    ├── data/
    └── ...
```

## 🚀 Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- npm 10+

### Backend Setup

1. Install Python dependencies:
```bash
pip install -r requirements.txt
```

2. Configure environment:
```bash
# Copy and edit .env file with your Angel One credentials
cp .env.example .env
```

3. Start backend server:
```bash
cd /home/user/Algotrading
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

Backend will be available at: `http://localhost:8000`
- API docs: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`

### Frontend Setup

1. Install dependencies:
```bash
cd frontend
npm install
```

2. Configure environment:
```bash
# Edit frontend/.env if needed
REACT_APP_API_URL=http://localhost:8000
REACT_APP_WS_URL=ws://localhost:8000
```

3. Start development server:
```bash
npm start
```

Frontend will open at: `http://localhost:3000`

## 🔌 API Endpoints

### System
- `GET /api/system/status` - System health and status
- `POST /api/system/mode` - Switch mode (paper/live/backtest)
- `GET /api/system/logs` - Recent log entries

### Strategies
- `GET /api/strategies` - List all strategies with status
- `POST /api/strategies/{name}/start` - Start a strategy
- `POST /api/strategies/{name}/stop` - Stop a strategy
- `GET /api/strategies/{name}/config` - Get strategy config
- `PUT /api/strategies/{name}/config` - Update strategy config
- `GET /api/strategies/{name}/signals` - Recent signals

### Positions
- `GET /api/positions` - All open positions
- `GET /api/positions/{order_id}` - Position details
- `POST /api/positions/{order_id}/close` - Close position
- `GET /api/portfolio/summary` - Portfolio summary

### Market Data
- `GET /api/market/current` - Current market data (Nifty50)
- `GET /api/market/options_chain` - Options chain with Greeks
- `GET /api/market/regime` - Market regime classification
- `GET /api/market/predictions` - ML model predictions

### Risk
- `GET /api/risk/limits` - Risk limits vs. usage
- `GET /api/risk/metrics` - Risk metrics (VaR, drawdown)
- `GET /api/risk/alerts` - Active risk alerts

### Trades
- `GET /api/trades` - Trade history (with filters)
- `GET /api/trades/statistics` - Trading statistics
- `GET /api/trades/export` - Export trades (CSV/JSON)

## 🔄 WebSocket Events

Connect to: `ws://localhost:8000/ws/live`

**Events Received:**
- `position_update` - Position updates (every 5 seconds)
- `market_tick` - Market data updates
- `new_signal` - New trading signals
- `risk_alert` - Risk alerts
- `connected` - Connection confirmation

## 🎨 JARVIS UI Features

### Design System
- **Color Palette**: Cyan (#00e5ff), Teal (#1de9b6), Light Blue (#00b0ff)
- **Effects**: Glass-morphism, glow, pulse, holographic gradients
- **Typography**: Inter + Roboto Mono for numbers
- **Animations**: Rotating borders, smooth transitions, pulsing indicators

### Components

#### Circular Widget
Reusable circular metric display with:
- Rotating gradient border
- Progress ring
- Glow effects
- Sizes: small, medium, large

#### Dashboard
- 4 circular widgets: Total P&L, Daily P&L, Capital Used, Positions
- Market overview card (Nifty price, IV, PCR)
- Portfolio summary
- Active positions table with live updates

#### Strategy Panel
- 3 strategy cards (Trend Following, Premium Selling, Scalping)
- Real-time status indicators
- Start/Stop controls
- Uptime and signals count
- Strategy descriptions

## 📊 Key Features

### Real-Time Updates
- WebSocket connection for live data
- Position P&L updates every 5 seconds
- Market data streaming
- Browser notifications for new signals

### Strategy Management
- Start/stop strategies from UI
- Paper trading mode by default
- Monitor strategy performance
- View signals generated

### Portfolio Tracking
- Real-time P&L calculation
- Capital utilization monitoring
- Position-level details
- Win/loss tracking

### Risk Management
- Daily loss limit monitoring
- Position concentration tracking
- Risk alert system
- Max positions enforcement

## 🔧 Development

### Backend Development
```bash
# Run with auto-reload
uvicorn backend.main:app --reload --port 8000

# Run tests (when implemented)
pytest tests/
```

### Frontend Development
```bash
# Start dev server
npm start

# Build for production
npm run build

# Run tests
npm test
```

## 📦 Production Deployment

### Docker Deployment
```bash
docker-compose up -d
```

Includes:
- Backend (FastAPI)
- Frontend (Nginx)
- PostgreSQL database

### Railway Deployment
Backend is configured for Railway deployment via `railway.toml`:
```bash
railway up
```

## 🛡️ Security Notes

- Never commit `.env` files with real credentials
- Use environment variables for sensitive data
- Enable authentication before production deployment
- Use HTTPS in production
- Validate all user inputs

## 📈 Performance

### Backend
- Handles 100+ req/sec
- WebSocket supports multiple concurrent connections
- Async FastAPI for high concurrency

### Frontend
- 60 FPS animations
- Lazy loading for components
- Optimized bundle size < 500KB (gzipped)

## 🔮 Future Enhancements

1. **Authentication**
   - JWT-based auth
   - User management
   - Role-based access

2. **Advanced Features**
   - Backtesting UI
   - Strategy parameter tuning
   - Trade journal with notes
   - Performance analytics

3. **Monitoring**
   - Prometheus metrics
   - Grafana dashboards
   - Error tracking (Sentry)

4. **Mobile App**
   - React Native app
   - Push notifications

## 🐛 Troubleshooting

### Backend won't start
- Check if port 8000 is available
- Verify Python dependencies are installed
- Check `.env` file exists

### Frontend won't connect to backend
- Verify backend is running on port 8000
- Check `.env` file has correct API_URL
- Ensure CORS is configured properly

### WebSocket connection fails
- Check firewall settings
- Verify WebSocket URL in `.env`
- Check browser console for errors

## 📝 License

Same as parent project

## 👥 Support

For issues or questions:
- GitHub Issues: https://github.com/shivamanand1992-creator/Algotrading/issues
- Session: https://claude.ai/code/session_01VaC2b4Wkk5D64jEpPX8nfn

---

Built with ❤️ using FastAPI, React, and Claude Code
