import React, { useEffect, useRef } from 'react';

export interface LogEntry {
  id: string | number;
  time: string;
  type: 'buy' | 'sell' | 'info' | 'warn' | 'target';
  message: string;
}

interface ExecutionLogFeedProps {
  entries?: LogEntry[];
  maxLines?: number;
  title?: string;
}

const TYPE_COLOR: Record<string, string> = {
  buy:    '#00e676',
  sell:   '#ff1744',
  info:   '#00e5ff',
  warn:   '#ffab00',
  target: '#ffd600',
};
const TYPE_LABEL: Record<string, string> = {
  buy: 'BUY', sell: 'SELL', info: 'INFO', warn: 'WARN', target: 'HIT!',
};

export function ExecutionLogFeed({
  entries = [], maxLines = 8, title = 'Execution Log',
}: ExecutionLogFeedProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const visible   = entries.slice(-maxLines);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [visible.length]);

  return (
    <div style={{
      background:   'rgba(0,5,15,0.82)',
      border:       '1px solid rgba(0,229,255,0.1)',
      borderRadius: 12,
      padding:      '12px 14px',
    }}>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <div
          className="live-dot"
          style={{ width: 6, height: 6, background: '#00e5ff', color: '#00e5ff', flexShrink: 0 }}
        />
        <span style={{
          fontSize: 9, fontFamily: 'monospace', letterSpacing: '0.2em',
          color: 'rgba(0,229,255,0.5)', textTransform: 'uppercase',
        }}>
          {title}
        </span>
        <span className="type-cursor" />
      </div>

      {/* Log lines */}
      <div ref={scrollRef} style={{ maxHeight: maxLines * 22, overflow: 'hidden' }}>
        {visible.length === 0 ? (
          <div style={{
            fontSize: 10, color: 'rgba(160,196,224,0.3)',
            fontFamily: 'monospace', padding: '4px 0',
          }}>
            Awaiting signals…
          </div>
        ) : (
          visible.map((e, i) => (
            <div
              key={e.id}
              className="log-enter"
              style={{ display: 'flex', alignItems: 'baseline', gap: 8, padding: '2px 0', animationDelay: `${i * 0.025}s` }}
            >
              <span style={{ fontSize: 9, color: 'rgba(160,196,224,0.35)', fontFamily: 'monospace', flexShrink: 0 }}>
                {e.time}
              </span>
              <span style={{ fontSize: 9, fontFamily: 'monospace', color: TYPE_COLOR[e.type] ?? '#00e5ff', flexShrink: 0, fontWeight: 700 }}>
                [{TYPE_LABEL[e.type] ?? e.type.toUpperCase()}]
              </span>
              <span style={{ fontSize: 10, color: 'rgba(160,196,224,0.78)', fontFamily: 'monospace', lineHeight: 1.4 }}>
                {e.message}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
