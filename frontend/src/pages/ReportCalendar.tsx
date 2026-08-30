import React, { useState } from 'react';
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

const HORIZONS = [
  { days: 60, label: '2 месяца' },
  { days: 140, label: 'до конца года' },
  { days: 300, label: 'год вперёд' },
];

function DayCard({ day, items, today }: { day: string; items: UpcomingReport[]; today: string }) {
  const d = new Date(`${day}T00:00:00`);
  const past = day < today;
  return (
    <div className={`cal-row${past ? ' cal-row--past' : ''}`}>
      <div className="cal-date">
        <span className="cal-date-num">{d.getDate()}</span>
        <span className="cal-date-mon">{MONTHS[d.getMonth()]}</span>
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
            <Link className="cal-company" to={`/company/${i.company_id}/reports-matrix`}>
              <CompanyLogo url={i.logo_url} className="cal-logo" />
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
  const [days, setDays] = useState(140);
  const { data, isLoading, error } = useQuery({
    queryKey: ['report-calendar', days],
    queryFn: () => getReportCalendar(days),
    staleTime: 10 * 60 * 1000,
  });

  return (
    <div className="cal-page">
      <div className="cal-head">
        <h1>Календарь отчётностей</h1>
        <div className="cal-horizons">
          {HORIZONS.map((h) => (
            <button
              key={h.days}
              type="button"
              className={days === h.days ? 'is-active' : undefined}
              onClick={() => setDays(h.days)}
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
        <div className="cal-empty">В выбранном горизонте публикаций не ожидается.</div>
      )}

      {data && data.days.length > 0 && (
        <>
          <div className="cal-summary">
            Ожидается <b>{data.total}</b> публикаций на {data.days.length} дат
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
