import React, { useState, useEffect } from 'react';
import { BalanceVisibilityProvider } from './context/BalanceVisibilityContext';
import { MainLayout } from './components/layout/MainLayout';
import { DashboardView } from './components/dashboard/DashboardView';
import { MarketDataView } from './components/market/MarketDataView';
import { MarketNewsView } from './components/news/MarketNewsView';
import { HelpView } from './components/help/HelpView';
import { StocksView } from './components/stocks/StocksView';
import { NiftyBeesView } from './components/niftybees/NiftyBeesView';
import { SectorAnalysisView } from './components/sectors/SectorAnalysisView';
import { ETFHoldingsView } from './components/holdings/ETFHoldingsView';
import { PortfolioView } from './components/portfolio/PortfolioView';
import { StockConvictionView } from './components/conviction/StockConvictionView';
import { WeeklyIncomeTrader } from './components/weekly-income/WeeklyIncomeTrader';
import { LoginView } from './components/auth/LoginView';
import { api } from './api/client';
import './styles/jarvis-theme.css';
import './styles/jarvis-hud.css';
import './styles/jarvis-mobile.css';

const TOKEN_KEY = 'algo_auth_token';

function App() {
  const [currentView, setCurrentView] = useState<string>('dashboard');
  const [authState, setAuthState] = useState<'checking' | 'authenticated' | 'unauthenticated'>('checking');

  // On mount: check if a stored token is still valid
  useEffect(() => {
    const stored = localStorage.getItem(TOKEN_KEY);
    if (!stored) {
      setAuthState('unauthenticated');
      return;
    }
    // Verify token with backend
    api.defaults.headers.common['Authorization'] = `Bearer ${stored}`;
    api.get('/api/auth/me')
      .then(() => setAuthState('authenticated'))
      .catch(() => {
        localStorage.removeItem(TOKEN_KEY);
        delete api.defaults.headers.common['Authorization'];
        setAuthState('unauthenticated');
      });
  }, []);

  const handleLoginSuccess = (token: string) => {
    localStorage.setItem(TOKEN_KEY, token);
    api.defaults.headers.common['Authorization'] = `Bearer ${token}`;
    setAuthState('authenticated');
  };

  const handleLogout = () => {
    localStorage.removeItem(TOKEN_KEY);
    delete api.defaults.headers.common['Authorization'];
    setAuthState('unauthenticated');
  };

  const renderView = () => {
    switch (currentView) {
      case 'dashboard':  return <DashboardView />;
      case 'weekly-income': return <WeeklyIncomeTrader />;
      case 'market':     return <MarketDataView />;
      case 'news':       return <MarketNewsView />;
      case 'stocks':     return <StocksView />;
      case 'niftybees':  return <NiftyBeesView />;
      case 'sectors':    return <SectorAnalysisView />;
      case 'holdings':   return <ETFHoldingsView />;
      case 'portfolio':  return <PortfolioView />;
      case 'conviction': return <StockConvictionView />;
      case 'help':       return <HelpView />;
      default:           return <DashboardView />;
    }
  };

  if (authState === 'checking') {
    return (
      <div style={{
        minHeight: '100vh', background: '#050d1a',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: 'rgba(0,229,255,0.4)', fontFamily: "'Courier New', monospace",
        letterSpacing: 4, fontSize: 12,
      }}>
        INITIALISING SYSTEM...
      </div>
    );
  }

  if (authState === 'unauthenticated') {
    return <LoginView onLoginSuccess={handleLoginSuccess} />;
  }

  return (
    <BalanceVisibilityProvider>
      <MainLayout activeView={currentView} onNavigate={setCurrentView} onLogout={handleLogout}>
        {renderView()}
      </MainLayout>
    </BalanceVisibilityProvider>
  );
}

export default App;
