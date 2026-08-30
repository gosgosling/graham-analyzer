import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { getMarketMultiple, type MarketMultipleOut } from '../services/valuation.api';
import './MarketMultiple.css';

/**
 * Разбор базового множителя рынка.
 *
 * Страница существует не ради числа, а ради того, чтобы было видно, из чего
 * оно сложилось. Из четырёх аргументов формулы только один взят из отчётов,
 * один выведен арифметикой, а два назначены суждением — и пока это не
 * показано рядом с ответом, множитель читается как измерение, каковым он
 * на две трети не является.
 */

/** Происхождение величины. Расставлено по всей странице одинаково. */
type Origin = 'fact' | 'derived' | 'judgement';

const ORIGIN: Record<Origin, { label: string; hint: string }> = {
  fact: {
    label: 'из отчётов',
    hint: 'Посчитано по данным компаний, спорить не о чем.',
  },
  derived: {
    label: 'выведено',
    hint: 'Получено арифметикой из величин, взятых из отчётов.',
  },
  judgement: {
    label: 'суждение',
    hint: 'Назначено человеком. Проверить нечем — можно только не согласиться.',
  },
};

function OriginTag({ origin }: { origin: Origin }) {
  const o = ORIGIN[origin];
  return (
    <span className={`mm-origin mm-origin--${origin}`} title={o.hint}>
      {o.label}
    </span>
  );
}

const fmt = (v: number | null | undefined, digits = 2, suffix = '') =>
  v === null || v === undefined ? '—' : `${v.toFixed(digits)}${suffix}`;

const money = (v: number | null | undefined) => {
  if (v === null || v === undefined) return '—';
  const trillions = v / 1_000_000;
  return trillions >= 1
    ? `${trillions.toFixed(2)} трлн ₽`
    : `${(v / 1_000).toFixed(1)} млрд ₽`;
};

/** Аргумент формулы: что это, сколько у нас и откуда взялось. */
function Argument({
  symbol,
  name,
  value,
  origin,
  children,
}: {
  symbol: string;
  name: string;
  value: string;
  origin: Origin;
  children: React.ReactNode;
}) {
  return (
    <section className="mm-arg">
      <header className="mm-arg-head">
        <span className="mm-arg-symbol">{symbol}</span>
        <div className="mm-arg-title">
          <h3>{name}</h3>
          <OriginTag origin={origin} />
        </div>
        <span className="mm-arg-value">{value}</span>
      </header>
      <div className="mm-arg-body">{children}</div>
    </section>
  );
}

/**
 * Числовая ось: где фактическая цена относительно двух расчётных крайностей.
 *
 * Смысл в том, что рынок обычно стоит между «сегодняшняя ставка навсегда» и
 * «ставка вернулась к норме», и его положение на этой оси — содержательное
 * утверждение, в отличие от одиночного множителя.
 */
function Scale({ low, actual, high }: { low: number; actual: number; high: number }) {
  const span = high - low;
  const at = span > 0 ? Math.min(Math.max((actual - low) / span, 0), 1) : 0.5;
  return (
    <div className="mm-scale">
      <div className="mm-scale-track">
        <div className="mm-scale-marker" style={{ left: `${at * 100}%` }}>
          <span className="mm-scale-dot" />
          <span className="mm-scale-label">
            {actual.toFixed(2)}
            <em>рынок</em>
          </span>
        </div>
      </div>
      <div className="mm-scale-ends">
        <span>
          <strong>{low.toFixed(2)}</strong>
          <em>сегодняшняя ставка навсегда</em>
        </span>
        <span className="mm-scale-right">
          <strong>{high.toFixed(2)}</strong>
          <em>ставка вернулась к норме</em>
        </span>
      </div>
    </div>
  );
}

