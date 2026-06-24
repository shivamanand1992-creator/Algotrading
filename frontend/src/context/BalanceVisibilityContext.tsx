import React, { createContext, useContext, useState } from 'react';

interface BalanceVisibilityContextType {
  balVisible: boolean;
  toggleBalVisible: () => void;
}

const BalanceVisibilityContext = createContext<BalanceVisibilityContextType>({
  balVisible: false,
  toggleBalVisible: () => {},
});

export function BalanceVisibilityProvider({ children }: { children: React.ReactNode }) {
  const [balVisible, setBalVisible] = useState(false);
  return (
    <BalanceVisibilityContext.Provider value={{ balVisible, toggleBalVisible: () => setBalVisible(v => !v) }}>
      {children}
    </BalanceVisibilityContext.Provider>
  );
}

export function useBalanceVisibility() {
  return useContext(BalanceVisibilityContext);
}

/** Masks a pre-formatted monetary string when hidden. */
export function maskAmount(value: string, visible: boolean): string {
  return visible ? value : '••••••';
}
