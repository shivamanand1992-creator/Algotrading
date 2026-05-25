import React, { useState } from 'react';
import { MainLayout } from './components/layout/MainLayout';
import { DashboardView } from './components/dashboard/DashboardView';
import { StrategyPanel } from './components/strategies/StrategyPanel';
import './styles/jarvis-theme.css';

function App() {
  const [currentView, setCurrentView] = useState<'dashboard' | 'strategies'>(
    'dashboard'
  );

  return (
    <MainLayout>
      {currentView === 'dashboard' ? <DashboardView /> : <StrategyPanel />}
    </MainLayout>
  );
}

export default App;
