import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  getCompanyValuation,
  type CompanyValuationOut,
  type ValueBandOut,
} from '../services/valuation.api';
import ValuationCharts from './ValuationCharts';
import './CompanyValuation.css';

/**
 * Оценка стоимости компании — оборотная сторона панели мультипликаторов.
 *
 * Показывает не число, а полосу и путь к ней. Причина в том, что три из
 * четырёх слагаемых оценки — суждение либо нормализация, и одно число
 * притворялось бы измерением. Ширина полосы здесь сама несёт смысл: у ровной
 * компании с длинной историей она узкая, у дёрганой широкая.
 */

/** Окна нормализации. Каждое отвечает на свой вопрос — см. earning_power. */
const WINDOWS = [3, 5, 7, 10];

const fmt = (v: number | null | undefined, digits = 0) =>
  v === null || v === undefined
    ? '—'
    : v.toLocaleString('ru-RU', {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      });

const pct = (v: number | null | undefined, digits = 1) =>
  v === null || v === undefined ? '—' : `${v.toFixed(digits)}%`;

/** Согласование числительного: 3 года, 5 лет, 21 год. */
const years = (n: number) => {
  const mod100 = n % 100;
  if (mod100 >= 11 && mod100 <= 14) return `${n} лет`;
  const mod10 = n % 10;
  if (mod10 === 1) return `${n} год`;
  if (mod10 >= 2 && mod10 <= 4) return `${n} года`;
  return `${n} лет`;
};

/**
 * Полоса стоимости с отметкой цены.
 *
 * Цена может лежать вне полосы — тогда отметка прижимается к краю, а
 * подпись говорит, насколько именно вне. Прятать выход за границу нельзя:
 * это и есть самое содержательное положение из трёх.
 */
function Band({ band, price }: { band: ValueBandOut; price: number | null | undefined }) {
  const low = band.low;
  const high = band.high;
  if (low === null || high === null) return null;

  const span = high - low;
  const raw = price && span > 0 ? (price - low) / span : 0.5;
  const at = Math.min(Math.max(raw, 0), 1);
  const outside = price !== null && price !== undefined && (price < low || price > high);

  return (
    <div className="cv-band">
      <div className="cv-band-track">
        <div className="cv-band-fill" />
        {price !== null && price !== undefined && (
          <div
            className={`cv-band-marker${outside ? ' cv-band-marker--outside' : ''}`}
            style={{ left: `${at * 100}%` }}
          >
            <span className="cv-band-dot" />
            <span className="cv-band-price">
              {fmt(price)} ₽<em>цена</em>
            </span>
          </div>
        )}
      </div>
      <div className="cv-band-ends">
        <span>
          <strong>{fmt(low)} ₽</strong>
          <em>нижняя граница</em>
        </span>
        <span className="cv-band-right">
          <strong>{fmt(high)} ₽</strong>
          <em>верхняя граница</em>
        </span>
      </div>
    </div>
  );
}

function Verdict({ data }: { data: CompanyValuationOut }) {
  const { band, price, price_to_low: toLow, price_to_high: toHigh } = data;
  if (!band || band.low === null || band.high === null || !price) return null;

  if (price < band.low) {
    return (
      <p className="cv-verdict cv-verdict--under">
        Цена <b>ниже</b> полосы: {fmt(band.low)} ₽ против {fmt(price)} ₽, то есть
        рынок платит {toLow ? `${(toLow * 100).toFixed(0)}%` : '—'} нижней границы.
      </p>
    );
  }
  if (price > band.high) {
    return (
      <p className="cv-verdict cv-verdict--over">
        Цена <b>выше</b> полосы: {fmt(price)} ₽ против {fmt(band.high)} ₽ —
        премия {toHigh ? `${((toHigh - 1) * 100).toFixed(0)}%` : '—'} к верхней
        границе.
      </p>
    );
  }
  return (
    <p className="cv-verdict cv-verdict--inside">
      Цена <b>внутри</b> полосы. Модель и рынок не расходятся — по Коттлу это
      признак того, что оценка построена не зря: расчёт, ни разу не совпадающий
      с ценой за полный цикл, сам по себе подозрителен.
    </p>
  );
}

