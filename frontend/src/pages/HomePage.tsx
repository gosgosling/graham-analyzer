import React, { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getCompanies } from '../services';
import { fetchMarketScreen, type MarketRow, type MarketScreenOut } from '../services/screen.api';
import { fetchMarketOverview } from '../services/market.api';
import type { Company } from '../types';
import { CompanySearch } from '../components/SiteHeader';
import { formatPerShare } from '../utils/perShare';
import './HomePage.css';

/**
 * Главная: что это за сайт — одной фразой, рынок сегодня — тремя числами,
 * суть метода — на живых компаниях, и что здесь ещё есть.
 *
 * Раньше адрес сайта сразу перебрасывал в список компаний — человек из
 * ссылки в Telegram видел тикеры и не понимал, что с ними делать. Потом здесь
 * был рекламный первый экран с плитками идей; он рассказывал о методе, а не
 * показывал его. Теперь вместо пересказа — таблица: цена известных компаний
 * против их опорной стоимости. Это и есть то, что сайт считает.
 *
 * Без рекомендаций: числа — расчёт по методу, «проходит отбор» — результат
 * проверки, не совет покупать.
 */

/** Знакомые имена: с них проще всего понять, что показывает сайт. */
const POPULAR = ['SBER', 'LKOH', 'YDEX', 'GAZP', 'T', 'GMKN'];
/** Строк в таблице «цена против опорной». */
const SAMPLE_SIZE = 7;

const ru = (n: number, digits = 1) => n.toLocaleString('ru-RU', { maximumFractionDigits: digits });
const rub = (n: number) => (Math.abs(n) >= 100 ? ru(n, 0) : formatPerShare(n));

/**
 * Положение цены на шкале, где середина — опорная стоимость. Шкала
 * логарифмическая: вдвое дешевле — левый край, вдвое дороже — правый, и
 * «на 30% дешевле» не выглядит меньше, чем «на 30% дороже».
 */
/** «дешевле на 23%», «дороже на 19%», а от двух раз — «дороже в 5,3 раза». */
const gapText = (price: number, reference: number) => {
  if (price >= reference * 2) return `дороже в ${ru(price / reference)} раза`;
  const pct = Math.round(Math.abs(price / reference - 1) * 100);
  return `${price < reference ? 'дешевле' : 'дороже'} на ${pct}%`;
};

const scaleX = (price: number, reference: number) => {
  const r = Math.log2(price / reference);
  return 50 + Math.max(-1, Math.min(1, r)) * 50;
};

function ValueRow({ row }: { row: MarketRow }) {
  const s = row.safety!;
  const price = s.price as number;
  const reference = s.reference as number;
  const x = scaleX(price, reference);
  const below = price < reference;
  const from = Math.min(x, 50);
  const width = Math.abs(x - 50);
  return (
    <li className="hp-vr">
      <Link to={`/company/${row.id}`} className="hp-vr-name">
        <b>{row.name}</b>
        {row.clears && <span className="hp-vr-tag">проходит отбор</span>}
      </Link>
      <span className="hp-vr-num">{rub(price)}</span>
      <span className="hp-vr-num hp-vr-ref">{rub(reference)}</span>
      <span className="hp-vr-scale" aria-hidden>
        <span className="hp-vr-axis" />
        <span className={`hp-vr-gap${below ? ' is-below' : ''}`} style={{ left: `${from}%`, width: `${width}%` }} />
        <span className={`hp-vr-dot${below ? ' is-below' : ''}`} style={{ left: `${x}%` }} />
      </span>
      <span className={`hp-vr-margin${below ? ' is-below' : ''}`}>
        {gapText(price, reference)}
      </span>
    </li>
  );
}

