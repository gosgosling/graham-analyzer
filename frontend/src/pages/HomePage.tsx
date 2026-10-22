import React, { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getCompanies } from '../services';
import { fetchMarketScreen, type MarketScreenOut } from '../services/screen.api';
import { fetchMarketOverview } from '../services/market.api';
import type { Company } from '../types';
import { CompanySearch } from '../components/SiteHeader';
import './HomePage.css';

/**
 * Главная: куда человек попал, во что здесь верят и куда идти.
 *
 * Раньше адрес сайта сразу перебрасывал в список компаний — человек из
 * ссылки в Telegram видел тикеры и не понимал, что с ними делать. Здесь
 * — суть одной фразой и картинкой (стоимость, цена и разрыв между ними),
 * рынок сегодня в трёх числах, идеи Грэма своими словами и входы в разделы.
 *
 * Без рекомендаций: числа — расчёт по методу, а «кто проходит требования» —
 * результат проверки, не совет покупать.
 */

/** Быстрые кнопки: самые известные бумаги, чтобы было с чего начать. */
const POPULAR = ['SBER', 'LKOH', 'YDEX', 'GAZP', 'T', 'GMKN'];

const ru = (n: number, digits = 1) => n.toLocaleString('ru-RU', { maximumFractionDigits: digits });

/** Идеи «Разумного инвестора» — пересказ, а не цитаты, и где они на сайте. */
const IDEAS: { title: string; text: string; to: string; link: string }[] = [
  {
    title: 'Запас прочности',
    text: 'Покупать заметно дешевле стоимости. Разница защищает от собственных ошибок в оценке и от невезения.',
    to: '/valuation',
    link: 'Как считается стоимость',
  },
  {
    title: 'Мистер Рынок',
    text: 'Рынок каждый день предлагает цену. Её можно принять или проигнорировать — но не стоит ей подчиняться.',
    to: '/market',
    link: 'Рынок целиком',
  },
  {
    title: 'Средняя прибыль, а не рекорд',
    text: 'Оценивать по прибыли за много лет: один удачный год говорит о бизнесе меньше, чем семь обычных.',
    to: '/valuation',
    link: 'Почему средняя',
  },
  {
    title: 'Привычка платить',
    text: 'Дивиденды год за годом — признак того, что прибыль настоящая, а не только на бумаге.',
    to: '/screen',
    link: 'Кто платит подряд',
  },
  {
    title: 'Облигация как мерило',
    text: 'Акция должна зарабатывать больше надёжной облигации — иначе риск ничем не оплачен.',
    to: '/market',
    link: 'Акции против ОФЗ',
  },
  {
    title: 'Скромные ожидания',
    text: 'Консервативный инвестор не ищет «иксы». Ему достаточно не потерять и получать разумный доход.',
    to: '/screen',
    link: 'Требования защитного инвестора',
  },
];

