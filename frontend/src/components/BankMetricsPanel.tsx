import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { BankMetrics, FinancialReport } from '../types';
import { getLtmBankMetrics } from '../services';
import { formatMln } from '../utils/format';
import { isFullYear, periodLabel, pickBankPeriods } from '../utils/bankPeriod';
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
  unit: 'pct' | 'mln' | 'pp';
  /** Что метрика говорит по существу — видно без наведения. */
  meaning: string;
  /**
   * Показатель, который выносится значком в угол карточки: сам по себе
   * бессмысленный, но осмысленный в сравнении. Значок несёт цвет и порог.
   */
  badgeKey?: keyof BankMetrics;
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
  {
    key: 'cost_of_funding',
    label: 'Стоимость фондирования',
    unit: 'pct',
    meaning: 'Процентные расходы к средствам клиентов',
    // Само значение без ставки ничего не значит, поэтому оценку несёт
    // угловой значок — спред к ключевой ставке того же периода.
    badgeKey: 'funding_spread',
  },
  { key: 'retail_loans_share', label: 'Розница в портфеле', unit: 'pct', meaning: 'Профиль риска: розница доходнее и рискованнее' },
  { key: 'retail_deposits_share', label: 'Физлица в депозитах', unit: 'pct', meaning: 'Доля липкого и дешёвого фондирования' },
];

/**
 * Что показываем гибриду. Остальное — ROA, маржа, фондирование, достаточность
 * капитала — считается от групповых знаменателей: «прибыль всего Яндекса ÷
 * активы всего Яндекса» ничего не говорит о его банке. Бэкенд эти поля
 * обнуляет, здесь мы не рисуем и сами карточки.
 */
const HYBRID_METRIC_KEYS = new Set<keyof BankMetrics>([
  'cost_of_risk',
  'npl_ratio',
  'npl_coverage',
  'loans_to_deposits',
  'retail_loans_share',
  'retail_deposits_share',
]);

/** Показатели сегмента в истории по годам — те же ключи, что и в карточках. */
const HISTORY_ROWS: { key: keyof BankMetrics; label: string }[] = [
  { key: 'cost_of_risk', label: 'Стоимость риска' },
  { key: 'npl_ratio', label: 'Доля проблемных' },
  { key: 'npl_coverage', label: 'Покрытие резервом' },
  { key: 'loans_to_deposits', label: 'Кредиты / депозиты' },
  { key: 'retail_loans_share', label: 'Розница в портфеле' },
];

interface Props {
  companyId: number;
  reports: FinancialReport[];
  /** 'lender' — банк целиком, 'hybrid' — финсегмент внутри обычной компании */
  companyType?: string | null;
}

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

function fmtValue(value: number | null, unit: 'pct' | 'mln' | 'pp'): string {
  if (value === null || value === undefined) return '—';
  if (unit === 'mln') return formatMln(value);
  const num = value.toLocaleString('ru-RU', { maximumFractionDigits: 2 });
  // Спред показываем со знаком: минус — привлекает дешевле ключевой ставки.
  if (unit === 'pp') return `${value > 0 ? '+' : ''}${num} п.п.`;
  return `${num}%`;
}

