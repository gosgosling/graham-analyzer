import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';

/**
 * Режим темы:
 *  - 'auto'  — следовать системе (prefers-color-scheme)
 *  - 'light' — светлая (фиксированно)
 *  - 'dark'  — тёмная (фиксированно)
 */
export type ThemeMode = 'auto' | 'light' | 'dark';

/** Реально применённая тема — всегда конкретное значение. */
export type ResolvedTheme = 'light' | 'dark';

interface ThemeContextValue {
  /** Что выбрал пользователь. */
  mode: ThemeMode;
  /** Что реально применено сейчас (с учётом системной темы при mode='auto'). */
  resolved: ResolvedTheme;
  /** Сменить режим (auto / light / dark). */
  setMode: (mode: ThemeMode) => void;
  /** Удобный тумблер «light ↔ dark» (выходит из 'auto', если был). */
  toggle: () => void;
}

const STORAGE_KEY = 'graham-analyzer:theme';
const DARK_MQ = '(prefers-color-scheme: dark)';

const ThemeContext = createContext<ThemeContextValue | null>(null);

function readStoredMode(): ThemeMode {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === 'light' || v === 'dark' || v === 'auto') return v;
  } catch {
    /* localStorage недоступен (приватный режим, SSR и т.п.) */
  }
  return 'auto';
}

function getSystemTheme(): ResolvedTheme {
  if (typeof window === 'undefined' || !window.matchMedia) return 'light';
  return window.matchMedia(DARK_MQ).matches ? 'dark' : 'light';
}

function resolveMode(mode: ThemeMode): ResolvedTheme {
  return mode === 'auto' ? getSystemTheme() : mode;
}

interface ThemeProviderProps {
  children: React.ReactNode;
}

export const ThemeProvider: React.FC<ThemeProviderProps> = ({ children }) => {
  const [mode, setModeState] = useState<ThemeMode>(() => readStoredMode());
  const [resolved, setResolved] = useState<ResolvedTheme>(() =>
    resolveMode(readStoredMode()),
  );

  // Применяем тему на <html data-theme> и синхронизируем resolved.
  useEffect(() => {
    const r = resolveMode(mode);
    setResolved(r);
    document.documentElement.setAttribute('data-theme', r);
    try {
      localStorage.setItem(STORAGE_KEY, mode);
    } catch {
      /* ignore */
    }
  }, [mode]);

  // Слушаем системную тему — нужно только при mode='auto'.
  useEffect(() => {
    if (mode !== 'auto') return;
    if (typeof window === 'undefined' || !window.matchMedia) return;

    const mq = window.matchMedia(DARK_MQ);
    const handler = () => {
      const r: ResolvedTheme = mq.matches ? 'dark' : 'light';
      setResolved(r);
      document.documentElement.setAttribute('data-theme', r);
    };
    // Современный API + fallback для Safari < 14
    if (typeof mq.addEventListener === 'function') {
      mq.addEventListener('change', handler);
      return () => mq.removeEventListener('change', handler);
    }
    mq.addListener(handler);
    return () => mq.removeListener(handler);
  }, [mode]);

  const setMode = useCallback((m: ThemeMode) => setModeState(m), []);

  const toggle = useCallback(() => {
    setModeState((prev) => {
      const current = resolveMode(prev);
      return current === 'dark' ? 'light' : 'dark';
    });
  }, []);

  const value = useMemo<ThemeContextValue>(
    () => ({ mode, resolved, setMode, toggle }),
    [mode, resolved, setMode, toggle],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
};

/** Хук для чтения и переключения темы. */
export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    throw new Error('useTheme must be used inside <ThemeProvider>');
  }
  return ctx;
}

/**
 * Цвета для тех мест, где CSS-переменные неудобны
 * (recharts требует строковые значения в SVG-атрибутах).
 *
 * Эти значения должны соответствовать `--color-chart-*` в tokens.css.
 */
export interface ChartColors {
  grid: string;
  axis: string;
  line1: string;
  line2: string;
  line3: string;
  line4: string;
  line5: string;
  line6: string;
  refGood: string;
  refBad: string;
  tooltipBg: string;
  tooltipBorder: string;
  dotStroke: string;
  textPrimary: string;
}

const LIGHT_CHART: ChartColors = {
  grid: '#e2e8f0',
  axis: '#64748b',
  line1: '#6366f1',
  line2: '#8b5cf6',
  line3: '#10b981',
  line4: '#f59e0b',
  line5: '#06b6d4',
  line6: '#ec4899',
  refGood: '#22c55e',
  refBad: '#ef4444',
  tooltipBg: '#ffffff',
  tooltipBorder: '#e2e8f0',
  dotStroke: '#ffffff',
  textPrimary: '#1e293b',
};

const DARK_CHART: ChartColors = {
  grid: 'rgba(255,255,255,0.06)',
  axis: '#7a8499',
  line1: '#818cf8',
  line2: '#a78bfa',
  line3: '#34d399',
  line4: '#fbbf24',
  line5: '#22d3ee',
  line6: '#f472b6',
  refGood: '#34d399',
  refBad: '#f87171',
  tooltipBg: '#222937',
  tooltipBorder: 'rgba(255,255,255,0.10)',
  dotStroke: '#222937',
  textPrimary: '#e6e9ef',
};

/** Цвета recharts/SVG в зависимости от текущей темы. */
export function useChartColors(): ChartColors {
  const { resolved } = useTheme();
  return resolved === 'dark' ? DARK_CHART : LIGHT_CHART;
}
