import React, { ReactNode } from 'react';
import { Header } from './Header';
import { Sidebar } from './Sidebar';

interface MainLayoutProps {
  children: ReactNode;
  activeView: string;
  onNavigate: (view: string) => void;
  onLogout?: () => void;
}

export function MainLayout({ children, activeView, onNavigate, onLogout }: MainLayoutProps) {
  return (
    <div className="min-h-screen flex flex-col">
      <Header onLogout={onLogout} />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar activeView={activeView} onNavigate={onNavigate} />
        <main className="flex-1 overflow-y-auto p-6">
          {children}
        </main>
      </div>
    </div>
  );
}
