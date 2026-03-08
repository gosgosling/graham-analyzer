import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from 'recharts';
import {
  getCompanyCurrentMultipliers,
  getCompanyMultipliersHistory,
  refreshCompanyMultipliers,
} from '../services/api';
import { MultiplierRecord, CurrentMultipliers, Company } from '../types';
import './MultipliersPanel.css';

// ─── Критерии Грэма для цветовой кодировки ───────────────────────────────────

type Level = 'good' | 'warn' | 'bad' | 'neutral';

function peLevel(v: number | null): Level {
  if (v === null) return 'neutral';
  if (v <= 15) return 'good';
  if (v <= 25) return 'warn';
  return 'bad';
}
function pbLevel(v: number | null): Level {
  if (v === null) return 'neutral';
  if (v <= 1.5) return 'good';
  if (v <= 3) return 'warn';
  return 'bad';
}
function roeLevel(v: number | null): Level {
  if (v === null) return 'neutral';
  if (v >= 15) return 'good';
  if (v >= 10) return 'warn';
  return 'bad';
}
function deLevel(v: number | null): Level {
  if (v === null) return 'neutral';
  if (v <= 0.5) return 'good';
  if (v <= 1) return 'warn';
  return 'bad';
}
function crLevel(v: number | null): Level {
  if (v === null) return 'neutral';
  if (v >= 2) return 'good';
  if (v >= 1.5) return 'warn';
  return 'bad';
}
function dyLevel(v: number | null): Level {
  if (v === null) return 'neutral';
  if (v >= 3) return 'good';
  if (v >= 1) return 'warn';
  return 'bad';
}

// ─── Вспомогательные компоненты ──────────────────────────────────────────────

function MetricBadge({
  value, level, suffix = '', nullHint,
}: {
  value: number | null;
  level: Level;
  suffix?: string;
  nullHint?: string;
}) {
  if (value === null) {
    return (
      <span
        className="mult-cell neutral null-hint"
        title={nullHint ?? 'Недостаточно данных'}
      >
        —
      </span>
    );
  }
  return (
    <span className={`mult-cell ${level}`}>
      {value.toFixed(2)}{suffix}
    </span>
  );
}

function fmt(n: number | null, decimals = 2): string {
  if (n === null) return '—';
  return n.toLocaleString('ru-RU', { maximumFractionDigits: decimals });
}

/**
 * Форматирует значение в миллионах ₽.
 * Если >= 1000 млн — показывает в млрд, иначе в млн.
 */
function fmtMln(n: number | null): string {
  if (n === null) return '—';
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return (n / 1_000_000).toFixed(2) + ' трлн ₽';
  if (abs >= 1_000)     return (n / 1_000).toFixed(2) + ' млрд ₽';
  return n.toLocaleString('ru-RU', { maximumFractionDigits: 1 }) + ' млн ₽';
}

function fmtDate(d: string): string {
  return d.split('-')[0];
}

// ─── Карточки текущих мультипликаторов ────────────────────────────────────────

interface CurrentCardsProps {
  data: CurrentMultipliers;
}

const CurrentCards: React.FC<CurrentCardsProps> = ({ data }) => {
  const cards = [
    {
      label: 'P/E',
      value: data.pe_ratio,
      level: peLevel(data.pe_ratio),
      hint: 'Цена / Прибыль',
      threshold: '≤ 15 — хорошо',
    },
    {
      label: 'P/B',
      value: data.pb_ratio,
      level: pbLevel(data.pb_ratio),
      hint: 'Цена / Балансовая стоимость',
      threshold: '≤ 1.5 — хорошо',
    },
    {
      label: 'ROE',
      value: data.roe,
      level: roeLevel(data.roe),
      hint: 'Рентабельность капитала',
      threshold: '≥ 15% — хорошо',
      suffix: '%',
    },
    {
      label: 'Долг/Капитал',
      value: data.debt_to_equity,
      level: deLevel(data.debt_to_equity),
      hint: 'Total Liabilities / Equity',
      threshold: '≤ 0.5 — хорошо',
    },
    {
      label: 'Current Ratio',
      value: data.current_ratio,
      level: crLevel(data.current_ratio),
      hint: 'Текущая ликвидность',
      threshold: '≥ 2 — хорошо',
    },
    {
      label: 'Div. Yield',
      value: data.dividend_yield,
      level: dyLevel(data.dividend_yield),
      hint: 'Дивидендная доходность',
      threshold: '≥ 3% — хорошо',
      suffix: '%',
    },
  ];

  return (
    <div className="current-cards-grid">
      {cards.map(({ label, value, level, hint, threshold, suffix = '' }) => (
        <div key={label} className={`current-card level-${level}`}>
          <div className="current-card-label">{label}</div>
          <div className="current-card-value">
            {value !== null ? `${fmt(value)}${suffix}` : '—'}
          </div>
          <div className="current-card-hint">{hint}</div>
          <div className={`current-card-threshold level-${level}`}>{threshold}</div>
        </div>
      ))}
    </div>
  );
};

