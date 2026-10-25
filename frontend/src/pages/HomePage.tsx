import React, { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getCompanies } from '../services';
import { fetchMarketScreen, type MarketRow, type MarketScreenOut } from '../services/screen.api';
import { fetchMarketOverview } from '../services/market.api';
import { CompanySearch } from '../components/SiteHeader';
import { formatPerShare } from '../utils/perShare';
import './HomePage.css';

/**
 * Главная — приветственная страница: что это за сайт, как им пользоваться,
 * как выглядит ответ и куда идти дальше.
 *
 * Две раскладки из одной разметки. На компьютере — полная: шаги, два живых
 * примера, метод простыми словами, разделы, «что важно знать», словарь и
 * вопросы. На телефоне длинное прячется, и страница сводится к вопросу,
 * поиску, четырём числам, примерам вбок, трём шагам и четырём разделам —
 * текста на телефоне было слишком много.
 *
 * Все цифры живые: рынок — из обзора, примеры — из скринера. Без
 * рекомендаций: «ниже расчёта» — повод разобраться, а не сигнал.
 */

/** Примеры «дешевле расчёта»: знакомые имена, первая подходящая. */
const CHEAP_PICKS = ['IRAO', 'SBER', 'MOEX', 'AFLT', 'TRNFP', 'MTSS', 'GAZP', 'ROSN'];
/** Пример «проходит отбор» — по известности. */
const KNOWN = ['LKOH', 'SBER', 'TATN', 'GAZP', 'ROSN', 'GMKN', 'YDEX', 'T', 'NVTK', 'PLZL'];

const ru = (n: number, digits = 1) => n.toLocaleString('ru-RU', { maximumFractionDigits: digits }).replace('-', '−');
const rub = (n: number) => (Math.abs(n) >= 100 ? ru(n, 0) : formatPerShare(n));
const dotDate = (iso: string) => iso.slice(0, 10).split('-').reverse().join('.');

/** «Дешевле расчёта на 23%», а от двух раз — «дороже расчёта в 5,3 раза». */
const gapText = (price: number, reference: number) => {
  if (price >= reference * 2) return `Дороже расчёта в ${ru(price / reference)} раза`;
  const pct = Math.round(Math.abs(price / reference - 1) * 100);
  return `${price < reference ? 'Дешевле' : 'Дороже'} расчёта на ${pct}%`;
};

/**
 * Положение цены на шкале, где середина — опорная стоимость. Шкала
 * логарифмическая: вдвое дешевле — левый край, вдвое дороже — правый, и
 * «на 30% дешевле» не выглядит меньше, чем «на 30% дороже».
 */
const scaleX = (price: number, reference: number) => {
  const r = Math.log2(price / reference);
  return 50 + Math.max(-1, Math.min(1, r)) * 50;
};

const valued = (r: MarketRow) => Boolean(r.safety?.price && r.safety?.reference);
const ratio = (r: MarketRow) => (r.safety!.price as number) / (r.safety!.reference as number);

function Example({ row }: { row: MarketRow }) {
  const price = row.safety!.price as number;
  const reference = row.safety!.reference as number;
  const below = price < reference;
  const x = scaleX(price, reference);
  const note = below
    ? 'Это запас прочности — но и повод разобраться, почему так дёшево.'
    : row.clears
      ? 'Хорошая компания — ещё не дешёвая акция.'
      : 'Цена выше расчёта: запаса прочности нет.';
  return (
    <article className="hp-ex">
      <div className="hp-ex-head">
        <Link to={`/company/${row.id}`} className="hp-ex-name">
          {row.name} <span>{row.ticker}</span>
        </Link>
        {row.clears && <span className="hp-ex-tag">проходит отбор Грэма</span>}
      </div>
      <div className="hp-ex-nums">
        <div><span className="hp-ex-label">Цена</span><b>{rub(price)} ₽</b></div>
        <div><span className="hp-ex-label">Расчёт (опорная)</span><b>{rub(reference)} ₽</b></div>
      </div>
      <div className="hp-ex-scale" aria-hidden>
        <span className="hp-ex-axis" />
        <span className={`hp-ex-gap${below ? ' is-below' : ''}`} style={{ left: `${Math.min(x, 50)}%`, width: `${Math.abs(x - 50)}%` }} />
        <span className={`hp-ex-dot${below ? ' is-below' : ''}`} style={{ left: `${x}%` }} />
      </div>
      <div className="hp-ex-ends" aria-hidden><span>дешевле</span><span>дороже</span></div>
      <p className="hp-ex-verdict">
        <b className={below ? 'is-below' : 'is-above'}>{gapText(price, reference)}.</b>
        <span className="hp-desk"> {note}</span>
      </p>
    </article>
  );
}

