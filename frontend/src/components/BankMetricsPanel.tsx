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
  unit: 'pct' | 'mln' | 'pp' | 'x';
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
  { key: 'npl_ratio', label: 'Доля проблемных', unit: 'pct', meaning: 'Стадия 3 и POCI к портфелю' },
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

/**
 * Динамика биржи по годам. Здесь и посчитанные показатели, и сырые строки
 * отчёта: без комиссионных и процентных доходов в рублях не видно, почему
 * доля комиссий выросла — то ли комиссии прибавили, то ли проценты упали.
 * У МОЕХ за 2025 это ровно второе, и по одним процентам этого не понять.
 */
const EXCHANGE_HISTORY_ROWS: {
  key: keyof BankMetrics | 'fee_commission_income' | 'interest_income';
  label: string;
  unit: 'pct' | 'mln';
  /**
   * Куда «лучше» при росте. `null` — показатель описывает профиль бизнеса,
   * а не его качество: приток клиентских денег сам по себе ни хорош, ни плох.
   */
  higherIsBetter: boolean | null;
  /** Откуда взята величина — иначе расчёт ядра выглядит как магия. */
  tip: string;
  fromReport?: boolean;
}[] = [
  {
    key: 'fee_commission_income',
    higherIsBetter: true,
    label: 'Комиссионные доходы',
    unit: 'mln',
    fromReport: true,
    tip: 'ОПУ, «Комиссионные доходы». Плата за сделки, клиринг и депозитарий — то, что биржа зарабатывает своей инфраструктурой независимо от ставки.',
  },
  {
    key: 'interest_income',
    higherIsBetter: true,
    label: 'Процентные доходы',
    unit: 'mln',
    fromReport: true,
    tip: 'ОПУ, процентный и финансовый доход от размещения клиентских остатков. Зависит от ключевой ставки, а не от работы биржи.',
  },
  {
    key: 'fee_share',
    higherIsBetter: true,
    label: 'Доля комиссий',
    unit: 'pct',
    tip: 'Комиссионные доходы ÷ операционные доходы. Чем выше, тем меньше прибыль зависит от ставки.',
  },
  {
    key: 'opex_to_fees',
    higherIsBetter: false,
    label: 'Расходы к комиссиям',
    unit: 'pct',
    tip: 'Операционные расходы ÷ комиссионные доходы. Ниже 100% — инфраструктура окупается без процентных доходов.',
  },
  {
    key: 'client_funds',
    higherIsBetter: true,
    label: 'Средства клиентов',
    unit: 'mln',
    tip: 'Баланс: обязательства перед участниками торгов и депонентами. Чужие деньги, которые биржа держит у себя и размещает.',
  },
  {
    key: 'reported_fcf',
    higherIsBetter: null,
    label: 'FCF по отчёту',
    unit: 'mln',
    tip: 'Операционный поток минус CAPEX и погашение тела аренды — как считается у любой компании.',
  },
  {
    key: 'banking_flow',
    higherIsBetter: null,
    label: '− приток клиентских средств',
    unit: 'mln',
    tip: 'Сумма двух строк ОДДС: изменение обязательств перед участниками торгов и депонентами плюс изменение размещения этих денег, каждая со своим знаком. Деньги проходят баланс насквозь и попадают в операционный поток как приток, хотя вернуть их придётся по первому требованию.',
  },
  {
    key: 'core_fcf',
    higherIsBetter: true,
    label: 'FCF ядра',
    unit: 'mln',
    tip: 'FCF по отчёту минус приток клиентских средств. Только он сопоставим с дивидендами — по нему же считаются P/FCF и FCF/Прибыль.',
  },
];

/** Показатели сегмента в истории по годам — те же ключи, что и в карточках. */
const HISTORY_ROWS: {
  key: keyof BankMetrics;
  label: string;
  unit?: 'pct' | 'mln';
  higherIsBetter: boolean | null;
  tip: string;
}[] = [
  // Портфель первым: он знаменатель трёх строк ниже. Рост портфеля при
  // падающем покрытии объясняет ухудшение лучше, чем каждый коэффициент сам.
  {
    key: 'gross_loans',
    label: 'Портфель до резерва',
    unit: 'mln',
    higherIsBetter: null,
    tip: 'Кредиты клиентам по амортизированной стоимости до вычета резерва — знаменатель трёх строк ниже.',
  },
  {
    key: 'cost_of_risk',
    label: 'Стоимость риска',
    higherIsBetter: false,
    tip: 'Резервы под кредитные убытки ÷ портфель до резерва. Сколько портфеля банк списывает за год.',
  },
  {
    key: 'npl_ratio',
    label: 'Доля проблемных',
    higherIsBetter: false,
    tip: 'Обесцененные кредиты (Стадия 3 и POCI) ÷ портфель до резерва.',
  },
  {
    key: 'npl_coverage',
    label: 'Покрытие резервом',
    higherIsBetter: true,
    tip: 'Накопленный резерв ÷ обесцененные кредиты. Ниже 100% — часть потерь ещё не признана.',
  },
  {
    key: 'loans_to_deposits',
    label: 'Кредиты / депозиты',
    higherIsBetter: null,
    tip: 'Портфель ÷ средства клиентов. Выше 100% — банк занимает недостающее на рынке.',
  },
  {
    key: 'retail_loans_share',
    label: 'Розница в портфеле',
    higherIsBetter: null,
    tip: 'Кредиты физлицам ÷ портфель до резерва. Профиль риска: розница доходнее и рискованнее.',
  },
];

