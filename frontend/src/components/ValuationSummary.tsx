import React from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  fetchValuationSummary,
  type SummaryRate,
  type SummaryWindow,
  type ValuationSummaryOut,
} from '../services/valuation.api';
import './ValuationSummary.css';

/**
 * Свод оценки между графиком и таблицей множителей.
 *
 * Отвечает на другой вопрос, чем подробная вкладка. Там — одна настройка во
 * всех подробностях; здесь — **насколько ответ зависит от того, что мы в него
 * подставили**. Это и есть главное, что стоит знать про любую оценку по
 * формуле: у ЛУКОЙЛа при ставке ОФЗ 16% выходит 4 434 ₽, а при 8% — 7 157 ₽,
 * и разница между ними больше, чем разница между «дорого» и «дёшево».
 *
 * Поэтому здесь нет одной цифры крупным шрифтом. Три окна и четыре ставки
 * стоят рядом именно затем, чтобы одну цифру нельзя было принять за ответ.
 */

const ru = (value: number | null | undefined, digits = 0) =>
  value === null || value === undefined
    ? '—'
    : value.toLocaleString('ru-RU', { minimumFractionDigits: digits, maximumFractionDigits: digits });

const pct = (value: number | null | undefined) =>
  value === null || value === undefined
    ? '—'
    : `${value >= 0 ? '+' : ''}${(value * 100).toLocaleString('ru-RU', { maximumFractionDigits: 0 })}%`;

/** Знак запаса красит только запас, а не всю строку: строка — про ставку. */
const marginClass = (margin: number | null | undefined) => {
  if (margin === null || margin === undefined) return '';
  if (margin >= 1 / 3) return ' vs-good';
  if (margin >= 0) return ' vs-fair';
  return ' vs-bad';
};

const YEARS: Record<number, string> = { 3: '3 года', 5: '5 лет', 7: '7 лет', 10: '10 лет' };

function WindowCard({ item, price }: { item: SummaryWindow; price: number | null | undefined }) {
  return (
    <div className={`vs-window${item.refused ? ' is-refused' : ''}`}>
      <div className="vs-window-head">{YEARS[item.window] ?? `${item.window} лет`}</div>
      {item.refused ? (
        <div className="vs-window-refused" title={item.reason ?? undefined}>
          оценка не считается
        </div>
      ) : (
        <>
          <div className="vs-window-main">{ru(item.value)} <i>₽</i></div>
          <dl className="vs-window-rows">
            <div>
              {/* На длинных окнах лестница прибыли бывает пуста — у Аэрофлота
                  за десять лет она отрицательна, там ковид и двадцать второй
                  год. Полоса тогда держится на другой ступени, и назвать её
                  обязательно: «нормальная прибыль 8,78 ₽» у убыточной
                  компании — это не прибыль, а поток. */}
              <dt>{item.ladder ?? 'нормальная прибыль'}</dt>
              <dd>{ru(item.normal_earnings)} ₽</dd>
            </div>
            <div>
              <dt>опорная цена</dt>
              <dd>{ru(item.reference)} ₽</dd>
            </div>
            <div>
              <dt>запас к цене {ru(price)} ₽</dt>
              <dd className={marginClass(item.margin)}>{pct(item.margin)}</dd>
            </div>
          </dl>
          {item.method === 'epv' && (
            <div className="vs-window-method" title="Формула главы 32 требует выплаты; там, где её нет, считается способность зарабатывать — роста в такой оценке нет вовсе">
              EPV — нижняя граница
            </div>
          )}
        </>
      )}
    </div>
  );
}

