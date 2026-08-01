import React from 'react';
import type { BankMetrics, FinancialReport } from '../types';
import { formatMln } from '../utils/format';
import './BankMetricsPanel.css';

/**
 * Банковский блок карточки компании.
 *
 * Классические мультипликаторы отвечают, сколько банк стоит и сколько
 * зарабатывает. Здесь — вторая половина: во что обходится риск, чем банк
 * фондируется и сколько у него запаса по капиталу. Банк умирает не от дорогой
 * оценки, а от собственных кредитов.
 *
 * Значения и светофор приходят с бэкенда (`bank_metrics.py`): пороги живут в
 * одном месте, иначе одна метрика покрасится по-разному в карточке и в таблице.
 */

type Status = 'good' | 'normal' | 'bad' | 'n/a';

interface MetricSpec {
  key: keyof BankMetrics;
  label: string;
  /** Единица: проценты или миллионы валюты отчёта. */
  unit: 'pct' | 'mln';
  /** Что метрика говорит по существу — видно без наведения. */
  meaning: string;
}

const METRICS: MetricSpec[] = [
  { key: 'cost_of_risk', label: 'Стоимость риска', unit: 'pct', meaning: 'Сколько портфеля банк списывает за год' },
  { key: 'npl_ratio', label: 'Доля проблемных', unit: 'pct', meaning: 'Обесцененные кредиты к портфелю' },
  { key: 'npl_coverage', label: 'Покрытие резервом', unit: 'pct', meaning: 'Резерв к обесцененным кредитам' },
  { key: 'capital_adequacy_core', label: 'Основной капитал Н1.1', unit: 'pct', meaning: 'Ядро, которое поглощает убытки первым' },
  { key: 'capital_adequacy_ratio', label: 'Достаточность общая Н1.0', unit: 'pct', meaning: 'Включает суборды — списываются не сразу' },
  { key: 'roa', label: 'ROA', unit: 'pct', meaning: 'Отдача активов — её не поднять плечом' },
  { key: 'net_interest_margin', label: 'Процентная маржа', unit: 'pct', meaning: 'ЧПД к активам' },
  { key: 'loans_to_deposits', label: 'Кредиты / депозиты', unit: 'pct', meaning: 'Выше 100% — банк занимает на рынке' },
  { key: 'cost_of_funding', label: 'Стоимость фондирования', unit: 'pct', meaning: 'Процентные расходы к средствам клиентов' },
  { key: 'retail_loans_share', label: 'Розница в портфеле', unit: 'pct', meaning: 'Профиль риска: розница доходнее и рискованнее' },
  { key: 'retail_deposits_share', label: 'Физлица в депозитах', unit: 'pct', meaning: 'Доля липкого и дешёвого фондирования' },
];

/**
 * Статус бэкенда → CSS-класс панели.
 *
 * Имена не совпадают намеренно: в `n/a` слеш, и `level-n/a` невалиден как
 * селектор, а «нормально» во всём интерфейсе называется warn.
 */
function levelClass(status: Status): 'good' | 'warn' | 'bad' | 'na' {
  if (status === 'good') return 'good';
  if (status === 'normal') return 'warn';
  if (status === 'bad') return 'bad';
  return 'na';
}

/** Пороги payout повторяют backend/app/services/analysis/payout.py. */
function payoutLevel(value: number): Status {
  if (value <= 70) return 'good';
  return value <= 100 ? 'normal' : 'bad';
}

function fmtValue(value: number | null, unit: 'pct' | 'mln'): string {
  if (value === null || value === undefined) return '—';
  if (unit === 'mln') return formatMln(value);
  return `${value.toLocaleString('ru-RU', { maximumFractionDigits: 2 })}%`;
}

const BankMetricsPanel: React.FC<{ reports: FinancialReport[] }> = ({ reports }) => {
  // Годовые отчёты, свежие сверху: банк оценивают по динамике, а не по точке.
  const annual = reports
    .filter((r) => String(r.period_type).toLowerCase() === 'annual' && r.bank_metrics)
    .sort((a, b) => b.fiscal_year - a.fiscal_year);

  if (annual.length === 0) return null;

  const latest = annual[0];
  const metrics = latest.bank_metrics as BankMetrics;

  return (
    <div className="bank-panel">
      <div className="bank-panel-header">
        <h2>Банковские показатели</h2>
        <span className="bank-panel-period">
          за {latest.fiscal_year} год
          {latest.gross_loans != null && (
            <> · портфель {formatMln(metrics.net_loans ?? latest.gross_loans)}</>
          )}
        </span>
      </div>

      <div className="bank-metric-grid">
        {latest.dividend_payout != null && (
          <div
            className={`bank-metric-card level-${levelClass(payoutLevel(latest.dividend_payout))}`}
            title="≤ 70% — выплата с запасом; > 100% — платят не из прибыли"
          >
            <div className="bank-metric-label">Payout</div>
            <div className="bank-metric-value">{fmtValue(latest.dividend_payout, 'pct')}</div>
            <div className="bank-metric-meaning">Какая доля прибыли ушла на дивиденды</div>
            <div className="bank-metric-hint">≤ 70% — с запасом; &gt; 100% — не из прибыли</div>
          </div>
        )}
        {METRICS.map((spec) => {
          const value = metrics[spec.key] as number | null;
          const status = (metrics.statuses?.[spec.key as string] ?? 'n/a') as Status;
          const hint = metrics.hints?.[spec.key as string];
          return (
            <div key={String(spec.key)} className={`bank-metric-card level-${levelClass(status)}`} title={hint}>
              <div className="bank-metric-label">{spec.label}</div>
              <div className="bank-metric-value">{fmtValue(value, spec.unit)}</div>
              <div className="bank-metric-meaning">{spec.meaning}</div>
              {hint && <div className="bank-metric-hint">{hint}</div>}
            </div>
          );
        })}
      </div>

      {metrics.capital_to_rwa != null && metrics.capital_adequacy_ratio != null && (
        <p className="bank-panel-note">
          Сверка ввода: капитал ÷ RWA = {fmtValue(metrics.capital_to_rwa, 'pct')}, эмитент раскрыл{' '}
          {fmtValue(metrics.capital_adequacy_ratio, 'pct')}. Расхождение нормально — Н1.0 считается
          по методике ЦБ, а не по МСФО-капиталу.
        </p>
      )}

      <p className="bank-panel-note">
        Прибыль банка управляется резервами: в хороший год их распускают, в плохой
        доначисляют. Поэтому одиночный год говорит мало — стоимость риска, NPL,
        покрытие, LDR и Н1.1 по годам стоят в таблице истории выше, рядом с P/E и ROE.
      </p>

    </div>
  );
};

export default BankMetricsPanel;