/**
 * Изменение год к году. У процентных показателей — в пунктах: рост доли
 * комиссий с 43% до 61% это +17,54 п.п., а не «+40%», иначе величина
 * выглядит вчетверо крупнее, чем она есть. У денежных — относительное,
 * но если прошлый год ушёл в минус, делить не на что: показываем разницу.
 */
function formatChange(
  current: number | null,
  previous: number | null,
  unit: 'pct' | 'mln',
): { text: string; direction: number; tip?: string } {
  if (current === null || current === undefined) return { text: '—', direction: 0 };
  if (previous === null || previous === undefined) return { text: '—', direction: 0 };
  const diff = current - previous;
  const direction = Math.sign(diff);
  const sign = diff > 0 ? '+' : '';
  if (unit === 'pct') {
    return { text: `${sign}${diff.toLocaleString('ru-RU', { maximumFractionDigits: 2 })} п.п.`, direction };
  }
  if (previous <= 0) {
    // Делить на отрицательное нельзя: рост с −79 до +535 млрд дал бы «−776%»,
    // то есть падение там, где величина выросла. Показываем саму разницу.
    return {
      text: `${sign}${formatMln(diff)}`,
      direction,
      tip: `Год назад величина была отрицательной (${formatMln(previous)}), относительное изменение от неё считать нельзя — показана разница в рублях.`,
    };
  }
  const pct = (diff / previous) * 100;
  return { text: `${sign}${pct.toLocaleString('ru-RU', { maximumFractionDigits: 1 })}%`, direction };
}

/** Цвет изменения: направление × «куда лучше». Профильные строки не красим. */
function changeLevel(direction: number, higherIsBetter: boolean | null): 'good' | 'bad' | 'na' {
  if (higherIsBetter === null || direction === 0) return 'na';
  return direction > 0 === higherIsBetter ? 'good' : 'bad';
}

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

function fmtValue(value: number | null, unit: 'pct' | 'mln' | 'pp' | 'x'): string {
  if (value === null || value === undefined) return '—';
  if (unit === 'mln') return formatMln(value);
  if (unit === 'x') return `${value.toLocaleString('ru-RU', { maximumFractionDigits: 2 })}×`;
  const num = value.toLocaleString('ru-RU', { maximumFractionDigits: 2 });
  // Спред показываем со знаком: минус — привлекает дешевле ключевой ставки.
  if (unit === 'pp') return `${value > 0 ? '+' : ''}${num} п.п.`;
  return `${num}%`;
}

