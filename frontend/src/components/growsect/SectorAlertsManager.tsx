import React, { useState } from 'react';
import { IntradayAlertsConfig } from './IntradayAlertsConfig';
import { FoSectorAlertsConfig } from './FoSectorAlertsConfig';

export function SectorAlertsManager() {
  const [activeTab, setActiveTab] = useState<'intraday' | 'fo'>('intraday');

  return (
    <div>
      {/* Tab Navigation */}
      <div style={{
        display: 'flex',
        gap: '1rem',
        marginBottom: '2rem',
        borderBottom: '1px solid rgba(0,229,255,0.2)',
        paddingBottom: '1rem',
      }}>
        <button
          onClick={() => setActiveTab('intraday')}
          style={{
            padding: '0.75rem 1.5rem',
            background: activeTab === 'intraday' ? 'rgba(0,229,255,0.2)' : 'transparent',
            border: activeTab === 'intraday' ? '1px solid rgba(0,229,255,0.5)' : '1px solid transparent',
            color: activeTab === 'intraday' ? '#00e5ff' : 'rgba(0,229,255,0.6)',
            borderRadius: '6px',
            cursor: 'pointer',
            fontSize: '14px',
            fontWeight: activeTab === 'intraday' ? 'bold' : 'normal',
            transition: 'all 0.2s',
          }}
          onMouseEnter={(e) => {
            if (activeTab !== 'intraday') {
              (e.currentTarget as HTMLButtonElement).style.background = 'rgba(0,229,255,0.08)';
            }
          }}
          onMouseLeave={(e) => {
            if (activeTab !== 'intraday') {
              (e.currentTarget as HTMLButtonElement).style.background = 'transparent';
            }
          }}
        >
          📈 Intraday Alerts
        </button>
        <button
          onClick={() => setActiveTab('fo')}
          style={{
            padding: '0.75rem 1.5rem',
            background: activeTab === 'fo' ? 'rgba(0,229,255,0.2)' : 'transparent',
            border: activeTab === 'fo' ? '1px solid rgba(0,229,255,0.5)' : '1px solid transparent',
            color: activeTab === 'fo' ? '#00e5ff' : 'rgba(0,229,255,0.6)',
            borderRadius: '6px',
            cursor: 'pointer',
            fontSize: '14px',
            fontWeight: activeTab === 'fo' ? 'bold' : 'normal',
            transition: 'all 0.2s',
          }}
          onMouseEnter={(e) => {
            if (activeTab !== 'fo') {
              (e.currentTarget as HTMLButtonElement).style.background = 'rgba(0,229,255,0.08)';
            }
          }}
          onMouseLeave={(e) => {
            if (activeTab !== 'fo') {
              (e.currentTarget as HTMLButtonElement).style.background = 'transparent';
            }
          }}
        >
          📊 F&O Sector Alerts
        </button>
      </div>

      {/* Tab Content */}
      {activeTab === 'intraday' && <IntradayAlertsConfig />}
      {activeTab === 'fo' && <FoSectorAlertsConfig />}
    </div>
  );
}
