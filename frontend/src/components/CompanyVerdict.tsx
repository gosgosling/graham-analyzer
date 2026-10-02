import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchPassport, type PassportOut, type ScreenStatus, type Verdict } from '../services/screen.api';
import {
  fetchValuationSummary,
  type SafetySignal,
  type ValuationSummaryOut,
} from '../services/valuation.api';
import { formatPerShare } from '../utils/perShare';
import './CompanyVerdict.css';

/**
 * Вердикт карточки: фраза в шапке и карточки справа от графика.
 *
 * Грэм в гл. 14 рассуждает в два хода: сперва — можно ли вообще брать эту
 * компанию, потом — дёшево ли сейчас. Поэтому и здесь две половины, «Качество»
 * и «Цена и стоимость», а над ними одна фраза, которая сводит их вместе.
 *
 * Фраза нужна потому, что половины часто спорят. У ЛУКОЙЛа все семь критериев
 * пройдены, в том числе книжные пороги цены, а оценка говорит «выше стоимости».
 * Обе правы: пороги из книги откалиброваны при доходности облигаций 4–5%, а
 * оценка учитывает сегодняшние 16%. Без фразы читатель видит два вердикта и
 * не знает, какому верить.
 */

type AxisState = ScreenStatus;

const ru = (value: number, digits = 0) =>
  value.toLocaleString('ru-RU', { minimumFractionDigits: digits, maximumFractionDigits: digits })
    .replace('-', '−');

/** Ставка: круглая — без дробей, живая (16,44) — с сотыми. */
const rate = (value: number) => ru(value, Number.isInteger(value) ? 0 : 2);

/** Рубли на акцию: у дорогой бумаги копейки — шум, у копеечной — вся цена. */
const rub = (value: number | null | undefined) =>
  value === null || value === undefined
    ? '—'
    : `${Math.abs(value) >= 100 ? ru(value) : formatPerShare(value)} ₽`;

const pct = (share: number) => `${share >= 0 ? '+' : '−'}${ru(Math.abs(share) * 100)}%`;

/** Порог из API печатается с точкой: «≤ 1.2». На экране — запятая. */
const decimalComma = (text: string) => text.replace(/(\d)\.(\d)/g, '$1,$2');

/**
 * Причина из API — фраза для строки внутри текста: со строчной буквы и с
 * точкой в числах. Здесь она стоит отдельным предложением.
 */
const sentence = (text: string) => {
  const t = decimalComma(text.trim());
  if (!t) return t;
  const capital = t.charAt(0).toUpperCase() + t.slice(1);
  return /[.!?…]$/.test(capital) ? capital : `${capital}.`;
};

/** «на 6% дороже», а за сотней — «в 7,6 раза дороже». */
const dearer = (margin: number) =>
  margin < -1 ? `в ${ru(1 - margin, 1)} раза` : `на ${ru(Math.abs(margin) * 100)}%`;

/** «Текущая ликвидность» → «текущая ликвидность», но «P/E» остаётся «P/E». */
const lowerFirst = (text: string) =>
  /^[А-ЯЁA-Z][а-яёa-z]/.test(text) ? text.charAt(0).toLowerCase() + text.slice(1) : text;


/**
 * Ось проходит, только если прошли все её измеримые критерии. Провал старше
 * всего: «не прошла» по одному критерию не отменяется тем, что другой не
 * посчитан. Непосчитанный критерий без провалов делает ось неизвестной, а не
 * пройденной — иначе нехватка данных выглядела бы как достоинство.
 */
function axisState(verdicts: Verdict[], axis: string): AxisState {
  const own = verdicts.filter((v) => v.axis === axis && v.status !== 'n/a');
  if (own.length === 0) return 'n/a';
  if (own.some((v) => v.status === 'fail')) return 'fail';
  if (own.some((v) => v.status === 'unknown')) return 'unknown';
  return 'pass';
}

type PriceCase = 'cheap' | 'thin' | 'fair' | 'dear' | 'bond' | 'danger' | 'none';

/**
 * Сигнал цены в словах фразы. «Сигнала нет» бэкенд ставит и тогда, когда
 * свод не пройден, — но запас при этом посчитан, и фраза опирается на него:
 * «дорого и слабые места» полезнее, чем «сигнала нет».
 */
function priceCase(signal: SafetySignal | undefined, margin: number | null): PriceCase {
  switch (signal) {
    case 'favourable': return 'cheap';
    case 'acceptable': return 'thin';
    case 'fair': return 'fair';
    case 'expensive': return 'dear';
    case 'bond_better': return 'bond';
    case 'dangerous': return 'danger';
    default:
      if (margin === null) return 'none';
      if (margin >= 1 / 3) return 'cheap';
      if (margin >= 0.1) return 'thin';
      if (margin >= -0.1) return 'fair';
      return 'dear';
  }
}

