import React, { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { fetchThresholds, type ThresholdProfile, type ThresholdRule, type ThresholdsOut } from '../services/screen.api';
import { PHONE_QUERY, useMediaQuery } from '../hooks/useMediaQuery';
import './MarketOverview.css';
import './ThresholdsPage.css';

/**
 * Отраслевые пороги: почему у нефтяника ликвидность ≥ 1, а у завода ≥ 2.
 *
 * Страница объясняет то, что скринер делает молча: какие требования взяты из
 * книги как есть, какие пересчитаны под отрасль и как именно, где мы отошли
 * от Грэма намеренно. Все числа — из того же расчёта, что и скринер
 * (`/screen/thresholds`), поэтому текст не может разойтись с отбором.
 */

const decimal = (t: string) => t.replace(/(\d)\.(\d)/g, '$1,$2');
const num = (v: number | null) => (v === null ? '—' : String(v).replace('.', ','));

/** Подписи полос профиля — те же величины, что красятся в карточке компании. */
const BAND_LABEL: Record<string, string> = {
  pe: 'P/E',
  pb: 'P/B',
  de: 'Обязательства к капиталу',
  cr: 'Текущая ликвидность',
  roe: 'Отдача на капитал, %',
  dy: 'Дивидендная доходность, %',
  cir: 'Издержки к доходам, %',
};

/** Требование, которого в своде нет ни для одной отрасли (выручка у активного), не показываем. */
const visibleRules = (rules: ThresholdRule[]) =>
  rules.filter((r) => Object.values(r.applied).some((c) => c.status !== 'out' && c.text !== '—'));

/** Пример пересчёта — на живых числах профиля, а не выдуманных. */
function Example({ data }: { data: ThresholdsOut }) {
  const base = data.profiles.find((p) => p.key === data.base_profile);
  const oil = data.profiles.find((p) => p.key === 'oil_gas_mining');
  const baseCr = base?.bands.cr?.good;
  const oilCr = oil?.bands.cr?.good;
  if (!base || !oil || !baseCr || !oilCr) return null;
  const ratio = oilCr / baseCr;
  return (
    <div className="th-example">
      <div className="th-example-step">
        <span>Промышленность, «хорошо»</span>
        <b>ликвидность ≥ {num(baseCr)}</b>
        <small>это и есть число Грэма</small>
      </div>
      <div className="th-example-step">
        <span>Нефтегаз и металлургия, «хорошо»</span>
        <b>ликвидность ≥ {num(oilCr)}</b>
        <small>мощный поток покрывает короткий долг</small>
      </div>
      <div className="th-example-step">
        <span>Отрасль мягче промышленности</span>
        <b>в {num(1 / ratio)} раза</b>
        <small>{num(oilCr)} / {num(baseCr)} = {num(Math.round(ratio * 100) / 100)}</small>
      </div>
      <div className="th-example-step th-example-step--result">
        <span>Порог свода × {num(Math.round(ratio * 100) / 100)}</span>
        <b>защитный: 2 → {num(2 * ratio)}</b>
        <b>активный: 1,5 → {num(1.5 * ratio)}</b>
      </div>
    </div>
  );
}

function Matrix({ data, standard }: { data: ThresholdsOut; standard: string }) {
  const std = data.standards.find((s) => s.key === standard) ?? data.standards[0];
  return (
    <div className="th-matrix-wrap">
      <table className="th-matrix">
        <thead>
          <tr>
            <th scope="col" className="th-sticky">Требование</th>
            <th scope="col">У Грэма</th>
            {data.profiles.map((p) => <th key={p.key} scope="col">{p.label}</th>)}
          </tr>
        </thead>
        <tbody>
          {visibleRules(std.rules).map((r) => (
            <tr key={r.metric}>
              <th scope="row" className="th-sticky" title={[r.source, r.note].filter(Boolean).join('\n')}>
                {r.label}
                {r.ours && <span className="th-ours">наше</span>}
              </th>
              <td className="th-book">{decimal(r.book_text)}</td>
              {data.profiles.map((p) => {
                const cell = r.applied[p.key];
                return (
                  <td key={p.key} className={`th-cell th-cell--${cell?.status ?? 'out'}`}>
                    {decimal(cell?.text ?? '—')}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Телефон: одна отрасль — список «требование → порог», без таблицы в десять колонок. */
function PhoneMatrix({ data, standard }: { data: ThresholdsOut; standard: string }) {
  const [profile, setProfile] = useState(data.base_profile);
  const std = data.standards.find((s) => s.key === standard) ?? data.standards[0];
  return (
    <div className="th-phone">
      <label className="th-phone-pick">
        <span>Отрасль</span>
        <select value={profile} onChange={(e) => setProfile(e.target.value)}>
          {data.profiles.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
        </select>
      </label>
      <ul className="th-phone-list">
        {visibleRules(std.rules).filter((r) => r.applied[profile]?.status !== 'out').map((r) => {
          const cell = r.applied[profile];
          return (
            <li key={r.metric}>
              <span className="th-phone-name">{r.label}{r.ours && <span className="th-ours">наше</span>}</span>
              <span className={`th-phone-val th-cell--${cell.status}`}>
                <b>{decimal(cell.text)}</b>
                {cell.status === 'shifted' && !r.ours && <small>у Грэма {decimal(r.book_text)}</small>}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function ProfileCard({ profile, base }: { profile: ThresholdProfile; base: ThresholdProfile | undefined }) {
  const keys = Object.keys(BAND_LABEL).filter((k) => profile.bands[k]);
  return (
    <article className="th-profile" id={`profile-${profile.key}`}>
      <h3>{profile.label}</h3>
      <p className="th-profile-summary">{profile.summary}</p>
      {(!profile.book_value_reliable || profile.lease_heavy) && (
        <p className="th-flags">
          {!profile.book_value_reliable && <span>балансовый капитал не отражает бизнес — P/B и ROE с осторожностью</span>}
          {profile.lease_heavy && <span>аренда по МСФО 16 раздувает обязательства — смотрим чистый долг</span>}
        </p>
      )}
      <table className="th-bands">
        <thead>
          <tr><th scope="col">Показатель</th><th scope="col">хорошо</th><th scope="col">приемлемо</th><th scope="col" title="Профиль «Промышленность» — от него считается сдвиг">база</th></tr>
        </thead>
        <tbody>
          {keys.map((k) => {
            const b = profile.bands[k];
            const g = base?.bands[k];
            const sign = b.higher_is_better ? '≥' : '≤';
            return (
              <React.Fragment key={k}>
                <tr className={b.applicable ? undefined : 'is-na'}>
                  <th scope="row">{BAND_LABEL[k]}</th>
                  {b.applicable ? (
                    <>
                      <td>{b.good !== null ? `${sign} ${num(b.good)}` : '—'}</td>
                      <td>{b.warn !== null ? `${sign} ${num(b.warn)}` : '—'}</td>
                    </>
                  ) : <td colSpan={2}>не применяется</td>}
                  <td className="th-bands-book">{g && g.applicable && g.good !== null ? `${sign} ${num(g.good)}` : '—'}</td>
                </tr>
                {b.note && (
                  <tr className="th-bands-note"><td colSpan={4}>{b.note}</td></tr>
                )}
              </React.Fragment>
            );
          })}
        </tbody>
      </table>
    </article>
  );
}

export default function ThresholdsPage() {
  const { data, isLoading, error } = useQuery({ queryKey: ['screen-thresholds'], queryFn: fetchThresholds, staleTime: 60 * 60 * 1000 });
  const [standard, setStandard] = useState('defensive');
  const isPhone = useMediaQuery(PHONE_QUERY);
  const base = useMemo(() => data?.profiles.find((p) => p.key === data.base_profile), [data]);

  return (
    <div className="mo th">
      <section className="mo-card mo-head">
        <h1>Отраслевые пороги</h1>
        <p className="mo-lede">
          Грэм вывел свои требования для промышленных компаний США 1930–40-х годов. На российском рынке 2020-х часть
          из них даёт ложный сигнал чаще, чем верный. Здесь — какие пороги скринер берёт из книги как есть, какие
          пересчитывает под отрасль и как, и где мы отошли от Грэма намеренно.
        </p>
      </section>

      <section className="mo-card">
        <div className="mo-card-head"><h2>Зачем отрасли свои пороги</h2></div>
        <ul className="th-why">
          <li>
            <b>Ликвидность меньше единицы у продуктовой сети</b> — обычное дело при быстром обороте: покупатель платит
            сразу, поставщик получает деньги через месяц. По книжной норме ≥ 2 провалилась бы вся отрасль. Риск при
            этом остаётся — если оборот встанет, платить поставщикам будет нечем, — поэтому порог ниже, но не отменён.
          </li>
          <li>
            <b>Обязательства, в разы превышающие капитал, у той же сети</b> — следствие МСФО 16: в обязательствах
            сидит аренда тысяч магазинов. Платить по ней тоже надо, поэтому порог у ритейла мягче, но есть, а
            покрытие процентов операционной прибылью отдельно проверяет оценка.
          </li>
          <li>
            <b>P/B заметно ниже единицы у сетевой компании в энергетике</b> — не дешевизна, а огромная база основных средств при доходности,
            ограниченной регулятором.
          </li>
          <li>
            <b>Ликвидность и долг банка</b> не меряются вовсе: депозиты клиентов — обязательства по природе.
            Банк оценивается своими показателями — капиталом, стоимостью риска, проблемными кредитами.
          </li>
        </ul>
      </section>

      {data && (
        <section className="mo-card">
          <div className="mo-card-head"><h2>Как сдвигается порог</h2></div>
          <p className="th-text">
            Профиль «Промышленность» — это в точности числа Грэма. Остальные профили читаются как «во сколько
            раз эта отрасль отличается от промышленной», и на столько же двигается порог выбранного свода.
            Поправка относительная, а не подстановка: так отрасль и строгость свода складываются, а не
            спорят — активный инвестор, которому Грэм разрешает ликвидность 1,5 вместо 2, получает и
            отраслевую скидку поверх своей.
          </p>
          <Example data={data} />
          <ul className="th-rules">
            <li>
              <b>Сдвигаются</b> только те требования, у которых есть отраслевая мерка: ликвидность, P/E, P/B,
              отдача на капитал и издержки банка. Размер, годы без убытка, рост и дивиденды — одинаковы для всех.
            </li>
            <li>
              <b>«Не применяется» — не провал.</b> Если мерка к отрасли не подходит (ликвидность у банка и биржи),
              требование просто не считается, и компания по нему не теряет.
            </li>
            <li>
              <b>Сдвиг не делает порог строже отраслевого «хорошо».</b> У активного свода P/B уже включает скидку
              охотника за дешевизной; без этой оговорки нефтянику пришлось бы показывать P/B 0,96 — строже и
              книги, и собственной отрасли.
            </li>
            <li>
              <b>Порог всегда виден рядом с книжным.</b> В скринере под заголовком колонки стоит действующий
              диапазон («≥ 1–2») и, если отличается, книжный («у Грэма ≥ 2»).
            </li>
          </ul>
        </section>
      )}

      {data && (
        <section className="mo-card">
          <div className="mo-card-head"><h2>Где мы отошли от книги и почему</h2></div>
          <dl className="th-ours-list">
            <div>
              <dt>Выручка не меньше {Math.round(data.min_revenue / 1000)} млрд ₽</dt>
              <dd>
                У Грэма — 100 млн $ годовой выручки в ценах 1971 года. Доллар с тех пор подешевел примерно в восемь
                раз, это около 800 млн $, или порядка 65 млрд ₽. Берём меньше: российский рынок на порядок меньше
                американского, и планка «как в США» отсекла бы почти всех.
              </dd>
            </div>
            <div>
              <dt>Дивиденды {data.dividend_years} лет подряд вместо 20</dt>
              <dd>
                Российскому рынку акций в нынешнем виде меньше тридцати лет, а выплаты массово прерывались в 2008-м,
                2020-м и 2022-м. Порог в 20 лет отсекал бы почти всех по причине, к самим компаниям отношения не
                имеющей. Десять лет — полный экономический цикл с запасом.
              </dd>
            </div>
            <div>
              <dt>Проверки свободного денежного потока</dt>
              <dd>
                У Грэма их нет: отчёта о движении денег в нынешнем виде в его время не было, и он судил по прибыли.
                Но прибыль и деньги расходятся годами. Поэтому требуем, чтобы поток был положительным в большинстве
                лет (не во все — у того, кто строит, вложения идут волнами) и не сжимался за 10 и за 5 лет.
              </dd>
            </div>
            <div>
              <dt>Отдача на капитал</dt>
              <dd>
                У Грэма порога нет — это у него показатель описания. В проекте на неё опирается оценка роста,
                поэтому порог нужен, и берётся он целиком из отраслевого профиля.
              </dd>
            </div>
            <div>
              <dt>Требования к банкам</dt>
              <dd>
                Банков в списках Грэма нет вовсе. Мерим их своим: издержки к доходам и стоимость риска — в среднем
                за семь лет (это поведение, разовая удача ничего не доказывает), достаточность капитала и доля
                проблемных кредитов — на дату (это запас).
              </dd>
            </div>
          </dl>
        </section>
      )}

      <section className="mo-card">
        <div className="mo-card-head">
          <h2>Пороги по отраслям</h2>
          <span className="seg" role="radiogroup" aria-label="Свод требований">
            {(['defensive', 'enterprising'] as const).map((key) => (
              <button key={key} type="button" role="radio" aria-checked={standard === key}
                className={standard === key ? 'seg-btn is-on' : 'seg-btn'} onClick={() => setStandard(key)}>
                {key === 'defensive' ? 'Защитный инвестор' : 'Активный инвестор'}
              </button>
            ))}
          </span>
        </div>
        {isLoading && <div className="mo-state">Загружаем пороги…</div>}
        {error && <div className="mo-state">Не удалось загрузить пороги.</div>}
        {data && (isPhone ? <PhoneMatrix data={data} standard={standard} /> : <Matrix data={data} standard={standard} />)}
        {data && (
          <p className="mo-note">
            <span className="th-key th-cell--shifted">выделено</span> — порог сдвинут отраслью;
            {' '}<span className="th-key th-cell--na">не применяется</span> — мерка к отрасли не подходит;
            «—» — требование не для этой отрасли (банковские — только у банков, денежный поток — у всех, кроме банков).
            «Наше» — требования или пороги, которых в книге нет.
          </p>
        )}
      </section>

      {data && (
        <section className="mo-card">
          <div className="mo-card-head"><h2>Отрасли подробно</h2></div>
          <p className="th-text">
            Те же полосы красят мультипликаторы в карточке компании: «хорошо» — зелёным, «приемлемо» — жёлтым.
            Скринер судит по «хорошо», банковские требования — по краю «приемлемо». «База» — профиль
            «Промышленность»: его ликвидность, P/E и P/B — числа Грэма, от них и считается сдвиг.
          </p>
          <div className="th-profiles">
            {data.profiles.map((p) => <ProfileCard key={p.key} profile={p} base={base} />)}
          </div>
        </section>
      )}

      <section className="mo-card">
        <div className="mo-card-head"><h2>Как компания попадает в отрасль</h2></div>
        <p className="th-text">
          По сектору из данных биржи и брокера, а банк — по типу отчётности: у банка она устроена иначе, и это
          важнее названия сектора. Где сектор вводит в заблуждение (холдинг, записанный «прочим», или ритейлер с
          необычной моделью), аналитик закрепляет профиль вручную. Профиль компании виден в скринере при наведении
          на название и в её карточке.
        </p>
        <p className="th-links">
          <Link to="/screen">Скринер →</Link>
          <Link to="/valuation">Как считается стоимость →</Link>
        </p>
      </section>
    </div>
  );
}
