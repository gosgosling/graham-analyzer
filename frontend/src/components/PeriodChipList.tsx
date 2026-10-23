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
  /** Число для графика в истории строки; без него история — списком. */
  value?: number | null;
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
  /** История строки графиком (по умолчанию). false — только списком. */
  chart?: boolean;
}

/** Подпись на оси: у периодов «2025» → «’25», чтобы двадцать лет помещались. */
const shortLabel = (label: React.ReactNode): React.ReactNode =>
  (typeof label === 'string' && /^\d{4}$/.test(label) ? `’${label.slice(2)}` : label);

/**
 * Какие столбики подписать. Сначала — выбранный, последний и первый;
 * остальные — примерно через равный шаг, но только если подпись не налезет
 * на уже поставленные. Ширина подписи считается по числу знаков: «12 мес.»
 * вдвое шире «’25», и при равном шаге они ложились друг на друга.
 */
function labelled(labels: string[], current: number, width = 320): Set<number> {
  const n = labels.length;
  const slot = width / Math.max(n, 1);
  // Крайние подписи прижаты к краю поля (см. CSS) и всей шириной уходят
  // внутрь — считаем их вдвое «шире» с этой стороны.
  const half = (i: number) => (labels[i].length * 6 + 4) / (i === 0 || i === n - 1 ? 1 : 2);
  const chosen = new Set<number>();
  const add = (i: number) => {
    if (i < 0 || i >= n || chosen.has(i)) return;
    if (Array.from(chosen).every((j) => Math.abs(i - j) * slot >= half(i) + half(j))) chosen.add(i);
  };
  add(current);
  add(n - 1);
  add(0);
  const every = Math.max(1, Math.ceil(n / 6));
  for (let i = n - 1 - every; i > 0; i -= every) add(i);
  return chosen;
}

/**
 * История строки по нажатию: столбики, если значения числовые, иначе список.
 *
 * Столбики — по времени слева направо, выбранная колонка подсвечена;
 * нажатие на столбик показывает его значение под графиком тем же видом, что
 * в списке (с пометками и цветом). Полный список значений — по кнопке.
 */
function History({ columns, row, current, chart }: {
  columns: ChipColumn[];
  row: ChipRow;
  current: string;
  chart: boolean;
}) {
  const [picked, setPicked] = useState(current);
  const [listed, setListed] = useState(false);
  // Колонки идут свежими первыми — на графике время слева направо.
  const points = columns.map((c) => ({ column: c, cell: row.cell(c) })).reverse();
  const numeric = points.filter((p) => typeof p.cell?.value === 'number');
  const pickedPoint = points.find((p) => p.column.key === picked) ?? points[points.length - 1];

  const list = (
    <dl className="hl-history-list">
      {[...points].reverse().map(({ column, cell }) => (
        <div key={column.key} className={column.key === current ? 'is-current' : undefined}>
          <dt>{column.label}</dt>
          <dd className={cell?.className}>{cell?.node ?? '—'}</dd>
        </div>
      ))}
    </dl>
  );

  if (!chart || numeric.length < 2) return <div className="hl-history">{list}</div>;

  const values = numeric.map((p) => p.cell!.value as number);
  const maxPos = Math.max(0, ...values);
  const maxNeg = Math.max(0, ...values.map((v) => -v));
  const span = maxPos + maxNeg || 1;
  // Область столбиков — 80 пикселей; линия нуля — на доле положительной части.
  const AREA = 80;
  const zero = (maxPos / span) * AREA;
  // Подписи оси — не у каждого года: на двадцати столбиках они слиплись бы.
  const shown = labelled(
    points.map((p) => {
      const l = shortLabel(p.column.label);
      return typeof l === 'string' ? l : '';
    }),
    points.findIndex((p) => p.column.key === current),
  );

  return (
    <div className="hl-history">
      <div className="hl-bars" role="group" aria-label="Значения по периодам">
        <span className="hl-zero" style={{ top: zero }} aria-hidden />
        {points.map((p, i) => {
          const v = p.cell?.value;
          const has = typeof v === 'number';
          const h = has ? Math.max(2, (Math.abs(v as number) / span) * AREA) : 0;
          const neg = has && (v as number) < 0;
          const cls = ['hl-bar', neg ? 'is-neg' : '', p.column.key === current ? 'is-current' : '',
            p.column.key === pickedPoint?.column.key ? 'is-picked' : '', has ? '' : 'is-empty'].filter(Boolean).join(' ');
          return (
            <button key={p.column.key} type="button" className={cls} onClick={() => setPicked(p.column.key)}
              aria-label={typeof p.column.label === 'string' ? p.column.label : undefined}>
              <span className="hl-bar-fill" style={neg ? { top: zero, height: h } : { top: zero - h, height: h }} />
              <span className="hl-bar-label">
                {shown.has(i) ? shortLabel(p.column.label) : ''}
              </span>
            </button>
          );
        })}
      </div>
      {pickedPoint && (
        <p className="hl-readout">
          <span>{pickedPoint.column.label}</span>
          <b className={pickedPoint.cell?.className}>{pickedPoint.cell?.node ?? '—'}</b>
        </p>
      )}
      <button type="button" className="hl-all" onClick={() => setListed((v) => !v)} aria-expanded={listed}>
        {listed ? 'Скрыть значения' : 'Все значения списком'}
      </button>
      {listed && list}
    </div>
  );
}

export default function PeriodChipList({ columns, groups, compareWith = 'next', ariaLabel = 'Период', className, chart = true }: Props) {
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
                    <span className="hl-name">
                      {r.label}{r.tip && <i className="hl-more" aria-hidden>?</i>}
                    </span>
                    <span className="hl-values">
                      <span className={['hl-value', cell?.className].filter(Boolean).join(' ')}>{show(cell)}</span>
                      {other && (
                        <small className="hl-prev">{other.label}: {show(r.cell(other))}</small>
                      )}
                    </span>
                  </button>
                  {/* Пояснение — здесь же, в раскрытой строке, как в «Критериях»:
                      панель снизу экрана закрывала то, к чему относилась. */}
                  {isOpen && r.tip && <p className="hl-note">{r.tip}</p>}
                  {isOpen && <History columns={columns} row={r} current={current.key} chart={chart} />}
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}
