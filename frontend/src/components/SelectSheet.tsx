import React, { useEffect, useId, useState } from 'react';
import { createPortal } from 'react-dom';
import { PHONE_QUERY, useMediaQuery } from '../hooks/useMediaQuery';
import './SelectSheet.css';

/**
 * Выбор из списка: на компьютере — обычный выпадающий список, на телефоне —
 * своя панель снизу экрана.
 *
 * Системный выбор на телефоне — серое окно с кружками на весь экран, длинные
 * отрасли («Нефтегаз / горнодобыча / металлургия») переносятся в три строки,
 * и он не похож на остальной сайт. Панель снизу — привычный жест: открылась
 * под пальцем, пункты крупные, число компаний справа, закрывается нажатием
 * мимо.
 */

export interface SelectOption {
  value: string;
  label: string;
  /** Сколько компаний за пунктом — справа приглушённо. */
  count?: number;
}

interface Props {
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
  /** Заголовок панели и подпись для читалок экрана. */
  label: string;
  className?: string;
}

export default function SelectSheet({ value, options, onChange, label, className }: Props) {
  const isPhone = useMediaQuery(PHONE_QUERY);
  const [open, setOpen] = useState(false);
  const titleId = useId();
  const current = options.find((o) => o.value === value) ?? options[0];

  // Пока панель открыта, страница под ней не прокручивается, а «Назад» на
  // клавиатуре (Esc) закрывает её.
  useEffect(() => {
    if (!open) return undefined;
    const { overflow } = document.body.style;
    document.body.style.overflow = 'hidden';
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    window.addEventListener('keydown', onKey);
    return () => {
      document.body.style.overflow = overflow;
      window.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const text = (o: SelectOption) => (o.count !== undefined ? `${o.label} · ${o.count}` : o.label);

  if (!isPhone) {
    return (
      <select className={className} aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => <option key={o.value} value={o.value}>{text(o)}</option>)}
      </select>
    );
  }

  return (
    <>
      <button type="button" className={['ss-field', className].filter(Boolean).join(' ')}
        aria-haspopup="dialog" aria-label={`${label}: ${current?.label ?? ''}`} onClick={() => setOpen(true)}>
        <span className="ss-field-text">{current?.label}</span>
        {current?.count !== undefined && <span className="ss-field-count">{current.count}</span>}
        <svg className="ss-field-chevron" viewBox="0 0 16 16" width="16" height="16" aria-hidden>
          <path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && createPortal(
        <div className="ss-backdrop" onClick={() => setOpen(false)}>
          <div className="ss-sheet" role="dialog" aria-modal="true" aria-labelledby={titleId}
            onClick={(e) => e.stopPropagation()}>
            <div className="ss-grip" aria-hidden />
            <div className="ss-head">
              <h3 id={titleId}>{label}</h3>
              <button type="button" className="ss-close" onClick={() => setOpen(false)}>Закрыть</button>
            </div>
            <ul className="ss-list" role="listbox" aria-labelledby={titleId}>
              {options.map((o) => {
                const on = o.value === value;
                return (
                  <li key={o.value}>
                    <button type="button" role="option" aria-selected={on} className={`ss-option${on ? ' is-on' : ''}`}
                      onClick={() => { onChange(o.value); setOpen(false); }}>
                      <span className="ss-option-label">{o.label}</span>
                      {o.count !== undefined && <span className="ss-option-count">{o.count}</span>}
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        </div>,
        document.body,
      )}
    </>
  );
}
