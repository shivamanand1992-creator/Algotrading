import React, { useState, useEffect } from 'react';
import { MainLayout } from './components/layout/MainLayout';
import { DashboardView } from './components/dashboard/DashboardView';
import { MarketDataView } from './components/market/MarketDataView';
import { MarketNewsView } from './components/news/MarketNewsView';
import { HelpView } from './components/help/HelpView';
import { StocksView } from './components/stocks/StocksView';
import { NiftyBeesView } from './components/niftybees/NiftyBeesView';
import { SectorAnalysisView } from './components/sectors/SectorAnalysisView';
import { ETFHoldingsView } from './components/holdings/ETFHoldingsView';
import { LoginView } from './components/auth/LoginView';
import { api } from './api/client';
import './styles/jarvis-theme.css';

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
      case 'market':     return <MarketDataView />;
      case 'news':       return <MarketNewsView />;
      case 'stocks':     return <StocksView />;
      case 'niftybees':  return <NiftyBeesView />;
      case 'sectors':    return <SectorAnalysisView />;
      case 'holdings':   return <ETFHoldingsView />;
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
    <MainLayout activeView={currentView} onNavigate={setCurrentView} onLogout={handleLogout}>
      {renderView()}
    </MainLayout>
  );
}

export default App;
