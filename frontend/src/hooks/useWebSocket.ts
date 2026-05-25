import { useEffect, useState, useCallback, useRef } from 'react';
import { io, Socket } from 'socket.io-client';
import type { Position, MarketData, WebSocketMessage } from '../types/api';

const WS_URL = process.env.REACT_APP_WS_URL || 'ws://localhost:8000';

export function useWebSocket() {
  const [socket, setSocket] = useState<Socket | null>(null);
  const [connected, setConnected] = useState(false);
  const [positions, setPositions] = useState<Position[]>([]);
  const [marketData, setMarketData] = useState<MarketData | null>(null);
  const [lastSignal, setLastSignal] = useState<any>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout>();

  const connect = useCallback(() => {
    const ws = io(WS_URL, {
      transports: ['websocket'],
      reconnection: true,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
      reconnectionAttempts: 5,
    });

    ws.on('connect', () => {
      console.log('WebSocket connected');
      setConnected(true);
    });

    ws.on('disconnect', () => {
      console.log('WebSocket disconnected');
      setConnected(false);
    });

    ws.on('position_update', (data: any) => {
      if (data.data && data.data.positions) {
        setPositions(data.data.positions);
      }
    });

    ws.on('market_tick', (data: any) => {
      setMarketData(data);
    });

    ws.on('new_signal', (data: any) => {
      setLastSignal(data);
      // Show notification
      if ('Notification' in window && Notification.permission === 'granted') {
        new Notification('New Trading Signal', {
          body: `${data.action} - ${data.symbol}`,
          icon: '/logo192.png',
        });
      }
    });

    ws.on('connected', (data: any) => {
      console.log('Connected to trading platform:', data.message);
    });

    setSocket(ws);

    return ws;
  }, []);

  useEffect(() => {
    const ws = connect();

    // Request notification permission
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission();
    }

    return () => {
      if (ws) {
        ws.close();
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
    };
  }, [connect]);

  const sendMessage = useCallback(
    (message: any) => {
      if (socket && connected) {
        socket.emit('message', message);
      }
    },
    [socket, connected]
  );

  return {
    socket,
    connected,
    positions,
    marketData,
    lastSignal,
    sendMessage,
  };
}
