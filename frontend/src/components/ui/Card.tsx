import React from 'react';

interface CardProps {
  title?: string;
  children: React.ReactNode;
  className?: string;
  headerAction?: React.ReactNode;
}

export function Card({ title, children, className = '', headerAction }: CardProps) {
  return (
    <div className={`glass-panel p-6 ${className}`}>
      {title && (
        <div className="flex items-center justify-between mb-4 pb-3 border-b border-jarvis-primary/20">
          <h3 className="text-lg font-semibold text-jarvis-primary uppercase tracking-wide">
            {title}
          </h3>
          {headerAction && <div>{headerAction}</div>}
        </div>
      )}
      {children}
    </div>
  );
}
