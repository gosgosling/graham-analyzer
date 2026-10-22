import React, { useState } from 'react';
import './PeriodChipList.css';

/**
 * Таблица «показатели × колонки» для телефона: колонка выбирается кнопкой,
 * показатели — списком, по нажатию на строку — значения во всех колонках.
 *
 * Колонки — периоды («По годам», «Отчётность», «Рынок») или компании
 * («Сравнение»). Широкая таблица на экране в 375 пикселей читалась по одной
 * колонке за раз и прокруткой вбок, при этом подпись строки уезжала за край;
 * здесь строка целиком на экране и читается сверху вниз.
 */

export interface ChipColumn {
  key: string;
  /** Подпись на кнопке и в истории строки. */
  label: React.ReactNode;
}

export interface ChipCell {
  node: React.ReactNode;
  className?: string;
}

export interface ChipRow {
  key: string;
  label: React.ReactNode;
  tip?: string;
  /** Подстрока — с отступом, как в таблице. */
  sub?: boolean;
  cell: (column: ChipColumn) => ChipCell | null | undefined;
}

export interface ChipGroup {
  key: string;
  title?: React.ReactNode;
  rows: ChipRow[];
}

interface Props {
  /** В порядке кнопок; первая выбрана сразу. */
  columns: ChipColumn[];
  groups: ChipGroup[];
  /**
   * С чем сравнивать под значением. По умолчанию — со следующей колонкой
   * (у периодов это прошлый год). Ключ колонки — сравнение с ней всегда
   * (у «Сравнения» — с компанией, ради которой открыли страницу).
   */
  compareWith?: 'next' | string;
  ariaLabel?: string;
  className?: string;
}

export default function PeriodChipList({ columns, groups, compareWith = 'next', ariaLabel = 'Период', className }: Props) {
  const [selected, setSelected] = useState<string | undefined>(columns[0]?.key);
  const [open, setOpen] = useState<string | null>(null);
  const index = Math.max(0, columns.findIndex((c) => c.key === selected));
  const current = columns[index];
  const other = compareWith === 'next'
    ? columns[index + 1]
    : columns.find((c) => c.key === compareWith && c.key !== current?.key);
  if (!current) return null;

  const show = (cell: ChipCell | null | undefined) => (cell?.node ?? '—');

  return (
    <div className={['hl', className].filter(Boolean).join(' ')}>
      <div className="hl-periods" role="group" aria-label={ariaLabel}>
        {columns.map((c) => (
          <button key={c.key} type="button" className={`hl-chip${c.key === current.key ? ' is-on' : ''}`}
            aria-pressed={c.key === current.key} onClick={() => setSelected(c.key)}>
            {c.label}
          </button>
        ))}
      </div>
      {groups.map((g) => (
        <section key={g.key} className="hl-group">
          {g.title && <h4 className="hl-kicker">{g.title}</h4>}
          <ul className="hl-list">
            {g.rows.map((r) => {
              const isOpen = open === `${g.key}/${r.key}`;
              const cell = r.cell(current);
              return (
                <li key={r.key} className={`hl-item${isOpen ? ' is-open' : ''}${r.sub ? ' hl-item--sub' : ''}`}>
                  <button type="button" className="hl-row" aria-expanded={isOpen}
                    onClick={() => setOpen(isOpen ? null : `${g.key}/${r.key}`)}>
                    <span className="hl-name" title={r.tip}>{r.label}</span>
                    <span className="hl-values">
                      <span className={['hl-value', cell?.className].filter(Boolean).join(' ')}>{show(cell)}</span>
                      {other && (
                        <small className="hl-prev">{other.label}: {show(r.cell(other))}</small>
                      )}
                    </span>
                  </button>
                  {isOpen && (
                    <dl className="hl-history">
                      {columns.map((c) => {
                        const v = r.cell(c);
                        return (
                          <div key={c.key} className={c.key === current.key ? 'is-current' : undefined}>
                            <dt>{c.label}</dt>
                            <dd className={v?.className}>{show(v)}</dd>
                          </div>
                        );
                      })}
                    </dl>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}