export default function HomePage() {
  // Ключи те же, что у списка компаний, скринера и «Рынка»: перейдёшь туда —
  // уже загружено.
  const { data: companies } = useQuery({
    queryKey: ['companies'],
    queryFn: getCompanies,
    staleTime: 10 * 60 * 1000,
  });
  const { data: screen } = useQuery<MarketScreenOut>({
    queryKey: ['screen-market', 'defensive', false],
    queryFn: () => fetchMarketScreen('defensive', false),
    staleTime: 5 * 60 * 1000,
  });
  const { data: market } = useQuery({
    queryKey: ['market-overview'],
    queryFn: fetchMarketOverview,
    staleTime: 30 * 60 * 1000,
  });

  const popular = useMemo(() => {
    const byTicker = new Map((companies ?? []).map((c: Company) => [c.ticker, c]));
    return POPULAR.map((t) => byTicker.get(t)).filter((c): c is Company => Boolean(c?.id));
  }, [companies]);

  // Сначала те, кто проходит отбор, потом знакомые имена — только с оценкой.
  const sample = useMemo(() => {
    const rows = (screen?.rows ?? []).filter((r) => r.safety?.price && r.safety?.reference);
    const picked = [
      ...rows.filter((r) => r.clears),
      ...POPULAR.map((t) => rows.find((r) => r.ticker === t)).filter((r): r is MarketRow => Boolean(r)),
    ];
    return picked.filter((r, i) => picked.findIndex((p) => p.id === r.id) === i).slice(0, SAMPLE_SIZE);
  }, [screen]);

  const cleared = screen ? screen.rows.filter((r) => r.clears).length : null;
  const now = market?.valuation.find((y) => y.year === 'now') ?? null;

  return (
    <div className="hp">
      <section className="hp-intro">
        <h1>Цена и стоимость российских акций</h1>
        <p className="hp-lede">
          Сайт считает, сколько стоит компания по методу Бенджамина Грэма — из отчётов МСФО за много
          лет, — и сравнивает это с ценой на бирже. {companies ? `${companies.length} компаний` : 'Компании Мосбиржи'},
          без прогнозов и без рекомендаций.
        </p>
        <div className="hp-search"><CompanySearch /></div>
        {popular.length > 0 && (
          <p className="hp-popular">
            <span>Например:</span>{' '}
            {popular.map((c, i) => (
              <React.Fragment key={c.id}>
                {i > 0 && <span className="hp-sep" aria-hidden> · </span>}
                <Link to={`/company/${c.id}`}>{c.name}</Link>
              </React.Fragment>
            ))}
          </p>
        )}
      </section>

      <section className="hp-today" aria-label="Рынок сегодня">
        <Link to="/market" className="hp-fig">
          <span className="hp-fig-label">P/E рынка</span>
          <span className="hp-fig-num">{now ? ru(now.pe) : '…'}</span>
          <span className="hp-fig-sub">столько рублей цены за рубль прибыли</span>
        </Link>
        <Link to="/market" className="hp-fig">
          <span className="hp-fig-label">Доходность акций</span>
          <span className="hp-fig-num">
            {now ? `${ru(now.earnings_yield)}%` : '…'}
          </span>
          <span className="hp-fig-sub">
            {now?.ofz10 != null ? `против ${ru(now.ofz10)}% у десятилетних ОФЗ` : 'прибыль к цене'}
          </span>
        </Link>
        <Link to="/screen" className="hp-fig">
          <span className="hp-fig-label">Проходят отбор Грэма</span>
          <span className="hp-fig-num">
            {cleared !== null && screen ? <>{cleared}<small> из {screen.rows.length}</small></> : '…'}
          </span>
          <span className="hp-fig-sub">все семь требований защитного инвестора</span>
        </Link>
      </section>

      {sample.length > 0 && (
        <section className="hp-block" aria-labelledby="hp-values">
          <div className="hp-block-head">
            <h2 id="hp-values">Цена против опорной стоимости</h2>
            <Link to="/companies">Все компании →</Link>
          </div>
          <p className="hp-note">
            Опорная — расчётная стоимость акции по средней прибыли за годы и балансу. Грэм советовал
            покупать заметно ниже неё: разница — запас прочности на случай ошибки в оценке.
          </p>
          <div className="hp-vr-head" aria-hidden>
            <span />
            <span>Цена, ₽</span>
            <span>Опорная, ₽</span>
            <span className="hp-vr-head-scale"><i>дешевле</i><i>дороже</i></span>
            <span />
          </div>
          <ul className="hp-vr-list">
            {sample.map((r) => <ValueRow key={r.id} row={r} />)}
          </ul>
        </section>
      )}

      <section className="hp-block" aria-labelledby="hp-inside">
        <div className="hp-block-head">
          <h2 id="hp-inside">Что здесь есть</h2>
        </div>
        <div className="hp-index">
          <Link to="/screen" className="hp-index-item">
            <b>Скринер</b>
            <span>Требования Грэма к защитному и активному инвестору: кто проходит и чего не хватило остальным.</span>
          </Link>
          <Link to="/companies" className="hp-index-item">
            <b>Карточка компании</b>
            <span>Отчётность за годы, опорная стоимость, график цены против неё, дивиденды и мультипликаторы.</span>
          </Link>
          <Link to="/market" className="hp-index-item">
            <b>Рынок</b>
            <span>P/E всего рынка за двадцать лет и сколько акции зарабатывают против облигаций.</span>
          </Link>
          <Link to="/calendar" className="hp-index-item">
            <b>Календарь отчётности</b>
            <span>Когда компании публикуют МСФО и чьи цифры уже обновились.</span>
          </Link>
          <Link to="/valuation" className="hp-index-item">
            <b>Как считается стоимость</b>
            <span>Метод Грэма и Додда по шагам: от средней прибыли до запаса прочности.</span>
          </Link>
          <a href="https://t.me/graham_analyzer" target="_blank" rel="noreferrer" className="hp-index-item">
            <b>Telegram</b>
            <span>Разборы новых отчётов и что изменилось в скринере — @graham_analyzer.</span>
          </a>
        </div>
      </section>
    </div>
  );
}
