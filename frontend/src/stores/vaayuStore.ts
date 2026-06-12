import { useState, useEffect } from 'react';

export type VaayuConvState = 'idle' | 'speaking' | 'listening' | 'processing';

type Listener = (state: VaayuConvState) => void;

let _state: VaayuConvState = 'idle';
const _listeners = new Set<Listener>();

export function setVaayuConvState(next: VaayuConvState) {
  if (_state === next) return;
  _state = next;
  _listeners.forEach(fn => fn(next));
}

export function useVaayuConvState(): VaayuConvState {
  const [s, setS] = useState<VaayuConvState>(_state);
  useEffect(() => {
    setS(_state);
    _listeners.add(setS);
    return () => { _listeners.delete(setS); };
  }, []);
  return s;
}
