import React, { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { getReportCalendar, type UpcomingReport } from '../services/disclosure.api';
import CompanyLogo from '../components/CompanyLogo';
import './ReportCalendar.css';

/**
 * Календарь ожидаемых публикаций отчётности.
 *
 * Важно понимать, что здесь прогноз, а не расписание. Точной даты будущей
 * публикации не существует: закон обязывает раскрыть отчётность не позднее
 * срока, но не обязывает объявлять день заранее. Поэтому каждая строка несёт
 * пометку о собственной точности, а не притворяется фактом.
 */

const MONTHS = [
  'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
];
const WEEKDAYS = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс'];

const CONFIDENCE: Record<string, { label: string; hint: string }> = {
  narrow: {
    label: 'по графику',
    hint: 'Компания публикует стабильно: разброс дат за прошлые годы меньше десяти дней.',
  },
  wide: {
    label: 'ориентир',
    hint: 'Разброс дат за прошлые годы до месяца — дата приблизительная.',
  },
  rough: {
    label: 'ожидается',
    hint:
      'Точной привычки нет: разброс больше месяца либо отчётов этого типа ещё не вносили. ' +
      'Дата оценена по сроку раскрытия и по тому, насколько быстро компания сдаёт годовой отчёт.',
  },
};

type HorizonKey = 'months' | 'year-end' | 'year';

const DAY_MS = 24 * 3600 * 1000;
const isoDay = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const dotDay = (d: Date) => isoDay(d).split('-').reverse().join('.');

/**
 * Горизонты — календарные, а не «N дней». Раньше «до конца года» было 140
 * днями от сегодня, и 25 октября показывало февраль–март следующего года;
 * «год вперёд» — 300 дней. Теперь конец года — 31 декабря, год — та же дата
 * через год. API принимает число дней, поэтому граница считается здесь, а
 * лишние дни (`days` не меньше 7) отрезаются по дате.
 */
function horizons(today: Date): { key: HorizonKey; label: string; until: Date }[] {
  const yearEnd = new Date(today.getFullYear(), 11, 31);
  const nextYear = new Date(today.getFullYear() + 1, today.getMonth(), today.getDate());
  const twoMonths = new Date(today.getTime() + 60 * DAY_MS);
  return [
    { key: 'months', label: '2 месяца', until: twoMonths },
    { key: 'year-end', label: 'до конца года', until: yearEnd },
    { key: 'year', label: `до ${dotDay(nextYear)}`, until: nextYear },
  ];
}

const daysUntil = (today: Date, until: Date) => Math.max(7, Math.ceil((until.getTime() - today.getTime()) / DAY_MS));

function DayCard({ day, items, today }: { day: string; items: UpcomingReport[]; today: string }) {
  const d = new Date(`${day}T00:00:00`);
  const past = day < today;
  // Год — у каждой даты не текущего года: «2 февраля» без года 26 октября
  // читалось как прошедший февраль.
  const otherYear = day.slice(0, 4) !== today.slice(0, 4);
  return (
    <div className={`cal-row${past ? ' cal-row--past' : ''}`}>
      <div className="cal-date">
        <span className="cal-date-num">{d.getDate()}</span>
        <span className="cal-date-mon">{MONTHS[d.getMonth()]}{otherYear && ` ${d.getFullYear()}`}</span>
        <span className="cal-date-wd">{WEEKDAYS[(d.getDay() + 6) % 7]}</span>
      </div>
      <div className="cal-items">
        {items.map((i) => (
          <div className="cal-item" key={`${i.company_id}-${i.period_key}`}>
            <div className="cal-item-head">
              <span className="cal-period">{i.period_label} · МСФО</span>
              <span
                className={`cal-conf cal-conf--${i.confidence}`}
                title={CONFIDENCE[i.confidence]?.hint}
              >
                {CONFIDENCE[i.confidence]?.label ?? i.confidence}
              </span>
            </div>
            {/* В карточку, а не в матрицу отчётов: матрица — служебная, гостю закрыта. */}
            <Link className="cal-company" to={`/company/${i.company_id}`}>
              <CompanyLogo url={i.logo_url} ticker={i.ticker} className="cal-logo" />
              <span className="cal-name">{i.name ?? i.ticker}</span>
              <span className="cal-ticker">{i.ticker}</span>
            </Link>
          </div>
        ))}
      </div>
    </div>
  );
}

const ReportCalendar: React.FC = () => {
  const today = useMemo(() => { const d = new Date(); d.setHours(0, 0, 0, 0); return d; }, []);
  const options = useMemo(() => horizons(today), [today]);
  const [key, setKey] = useState<HorizonKey>('year-end');
  const horizon = options.find((h) => h.key === key) ?? options[1];
  const yearOption = options[2];
  const { data: raw, isLoading, error } = useQuery({
    queryKey: ['report-calendar', daysUntil(today, horizon.until)],
    queryFn: () => getReportCalendar(daysUntil(today, horizon.until)),
    staleTime: 10 * 60 * 1000,
  });
  const data = useMemo(() => {
    if (!raw) return raw;
    const last = isoDay(horizon.until);
    const days = raw.days.filter((d) => d.day <= last);
    return { ...raw, days, total: days.reduce((n, d) => n + d.items.length, 0) };
  }, [raw, horizon]);
  // Пусто до конца года — назвать ближайшую публикацию за ним, а не просто
  // «ничего нет»: годовые отчёты выходят с февраля.
  const { data: ahead } = useQuery({
    queryKey: ['report-calendar', daysUntil(today, yearOption.until)],
    queryFn: () => getReportCalendar(daysUntil(today, yearOption.until)),
    staleTime: 10 * 60 * 1000,
    enabled: Boolean(data && data.days.length === 0 && key !== 'year'),
  });
  const nextDay = ahead?.days.find((d) => d.day > isoDay(horizon.until)) ?? null;

  return (
    <div className="cal-page">
      <div className="cal-head">
        <h1>Календарь отчётностей</h1>
        <div className="cal-horizons">
          {options.map((h) => (
            <button
              key={h.key}
              type="button"
              className={key === h.key ? 'is-active' : undefined}
              onClick={() => setKey(h.key)}
            >
              {h.label}
            </button>
          ))}
        </div>
      </div>

      <p className="cal-lead">
        Прогноз, а не расписание. Точной даты будущей публикации не существует: закон
        обязывает раскрыть отчётность не позднее срока, но не обязывает объявлять день
        заранее. Дата считается по привычке самой компании — медиане задержки
        «отчётная дата → публикация» — и переносится на рабочий день. У каждой строки
        своя пометка точности, наведите на неё.
      </p>

      {isLoading && <div className="cal-empty">Считаю…</div>}
      {error && <div className="cal-empty">Не удалось загрузить: {String(error)}</div>}

      {data && data.days.length === 0 && (
        <div className="cal-empty">
          <p>
            {key === 'year-end' ? 'До конца года' : `До ${dotDay(horizon.until)}`} публикаций не ожидается.
          </p>
          {nextDay && (
            <p>
              Ближайшая — <b>{dotDay(new Date(`${nextDay.day}T00:00:00`))}</b>,{' '}
              {nextDay.items.map((i) => i.name ?? i.ticker).join(', ')}.{' '}
              <button type="button" className="cal-more" onClick={() => setKey('year')}>
                Показать {yearOption.label} →
              </button>
            </p>
          )}
        </div>
      )}

      {data && data.days.length > 0 && (
        <>
          <div className="cal-summary">
            С {dotDay(today)} по {dotDay(horizon.until)} ожидается <b>{data.total}</b> публикаций на {data.days.length} дат
          </div>
          <div className="cal-list">
            {data.days.map((d) => (
              <DayCard key={d.day} day={d.day} items={d.items} today={data.today} />
            ))}
          </div>
        </>
      )}
    </div>
  );
};

export default ReportCalendar;
