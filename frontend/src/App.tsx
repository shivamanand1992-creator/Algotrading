import React, { useState } from 'react';
import { MainLayout } from './components/layout/MainLayout';
import { DashboardView } from './components/dashboard/DashboardView';
import { StrategyPanel } from './components/strategies/StrategyPanel';
import { PortfolioView } from './components/portfolio/PortfolioView';
import { MarketDataView } from './components/market/MarketDataView';
import { RiskView } from './components/risk/RiskView';
import './styles/jarvis-theme.css';

function App() {
  const [currentView, setCurrentView] = useState<string>('dashboard');

  const renderView = () => {
    switch (currentView) {
      case 'dashboard': return <DashboardView />;
      case 'strategies': return <StrategyPanel />;
      case 'portfolio': return <PortfolioView />;
      case 'market': return <MarketDataView />;
      case 'risk': return <RiskView />;
      default: return <DashboardView />;
    }
  };

  return (
    <MainLayout activeView={currentView} onNavigate={setCurrentView}>
      {renderView()}
    </MainLayout>
  );
}

export default App;
