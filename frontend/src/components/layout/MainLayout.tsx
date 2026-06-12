import React, { ReactNode } from 'react';
import { Header } from './Header';
import { Sidebar } from './Sidebar';
import { ParticleCanvas } from '../ui/ParticleCanvas';
import { CityBackground } from '../ui/CityBackground';
import { JarvisVoicePanel } from '../jarvis/JarvisVoicePanel';

interface MainLayoutProps {
  children: ReactNode;
  activeView: string;
  onNavigate: (view: string) => void;
  onLogout?: () => void;
}

export function MainLayout({ children, activeView, onNavigate, onLogout }: MainLayoutProps) {
  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', position: 'relative', overflow: 'hidden' }}>
      {/* Layered backgrounds: city at z=0, particles at z=1 */}
      <CityBackground />
      <ParticleCanvas />

      {/* App shell above backgrounds */}
      <div style={{ position: 'relative', zIndex: 2, display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
        <Header onLogout={onLogout} />
        <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
          <Sidebar activeView={activeView} onNavigate={onNavigate} />
          <main style={{ flex: 1, overflowY: 'auto', padding: '20px 24px' }}>
            {children}
          </main>
        </div>
      </div>

      {/* VAAYU voice panel — fixed bottom-right */}
      <JarvisVoicePanel />
    </div>
  );
}
