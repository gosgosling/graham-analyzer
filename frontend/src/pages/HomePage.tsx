import React, { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getCompanies } from '../services';
import { fetchMarketScreen, type MarketScreenOut } from '../services/screen.api';
import type { Company } from '../types';
import { CompanySearch } from '../components/SiteHeader';
import './HomePage.css';

/**
 * Главная: куда человек попал и куда ему идти.
 *
 * Раньше адрес сайта сразу перебрасывал в список компаний — длинную таблицу
 * без единого слова о том, что это за сайт. Человек из ссылки в Telegram
 * видел тикеры и ISIN и не понимал, что с ними делать.
 *
 * Здесь — одна фраза о сути, поиск (главное действие), три входа с живыми
 * цифрами и три слова, которые встретятся на каждой странице.
 */

/** Быстрые кнопки: самые известные бумаги, чтобы было с чего начать. */
const POPULAR = ['SBER', 'LKOH', 'YDEX', 'GAZP', 'T', 'GMKN'];

const GLOSSARY: { term: string; text: string }[] = [
  { term: 'Опорная стоимость', text: 'сколько акция стоит по прибыли, балансу и ставке ОФЗ — расчёт, не прогноз' },
  { term: 'Запас прочности', text: 'насколько цена ниже опорной; у Грэма — защита от собственных ошибок' },
  { term: 'Требования Грэма', text: 'семь проверок защитного инвестора из «Разумного инвестора»: размер, долг, прибыль, дивиденды, цена' },
];

export default function HomePage() {
  // Ключи те же, что у списка компаний и скринера: перейдёшь туда — уже загружено.
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

  const popular = useMemo(() => {
    const byTicker = new Map((companies ?? []).map((c: Company) => [c.ticker, c]));
    return POPULAR.map((t) => byTicker.get(t)).filter((c): c is Company => Boolean(c?.id));
  }, [companies]);

  const cleared = screen ? screen.rows.filter((r) => r.clears).length : null;

  return (
    <div className="hp">
      <section className="hp-hero">
        <h1>Сколько стоят российские акции — по&nbsp;Грэму</h1>
        <p className="hp-lede">
          Считаем опорную стоимость {companies ? companies.length : 'российских'} компаний из отчётов МСФО:
          по средней прибыли, балансу и ставке ОФЗ. Без прогнозов и без рекомендаций.
        </p>
        <div className="hp-search"><CompanySearch /></div>
        {popular.length > 0 && (
          <div className="hp-popular" aria-label="Популярные компании">
            {popular.map((c) => (
              <Link key={c.id} to={`/company/${c.id}`} className="hp-chip">{c.name}</Link>
            ))}
          </div>
        )}
      </section>

      <section className="hp-section" aria-labelledby="hp-start">
        <h2 id="hp-start" className="hp-kicker">С чего начать</h2>
        <div className="hp-go">
          <Link to="/screen" className="hp-card">
            <span className="hp-card-text">
              <b>Скринер</b>
              <small>Кто сейчас проходит все требования защитного инвестора</small>
            </span>
            <span className="hp-card-num">
              {cleared !== null && screen ? <>{cleared}<i> из {screen.rows.length}</i></> : '→'}
            </span>
          </Link>
          <Link to="/companies" className="hp-card">
            <span className="hp-card-text">
              <b>Все компании</b>
              <small>Цена, опорная стоимость и запас прочности по каждой</small>
            </span>
            <span className="hp-card-num">{companies ? companies.length : '→'}</span>
          </Link>
          <Link to="/valuation" className="hp-card">
            <span className="hp-card-text">
              <b>Как считается стоимость</b>
              <small>Метод Грэма и Додда — коротко и по шагам</small>
            </span>
            <span className="hp-card-num">→</span>
          </Link>
        </div>
        <p className="hp-more">
          Ещё: <Link to="/market">рынок целиком</Link> · <Link to="/calendar">календарь отчётности</Link>
        </p>
      </section>

      <section className="hp-section" aria-labelledby="hp-words">
        <h2 id="hp-words" className="hp-kicker">Три слова, которые встретятся</h2>
        <dl className="hp-glossary">
          {GLOSSARY.map((g) => (
            <div key={g.term}>
              <dt>{g.term}</dt>
              <dd>{g.text}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}