function Content({ data, window, onWindow, companyId }: {
  data: CompanyValuationOut;
  window: number;
  onWindow: (w: number) => void;
  companyId: number;
}) {
  if (!data.available) {
    return <div className="cv-empty">Оценка недоступна: {data.reason}</div>;
  }
  const band = data.band!;
  const penalty = band.penalty;

  return (
    <div className="cv-body">
      <div className="cv-windows">
        <span className="cv-windows-label">Окно нормализации</span>
        {WINDOWS.map((w) => (
          <button
            key={w}
            type="button"
            className={`cv-window${w === window ? ' is-active' : ''}`}
            onClick={() => onWindow(w)}
          >
            {years(w)}
          </button>
        ))}
      </div>

      {band.refused ? (
        <div className="cv-refused">
          <strong>Оценка не показывается.</strong> {band.reason}
        </div>
      ) : (
        <>
          <Band band={band} price={data.price} />
          <Verdict data={data} />

          {/* Ряды: итоговые средние скрывают, как величина себя вела */}
          <ValuationCharts companyId={companyId} window={window} />

          {/* Три лестницы: расхождение между ними и есть сообщение */}
          <table className="cv-table">
            <thead>
              <tr>
                <th>нормальная величина за {years(data.window!)}</th>
                <th className="cv-num">средняя</th>
                <th className="cv-num">тенденция</th>
                <th className="cv-num">× множитель</th>
                <th className="cv-num">оценка</th>
              </tr>
            </thead>
            <tbody>
              {band.ladders.map((item) => {
                const average = data.averages?.[item.name];
                const trend = data.trends?.[item.name];
                return (
                <tr key={item.name}>
                  <td>{item.name}</td>
                  <td className="cv-num cv-dim">
                    {average !== undefined ? `${fmt(average)} ₽` : '—'}
                  </td>
                  <td className="cv-num">
                    {trend ? `${fmt(trend.value)} ₽` : '—'}
                    {trend?.capped && (
                      <span className="cv-asset" title="Линия ушла выше исторического максимума и подрезана по нему: выше уже достигнутого брать нельзя (гл. 30, с. 568).">
                        ⌐
                      </span>
                    )}
                  </td>
                  <td className="cv-num">{item.multiple}</td>
                  <td className="cv-num">
                    {fmt(item.adjusted ?? item.value)} ₽
                    {item.asset_note && (
                      <span className="cv-asset" title={item.asset_note}>
                        ⚖
                      </span>
                    )}
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>

          <p className="cv-small">
            Уровень берётся{' '}
            <b>{band.basis === 'trend' ? 'по линии тенденции' : 'простой средней'}</b>.
            Пятое издание отказалось от средней (гл. 30, с. 568): она занижает
            растущие компании и завышает падающие. Обратный тест это подтвердил —
            со средней полоса накрывала цену в 28% лет, с тенденцией в 44%.
          </p>

          {band.asset_lift !== null && band.asset_lift !== 1 && (
            <div className="cv-note">
              <strong>Поправка на активы подняла оценку в {band.asset_lift} раза.</strong>{' '}
              По прибыли компания стоит {fmt(band.low_by_earnings)}–
              {fmt(band.high_by_earnings)} ₽; в счёт пошли две трети балансовой
              стоимости {fmt(data.book_value_per_share)} ₽ на акцию — правило гл. 34
              для компаний, чьи активы стоят больше, чем зарабатывают.
            </div>
          )}

          {/* Из чего сложился множитель */}
          <div className="cv-grid">
            <div className="cv-cell">
              <span className="cv-label">возврат владельцу за {years(data.window!)}</span>
              <span className="cv-value">{pct(data.payout)}</span>
              <span className="cv-hint">
                {data.payout_buyback !== null && data.payout_buyback !== undefined
                  ? `дивиденды ${pct(data.payout_dividends)} + выкуп ${pct(data.payout_buyback)}`
                  : 'дивиденды к прибыли; выкуп посчитать не удалось'}
              </span>
            </div>
            <div className="cv-cell">
              <span className="cv-label">отдача на капитал</span>
              <span className="cv-value">
                {pct(data.stability?.median)}
                {data.denominator && (
                  <span className="cv-flag" title={data.denominator.reason}>
                    мал капитал
                  </span>
                )}
              </span>
              <span className="cv-hint">
                {data.denominator
                  ? `при P/B ${data.denominator.price_to_book ?? '—'} — столько зарабатывают не на выдающемся бизнесе, а на малом балансовом капитале`
                  : `медиана, коридор ${pct(data.stability?.minimum)} … ${pct(data.stability?.maximum)}`}
              </span>
            </div>
            <div className="cv-cell">
              <span className="cv-label">ровность</span>
              <span className={`cv-value cv-steady cv-steady--${data.stability?.label ?? 'нет'}`}>
                {data.stability?.label ?? '—'}
              </span>
              <span className="cv-hint">
                разброс {data.stability?.relative_spread ?? '—'} от уровня
              </span>
            </div>
            <div className="cv-cell">
              <span className="cv-label">рост, который она может себе позволить</span>
              <span className="cv-value">{pct(band.growth)}</span>
              <span className="cv-hint">
                {band.growth_capped
                  ? `подрезан с ${pct(band.growth_uncapped)} — отдача держится на малом капитале`
                  : 'отдача × (1 − выплата)'}
              </span>
            </div>
            <div className="cv-cell">
              <span className="cv-label">множитель компании</span>
              <span className="cv-value">{band.multiple_high ?? '—'}</span>
              <span className="cv-hint">
                нижняя граница по {band.multiple_low ?? '—'}
              </span>
            </div>
          </div>

          {/* Надбавка за риск — единственное, что здесь назначено человеком */}
          {penalty && penalty.total > 0 && (
            <div className="cv-penalty">
              <div className="cv-penalty-head">
                <span>Надбавка к премии за риск</span>
                <b>+{penalty.total} п.п.</b>
              </div>
              <ul>
                {penalty.notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
              <p className="cv-hint">
                Она и растягивает полосу: верхняя граница считается по рыночной
                премии {pct(data.assumption?.risk_premium, 1)}, нижняя — с этой
                надбавкой. Ширина полосы {band.width ?? '—'}× и есть высказывание
                о качестве компании.
              </p>
            </div>
          )}

          {/* Обратный ход: превращает «дорого» в вопрос, на который можно
              ответить фактами, а не вкусом */}
          {data.priced_in && (
            <div className={`cv-priced${data.priced_in.demanding ? ' cv-priced--demanding' : ''}`}>
              <div className="cv-priced-head">
                <span>Что заложено в цену</span>
                <b>{fmt(data.priced_in.multiple_paid, 2)}× нормальной прибыли</b>
              </div>
              <div className="cv-priced-pair">
                <span>
                  <em>рынок платит так, будто дивиденды растут на</em>
                  <b>{pct(data.priced_in.growth_priced_in)}</b>
                </span>
                <span>
                  <em>компания при своей отдаче и выплате способна на</em>
                  <b>{pct(data.priced_in.growth_affordable)}</b>
                </span>
              </div>
              <p className="cv-hint">
                {data.priced_in.demanding ? (
                  <>
                    Разрыв {pct(data.priced_in.gap)} — это и есть весь спор о
                    компании. Не «дорого», а «верите ли вы, что она вырастет
                    настолько». Ответ на этот вопрос не в отчётах, и модель его
                    не даёт.
                  </>
                ) : (
                  <>
                    Рынок закладывает рост <b>ниже</b> того, что компания
                    вытягивает сама. Либо в цене сидит риск, которого в наших
                    числах нет, либо расхождение стоит того, чтобы в нём
                    разобраться.
                  </>
                )}
              </p>
            </div>
          )}

          {/* Ограждения */}
          {data.molodovsky?.artifact && (
            <div className="cv-note cv-note--warn">
              <strong>Эффект Молодовского.</strong> {data.molodovsky.reason}
            </div>
          )}
          {band.warnings.map((w) => (
            <div key={w} className="cv-note cv-note--warn">
              {w}
            </div>
          ))}
          {data.structure?.reason && data.structure.verdict !== 'ok' && (
            <div className="cv-note cv-note--warn">
              <strong>Структура капитала.</strong> {data.structure.reason}
            </div>
          )}

          <p className="cv-foot">
            Допущения за {data.assumption?.year} год: безрисковая ставка{' '}
            {pct(data.assumption?.risk_free_rate)}, премия за риск{' '}
            {pct(data.assumption?.risk_premium)}. История {years(data.history_years!)}.
            Разбор формулы — на странице «Множитель рынка».
          </p>
        </>
      )}
    </div>
  );
}

export default function CompanyValuation({ companyId }: { companyId: number }) {
  const [window, setWindow] = useState(7);
  const { data, isLoading, error } = useQuery({
    queryKey: ['company-valuation', companyId, window],
    queryFn: () => getCompanyValuation(companyId, window),
  });

  if (isLoading) return <div className="cv-empty">Считаю оценку…</div>;
  if (error || !data) {
    // Причину показываем ту, что вернул сервер. Раньше здесь стояло «не
    // заданы допущения» на любой сбой — и сообщение врало, отправляя чинить
    // не то: настоящей причиной был отсутствующий эндпоинт.
    const detail =
      (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    return (
      <div className="cv-empty">
        Оценка недоступна.{' '}
        {detail ?? 'Сервер не ответил — проверьте, что бэкенд запущен.'}
      </div>
    );
  }
  return (
    <Content data={data} window={window} onWindow={setWindow} companyId={companyId} />
  );
}
