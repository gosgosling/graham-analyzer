import React, { useEffect, useRef } from 'react';
import './ReportMatrixViewport.css';

interface Props {
  columns: { id: number; label: string }[];
  children: React.ReactNode;
  filters?: React.ReactNode;
}

/** The document owns vertical scrolling. Only the columns scroll inside the table.
 * A translated thead stays below the site header without a second, duplicated table.
 */
export default function ReportMatrixViewport({ columns, children, filters }: Props) {
  const root = useRef<HTMLDivElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const toolbar = useRef<HTMLDivElement>(null);
  const dock = useRef<HTMLDivElement>(null);
  const slider = useRef<HTMLInputElement>(null);
  const position = useRef<HTMLOutputElement>(null);
  const previous = useRef<HTMLButtonElement>(null);
  const next = useRef<HTMLButtonElement>(null);
  const columnKey = columns.map(c => c.id).join(',');

  const move = (direction: number) => {
    const el = viewport.current;
    if (!el) return;
    const label = el.querySelector<HTMLElement>('.crm-th-label')?.offsetWidth || 220;
    const headers = Array.from(el.querySelectorAll<HTMLElement>('thead [data-report-id]'));
    const first = Math.max(0, headers.findIndex(h => h.offsetLeft + h.offsetWidth > el.scrollLeft + label + 1));
    const step = Math.max(1, Math.floor((el.clientWidth - label) / (headers[first]?.offsetWidth || 180)));
    const target = headers[Math.max(0, Math.min(headers.length - 1, first + direction * step))];
    el.scrollLeft = target ? Math.max(0, target.offsetLeft - label) : el.scrollLeft + direction * el.clientWidth;
    el.dispatchEvent(new Event('scroll'));
  };

  useEffect(() => {
    const el = viewport.current;
    const shell = root.current;
    if (!el || !shell) return;
    let frame = 0;
    let disposed = false;
    const measure = () => {
      if (disposed) return;
      const table = el.querySelector('table');
      const head = table?.tHead;
      const rect = el.getBoundingClientRect();
      const header = document.querySelector('.sh')?.getBoundingClientRect();
      const siteBottom = Math.max(0, header?.bottom || 0);
      shell.style.setProperty('--crm-header-top', `${siteBottom}px`);
      const top = siteBottom + (toolbar.current?.offsetHeight || 0);
      if (head) {
        const y = Math.max(0, Math.min(top - rect.top, el.offsetHeight - head.offsetHeight));
        head.style.transform = `translateY(${y}px)`;
        const corner = head.querySelector<HTMLElement>('.crm-th-label');
        if (corner) corner.style.transform = `translateX(${el.scrollLeft}px)`;
      }
      const max = Math.max(0, el.scrollWidth - el.clientWidth);
      if (slider.current) {
        slider.current.max = String(max);
        slider.current.value = String(el.scrollLeft);
        const track = slider.current.clientWidth || el.clientWidth;
        slider.current.style.setProperty('--crm-thumb-size', `${Math.max(32, Math.min(120, track * el.clientWidth / Math.max(1, el.scrollWidth)))}px`);
      }
      if (previous.current) previous.current.disabled = el.scrollLeft < 1;
      if (next.current) next.current.disabled = el.scrollLeft >= max - 1;
      const headers = Array.from(el.querySelectorAll<HTMLElement>('thead [data-report-id]'));
      const labelWidth = el.querySelector<HTMLElement>('.crm-th-label')?.offsetWidth || 220;
      const visible = headers.map((h, i) => ({ h, i })).filter(({ h }) => h.offsetLeft + h.offsetWidth > el.scrollLeft + labelWidth + 1 && h.offsetLeft < el.scrollLeft + el.clientWidth - 1);
      if (position.current) position.current.textContent = visible.length
        ? `${visible[0].i + 1}–${visible[visible.length - 1].i + 1} из ${headers.length}` : `${headers.length} отчётов`;
      if (dock.current) {
        const left = Math.max(12, rect.left);
        const right = Math.min(window.innerWidth - 12, rect.right);
        dock.current.style.left = `${left}px`;
        dock.current.style.width = `${Math.max(0, right - left)}px`;
        dock.current.hidden = !(max > 0 && rect.top < window.innerHeight - 64 && rect.bottom > top + (head?.offsetHeight || 0) + 48);
      }
    };
    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(measure);
    };
    const wheel = (event: WheelEvent) => {
      if (!event.shiftKey || !event.deltaY || el.scrollWidth <= el.clientWidth) return;
      event.preventDefault();
      el.scrollLeft += event.deltaY;
      schedule();
    };
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(schedule) : null;
    observer?.observe(el);
    const table = el.querySelector('table');
    if (table) observer?.observe(table);
    el.addEventListener('scroll', schedule, { passive: true });
    el.addEventListener('wheel', wheel, { passive: false });
    window.addEventListener('scroll', schedule, { passive: true });
    window.addEventListener('resize', schedule);
    measure();
    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      observer?.disconnect();
      el.removeEventListener('scroll', schedule);
      el.removeEventListener('wheel', wheel);
      window.removeEventListener('scroll', schedule);
      window.removeEventListener('resize', schedule);
    };
  }, [columnKey, children]);

  return <div className="crm-matrix" ref={root}>
    {(columns.length > 0 || filters) && <div className="crm-navigation" ref={toolbar}>
      {filters}
      <label>К отчёту{' '}
        <select aria-label="Перейти к отчёту" defaultValue="" onChange={event => {
          const el = viewport.current;
          const header = el?.querySelector<HTMLElement>(`thead [data-report-id="${event.target.value}"]`);
          const label = el?.querySelector<HTMLElement>('.crm-th-label');
          if (el && header) {
            el.scrollLeft = Math.max(0, header.offsetLeft - (label?.offsetWidth || 220));
            el.dispatchEvent(new Event('scroll'));
          }
          event.target.value = '';
        }}>
          <option value="" disabled>Выберите период…</option>
          {columns.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}
        </select>
      </label>
      <span className="crm-navigation-hint">Поля — прокрутка страницы · Отчёты — ползунок снизу или Shift + колесо</span>
    </div>}
    <div className="crm-table-scroll" ref={viewport} role="region" aria-label="Матрица отчётов" tabIndex={0}>{children}</div>
    <div className="crm-scroll-dock" ref={dock} role="group" aria-label="Навигация по столбцам" hidden>
      <button type="button" ref={previous} onClick={() => move(-1)} title="К более новым отчётам" aria-label="К более новым отчётам">←</button>
      <input ref={slider} type="range" min={0} max={0} defaultValue={0} step={1} aria-label="Прокрутка столбцов отчётов" onChange={event => {
        if (!viewport.current) return;
        viewport.current.scrollLeft = Number(event.target.value);
        viewport.current.dispatchEvent(new Event('scroll'));
      }} />
      <button type="button" ref={next} onClick={() => move(1)} title="К более старым отчётам" aria-label="К более старым отчётам">→</button>
      <output ref={position} className="crm-scroll-position" aria-label="Видимые столбцы" />
    </div>
  </div>;
}