function RateRow({ item, current }: { item: SummaryRate; current: number }) {
  const isNow = Math.abs(item.risk_free_rate - current) < 0.01;
  return (
    <tr className={isNow ? 'is-now' : undefined}>
      <th scope="row">
        {ru(item.risk_free_rate, 0)}%
        {isNow && <span className="vs-now-tag">сейчас</span>}
      </th>
      <td>{ru(item.required_return, 0)}%</td>
      <td>{ru(item.multiple, 2)}</td>
      <td className="vs-rate-value">{ru(item.value)} ₽</td>
      <td className={marginClass(item.margin)}>{pct(item.margin)}</td>
    </tr>
  );
}

export default function ValuationSummary({ companyId }: { companyId: number }) {
  const { data, isLoading, error } = useQuery<ValuationSummaryOut>({
    queryKey: ['valuation-summary', companyId],
    queryFn: () => fetchValuationSummary(companyId),
    staleTime: 10 * 60 * 1000,
    enabled: Number.isFinite(companyId) && companyId > 0,
  });

  if (isLoading) return <div className="vs-state">Считаем оценку…</div>;
  if (error) return <div className="vs-state vs-state--error">Не удалось посчитать оценку</div>;
  if (!data?.available) {
    return (
      <div className="vs-state">
        Оценка не считается{data?.reason ? `: ${data.reason}` : '.'}
      </div>
    );
  }

  const { windows = [], rates = [], safety, band, price, assumption } = data;

  return (
    <section className="vs">
      <header className="vs-head">
        <h3>Справедливая стоимость</h3>
        {safety && safety.signal !== 'no_signal' && (
          <span className={`vs-signal vs-signal--${safety.signal}`}>
            {safety.label}
            {safety.value_margin !== null && (
              <i> · запас {pct(safety.value_margin)}</i>
            )}
          </span>
        )}
      </header>

      {band?.refused ? (
        <p className="vs-refused">{band.reason}</p>
      ) : (
        <>
          <p className="vs-lede">
            Средняя прибыль за разные окна даёт разную оценку — и расхождение между
            ними само по себе есть сообщение. Три года говорят, дорого ли сейчас,
            семь — сколько компания стоит, десять — что было за полный цикл.
          </p>

          <div className="vs-windows">
            {windows.map((w) => (
              <WindowCard key={w.window} item={w} price={price} />
            ))}
          </div>

          <div className="vs-rates">
            <div className="vs-rates-head">
              <h4>Если ставка изменится</h4>
              <p>
                Множитель — это <code>выплата ÷ (K − g)</code>, и ставка сидит
                в знаменателе. Поэтому оценка зависит от неё сильнее, чем от чего-либо
                ещё в расчёте: это не прогноз, а мера чувствительности.
              </p>
            </div>
            <div className="vs-rates-scroll">
              <table className="vs-rates-table">
                <thead>
                  <tr>
                    <th scope="col">ОФЗ</th>
                    <th scope="col" title="Безрисковая плюс премия за риск">Требуемая</th>
                    <th scope="col">Множитель</th>
                    <th scope="col">Оценка</th>
                    <th scope="col" title="Доля опорной оценки; отрицательный — цена выше неё">Запас</th>
                  </tr>
                </thead>
                <tbody>
                  {rates.map((r) => (
                    <RateRow
                      key={r.risk_free_rate}
                      item={r}
                      current={assumption?.risk_free_rate ?? 0}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="vs-reference">
            <div className="vs-reference-main">
              <span className="vs-reference-label">Опорная цена</span>
              <span className="vs-reference-value">{ru(safety?.reference)} ₽</span>
              <span className="vs-reference-vs">против цены {ru(price)} ₽</span>
            </div>
            <p className="vs-reference-note">
              Опора берётся по лестнице прибыли при множителе с надбавкой за риск —
              не по середине полосы и не по её низу. Середина не даёт ошибаться в свою
              пользу, а низ полосы — это худшая ступень при худшем множителе, и запас
              от него не читается.
              {band?.low !== null && band?.high !== null && (
                <> Вся полоса: {ru(band?.low)} — {ru(band?.high)} ₽.</>
              )}
            </p>
          </div>
        </>
      )}
    </section>
  );
}