const BankMetricsPanel: React.FC<Props> = ({ companyId, reports, companyType }) => {
  const isHybrid = companyType === 'hybrid';
  // Свежий отчёт отвечает «как идёт сейчас», последний полный год — «чем
  // кончилось». Ответы расходятся, поэтому выбор оставлен пользователю.
  const { latest, lastFullYear } = pickBankPeriods(reports);
  const [showFullYear, setShowFullYear] = useState(false);

  // Скользящий год: собирается из трёх отчётов на бэкенде, поэтому отдельным
  // запросом. Нужен только когда свежий отчёт неполный — у годового LTM
  // совпадает с самим отчётом.
  const { data: ltmMetrics } = useQuery({
    queryKey: ['bank-metrics-ltm', companyId],
    queryFn: () => getLtmBankMetrics(companyId),
    // У гибрида показатели сегмента существуют только в этом виде: в самих
    // отчётах их нет, потому что тип отчёта у него общий.
    enabled: isHybrid || (latest !== null && !isFullYear(latest)),
    retry: false,
  });

  const shown = showFullYear ? lastFullYear ?? latest : latest ?? lastFullYear;
  if (isHybrid && !ltmMetrics) return null;
  if (!isHybrid && !shown) return null;

  // У гибрида переключать нечего: показатели сегмента считаются только за
  // скользящий год, в самих отчётах их нет.
  const canSwitch =
    !isHybrid && latest !== null && lastFullYear !== null && latest !== lastFullYear;
  // За полный год показатели берутся из самого отчёта, за свежий неполный —
  // с бэкенда, который собирает потоки за скользящий год. Домножение полугодия
  // на два остаётся крайним случаем: оно допускает, что оставшиеся месяцы
  // будут как прошедшие.
  const useLtm = isHybrid || (shown === latest && !isFullYear(shown!) && !!ltmMetrics);
  const metrics = (useLtm ? ltmMetrics : shown!.bank_metrics) as BankMetrics;
  const visibleMetrics = isHybrid
    ? METRICS.filter((spec) => HYBRID_METRIC_KEYS.has(spec.key))
    : METRICS;
  const basis = useLtm ? metrics.flow_basis : undefined;
  const annualised = !isHybrid && !isFullYear(shown!) && (!useLtm || basis === 'annualised');
  // Payout живёт по годовому календарю и от выбранного периода не зависит.
  // Гибриду он здесь не нужен: панель про финсегмент, а дивиденды платит
  // компания целиком — их доля есть в блоке мультипликаторов.
  const payoutReport = isHybrid ? null : lastFullYear;
  // История сегмента: годовые отчёты, старые слева — так читается динамика.
  // Показатели у них считает бэкенд, здесь только раскладка.
  const segmentHistory = isHybrid
    ? reports
        .filter((r) => r.bank_metrics && isFullYear(r))
        .sort((a, b) => a.fiscal_year - b.fiscal_year)
    : [];

  return (
    <div className="bank-panel">
      <div className="bank-panel-header">
        <h2>{isHybrid ? 'Показатели финсегмента' : 'Банковские показатели'}</h2>
        {canSwitch && (
          <div className="bank-period-switch" role="group" aria-label="Период показателей">
            <button
              type="button"
              className={!showFullYear ? 'is-active' : undefined}
              onClick={() => setShowFullYear(false)}
              title={`Свежий отчёт: ${periodLabel(latest!)}`}
            >
              {periodLabel(latest!)}
            </button>
            <button
              type="button"
              className={showFullYear ? 'is-active' : undefined}
              onClick={() => setShowFullYear(true)}
              title={`Последний полный год: ${periodLabel(lastFullYear!)}`}
            >
              {periodLabel(lastFullYear!)}
            </button>
          </div>
        )}
        <span className="bank-panel-period">
          за {isHybrid ? 'последние 12 месяцев' : periodLabel(shown!)}
          {basis === 'ltm' && (
            <span
              className="bank-panel-flag"
              title="Прибыль, процентный доход, резервы и процентные расходы — за последние 12 месяцев: годовой отчёт плюс текущий период минус тот же период прошлого года. Балансовые величины — на отчётную дату."
            >
              потоки за 12 месяцев
            </span>
          )}
          {basis === 'prior_full_year' && (
            <span
              className="bank-panel-flag"
              title="Прошлогоднего отчёта за тот же период нет, поэтому потоки взяты за последний полный год — так же считаются P/E и ROE. Числа настоящие, но период закончился раньше отчётной даты, и отдача выходит заниженной."
            >
              потоки за прошлый год
            </span>
          )}
          {annualised && (
            <span
              className="bank-panel-flag"
              title="Прибыль, процентный доход, резервы и процентные расходы умножены на 12 / число месяцев периода: прошлогоднего отчёта за тот же период нет, и скользящий год собрать не из чего."
            >
              в годовом выражении
            </span>
          )}
          {metrics.net_loans != null && (
            <> · портфель {formatMln(metrics.net_loans)}</>
          )}
          {metrics.key_rate != null && (
            <> · ключевая ставка {fmtValue(metrics.key_rate, 'pct')}</>
          )}
        </span>
      </div>

      <div className="bank-metric-grid">
        {/* Payout всегда за последний полный год, каким бы период ни был
            выбран: дивиденд объявляют раз в год, и за полугодие карточка
            показала бы ноль при живой прибыли. Год подписан, если он не
            совпадает с выбранным периодом. */}
        {payoutReport?.dividend_payout != null && (
          <div
            className={`bank-metric-card level-${levelClass(payoutLevel(payoutReport.dividend_payout))}`}
            title={`Выплата за ${payoutReport.fiscal_year} год. ≤ 70% — с запасом; > 100% — платят не из прибыли`}
          >
            <div className="bank-metric-label">Payout</div>
            <div className="bank-metric-value">{fmtValue(payoutReport.dividend_payout, 'pct')}</div>
            <div className="bank-metric-meaning">Какая доля прибыли ушла на дивиденды</div>
            <div className="bank-metric-hint">
              {payoutReport !== shown && `за ${payoutReport.fiscal_year} год · `}
              ≤ 70% — с запасом; &gt; 100% — не из прибыли
            </div>
          </div>
        )}
        {visibleMetrics.map((spec) => {
          const value = metrics[spec.key] as number | null;
          const status = (metrics.statuses?.[spec.key as string] ?? 'n/a') as Status;
          const hint = metrics.hints?.[spec.key as string];
          const badgeValue = spec.badgeKey ? (metrics[spec.badgeKey] as number | null) : null;
          const badgeStatus = spec.badgeKey
            ? ((metrics.statuses?.[spec.badgeKey as string] ?? 'n/a') as Status)
            : null;
          const badgeHint = spec.badgeKey ? metrics.hints?.[spec.badgeKey as string] : undefined;

          return (
            <div key={String(spec.key)} className={`bank-metric-card level-${levelClass(status)}`} title={hint}>
              {badgeValue !== null && badgeStatus && (
                <span
                  className={`bank-metric-badge level-${levelClass(badgeStatus)}`}
                  title={`Спред к ключевой ставке. ${badgeHint ?? ''}`}
                >
                  {fmtValue(badgeValue, 'pp')}
                </span>
              )}
              <div className="bank-metric-label">{spec.label}</div>
              <div className="bank-metric-value">{fmtValue(value, spec.unit)}</div>
              <div className="bank-metric-meaning">{spec.meaning}</div>
              {hint ? (
                <div className="bank-metric-hint">{hint}</div>
              ) : badgeValue !== null ? (
                // Оценку несёт значок в углу — пометка «справочно» была бы неправдой.
                <div className="bank-metric-hint">
                  Оценивается спредом к ключевой ставке — значок в углу
                </div>
              ) : (
                // Порога нет по существу: доля розницы — профиль банка, а
                // стоимость фондирования без ключевой ставки ни о чём не
                // говорит. Без пометки это читается как «нет данных».
                <span className="bank-metric-note" title="Показатель без порога: смысл зависит от профиля банка и фазы ставочного цикла">
                  справочно
                </span>
              )}
            </div>
          );
        })}
      </div>

      {/* Свободный поток ядра и динамика сегмента — в два столбца. Место у
          них здесь, рядом с портфелем и депозитами: приток, который
          вычитается, складывается ровно из их движения. Раньше расчёт жил в
          карточке мультипликаторов, где связь с финсегментом была неочевидна. */}
      {isHybrid && (metrics.core_fcf != null || segmentHistory.length > 0) && (
        <div className="bank-bottom-grid">
      {isHybrid && metrics.core_fcf != null && (
        <div className="bank-core-flow">
          <div className="bank-core-flow-title">Свободный поток без финсегмента</div>
          <div className="bank-core-flow-row">
            <span>FCF по отчёту</span>
            <b>{formatMln(metrics.reported_fcf ?? null)}</b>
          </div>
          <div className="bank-core-flow-row">
            <span>− приток от роста банковского баланса</span>
            <b>{formatMln(metrics.banking_flow ?? null)}</b>
          </div>
          <div className="bank-core-flow-row is-total">
            <span>FCF ядра</span>
            <b>{formatMln(metrics.core_fcf)}</b>
          </div>
          <p className="bank-panel-note">
            Приток средств клиентов минус выдача кредитов. Эти деньги придётся
            вернуть: с дивидендами и с долгом сопоставим только поток ядра —
            по нему же считаются P/FCF, ND/FCF и FCF/Прибыль.
            {metrics.banking_flow_basis === 'balance_delta' && (
              <>
                {' '}Посчитано по приростам остатков — приблизительно: в них попадают
                секьюритизация и списания, не проходящие через денежный поток.
                Выпишите строки ОДДС, чтобы получить точную цифру.
              </>
            )}
          </p>
        </div>
      )}

      {metrics.capital_to_rwa != null && metrics.capital_adequacy_ratio != null && (
        <p className="bank-panel-note">
          Сверка ввода: капитал ÷ RWA = {fmtValue(metrics.capital_to_rwa, 'pct')}, эмитент раскрыл{' '}
          {fmtValue(metrics.capital_adequacy_ratio, 'pct')}. Расхождение нормально — Н1.0 считается
          по методике ЦБ, а не по МСФО-капиталу.
        </p>
      )}

      {(annualised || basis === 'prior_full_year') && (
        <p className="bank-panel-note">
          Скользящий год собрать не из чего:{' '}
          {annualised
            ? 'потоки домножены до года, то есть предполагается, что оставшиеся месяцы будут такими же'
            : 'взяты потоки за последний полный год, хотя баланс — на отчётную дату, и отдача выходит заниженной'}
          . Внесите отчёт за{' '}
          {periodLabel(shown!).replace(String(shown!.fiscal_year), String(shown!.fiscal_year - 1))} — и
          показатели пересчитаются по фактическим двенадцати месяцам.
        </p>
      )}

      {segmentHistory.length > 0 && (
        <div className="bank-core-flow bank-segment-history">
          <div className="bank-core-flow-title">Финсегмент по годам</div>
          <div className="bank-history-scroll">
            <table className="bank-history-table">
              <thead>
                <tr>
                  <th>Показатель</th>
                  {segmentHistory.map((r) => (
                    <th key={r.id}>{r.fiscal_year}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {HISTORY_ROWS.map((row) => (
                  <tr key={String(row.key)}>
                    <td className="bank-history-label">{row.label}</td>
                    {segmentHistory.map((rep) => {
                      const m = rep.bank_metrics as BankMetrics | null;
                      const value = (m?.[row.key] ?? null) as number | null;
                      const status = (m?.statuses?.[row.key as string] ?? 'n/a') as Status;
                      return (
                        <td
                          key={rep.id}
                          className={`bank-history-cell level-${levelClass(status)}`}
                        >
                          {fmtValue(value, 'pct')}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
        </div>
      )}

      {isHybrid && (
        <p className="bank-panel-note">
          Показатели считаются по портфелю и депозитам финансового сегмента, а не
          по всей компании. ROA, процентная маржа и достаточность капитала здесь
          не выводятся: их знаменатели — активы и капитал группы целиком, вместе с
          основным бизнесом, а нормативы ЦБ раскрывает только сам банк.
        </p>
      )}

      {!isHybrid && (
      <p className="bank-panel-note">
        Прибыль банка управляется резервами: в хороший год их распускают, в плохой
        доначисляют. Поэтому одиночный год говорит мало — стоимость риска, NPL,
        покрытие, LDR и Н1.1 по годам стоят в таблице истории выше, рядом с P/E и ROE.
      </p>
      )}

    </div>
  );
};

export default BankMetricsPanel;
