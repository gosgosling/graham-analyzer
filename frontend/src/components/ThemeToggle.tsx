import React from 'react';
import { useTheme, ThemeMode } from '../contexts/ThemeContext';
import './ThemeToggle.css';

interface Option {
  key: ThemeMode;
  label: string;
  icon: string;
  ariaLabel: string;
}

const OPTIONS: Option[] = [
  { key: 'light', label: 'Светлая', icon: '☀', ariaLabel: 'Светлая тема' },
  { key: 'auto',  label: 'Авто',     icon: '⊙', ariaLabel: 'Авто-тема (по системе)' },
  { key: 'dark',  label: 'Тёмная',   icon: '☾', ariaLabel: 'Тёмная тема' },
];

/**
 * `compact` — одна кнопка для шапки: показывает нынешнюю тему и по нажатию
 * переходит к следующей (светлая → тёмная → по системе).
 */
const ThemeToggle: React.FC<{ compact?: boolean }> = ({ compact = false }) => {
  const { mode, setMode } = useTheme();

  if (compact) {
    const index = OPTIONS.findIndex((o) => o.key === mode);
    const current = OPTIONS[index >= 0 ? index : 0];
    const order: ThemeMode[] = ['light', 'dark', 'auto'];
    const next = OPTIONS.find((o) => o.key === order[(order.indexOf(current.key) + 1) % order.length])!;
    return (
      <button
        type="button"
        className="theme-toggle-compact"
        onClick={() => setMode(next.key)}
        title={`Тема: ${current.label.toLowerCase()}. Нажмите — ${next.label.toLowerCase()}`}
        aria-label={`${current.ariaLabel}. Переключить на: ${next.ariaLabel.toLowerCase()}`}
      >
        <span aria-hidden>{current.icon}</span>
      </button>
    );
  }

  return (
    <div className="theme-toggle" role="radiogroup" aria-label="Тема оформления">
      {OPTIONS.map((opt) => (
        <button
          key={opt.key}
          type="button"
          role="radio"
          aria-checked={mode === opt.key}
          aria-label={opt.ariaLabel}
          className={`theme-toggle-option${mode === opt.key ? ' is-active' : ''}`}
          onClick={() => setMode(opt.key)}
        >
          <span className="theme-toggle-icon" aria-hidden>
            {opt.icon}
          </span>
          <span className="theme-toggle-label">{opt.label}</span>
        </button>
      ))}
    </div>
  );
};

export default ThemeToggle;