function Content({ data }: { data: MarketMultipleOut }) {
  const { assumption: a, snapshot: s, current, normalized, implied, reference } = data;
  const spread = current?.spread ?? null;

  return (
    <div className="mm-page">
      <header className="mm-head">
        <h1>Базовый множитель рынка</h1>
        <p className="mm-lede">
          Какой P/E оправдан для рынка в целом. Множитель отдельной компании без
          этой опоры повисает в воздухе: P/E&nbsp;12 на дорогом и на дешёвом рынке
          говорят о разном.
        </p>
      </header>

      {/* ── Вывод ──────────────────────────────────────────────────────── */}
      <section className="mm-block">
        <h2>Откуда берётся формула</h2>
        <p>
          Это модель Гордона, повёрнутая так, чтобы отвечать на вопрос «какой
          множитель оправдан», а не «какая цена справедлива». Вывод занимает три
          шага.
        </p>

        <ol className="mm-derivation">
          <li>
            <span className="mm-step">1</span>
            <div>
              <p>
                Акция приносит владельцу дивиденды и ничего больше. Значит её цена —
                сумма всех будущих выплат, приведённых к сегодня.
              </p>
              <code>P = D/(1+K) + D(1+g)/(1+K)² + D(1+g)²/(1+K)³ + …</code>
            </div>
          </li>
          <li>
            <span className="mm-step">2</span>
            <div>
              <p>
                Это убывающая геометрическая прогрессия, и она сворачивается в одну
                дробь.
              </p>
              <code>P = D / (K − g)</code>
            </div>
          </li>
          <li>
            <span className="mm-step">3</span>
            <div>
              <p>
                Делим обе части на прибыль. Слева получается P/E — множитель. Справа
                D/E — доля прибыли, уходящая на дивиденды.
              </p>
              <code className="mm-code-final">Множитель = payout / (K − g)</code>
            </div>
          </li>
        </ol>

        <div className="mm-note">
          <strong>Почему требуется K&nbsp;&gt;&nbsp;g.</strong> Это не техническая
          оговорка. При g&nbsp;≥&nbsp;K каждое следующее слагаемое больше предыдущего
          и сумма бесконечна. Экономически это значит «компания растёт быстрее
          экономики вечно», то есть однажды становится всей экономикой. Поэтому
          формула в таком случае честно отказывается считать.
        </div>
      </section>

      {/* ── Аргументы ──────────────────────────────────────────────────── */}
      <section className="mm-block">
        <h2>Разбор аргументов</h2>

        <Argument
          symbol="payout"
          name="Доля прибыли на дивиденды"
          value={fmt(a.payout_used, 2, '%')}
          origin={a.payout_from_data ? 'fact' : 'judgement'}
        >
          <p>
            Только те деньги, которые доходят до владельца. Нераспределённая
            прибыль в формулу входит не напрямую, а через рост&nbsp;<code>g</code>:
            она работает, лишь если превращается в будущие дивиденды.
          </p>
          <div className="mm-calc">
            <span>дивиденды {money(s.total_dividends)}</span>
            <span className="mm-op">÷</span>
            <span>прибыль {money(s.total_profit)}</span>
            <span className="mm-op">=</span>
            <strong>{fmt(s.payout, 2, '%')}</strong>
          </div>
          <p className="mm-small">
            Совокупно, а не в среднем по компаниям: множитель считается для рынка, а
            рынок — взвешенная сумма, где Сбербанк весит больше Ленэнерго. Считано по{' '}
            {s.companies} компаниям за {s.year} год — тем, что помечены проверенными
            и прошли аудит без дефектов.
          </p>
        </Argument>

        <Argument
          symbol="K"
          name="Требуемая доходность"
          value={fmt(current?.required_return, 2, '%')}
          origin="judgement"
        >
          <p>
            Сколько мы хотим зарабатывать на вложении в акции. Складывается из двух
            частей, и они очень разного качества.
          </p>
          <div className="mm-split">
            <div>
              <span className="mm-split-label">
                безрисковая ставка <OriginTag origin="fact" />
              </span>
              <span className="mm-split-value">{fmt(a.risk_free_rate, 2, '%')}</span>
              <p className="mm-small">
                Доходность длинных ОФЗ. Наблюдаемая величина: её можно посмотреть на
                бирже.
              </p>
            </div>
            <div className="mm-split-plus">+</div>
            <div>
              <span className="mm-split-label">
                премия за риск <OriginTag origin="judgement" />
              </span>
              <span className="mm-split-value">{fmt(a.risk_premium, 2, ' п.п.')}</span>
              <p className="mm-small">
                Надбавка за то, что акция не облигация. Измерить нечем. У авторов
                книги для США 1987&nbsp;года — 2,75&nbsp;п.п.
              </p>
            </div>
          </div>
          {a.normalized_risk_free_rate !== null && (
            <div className="mm-note mm-note--warn">
              <strong>Ставка подставляется как вечная.</strong> Формула считает{' '}
              <code>K</code> доходностью на бесконечность, то есть предполагает
              сегодняшние {fmt(a.risk_free_rate, 1, '%')} навсегда. Когда кривая на
              многолетних максимумах, это занижает множитель, и вина тут не
              компаний, а момента. Поэтому рядом считается вариант со ставкой{' '}
              {fmt(a.normalized_risk_free_rate, 1, '%')}.
            </div>
          )}
        </Argument>

        <Argument
          symbol="g"
          name="Рост дивидендов"
          value={fmt(a.dividend_growth, 2, '%')}
          origin="derived"
        >
          <p>
            Здесь у книги слабое место: она обращается с <code>payout</code> и{' '}
            <code>g</code> как с независимыми величинами. Они не независимы — расти
            можно только на то, что не раздал. Раздал всё, и источника роста не
            осталось.
          </p>
          <div className="mm-calc">
            <span>отдача на капитал {fmt(s.roe, 2, '%')}</span>
            <span className="mm-op">×</span>
            <span>(1 − {fmt(s.payout, 2, '%')})</span>
            <span className="mm-op">=</span>
            <strong>{fmt(s.sustainable_growth, 2, '%')}</strong>
          </div>
          <p className="mm-small">
            Поэтому рост не назначается суждением, а выводится. Величина{' '}
            <b>номинальная</b>, как и отдача на капитал: при инфляции около 7% рост
            в {fmt(s.sustainable_growth, 1, '%')} означает реальный рост около нуля.
            Смешать номинальную ставку с реальным ростом — самая частая ошибка в
            этой формуле, и она даёт множитель вдвое не тот.
          </p>
        </Argument>

        <Argument
          symbol="K − g"
          name="Зазор"
          value={fmt(spread, 2, ' п.п.')}
          origin="derived"
        >
          <p>
            Весь ответ висит на этой разности, потому что мы делим на маленькое
            число. Отсюда главный вывод главы&nbsp;32: множитель рынка — про ставки,
            а не про качество компаний. У авторов средние по эпохам 10,1 / 17,6 /
            10,1, и разброс вдвое объясняется режимом ставок.
          </p>
          {current?.fragile && (
            <div className="mm-note mm-note--warn">
              Зазор мал: ответ определяется погрешностью входных величин сильнее,
              чем состоянием рынка.
            </div>
          )}
        </Argument>
      </section>

      {/* ── Результат ──────────────────────────────────────────────────── */}
      <section className="mm-block">
        <h2>Результат</h2>
        <div className="mm-results">
          <div className="mm-result">
            <span className="mm-result-label">при сегодняшней ставке</span>
            <span className="mm-result-value">{fmt(current?.value)}</span>
            <span className="mm-result-sub">
              {fmt(a.payout_used, 2, '%')} ÷ {fmt(current?.spread, 2)} п.п.
            </span>
            <span className="mm-result-sub">
              доходность {fmt(current?.earnings_yield, 2, '%')}
            </span>
          </div>
          {normalized && (
            <>
              <div className="mm-result-arrow">
                {data.rate_effect ? `×${data.rate_effect}` : ''}
              </div>
              <div className="mm-result">
                <span className="mm-result-label">если ставки нормализуются</span>
                <span className="mm-result-value">{fmt(normalized.value)}</span>
                <span className="mm-result-sub">
                  {fmt(a.payout_used, 2, '%')} ÷ {fmt(normalized.spread, 2)} п.п.
                </span>
                <span className="mm-result-sub">
                  доходность {fmt(normalized.earnings_yield, 2, '%')}
                </span>
              </div>
            </>
          )}
        </div>
        {data.rate_effect && (
          <p className="mm-small">
            Разница в {data.rate_effect} раза — целиком про момент в цикле ставок. Ни
            одна компания за неё не отвечает.
          </p>
        )}
      </section>

      {/* ── Где рынок на самом деле ────────────────────────────────────── */}
      {current?.value && normalized?.value && s.observed_multiple && (
        <section className="mm-block">
          <h2>Где рынок на самом деле</h2>
          <Scale
            low={current.value}
            actual={s.observed_multiple}
            high={normalized.value}
          />
          <p>
            Проверенные {s.companies} компаний стоят {money(s.market_cap)} при
            прибыли {money(s.profit_ltm)} за последние двенадцать месяцев — то есть{' '}
            <b>{fmt(s.observed_multiple)}</b> прибыли.
          </p>
          <p>
            Цена лежит <b>между</b> двумя расчётными крайностями. Значит рынок не
            считает сегодняшнюю ставку вечной, но и полной нормализации не
            закладывает.
          </p>
        </section>
      )}

      {/* ── Обратный ход ───────────────────────────────────────────────── */}
      <section className="mm-block">
        <h2>Что рынок закладывает сам</h2>
        <p>
          Формулу можно развернуть: вместо того чтобы назначить величину и потом
          удивляться расхождению с ценой, честнее спросить, какое значение уже
          сидит в цене.
        </p>
        <table className="mm-table">
          <tbody>
            <tr>
              <td>
                если премия за риск {fmt(a.risk_premium, 1, ' п.п.')}, то рост
                дивидендов
              </td>
              <td className="mm-num">
                {fmt(implied.growth_at_stated_premium, 2, '%')}
              </td>
              <td className="mm-vs">против {fmt(a.dividend_growth, 2, '%')} у нас</td>
            </tr>
            <tr>
              <td>если рост {fmt(a.dividend_growth, 1, '%')}, то премия за риск</td>
              <td className="mm-num">
                {fmt(implied.premium_at_stated_growth, 2, ' п.п.')}
              </td>
              <td className="mm-vs">против {fmt(a.risk_premium, 2, ' п.п.')} у нас</td>
            </tr>
            <tr>
              <td>
                если премия и рост приняты, то долгосрочная безрисковая ставка
              </td>
              <td className="mm-num">
                {fmt(implied.risk_free_at_stated_premium_and_growth, 2, '%')}
              </td>
              <td className="mm-vs">
                против {fmt(a.risk_free_rate, 2, '%')} сегодня
              </td>
            </tr>
          </tbody>
        </table>
        <div className="mm-note">
          Читается так: <b>если</b> верить, что дивиденды растут на{' '}
          {fmt(a.dividend_growth, 1, '%')} в год, <b>то</b> рынок доплачивает за
          риск всего {fmt(implied.premium_at_stated_growth, 1, ' п.п.')} сверх
          госбумаги. Либо рост на самом деле выше, либо премии на этом рынке
          действительно почти нет. Оба вывода содержательны — в отличие от одного
          числа «{fmt(current?.value)}».
        </div>
      </section>

      {/* ── Чувствительность ───────────────────────────────────────────── */}
      {data.sensitivity.length > 0 && (
        <section className="mm-block">
          <h2>Цена произвола в премии за риск</h2>
          <p>
            Премия — самая произвольная из входных величин, поэтому показывать её
            влияние обязательно.
          </p>
          <table className="mm-table mm-table--compact">
            <thead>
              <tr>
                <th>премия за риск</th>
                <th className="mm-num">множитель</th>
              </tr>
            </thead>
            <tbody>
              {data.sensitivity.map((row) => (
                <tr key={row.risk_premium}>
                  <td>{fmt(row.risk_premium, 1, ' п.п.')}</td>
                  <td className="mm-num">
                    {row.value !== null ? fmt(row.value) : row.problem}
                  </td>
                </tr>
              ))}
              <tr className="mm-row-current">
                <td>{fmt(a.risk_premium, 1, ' п.п.')} — принято у нас</td>
                <td className="mm-num">{fmt(current?.value)}</td>
              </tr>
            </tbody>
          </table>
          <p className="mm-small">
            При высокой ставке зазор <code>K − g</code> велик, и произвол в премии
            влияет слабо. У авторов книги зазор был 3,75&nbsp;п.п., и тот же сдвиг на
            пункт менял ответ на треть. То есть высокие ставки делают формулу
            устойчивее.
          </p>
        </section>
      )}

      {/* ── Книга ──────────────────────────────────────────────────────── */}
      <section className="mm-block">
        <h2>Для сравнения: расчёт из книги</h2>
        <p className="mm-small">
          Коттл, Мюррей, Блок. «Анализ ценных бумаг», 5-е изд., гл. 32, с. 605–606.
          Расчёт для S&amp;P&nbsp;400 на 1987 год.
        </p>
        <table className="mm-table mm-table--compact">
          <tbody>
            <tr>
              <td>ставка облигаций Aaa</td>
              <td className="mm-num">{fmt(reference.book.risk_free_rate, 2, '%')}</td>
            </tr>
            <tr>
              <td>премия за риск</td>
              <td className="mm-num">{fmt(reference.book.risk_premium, 2, ' п.п.')}</td>
            </tr>
            <tr>
              <td>рост дивидендов</td>
              <td className="mm-num">
                {fmt(reference.book.dividend_growth, 2, '%')}
              </td>
            </tr>
            <tr>
              <td>выплата</td>
              <td className="mm-num">{fmt(reference.book.payout, 2, '%')}</td>
            </tr>
            <tr className="mm-row-current">
              <td>множитель</td>
              <td className="mm-num">{fmt(reference.book_multiple)}</td>
            </tr>
          </tbody>
        </table>
        <p className="mm-small">
          Средний множитель рынка США за 115 лет (1871–1985) —{' '}
          {reference.historic_average}, средние за пятилетия от{' '}
          {reference.historic_range[0]} до {reference.historic_range[1]}. Это
          справка, а не проверка: при российских ставках формула честно даёт
          величину втрое меньше, и подгонять её под чужой диапазон значило бы
          выбросить единственное, что формула умеет — реагировать на ставку.
        </p>
      </section>

      {/* ── Честность ──────────────────────────────────────────────────── */}
      <section className="mm-block mm-block--honesty">
        <h2>Что здесь факт, а что суждение</h2>
        <ul className="mm-honesty">
          <li>
            <OriginTag origin="fact" /> выплата {fmt(a.payout_used, 2, '%')} и отдача
            на капитал {fmt(s.roe, 2, '%')} — посчитаны по отчётам {s.companies}{' '}
            компаний
          </li>
          <li>
            <OriginTag origin="fact" /> безрисковая ставка{' '}
            {fmt(a.risk_free_rate, 2, '%')} — наблюдается на бирже
          </li>
          <li>
            <OriginTag origin="derived" /> рост {fmt(a.dividend_growth, 2, '%')} —
            выведен как отдача × (1 − выплата)
          </li>
          <li>
            <OriginTag origin="judgement" /> премия за риск{' '}
            {fmt(a.risk_premium, 2, ' п.п.')} — назначена, проверить нечем
          </li>
          {a.normalized_risk_free_rate !== null && (
            <li>
              <OriginTag origin="judgement" /> нормализованная ставка{' '}
              {fmt(a.normalized_risk_free_rate, 2, '%')} — назначена
            </li>
          )}
        </ul>
        {a.note && (
          <div className="mm-note">
            <strong>Приписка к допущениям за {a.year} год.</strong> {a.note}
          </div>
        )}
        <p className="mm-small">
          Величины хранятся по годам и меняются командой{' '}
          <code>python -m scripts.set_market_assumption</code>. Умолчаний у неё нет:
          пока суждения не названы явно, она отказывается считать.
        </p>
        <div className="mm-note mm-note--warn">
          <strong>Осторожно с обобщением.</strong> {s.companies} компаний — не
          «российский рынок». В этой выборке доминируют нефтегаз и металлурги, и
          многие из них на дне цикла. Величины на этой странице описывают её, а не
          рынок целиком.
        </div>
      </section>
    </div>
  );
}

export default function MarketMultiple() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['market-multiple'],
    queryFn: getMarketMultiple,
  });

  if (isLoading) return <div className="mm-state">Считаю…</div>;
  if (error || !data) {
    return (
      <div className="mm-state mm-state--error">
        Допущений об уровне рынка нет. Задайте их командой{' '}
        <code>python -m scripts.set_market_assumption</code>
      </div>
    );
  }
  return <Content data={data} />;
}