/** Метод в одной картинке: стоимость, цена ниже неё и разрыв — запас. */
function MethodPicture() {
  return (
    <figure className="hp-pic" aria-label="Опорная стоимость выше цены, разница — запас прочности">
      <div className="hp-pic-row">
        <span className="hp-pic-label">Опорная стоимость</span>
        <span className="hp-pic-bar hp-pic-bar--value" />
      </div>
      <div className="hp-pic-row">
        <span className="hp-pic-label">Цена на бирже</span>
        <span className="hp-pic-track">
          <span className="hp-pic-bar hp-pic-bar--price" />
          <span className="hp-pic-gap">запас прочности</span>
        </span>
      </div>
      <figcaption>Чем шире зелёный разрыв, тем больше права на ошибку.</figcaption>
    </figure>
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

  const cleared = screen ? screen.rows.filter((r) => r.clears) : null;
  const now = market?.valuation.find((y) => y.year === 'now') ?? null;

  return (
    <div className="hp">
      <section className="hp-hero">
        <div className="hp-hero-text">
          <p className="hp-eyebrow">Метод Бенджамина Грэма — для Мосбиржи</p>
          <h1>Сколько стоят российские акции — по&nbsp;Грэму</h1>
          <p className="hp-lede">
            Считаем опорную стоимость {companies ? companies.length : 'российских'} компаний из отчётов МСФО:
            по средней прибыли за годы, балансу и ставке ОФЗ. Без прогнозов и без рекомендаций.
          </p>
          <div className="hp-search"><CompanySearch /></div>
          {popular.length > 0 && (
            <div className="hp-popular" aria-label="Популярные компании">
              {popular.map((c) => (
                <Link key={c.id} to={`/company/${c.id}`} className="hp-chip">{c.name}</Link>
              ))}
            </div>
          )}
        </div>
        <MethodPicture />
      </section>

      <section className="hp-section" aria-labelledby="hp-today">
        <div className="hp-section-head">
          <h2 id="hp-today" className="hp-kicker">Рынок сегодня</h2>
          <Link to="/market" className="hp-section-link">Подробнее →</Link>
        </div>
        <div className="hp-stats">
          <Link to="/market" className="hp-stat">
            <span className="hp-stat-num">{now ? ru(now.pe) : '…'}</span>
            <span className="hp-stat-label">P/E рынка</span>
            <small>за рубль прибыли платят столько рублей цены</small>
          </Link>
          <Link to="/market" className="hp-stat">
            <span className="hp-stat-num">
              {now ? `${ru(now.earnings_yield)}%` : '…'}
              {now?.ofz10 != null && <i> против {ru(now.ofz10)}%</i>}
            </span>
            <span className="hp-stat-label">акции зарабатывают против ОФЗ</span>
            <small>
              {now?.premium != null
                ? `премия за риск ${now.premium >= 0 ? '+' : '−'}${ru(Math.abs(now.premium))} п.п.`
                : 'доходность по прибыли и десятилетних облигаций'}
            </small>
          </Link>
          <Link to="/screen" className="hp-stat hp-stat--accent">
            <span className="hp-stat-num">
              {cleared && screen ? <>{cleared.length}<i> из {screen.rows.length}</i></> : '…'}
            </span>
            <span className="hp-stat-label">проходят все требования защитного инвестора</span>
            <small>
              {cleared && cleared.length > 0
                ? cleared.slice(0, 3).map((r) => r.name).join(', ')
                : 'семь проверок из главы 14'}
            </small>
          </Link>
        </div>
      </section>

      <section className="hp-section" aria-labelledby="hp-ideas">
        <h2 id="hp-ideas" className="hp-kicker">Идеи Грэма, на которых всё построено</h2>
        <ol className="hp-ideas">
          {IDEAS.map((idea, i) => (
            <li key={idea.title} className="hp-idea">
              <span className="hp-idea-num">{String(i + 1).padStart(2, '0')}</span>
              <h3>{idea.title}</h3>
              <p>{idea.text}</p>
              <Link to={idea.to}>{idea.link} →</Link>
            </li>
          ))}
        </ol>
        <blockquote className="hp-motto">
          Рынок голосует, весы взвешивают: в короткую цену решает настроение, в долгую — прибыль.
        </blockquote>
      </section>

      <section className="hp-section" aria-labelledby="hp-start">
        <h2 id="hp-start" className="hp-kicker">С чего начать</h2>
        <div className="hp-go">
          <Link to="/screen" className="hp-card hp-card--screen">
            <span className="hp-card-text">
              <b>Скринер</b>
              <small>Кто проходит требования защитного и активного инвестора</small>
            </span>
            <span className="hp-card-num">
              {cleared && screen ? <>{cleared.length}<i> из {screen.rows.length}</i></> : '→'}
            </span>
          </Link>
          <Link to="/companies" className="hp-card hp-card--companies">
            <span className="hp-card-text">
              <b>Все компании</b>
              <small>Цена, опорная стоимость и запас прочности по каждой</small>
            </span>
            <span className="hp-card-num">{companies ? companies.length : '→'}</span>
          </Link>
          <Link to="/valuation" className="hp-card hp-card--method">
            <span className="hp-card-text">
              <b>Как считается стоимость</b>
              <small>Метод Грэма и Додда — коротко и по шагам</small>
            </span>
            <span className="hp-card-num">→</span>
          </Link>
        </div>
      </section>

      <section className="hp-section" aria-labelledby="hp-how">
        <h2 id="hp-how" className="hp-kicker">Как считаем</h2>
        <ol className="hp-steps">
          <li><b>Отчёты МСФО</b><span>за много лет — в скринер идут только проверенные</span></li>
          <li><b>Средняя прибыль и баланс</b><span>без разовых статей, по долям акционеров</span></li>
          <li><b>Опорная стоимость</b><span>и запас прочности к сегодняшней цене</span></li>
        </ol>
      </section>

      <a className="hp-tg" href="https://t.me/graham_analyzer" target="_blank" rel="noreferrer">
        <span>
          <b>Разборы компаний — в Telegram</b>
          <small>Новые отчёты, компании недели и что изменилось в скринере</small>
        </span>
        <span className="hp-tg-handle">@graham_analyzer →</span>
      </a>
    </div>
  );
}