const Check = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
    strokeLinecap="round" aria-hidden="true"><path d="M5 12l5 5 9-10" /></svg>
);

/** Иконки разделов — только на телефоне, где разделы плитками. */
const ICONS: Record<string, React.ReactNode> = {
  companies: <path d="M4 20V9l8-5 8 5v11M9 20v-6h6v6" />,
  screen: <path d="M4 5h16l-6 7v6l-4 2v-8z" />,
  market: <><path d="M4 19l5-6 4 3 7-9" /><path d="M4 4v15h16" /></>,
  economy: <><circle cx="12" cy="12" r="8" /><path d="M12 4v8l5 3" /></>,
};

type Section = { key: string; to: string; ask: string; title: string; text: string; short: string; external?: boolean };

const SECTIONS: Section[] = [
  { key: 'companies', to: '/companies', ask: '«Сколько стоит эта компания?»', title: 'Карточка компании',
    text: 'Отчётность за годы, опорная стоимость, график цены против неё, дивиденды и мультипликаторы.', short: 'расчёт и отчёты' },
  { key: 'screen', to: '/screen', ask: '«Что сейчас подходит по Грэму?»', title: 'Скринер',
    text: 'Требования Грэма к надёжной компании — кто проходит и чего не хватило остальным.', short: 'отбор Грэма' },
  { key: 'market', to: '/market', ask: '«Дорогой ли рынок целиком?»', title: 'Рынок',
    text: 'P/E рынка по годам и выгоднее ли сейчас облигации.', short: 'акции против ОФЗ' },
  { key: 'economy', to: '/economy', ask: '«Что с экономикой — и что было в 2022-м?»', title: 'Экономика',
    text: 'Бюджет, долг, инфляция, курс. Выберите дату в прошлом — увидите рынок и компании тогда.', short: 'бюджет, курс, снимок' },
  { key: 'calendar', to: '/calendar', ask: '«Когда новый отчёт?»', title: 'Календарь отчётности',
    text: 'Когда компании публикуют МСФО и чьи цифры уже обновились.', short: '' },
  { key: 'telegram', to: 'https://t.me/graham_analyzer', ask: '«Что изменилось?»', title: 'Telegram @graham_analyzer',
    text: 'Разборы новых отчётов и изменения в скринере.', short: '', external: true },
];