// ─── Информационная строка с LTM-метаданными ─────────────────────────────────

const LtmMeta: React.FC<{ data: CurrentMultipliers }> = ({ data }) => {
  const sourceLabel: Record<string, string> = {
    quarterly_4: '4 квартала',
    annual: 'Годовой отчёт',
  };
  const src = data.ltm_source ? sourceLabel[data.ltm_source] ?? data.ltm_source : '—';

  return (
    <div className="ltm-meta-bar">
      <span className="ltm-meta-item">
        <span className="ltm-meta-icon">💰</span>
        <span className="ltm-meta-label">Текущая цена:</span>
        <span className="ltm-meta-value">
          {data.current_price !== null ? `${fmt(data.current_price)} ₽` : 'не задана'}
        </span>
      </span>
      <span className="ltm-meta-item">
        <span className="ltm-meta-icon">📊</span>
        <span className="ltm-meta-label">Капитализация:</span>
        <span className="ltm-meta-value">{fmtMln(data.market_cap)}</span>
      </span>
      <span className="ltm-meta-item">
        <span className="ltm-meta-icon">📈</span>
        <span className="ltm-meta-label">LTM источник:</span>
        <span className="ltm-meta-value">{src}</span>
      </span>
      <span className="ltm-meta-item">
        <span className="ltm-meta-icon">📅</span>
        <span className="ltm-meta-label">Баланс от:</span>
        <span className="ltm-meta-value">{data.balance_report_date ?? '—'}</span>
      </span>
    </div>
  );
};

// ─── Историческая таблица ─────────────────────────────────────────────────────

interface HistTableProps {
  rows: MultiplierRecord[];
  currentRow?: CurrentMultipliers;
}