const BankMetricsPanel: React.FC<Props> = ({ companyId, reports, companyType }) => {
  // У биржи и гибрида одинаково считается поток без клиентских денег, но
  // кредитных показателей у биржи нет вовсе: она не выдаёт займы. Шесть
  // пустых карточек — не «нет данных», а «показателя не существует», и
  // рисовать их нельзя.
  const isExchange = companyType === 'exchange';
  const isHybrid = companyType === 'hybrid' || isExchange;
  // Свежий отчёт отвечает «как идёт сейчас», последний полный год — «чем
  // кончилось». Ответы расходятся, поэтому выбор оставлен пользователю.
  const { latest, lastFullYear } = pickBankPeriods(reports);
  const [showFullYear, setShowFullYear] = useState(false);
  // Значения отвечают «сколько», изменения — «куда движется». Светофорить
  // сами величины нечем: у комиссий и клиентских остатков нет порога, хорош
  // или плох только их сдвиг, поэтому вердикт живёт в режиме изменений.
  const [showChange, setShowChange] = useState(false);

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
        <h2>
          {isExchange
            ? 'Показатели биржи'
            : isHybrid
              ? 'Показатели финсегмента'
              : 'Банковские показатели'}
        </h2>
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

      {!isExchange && (
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
      )}

      {/* Свободный поток ядра и динамика сегмента — в два столбца. Место у
          них здесь, рядом с портфелем и депозитами: приток, который
          вычитается, складывается ровно из их движения. Раньше расчёт жил в
          карточке мультипликаторов, где связь с финсегментом была неочевидна. */}
      {isHybrid && (metrics.core_fcf != null || segmentHistory.length > 0) && (
        <div className={isExchange ? 'bank-exchange-bottom' : 'bank-bottom-grid'}>
      {isHybrid && !isExchange && metrics.core_fcf != null && (
        <div className="bank-core-flow">
          <div className="bank-core-flow-title">
            {isExchange ? 'Поток без клиентских денег' : 'Свободный поток без финсегмента'}
          </div>
          <div className="bank-core-flow-row">
            <span>FCF по отчёту</span>
            <b>{formatMln(metrics.reported_fcf ?? null)}</b>
          </div>
          <div className="bank-core-flow-row">
            <span>
              {isExchange
                ? '− приток клиентских средств'
                : '− приток от роста банковского баланса'}
            </span>
            <b>{formatMln(metrics.banking_flow ?? null)}</b>
          </div>
          <div className="bank-core-flow-row is-total">
            <span>FCF ядра</span>
            <b>{formatMln(metrics.core_fcf)}</b>
          </div>

          <p className="bank-panel-note">
            {isExchange
              ? 'Прирост обязательств перед участниками торгов и депонентами минус размещение этих денег. Средства клиентов проходят через баланс насквозь и в отчётный поток попадают как приток — но вернуть их придётся по первому требованию.'
              : 'Приток средств клиентов минус выдача кредитов. Эти деньги придётся вернуть.'}
            {' '}С дивидендами сопоставим только поток ядра — по нему же
            считаются P/FCF и FCF/Прибыль.
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
        <div
          className="bank-core-flow bank-segment-history"
        >
          <div className="bank-core-flow-title bank-history-title">
            <span>
              {isExchange ? 'Динамика по годам' : 'Финсегмент по годам'}
              {showChange && ' — изменение г/г'}
            </span>
            <button
              type="button"
              className="bank-history-toggle"
              onClick={() => setShowChange((v) => !v)}
              aria-label={showChange ? 'Показать значения' : 'Показать изменение год к году'}
              title="Переключить значения ↔ изменение год к году"
            >
              ⇄
            </button>
          </div>
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
                {(isExchange ? EXCHANGE_HISTORY_ROWS : HISTORY_ROWS).map((row) => {
                  // Сырые строки отчёта берём из самого отчёта: они не
                  // показатели, а исходные величины, из которых те считаются.
                  const fromReport = 'fromReport' in row && row.fromReport;
                  const unit = row.unit ?? 'pct';
                  const valueOf = (rep: FinancialReport): number | null =>
                    (fromReport
                      ? ((rep as unknown as Record<string, number | null>)[row.key as string] ?? null)
                      : (((rep.bank_metrics as BankMetrics | null)?.[
                          row.key as keyof BankMetrics
                        ] ?? null) as number | null)) as number | null;
                  return (
                  <tr key={String(row.key)}>
                    <td className="bank-history-label has-tip" title={row.tip}>
                      {row.label}
                    </td>
                    {segmentHistory.map((rep, i) => {
                      const value = valueOf(rep);
                      if (showChange) {
                        // Первому году сравнивать не с чем — он остаётся пустым.
                        const prev = i > 0 ? valueOf(segmentHistory[i - 1]) : null;
                        const { text, direction, tip } = formatChange(value, prev, unit);
                        const level = changeLevel(direction, row.higherIsBetter);
                        return (
                          <td
                            key={rep.id}
                            title={tip}
                            className={`bank-history-cell level-${level}${
                              text === '—' ? ' is-empty' : ''
                            }${tip ? ' has-tip' : ''}`}
                          >
                            {text}
                          </td>
                        );
                      }
                      const status = (
                        fromReport ? 'n/a' : (rep.bank_metrics as BankMetrics | null)
                          ?.statuses?.[row.key as string] ?? 'n/a'
                      ) as Status;
                      return (
                        <td
                          key={rep.id}
                          className={`bank-history-cell level-${levelClass(status)}${
                            value === null ? ' is-empty' : ''
                          }`}
                        >
                          {fmtValue(value, unit)}
                        </td>
                      );
                    })}
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
        </div>
      )}

      {isExchange && (
        <p className="bank-panel-note">
          Кредитных показателей у биржи нет: она не выдаёт займы, поэтому доля
          проблемных, стоимость риска и покрытие резервом к ней неприменимы.
          Плечо и текущая ликвидность тоже не считаются — обязательства состоят
          из чужих денег и зеркальных позиций центрального контрагента, у
          которых актив и обязательство совпадают до рубля. Чистый долг не
          выводится по той же причине: в наличности лежат средства клиентов.
        </p>
      )}

      {isHybrid && !isExchange && (
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