export default function HomePage() {
  // Ключи те же, что у списка компаний, скринера и «Рынка»: перейдёшь туда —
  // уже загружено.
  const { data: companies } = useQuery({ queryKey: ['companies'], queryFn: getCompanies, staleTime: 10 * 60 * 1000 });
  const { data: screen } = useQuery<MarketScreenOut>({
    queryKey: ['screen-market', 'defensive', false],
    queryFn: () => fetchMarketScreen('defensive', false),
    staleTime: 5 * 60 * 1000,
  });
  const { data: market } = useQuery({ queryKey: ['market-overview'], queryFn: fetchMarketOverview, staleTime: 30 * 60 * 1000 });

  // Два примера: знакомое имя дешевле расчёта и компания, прошедшая отбор (по
  // известности). Не нашлось — берём что есть, но не одну и ту же дважды.
  const examples = useMemo(() => {
    const rows = (screen?.rows ?? []).filter(valued);
    const byTicker = new Map(rows.map((r) => [r.ticker, r]));
    const known = (list: string[]) => list.map((t) => byTicker.get(t)).filter((r): r is MarketRow => Boolean(r));
    const cheap = known(CHEAP_PICKS).find((r) => ratio(r) < 1)
      ?? rows.filter((r) => ratio(r) < 1).sort((a, b) => ratio(b) - ratio(a))[0];
    const passed = known(KNOWN).find((r) => r.clears && r !== cheap)
      ?? rows.find((r) => r.clears && r !== cheap)
      ?? known(KNOWN).find((r) => r !== cheap);
    return [cheap, passed].filter((r): r is MarketRow => Boolean(r));
  }, [screen]);

  const cleared = screen ? screen.rows.filter((r) => r.clears).length : null;
  const now = market?.valuation.find((y) => y.year === 'now') ?? null;

  return (
    <div className="hp">
      <section className="hp-hero">
        <p className="hp-kicker hp-desk">Добро пожаловать</p>
        <h1>
          <span className="hp-desk">Узнайте, дорого или дёшево стоит акция — по отчётам компании</span>
          <span className="hp-mob">Дорого или дёшево стоит акция?</span>
        </h1>
        <p className="hp-lede">
          <span className="hp-desk">
            Сайт берёт отчёты МСФО компании за много лет и считает, сколько она стоит по методу Бенджамина
            Грэма. Потом сравнивает с ценой на бирже. Вы сразу видите: цена ниже расчёта или выше — и откуда
            взято каждое число.
          </span>
          <span className="hp-mob">Считаем по отчётам компании за много лет и сравниваем с ценой на бирже.</span>
        </p>
        <div className="hp-search"><CompanySearch /></div>
        <ul className="hp-checks hp-desk">
          <li><Check />Бесплатно</li>
          <li><Check />Без регистрации</li>
          <li><Check />Работает на телефоне</li>
          <li><Check />Без советов «купи-продай»</li>
        </ul>
        <p className="hp-checks-short hp-mob">Бесплатно · без регистрации · без советов</p>
        <p className="hp-first hp-desk"><a href="#hp-steps">Впервые здесь? Как пользоваться — за минуту ↓</a></p>
      </section>

      <section className="hp-today" aria-label="Рынок сегодня">
        <Link to="/market" className="hp-fig">
          <span className="hp-fig-label">P/E рынка</span>
          <span className="hp-fig-num">{now ? ru(now.pe) : '…'}</span>
          <span className="hp-fig-sub">рублей цены за рубль прибыли</span>
        </Link>
        <Link to="/market" className="hp-fig">
          <span className="hp-fig-label">Акции против ОФЗ</span>
          <span className="hp-fig-num">{now?.premium != null ? `${now.premium >= 0 ? '+' : ''}${ru(now.premium)} п.п.` : '…'}</span>
          <span className="hp-fig-sub">
            {now?.ofz10 != null ? `${ru(now.earnings_yield)}% прибыли на рубль цены против ${ru(now.ofz10)}% у ОФЗ` : 'прибыль к цене против ОФЗ'}
          </span>
        </Link>
        <Link to="/screen" className="hp-fig">
          <span className="hp-fig-label">Проходят отбор Грэма</span>
          <span className="hp-fig-num">{cleared !== null && screen ? <>{cleared}<small> из {screen.rows.length}</small></> : '…'}</span>
          <span className="hp-fig-sub">компаний с проверенными отчётами</span>
        </Link>
        <Link to="/companies" className="hp-fig">
          <span className="hp-fig-label">Компаний в базе</span>
          <span className="hp-fig-num">{companies ? companies.length : '…'}</span>
          <span className="hp-fig-sub">отчёты МСФО за много лет</span>
        </Link>
      </section>

      <section id="hp-steps" className="hp-block hp-steps-block" aria-labelledby="hp-steps-h">
        <div className="hp-block-head">
          <h2 id="hp-steps-h">
            <span className="hp-desk">Как пользоваться — три шага</span>
            <span className="hp-mob">Как пользоваться</span>
          </h2>
        </div>
        <ol className="hp-steps">
          <li>
            <span className="hp-step-num">1</span>
            <div>
              <h3>Найдите компанию</h3>
              <p className="hp-desk">Напишите название или тикер в поиске: «Сбербанк», «Лукойл», «SBER».</p>
            </div>
          </li>
          <li>
            <span className="hp-step-num">2</span>
            <div>
              <h3><span className="hp-desk">Посмотрите на шкалу</span><span className="hp-mob">Левее середины шкалы — дешевле</span></h3>
              <p className="hp-desk">Середина — расчётная стоимость. Точка левее — цена ниже расчёта, правее — выше. Рядом написано, на сколько процентов.</p>
            </div>
          </li>
          <li>
            <span className="hp-step-num">3</span>
            <div>
              <h3><span className="hp-desk">Нажмите на любое число</span><span className="hp-mob">Нажмите на число — увидите источник</span></h3>
              <p className="hp-desk">Увидите, из какого отчёта оно взято, когда отчёт вышел и сверено ли число. Ничего не нужно принимать на веру.</p>
            </div>
          </li>
        </ol>
      </section>

      {examples.length > 0 && (
        <section className="hp-block hp-examples-block" aria-labelledby="hp-ex-h">
          <div className="hp-block-head">
            <h2 id="hp-ex-h">Так выглядит ответ</h2>
            {examples.length > 1 && <span className="hp-mob hp-swipe">листайте →</span>}
          </div>
          <p className="hp-note hp-desk">
            {examples.length === 2 ? 'Два примера' : 'Пример'}{market ? ` на ${dotDate(market.as_of)}` : ''}. Середина шкалы — опорная (расчётная) стоимость.
          </p>
          <div className="hp-examples">
            {examples.map((r) => <Example key={r.id} row={r} />)}
          </div>
          <p className="hp-warn">
            <span className="hp-desk">
              <b>Важно:</b> «ниже расчёта» — не значит «надо покупать». Иногда акция дешёвая не просто так, и у
              оценки на этот случай есть признаки ловушки стоимости. Сайт показывает расчёт, а решение всегда за вами.
            </span>
            <span className="hp-mob">Дешевле — не значит «покупай». Это расчёт, а не совет.</span>
          </p>
        </section>
      )}

      <section className="hp-block hp-desk" aria-labelledby="hp-how">
        <div className="hp-block-head"><h2 id="hp-how">Метод Грэма простыми словами</h2></div>
        <p className="hp-plain">
          Бенджамин Грэм — учитель Уоррена Баффета. Его идея: акция — доля в настоящем бизнесе, и стоимость
          бизнеса можно посчитать по его отчётам. Это как купить квартиру под сдачу: смотришь, сколько она
          приносит за много лет, а не за один удачный месяц, и сравниваешь с надёжным вкладом. Если цена заметно
          ниже — есть запас на случай ошибки.
        </p>
        <ol className="hp-method">
          <li>
            <span className="hp-method-num">1</span>
            <h3>Отчёты за много лет</h3>
            <p>Отчётность МСФО за 10–20 лет, приведённая к одной шкале: валюта, дробления акций, «последние 12 месяцев» из полугодий.</p>
          </li>
          <li>
            <span className="hp-method-num">2</span>
            <h3>Средняя прибыль и ставка ОФЗ</h3>
            <p>Средняя прибыль за 3, 7 и 10 лет без разовых списаний — против того, сколько без риска платит государство.</p>
          </li>
          <li>
            <span className="hp-method-num">3</span>
            <h3>Опорная стоимость и запас</h3>
            <p>Полоса оценки и осторожная опорная цена. Разница с биржевой ценой — запас прочности.</p>
          </li>
        </ol>
        <p className="hp-more"><Link to="/valuation">Подробно, с формулами — «Как считается стоимость» →</Link></p>
      </section>

      <section className="hp-block hp-where-block" aria-labelledby="hp-where">
        <div className="hp-block-head">
          <h2 id="hp-where">
            <span className="hp-desk">Куда пойти дальше</span>
            <span className="hp-mob">Что здесь есть</span>
          </h2>
        </div>
        <div className="hp-where">
          {SECTIONS.map((s) => {
            const body = (
              <>
                {ICONS[s.key] && (
                  <svg className="hp-where-icon hp-mob" width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                    strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{ICONS[s.key]}</svg>
                )}
                <span className="hp-where-ask hp-desk">{s.ask}</span>
                <b>{s.title}</b>
                <span className="hp-where-text hp-desk">
                  {s.text}{s.key === 'screen' && cleared !== null && screen ? ` Сейчас — ${cleared} из ${screen.rows.length}.` : ''}
                </span>
                {s.short && <span className="hp-where-text hp-mob">{s.short}</span>}
              </>
            );
            // Календарь и Telegram на телефоне — строкой ссылок внизу, не плитками.
            const cls = `hp-where-item${s.short ? '' : ' hp-desk'}`;
            return s.external
              ? <a key={s.key} href={s.to} target="_blank" rel="noreferrer" className={cls}>{body}</a>
              : <Link key={s.key} to={s.to} className={cls}>{body}</Link>;
          })}
        </div>
      </section>

      <section className="hp-block hp-desk" aria-labelledby="hp-know">
        <div className="hp-block-head"><h2 id="hp-know">Что важно знать заранее</h2></div>
        <div className="hp-know">
          <div>
            <h3>Что нужно от вас</h3>
            <ul>
              <li>Телефон или компьютер — устанавливать ничего не нужно.</li>
              <li>Пять минут на первую компанию. Лучше начать с той, акции которой у вас уже есть.</li>
              <li>Знать финансы не обязательно: у сложных слов есть подсказки со знаком «?».</li>
              <li>Регистрироваться не нужно.</li>
            </ul>
          </div>
          <div>
            <h3>Чего сайт не делает</h3>
            <ul>
              <li>Не советует покупать или продавать и не прогнозирует цену.</li>
              <li>Не учитывает новости, санкции и решения властей — только отчётность и ставки.</li>
              <li>Банки оценивает по своим показателям: общий метод к ним подходит хуже.</li>
              <li>Числа сверены, но ошибки возможны — у каждого видно, откуда оно.</li>
            </ul>
          </div>
        </div>
      </section>

      <section className="hp-block hp-desk" aria-labelledby="hp-words">
        <div className="hp-block-head"><h2 id="hp-words">Четыре слова, которые встретятся везде</h2></div>
        <dl className="hp-words">
          <div><dt>Опорная стоимость</dt><dd>Осторожная оценка акции по средней прибыли и балансу. От неё считается запас.</dd></div>
          <div><dt>Запас прочности</dt><dd>На сколько цена ниже опорной. Грэм покупал с запасом — на случай ошибки в оценке.</dd></div>
          <div><dt>Нормализованная прибыль</dt><dd>Средняя за годы без разовых списаний: один удачный или провальный год её не сбивает.</dd></div>
          <div><dt>Отбор Грэма</dt><dd>Требования к надёжной компании: размер, устойчивость, дивиденды, рост, цена.</dd></div>
        </dl>
      </section>

      <section className="hp-block hp-desk" aria-labelledby="hp-faq">
        <div className="hp-block-head"><h2 id="hp-faq">Частые вопросы</h2></div>
        <div className="hp-faq">
          <details open>
            <summary>Это советы, что покупать?</summary>
            <p>Нет. Это расчёт по известному методу. Что будет с ценой, никто не знает, и сайт не советует.</p>
          </details>
          <details>
            <summary>Откуда цифры и можно ли им верить?</summary>
            <p>
              Отчётность — из раскрытия компаний (МСФО), цены — Московская биржа, ставки и экономика — Банк России и
              Минфин. Отчёты сверены, но ошибки бывают: у каждого числа видно, откуда оно, — можно проверить самому.
            </p>
          </details>
          <details>
            <summary>Почему расчёт отличается от прогнозов аналитиков?</summary>
            <p>Аналитики прогнозируют будущее. Сайт считает по тому, что компания уже заработала за много лет, — это осторожнее и проще проверить.</p>
          </details>
          <details>
            <summary>Почему «опорная», а не «справедливая» цена?</summary>
            <p>Точной справедливой цены не знает никто. Опорная — осторожная часть оценки, от которой удобно считать запас прочности.</p>
          </details>
          <details>
            <summary>Сколько это стоит?</summary>
            <p>Бесплатно и без регистрации.</p>
          </details>
        </div>
      </section>

      <section className="hp-cta hp-desk">
        <div>
          <b>Начните с компании, акции которой у вас уже есть</b>
          <span>Так проще всего понять, что показывает расчёт.</span>
        </div>
        <Link to="/companies">Найти компанию</Link>
      </section>

      <p className="hp-mob-links hp-mob">
        <Link to="/valuation">Как считается</Link> · <Link to="/calendar">Календарь</Link> ·{' '}
        <a href="https://t.me/graham_analyzer" target="_blank" rel="noreferrer">Telegram</a>
      </p>
    </div>
  );
}