const HistTable: React.FC<HistTableProps> = ({ rows, currentRow }) => {
  return (
    <div className="hist-table-wrapper">
      <table className="hist-table">
        <thead>
          <tr>
            <th className="col-year">Период</th>
            <th className="col-price">Цена, ₽</th>
            <th className="col-mkt">Кап., млрд ₽</th>
            <th className="col-mult">P/E</th>
            <th className="col-mult">P/B</th>
            <th className="col-mult">ROE, %</th>
            <th className="col-mult">D/E</th>
            <th className="col-mult">CR</th>
            <th className="col-mult">Div, %</th>
            <th className="col-rev">Выручка LTM</th>
            <th className="col-ni">Прибыль LTM</th>
          </tr>
        </thead>
        <tbody>
          {/* LTM-строка (актуальные данные) */}
          {currentRow && (
            <tr className="row-ltm">
              <td className="col-year">
                <span className="badge-ltm">LTM</span>
              </td>
              <td>{currentRow.price_used !== null ? fmt(currentRow.price_used) : '—'}</td>
              <td>{currentRow.market_cap !== null ? (currentRow.market_cap / 1_000).toFixed(2) : '—'}</td>
              <td><MetricBadge value={currentRow.pe_ratio} level={peLevel(currentRow.pe_ratio)} /></td>
              <td><MetricBadge value={currentRow.pb_ratio} level={pbLevel(currentRow.pb_ratio)} /></td>
              <td><MetricBadge value={currentRow.roe} level={roeLevel(currentRow.roe)} suffix="%" /></td>
              <td><MetricBadge value={currentRow.debt_to_equity} level={deLevel(currentRow.debt_to_equity)} /></td>
              <td><MetricBadge value={currentRow.current_ratio} level={crLevel(currentRow.current_ratio)} /></td>
              <td><MetricBadge value={currentRow.dividend_yield} level={dyLevel(currentRow.dividend_yield)} suffix="%" /></td>
              <td>{fmtMln(currentRow.ltm_revenue)}</td>
              <td>{fmtMln(currentRow.ltm_net_income)}</td>
            </tr>
          )}

          {/* Исторические строки */}
          {rows.map((r) => {
            const noPrice   = r.price_used === null || r.shares_used === null;
            const noIncome  = r.ltm_net_income === null;
            const noEquity  = r.equity === null;
            const noLiab    = r.total_liabilities === null;
            const noCurr    = r.current_assets === null || r.current_liabilities === null;
            const noDivs    = r.ltm_dividends_per_share === null;

            return (
              <tr key={r.id} className="row-hist">
                <td className="col-year">{fmtDate(r.date)}</td>
                <td>{r.price_used !== null ? fmt(r.price_used) : '—'}</td>
                <td>{r.market_cap !== null ? (r.market_cap / 1_000).toFixed(2) : '—'}</td>
                <td><MetricBadge value={r.pe_ratio} level={peLevel(r.pe_ratio)}
                  nullHint={noIncome ? 'Нет данных о чистой прибыли (net_income)' : noPrice ? 'Нет цены / акций' : undefined} /></td>
                <td><MetricBadge value={r.pb_ratio} level={pbLevel(r.pb_ratio)}
                  nullHint={noEquity ? 'Нет данных о капитале (equity)' : noPrice ? 'Нет цены / акций' : undefined} /></td>
                <td><MetricBadge value={r.roe} level={roeLevel(r.roe)} suffix="%"
                  nullHint={noIncome ? 'Нет данных о чистой прибыли (net_income)' : noEquity ? 'Нет данных о капитале (equity)' : undefined} /></td>
                <td><MetricBadge value={r.debt_to_equity} level={deLevel(r.debt_to_equity)}
                  nullHint={noLiab ? 'Нет данных об обязательствах (total_liabilities)' : noEquity ? 'Нет данных о капитале (equity)' : undefined} /></td>
                <td><MetricBadge value={r.current_ratio} level={crLevel(r.current_ratio)}
                  nullHint={noCurr ? 'Нет оборотных активов или краткосрочных обязательств' : undefined} /></td>
                <td><MetricBadge value={r.dividend_yield} level={dyLevel(r.dividend_yield)} suffix="%"
                  nullHint={noDivs ? 'Дивиденды не указаны' : noPrice ? 'Нет цены акции' : undefined} /></td>
                <td>{fmtMln(r.ltm_revenue)}</td>
                <td>{fmtMln(r.ltm_net_income)}</td>
              </tr>
            );
          })}

          {rows.length === 0 && !currentRow && (
            <tr>
              <td colSpan={11} className="table-empty">
                Нет данных. Добавьте годовые отчёты и нажмите «Обновить цену».
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
};

// ─── Графики мультипликаторов ─────────────────────────────────────────────────

interface ChartConfig {
  key: keyof MultiplierRecord;
  label: string;
  color: string;
  referenceLines?: { value: number; label: string; color: string }[];
  suffix?: string;
  domain?: [number | 'auto', number | 'auto'];
}

const CHARTS: ChartConfig[] = [
  {
    key: 'pe_ratio',
    label: 'P/E',
    color: '#6366f1',
    referenceLines: [
      { value: 15, label: 'Грэм 15', color: '#22c55e' },
      { value: 25, label: 'Грэм 25', color: '#ef4444' },
    ],
  },
  {
    key: 'pb_ratio',
    label: 'P/B',
    color: '#8b5cf6',
    referenceLines: [
      { value: 1.5, label: '1.5×', color: '#22c55e' },
      { value: 3, label: '3×', color: '#ef4444' },
    ],
  },
  {
    key: 'roe',
    label: 'ROE, %',
    color: '#10b981',
    suffix: '%',
    referenceLines: [
      { value: 15, label: '15%', color: '#22c55e' },
    ],
  },
  {
    key: 'debt_to_equity',
    label: 'Долг/Капитал',
    color: '#f59e0b',
    referenceLines: [
      { value: 0.5, label: '0.5', color: '#22c55e' },
      { value: 1, label: '1.0', color: '#ef4444' },
    ],
  },
  {
    key: 'current_ratio',
    label: 'Current Ratio',
    color: '#06b6d4',
    referenceLines: [
      { value: 2, label: '2.0', color: '#22c55e' },
    ],
  },
  {
    key: 'dividend_yield',
    label: 'Дивиденд. доходность, %',
    color: '#ec4899',
    suffix: '%',
    referenceLines: [
      { value: 3, label: '3%', color: '#22c55e' },
    ],
  },
];

interface MultipliersChartsProps {
  rows: MultiplierRecord[];
  currentRow?: CurrentMultipliers;
}

const MultipliersCharts: React.FC<MultipliersChartsProps> = ({ rows, currentRow }) => {
  // Разворачиваем хронологически + добавляем LTM точку
  const historical = [...rows].reverse();

  const chartData = [
    ...historical.map((r) => ({
      year: fmtDate(r.date),
      pe_ratio: r.pe_ratio,
      pb_ratio: r.pb_ratio,
      roe: r.roe,
      debt_to_equity: r.debt_to_equity,
      current_ratio: r.current_ratio,
      dividend_yield: r.dividend_yield,
      isLtm: false,
    })),
    ...(currentRow
      ? [{
          year: 'LTM',
          pe_ratio: currentRow.pe_ratio,
          pb_ratio: currentRow.pb_ratio,
          roe: currentRow.roe,
          debt_to_equity: currentRow.debt_to_equity,
          current_ratio: currentRow.current_ratio,
          dividend_yield: currentRow.dividend_yield,
          isLtm: true,
        }]
      : []),
  ];

  if (chartData.length === 0) {
    return (
      <div className="charts-empty">
        Недостаточно данных для построения графиков
      </div>
    );
  }

  return (
    <div className="charts-grid">
      {CHARTS.map(({ key, label, color, referenceLines, suffix }) => (
        <div key={String(key)} className="chart-card">
          <div className="chart-card-title">{label}</div>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis
                dataKey="year"
                tick={{ fontSize: 11, fill: '#64748b' }}
              />
              <YAxis
                tick={{ fontSize: 11, fill: '#64748b' }}
                tickFormatter={(v) => `${v}${suffix ?? ''}`}
                width={45}
              />
              <Tooltip
                formatter={(value: any) => [`${fmt(typeof value === 'number' ? value : null)}${suffix ?? ''}`, label]}
                labelStyle={{ color: '#1e293b', fontWeight: 600 }}
              />
              {referenceLines?.map((rl) => (
                <ReferenceLine
                  key={rl.value}
                  y={rl.value}
                  stroke={rl.color}
                  strokeDasharray="6 3"
                  label={{ value: rl.label, position: 'insideTopRight', fontSize: 10, fill: rl.color }}
                />
              ))}
              <Line
                type="monotone"
                dataKey={String(key)}
                stroke={color}
                strokeWidth={2}
                dot={(props: any) => {
                  const { cx, cy, payload } = props;
                  return payload.isLtm
                    ? <circle key="ltm" cx={cx} cy={cy} r={5} fill={color} stroke="#fff" strokeWidth={2} />
                    : <circle key={payload.year} cx={cx} cy={cy} r={3} fill={color} />;
                }}
                connectNulls
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      ))}
    </div>
  );
};

// ─── Главный компонент панели ─────────────────────────────────────────────────

type Tab = 'current' | 'table' | 'charts';

interface MultipliersPanelProps {
  company: Company;
}

const MultipliersPanel: React.FC<MultipliersPanelProps> = ({ company }) => {
  const [activeTab, setActiveTab] = useState<Tab>('current');
  const [refreshMsg, setRefreshMsg] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const companyId = company.id!;

  const { data: currentData, isLoading: currentLoading, error: currentError } = useQuery({
    queryKey: ['multipliers-current', companyId],
    queryFn: () => getCompanyCurrentMultipliers(companyId),
    retry: false,
  });

  const { data: histData, isLoading: histLoading } = useQuery({
    queryKey: ['multipliers-history', companyId, 'report_based'],
    queryFn: () => getCompanyMultipliersHistory(companyId, 'report_based', 20),
    retry: false,
  });

  const refreshMutation = useMutation({
    mutationFn: () => refreshCompanyMultipliers(companyId),
    onSuccess: (res) => {
      setRefreshMsg(
        res.success
          ? `✓ Цена обновлена: ${fmt(res.price)} ₽`
          : '⚠ Не удалось получить цену из T-Invest API',
      );
      queryClient.invalidateQueries({ queryKey: ['multipliers-current', companyId] });
      queryClient.invalidateQueries({ queryKey: ['multipliers-history', companyId] });
      setTimeout(() => setRefreshMsg(null), 4000);
    },
    onError: () => {
      setRefreshMsg('✗ Ошибка при обновлении цены');
      setTimeout(() => setRefreshMsg(null), 4000);
    },
  });

  const rows = histData ?? [];

  const tabs: { key: Tab; label: string }[] = [
    { key: 'current', label: 'Текущие' },
    { key: 'table', label: 'История' },
    { key: 'charts', label: 'Графики' },
  ];

  return (
    <div className="mult-panel">
      {/* Заголовок */}
      <div className="mult-panel-header">
        <h2 className="mult-panel-title">Мультипликаторы</h2>
        <div className="mult-panel-controls">
          {refreshMsg && <span className="refresh-msg">{refreshMsg}</span>}
          <button
            className="btn-refresh"
            onClick={() => refreshMutation.mutate()}
            disabled={refreshMutation.isPending}
          >
            {refreshMutation.isPending ? 'Обновляем...' : '↺ Обновить цену'}
          </button>
        </div>
      </div>

      {/* Легенда цветовой кодировки */}
      <div className="legend-bar">
        <span className="legend-item good">● Норма по Грэму</span>
        <span className="legend-item warn">● Внимание</span>
        <span className="legend-item bad">● Превышение</span>
        <span className="legend-item neutral">● Нет данных</span>
      </div>

      {/* Табы */}
      <div className="mult-tabs">
        {tabs.map((t) => (
          <button
            key={t.key}
            className={`mult-tab ${activeTab === t.key ? 'active' : ''}`}
            onClick={() => setActiveTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Контент */}
      <div className="mult-tab-content">
        {/* ── Текущие ── */}
        {activeTab === 'current' && (
          <>
            {currentLoading && <div className="mult-loading">Загрузка мультипликаторов...</div>}
            {currentError && (
              <div className="mult-error">
                Нет данных: убедитесь, что добавлены финансовые отчёты и задана текущая цена.
              </div>
            )}
            {currentData && (
              <>
                <LtmMeta data={currentData} />
                <CurrentCards data={currentData} />
                <div className="ltm-financials">
                  <h3 className="ltm-fin-title">Финансовые показатели LTM</h3>
                  <div className="ltm-fin-grid">
                    <div className="ltm-fin-item">
                      <span className="ltm-fin-label">Выручка</span>
                      <span className="ltm-fin-value">{fmtMln(currentData.ltm_revenue)}</span>
                    </div>
                    <div className="ltm-fin-item">
                      <span className="ltm-fin-label">Чистая прибыль</span>
                      <span className="ltm-fin-value">{fmtMln(currentData.ltm_net_income)}</span>
                    </div>
                    <div className="ltm-fin-item">
                      <span className="ltm-fin-label">Дивиденды на акцию</span>
                      <span className="ltm-fin-value">
                        {currentData.ltm_dividends_per_share !== null
                          ? `${fmt(currentData.ltm_dividends_per_share)} ₽`
                          : '—'}
                      </span>
                    </div>
                    <div className="ltm-fin-item">
                      <span className="ltm-fin-label">Кол-во акций</span>
                      <span className="ltm-fin-value">
                        {currentData.shares_used !== null
                          ? currentData.shares_used.toLocaleString('ru-RU')
                          : '—'}
                      </span>
                    </div>
                  </div>
                </div>
              </>
            )}
          </>
        )}

        {/* ── История ── */}
        {activeTab === 'table' && (
          <>
            {histLoading && <div className="mult-loading">Загрузка истории...</div>}
            {!histLoading && (
              <HistTable rows={rows} currentRow={currentData ?? undefined} />
            )}
          </>
        )}

        {/* ── Графики ── */}
        {activeTab === 'charts' && (
          <>
            {histLoading && <div className="mult-loading">Загрузка данных для графиков...</div>}
            {!histLoading && (
              <MultipliersCharts rows={rows} currentRow={currentData ?? undefined} />
            )}
          </>
        )}
      </div>
    </div>
  );
};

export default MultipliersPanel;
