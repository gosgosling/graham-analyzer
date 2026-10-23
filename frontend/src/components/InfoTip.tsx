import React, { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import './InfoTip.css';

/**
 * Знак «?» с пояснением во всплывающем окошке рядом — как в приложениях
 * брокеров.
 *
 * Абзац пояснения над графиком или под таблицей читают один раз, а место он
 * занимает всегда. Здесь пояснение спрятано за знаком и открывается возле
 * него: без затемнения и без панели во весь экран, страницу под окошком
 * можно листать дальше. Закрывается повторным нажатием, нажатием мимо или
 * клавишей Esc.
 */
export default function InfoTip({ children, label = 'Пояснение' }: {
  children: React.ReactNode;
  /** Подпись знака для читалок экрана. */
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number; arrow: number } | null>(null);
  const button = useRef<HTMLButtonElement | null>(null);
  const bubble = useRef<HTMLDivElement | null>(null);
  const id = useId();

  // Окошко — под знаком, но в пределах экрана: у правого края оно
  // сдвигается влево, а стрелка остаётся над знаком.
  useLayoutEffect(() => {
    if (!open) { setPos(null); return undefined; }
    const place = () => {
      const b = button.current?.getBoundingClientRect();
      const w = bubble.current?.offsetWidth ?? 280;
      if (!b) return;
      const centre = b.left + b.width / 2;
      const left = Math.max(12, Math.min(window.innerWidth - w - 12, centre - w / 2));
      setPos({ top: b.bottom + window.scrollY + 8, left: left + window.scrollX, arrow: centre - left });
    };
    place();
    window.addEventListener('resize', place);
    return () => window.removeEventListener('resize', place);
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    const close = (e: Event) => {
      const t = e.target as Node;
      if (button.current?.contains(t) || bubble.current?.contains(t)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('pointerdown', close);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', close);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <>
      <button
        ref={button}
        type="button"
        className={`it-q${open ? ' is-open' : ''}`}
        aria-label={label}
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}
      >
        ?
      </button>
      {open && createPortal(
        <div
          ref={bubble}
          id={id}
          role="tooltip"
          className="it-bubble"
          style={pos ? { top: pos.top, left: pos.left } : { visibility: 'hidden', top: 0, left: 0 }}
        >
          <span className="it-arrow" style={{ left: pos?.arrow ?? 0 }} aria-hidden />
          {children}
        </div>,
        document.body,
      )}
    </>
  );
}