type Quality = 'strong' | 'weak' | 'unknown';

function headline(quality: Quality, price: PriceCase, margin: number | null): string {
  if (price === 'danger') return 'Опасная компания: долг способен стереть владельца';
  if (quality === 'strong') {
    switch (price) {
      case 'cheap': return 'Сильная компания с запасом прочности';
      case 'thin': return 'Сильная компания, запас прочности тонкий';
      case 'fair': return 'Сильная компания по цене около стоимости';
      case 'dear': return margin !== null && margin >= -0.15
        ? 'Сильная компания по цене чуть выше стоимости'
        : 'Сильная компания, но цена заметно выше стоимости';
      case 'bond': return 'Сильная компания, но облигации сейчас выгоднее';
      default: return 'Сильная компания, но оценку посчитать не удалось';
    }
  }
  if (quality === 'weak') {
    switch (price) {
      case 'cheap':
      case 'thin': return 'Дёшево, но не все консервативные критерии пройдены';
      case 'fair': return 'Цена около стоимости, но есть слабые места';
      case 'dear': return 'Дорого, и не все консервативные критерии пройдены';
      case 'bond': return 'Облигации выгоднее, и не все критерии пройдены';
      default: return 'Не все консервативные критерии пройдены, оценки нет';
    }
  }
  switch (price) {
    case 'cheap': return 'Цена ниже стоимости с запасом';
    case 'thin': return 'Цена немного ниже стоимости';
    case 'fair': return 'Цена около стоимости';
    case 'dear': return 'Цена выше стоимости';
    case 'bond': return 'Облигации сейчас выгоднее';
    default: return 'Оценку посчитать не удалось';
  }
}


export interface VerdictData {
  loading: boolean;
  headline: string;
  lede: string;
  /** Разделы консервативных критериев: пройдено и всего применимых. */
  passed: number;
  total: number;
  quality: Quality;
  failedAxes: string[];
  adjusted: Verdict[];
  available: boolean;
  margin: number | null;
  price: number | null;
  reference: number | null;
  normal: number | null;
  multiple: number | null;
  riskFree: number | null;
  lower: { rate: number; reference: number | null; margin: number | null } | null;
  marginTone: 'good' | 'warn' | 'bad' | 'neutral';
  summary: ValuationSummaryOut | undefined;
  passport: PassportOut | undefined;
}

