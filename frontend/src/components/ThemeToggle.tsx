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

const ThemeToggle: React.FC = () => {
  const { mode, setMode } = useTheme();

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
