import React, { ReactNode } from 'react';
import { Header } from './Header';
import { Sidebar } from './Sidebar';
import { ParticleCanvas } from '../ui/ParticleCanvas';
import { JarvisVoicePanel } from '../jarvis/JarvisVoicePanel';

interface MainLayoutProps {
  children: ReactNode;
  activeView: string;
  onNavigate: (view: string) => void;
  onLogout?: () => void;
}

export function MainLayout({ children, activeView, onNavigate, onLogout }: MainLayoutProps) {
  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', position: 'relative' }}>
      <ParticleCanvas />
      <div style={{ position: 'relative', zIndex: 1, display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
        <Header onLogout={onLogout} />
        <div className="flex flex-1 overflow-hidden">
          <Sidebar activeView={activeView} onNavigate={onNavigate} />
          <main className="flex-1 overflow-y-auto p-6">
            {children}
          </main>
        </div>
      </div>
      {/* JARVIS voice panel — fixed bottom-right, available on all pages */}
      <JarvisVoicePanel />
    </div>
  );
}