/** Всё, что карточка говорит о компании, — одним расчётом для шапки и боковой колонки. */
export function useCompanyVerdict(companyId: number): VerdictData {
  const enabled = Number.isFinite(companyId) && companyId > 0;
  // Ключи те же, что у разделов ниже на странице: запрос уходит один раз.
  const { data: summary, isLoading: summaryLoading } = useQuery<ValuationSummaryOut>({
    queryKey: ['valuation-summary', companyId],
    queryFn: () => fetchValuationSummary(companyId),
    staleTime: 10 * 60 * 1000,
    enabled,
  });
  const { data: passport, isLoading: passportLoading } = useQuery<PassportOut>({
    queryKey: ['screen-passport', companyId],
    queryFn: () => fetchPassport(companyId),
    staleTime: 5 * 60 * 1000,
    enabled,
  });

  // ── Качество ──
  const screen = passport?.screens?.defensive ?? null;
  const verdicts = screen?.verdicts ?? [];
  const axes = (passport?.order ?? [])
    .map((key) => ({ key, state: axisState(verdicts, key) }))
    .filter((a) => a.state !== 'n/a');
  const passed = axes.filter((a) => a.state === 'pass').length;
  const failed = axes.filter((a) => a.state === 'fail');
  const quality: Quality = !screen || axes.length === 0
    ? 'unknown'
    : failed.length > 0
      ? 'weak'
      : axes.some((a) => a.state === 'unknown') ? 'unknown' : 'strong';
  // Отраслевые поправки называются прямо: «7 из 7» при сдвинутом пороге и
  // при книжном — разные утверждения.
  const adjusted = verdicts.filter((v) => v.adjusted && v.status !== 'n/a' && v.book_text).slice(0, 2);

  // ── Цена ──
  const available = Boolean(summary?.available) && !summary?.band?.refused;
  const safety = available ? summary?.safety ?? null : null;
  const margin = safety?.value_margin ?? null;
  const price = summary?.price ?? safety?.price ?? null;
  const reference = safety?.reference ?? null;
  const current = summary?.windows?.find((w) => w.window === summary.window) ?? null;
  const normal = summary?.headline?.normal_earnings ?? current?.normal_earnings ?? null;
  const riskFree = summary?.assumption?.risk_free_rate ?? null;
  const rates = [...(summary?.rates ?? [])].sort((a, b) => b.risk_free_rate - a.risk_free_rate);
  const nowRow = rates.find((r) => riskFree !== null && Math.abs(r.risk_free_rate - riskFree) < 0.01);
  const required = nowRow?.required_return
    ?? (riskFree !== null && summary?.assumption ? riskFree + summary.assumption.risk_premium : null);
  const lowerRow = riskFree === null
    ? null
    : rates.find((r) => r.risk_free_rate < riskFree - 0.01 && !r.refused && r.reference !== null) ?? null;
  const pc = available ? priceCase(safety?.signal, margin) : 'none';

  // ── Фраза ──
  const priceAxis = axes.find((a) => a.key === 'price');
  let lede: string;
  if (!available) {
    lede = sentence(summary?.band?.reason ?? summary?.reason ?? 'Для оценки не хватает данных.');
  } else if (pc === 'danger' || pc === 'bond') {
    lede = sentence(safety?.reason ?? '');
  } else if (pc === 'dear' && priceAxis?.state === 'pass' && margin !== null && riskFree !== null && required !== null) {
    lede = `По книжным порогам Грэма акция дешёвая. Но при доходности ОФЗ ${rate(riskFree)}% `
      + `инвестор вправе требовать от неё ${ru(required)}% годовых — и при такой цене денег `
      + `она ${dearer(margin)} дороже опорной оценки.`;
  } else if (margin !== null && price !== null && reference !== null) {
    lede = pc === 'fair'
      ? `Цена ${rub(price)} почти совпадает с опорной оценкой ${rub(reference)}.`
      : margin < 0
        ? `Цена ${rub(price)} ${dearer(margin)} выше опорной оценки ${rub(reference)}.`
        : `Цена ${rub(price)} ниже опорной оценки ${rub(reference)} на ${ru(margin * 100)}%.`;
  } else {
    lede = sentence(safety?.reason ?? '');
  }

  return {
    loading: summaryLoading || passportLoading,
    headline: headline(quality, pc, margin),
    lede: lede.trim(),
    passed,
    total: axes.length,
    quality,
    failedAxes: failed.map((a) => passport?.axes[a.key]?.label ?? a.key),
    adjusted,
    available,
    margin,
    price,
    reference,
    normal,
    multiple: reference !== null && normal ? reference / normal : null,
    riskFree,
    lower: lowerRow
      ? { rate: lowerRow.risk_free_rate, reference: lowerRow.reference, margin: lowerRow.margin }
      : null,
    marginTone: pc === 'cheap' || pc === 'thin'
      ? 'good'
      : pc === 'dear' || pc === 'bond' || pc === 'danger' ? 'bad' : 'neutral',
    summary,
    passport,
  };
}

/** Запас прочности для шапки: «+12%», «−8%», «×2,3». */
export function marginLabel(margin: number | null): string {
  if (margin === null) return '—';
  return margin < -1 ? `×${ru(1 - margin, 1)}` : pct(margin);
}

export { rub as rubLabel };

/** Разовые статьи в последнем годовом отчёте — если аналитик их выделил. */
export type OneOffs = { year: number; reported: number; normalized: number } | null;

