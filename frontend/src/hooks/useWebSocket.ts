import { useEffect, useState, useCallback, useRef } from 'react';
import type { Position, MarketData } from '../types/api';

// Auto-detect host so it works on Railway, localhost, anywhere.
const WS_BASE =
  process.env.REACT_APP_WS_URL ||
  `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`;

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [positions, setPositions] = useState<Position[]>([]);
  const [marketData, setMarketData] = useState<MarketData | null>(null);
  const [lastSignal, setLastSignal] = useState<any>(null);
  const retryRef = useRef<NodeJS.Timeout>();

  const connect = useCallback(() => {
    if (wsRef.current) wsRef.current.close();

    const ws = new WebSocket(`${WS_BASE}/ws/live`);

    ws.onopen = () => {
      console.log('WebSocket connected');
      setConnected(true);
    };

    ws.onclose = () => {
      console.log('WebSocket disconnected — retrying in 3s');
      setConnected(false);
      retryRef.current = setTimeout(connect, 3000);
    };

    ws.onerror = () => {
      ws.close();
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'position_update' && msg.data?.positions) {
          setPositions(msg.data.positions);
        } else if (msg.type === 'market_tick' && msg.data) {
          setMarketData(msg.data);
        } else if (msg.type === 'new_signal' && msg.data) {
          setLastSignal(msg.data);
          if ('Notification' in window && Notification.permission === 'granted') {
            new Notification('New Trading Signal', {
              body: `${msg.data.action} — ${msg.data.symbol}`,
            });
          }
        }
      } catch (e) {
        // ignore parse errors
      }
    };

    wsRef.current = ws;
  }, []);

  useEffect(() => {
    connect();
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission();
    }
    return () => {
      clearTimeout(retryRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  const sendMessage = useCallback((message: any) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message));
    }
  }, []);

  return { connected, positions, marketData, lastSignal, sendMessage };
}