/** Пункты «Обратить внимание»: ловушка, её признаки, разовые статьи, провалы, поправки. */
function attentionNotes(verdict: VerdictData, oneOffs: OneOffs): React.ReactNode[] {
  const { summary } = verdict;
  const notes: React.ReactNode[] = [];
  if (summary?.trap_level) {
    notes.push(
      <li key="trap" className={`ca-note ca-note--${summary.trap_level === 'likely' ? 'bad' : 'warn'}`}>
        <strong>
          {summary.trap_level === 'likely' ? 'Похоже на ловушку стоимости' : 'Есть признаки ловушки стоимости'}
        </strong>
        <small>
          Дёшево по меркам Грэма, но рынок {summary.trap_level === 'likely' ? 'годами ' : ''}не соглашается
          с балансом. Прежде чем верить запасу, выясните, кто контролирует компанию и как она делится
          деньгами с миноритариями.
        </small>
      </li>,
    );
  }
  (summary?.trap_signs ?? []).forEach((s) => notes.push(
    <li key={s.kind} className="ca-note ca-note--warn">
      <span>{s.title}</span>
      {s.detail && <small>{sentence(s.detail)}</small>}
    </li>,
  ));
  if (oneOffs) {
    notes.push(
      <li key="oneoffs" className="ca-note ca-note--warn">
        <span>
          Прибыль за {oneOffs.year} год по отчёту — {moneyBn(oneOffs.reported)}, без разовых статей — {moneyBn(oneOffs.normalized)}.
        </span>
        <small>Мультипликаторы считаются без разовых, оценка — от прибыли как в отчёте.</small>
      </li>,
    );
  }
  if (verdict.failedAxes.length > 0) {
    notes.push(
      <li key="failed" className="ca-note ca-note--bad">
        <span>Не пройдено: {verdict.failedAxes.map((a) => a.toLowerCase()).join(', ')}.</span>
      </li>,
    );
  }
  if (verdict.adjusted.length > 0) {
    notes.push(
      <li key="adjusted" className="ca-note">
        <span>
          Пороги сдвинуты под отрасль:{' '}
          {verdict.adjusted.map((v, i) => (
            <React.Fragment key={v.metric}>
              {i > 0 && '; '}
              {lowerFirst(v.metric_label)} в книге {decimalComma(v.book_text)}, здесь {decimalComma(v.text)}
            </React.Fragment>
          ))}.
        </span>
      </li>,
    );
  }
  return notes;
}

/** Опорная стоимость с расчётом в одну строку. */
export function AsideValuation({ verdict }: { verdict: VerdictData }) {
  const { summary } = verdict;
  return (
    <section className="ca-card">
      <h2 className="ca-kicker">Опорная стоимость</h2>
      {verdict.available && verdict.reference !== null ? (
        <>
          {/* Расчёт столбиком, итог под двойной чертой — как в ведомости. */}
          <div className="ca-ledger">
            {verdict.normal !== null && verdict.multiple !== null && (
              <>
                <div><span>Нормальная прибыль на акцию</span><span>{rub(verdict.normal)}</span></div>
                <div><span>× множитель</span><span>{ru(verdict.multiple, 2)}</span></div>
              </>
            )}
            <div className="ca-ledger-total"><span>Опорная</span><span className="ca-ref">{rub(verdict.reference)}</span></div>
          </div>
          <p className="ca-text">
            {verdict.lower && verdict.riskFree !== null && verdict.lower.reference !== null && (
              <>При ОФЗ {rate(verdict.lower.rate)}% вместо {rate(verdict.riskFree)}% — {rub(verdict.lower.reference)}. </>
            )}
            <a className="ca-link" href="#valuation">Как посчитано</a>
          </p>
        </>
      ) : (
        <p className="ca-text">
          {sentence(summary?.band?.reason ?? summary?.reason ?? 'Оценка не считается: не хватает данных.')}
        </p>
      )}
    </section>
  );
}

/**
 * «Обратить внимание». В узкой колонке пункты идут списком, под графиком —
 * в две колонки, чтобы длинный список не тянул страницу вниз.
 */
export const AsideNotes = React.forwardRef<HTMLElement, { verdict: VerdictData; oneOffs: OneOffs; wide?: boolean }>(
  ({ verdict, oneOffs, wide = false }, ref) => {
    const notes = attentionNotes(verdict, oneOffs);
    if (notes.length === 0) return null;
    return (
      <section ref={ref} className={`ca-card${wide ? ' ca-card--wide' : ''}`}>
        <h2 className="ca-kicker">Обратить внимание</h2>
        <ul className="ca-notes">{notes}</ul>
        <span className="ca-foot">Это предупреждения, на расчёт они не влияют.</span>
      </section>
    );
  },
);
AsideNotes.displayName = 'AsideNotes';

/** Оглавление разделов страницы. */
export function AsideToc({ sections }: { sections: { id: string; label: string; note?: string }[] }) {
  return (
    <nav className="ca-card ca-toc" aria-label="Разделы страницы">
      <h2 className="ca-kicker">На странице</h2>
      {sections.map((s) => (
        <a key={s.id} href={`#${s.id}`} className="ca-toc-item">
          <span>{s.label}</span>
          {s.note && <span className="ca-toc-note">{s.note}</span>}
        </a>
      ))}
    </nav>
  );
}

/** Миллионы рублей → «92,5 млрд ₽». */
function moneyBn(mln: number): string {
  const abs = Math.abs(mln);
  if (abs >= 1_000_000) return `${ru(mln / 1_000_000, 2)} трлн ₽`;
  if (abs >= 1_000) return `${ru(mln / 1_000, 1)} млрд ₽`;
  return `${ru(mln, 0)} млн ₽`;
}
