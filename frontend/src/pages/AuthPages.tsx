import React, { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../services/companies.api';
import { fetchMarketOverview } from '../services/market.api';
import { AUTH_KEY, AuthMe, errorText, useAuth } from '../hooks/useAdmin';
import { safeNext } from '../utils/safeNext';
import { MIN_PASSWORD, passwordScore } from '../utils/passwordScore';
import { ScalesIcon } from '../components/BrandMark';
import { ConsentText } from './LegalPages';
import './Auth.css';

/**
 * Вход, регистрация, восстановление пароля, подтверждение почты.
 *
 * Экран пополам, как на биржах: слева — знак, мысль Грэма и рынок сегодня,
 * справа — форма. Шапки сайта здесь нет, чтобы ничто не отвлекало; знак
 * слева ведёт обратно на сайт.
 *
 * Читать сайт можно без аккаунта — он нужен для будущих функций сообщества.
 */


const num = (v: number | null | undefined, digits = 2) =>
  v == null ? '—' : v.toLocaleString('ru-RU', { minimumFractionDigits: digits, maximumFractionDigits: digits });

function MarketLine() {
  const { data } = useQuery({ queryKey: ['market-overview'], queryFn: fetchMarketOverview, staleTime: 10 * 60 * 1000 });
  if (!data) return null;
  const imoex = data.today.IMOEX;
  return (
    <div className="ax-market">
      {imoex && (
        <span>IMOEX <b>{num(imoex.value)}</b>{' '}
          {imoex.day != null && <i className={imoex.day >= 0 ? 'ax-up' : 'ax-down'}>{imoex.day >= 0 ? '+' : ''}{num(imoex.day)}%</i>}
        </span>
      )}
      {data.key_rate.value != null && <span>Ставка ЦБ <b>{num(data.key_rate.value)}%</b></span>}
      {data.ofz10.last != null && <span>ОФЗ 10 лет <b>{num(data.ofz10.last)}%</b></span>}
    </div>
  );
}

function AuthShell({ tabs, title, children }: { tabs?: 'login' | 'register'; title?: string; children: React.ReactNode }) {
  const [params] = useSearchParams();
  const raw = params.get('next');
  const keep = raw ? `?next=${encodeURIComponent(safeNext(raw))}` : '';
  return (
    <div className="ax">
      <aside className="ax-side">
        <Link to="/companies" className="ax-brand"><ScalesIcon />Graham Analyzer</Link>
        <figure className="ax-quote">
          <blockquote>«В краткосрочной перспективе рынок — машина для голосования, в долгосрочной — весы».</blockquote>
          <figcaption>Бенджамин Грэм</figcaption>
        </figure>
        <MarketLine />
      </aside>
      <main className="ax-main">
        <div className="ax-box">
          <Link to="/companies" className="ax-brand ax-brand--mobile"><ScalesIcon />Graham Analyzer</Link>
          {tabs ? (
            <nav className="ax-tabs" aria-label="Вход или регистрация">
              <Link to={`/login${keep}`} className={tabs === 'login' ? 'is-on' : ''} aria-current={tabs === 'login' ? 'page' : undefined}>Вход</Link>
              <Link to={`/register${keep}`} className={tabs === 'register' ? 'is-on' : ''} aria-current={tabs === 'register' ? 'page' : undefined}>Регистрация</Link>
            </nav>
          ) : (
            <h1 className="ax-title">{title}</h1>
          )}
          {children}
          <p className="ax-back">Всё на сайте открыто и без аккаунта. <Link to="/companies">Вернуться на сайт</Link></p>
        </div>
      </main>
    </div>
  );
}

export function Field({ label, aside, hint, ...input }: React.InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  aside?: React.ReactNode;
  hint?: React.ReactNode;
}) {
  return (
    <label className="ax-field">
      <span className="ax-label">{label}{aside}</span>
      <input className="ax-input" {...input} />
      {hint && <span className="ax-hint">{hint}</span>}
    </label>
  );
}

export function PasswordField({ label, aside, hint, ...input }: React.InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  aside?: React.ReactNode;
  hint?: React.ReactNode;
}) {
  const [shown, setShown] = useState(false);
  return (
    <label className="ax-field">
      <span className="ax-label">{label}{aside}</span>
      <span className="ax-password">
        <input className="ax-input" type={shown ? 'text' : 'password'} maxLength={128} {...input} />
        <button type="button" className="ax-eye" onClick={() => setShown((s) => !s)}
          aria-label={shown ? 'Скрыть пароль' : 'Показать пароль'} aria-pressed={shown}>
          {shown ? 'скрыть' : 'показать'}
        </button>
      </span>
      {hint && <span className="ax-hint">{hint}</span>}
    </label>
  );
}

export function Notice({ kind, children }: { kind: 'error' | 'ok' | 'info'; children: React.ReactNode }) {
  return <p className={`ax-notice ax-notice--${kind}`} role={kind === 'error' ? 'alert' : 'status'}>{children}</p>;
}

const SCORE_TEXT = ['', 'Слабоват — добавьте слов', 'Сойдёт', 'Хорошо', 'Отлично'];

export function PasswordMeter({ password }: { password: string }) {
  if (!password) return <span>От {MIN_PASSWORD} символов. Длинная фраза надёжнее сложного слова.</span>;
  const score = passwordScore(password);
  return (
    <span className="ax-meter-wrap">
      <span className={`ax-meter ax-meter--${score}`} aria-hidden>
        <i /><i /><i /><i />
      </span>
      {score === 0 ? `Ещё ${MIN_PASSWORD - password.length} симв.` : SCORE_TEXT[score]}
    </span>
  );
}

function AlreadyIn({ name, next }: { name: string; next: string }) {
  return <Notice kind="info">Вы уже вошли как {name}. <Link to={next}>Продолжить</Link></Notice>;
}

// ── Вход ──

export function LoginPage() {
  const [params] = useSearchParams();
  const next = safeNext(params.get('next'));
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { data } = await api.post<AuthMe>('/auth/login', { email, password });
      queryClient.setQueryData<AuthMe>(AUTH_KEY, (old) => ({ ...data, mail_configured: old?.mail_configured ?? false }));
      await queryClient.invalidateQueries();
      navigate(next, { replace: true });
    } catch (err) {
      setError(errorText(err));
      setPassword('');
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthShell tabs="login">
      {user ? <AlreadyIn name={user.name} next={next} /> : (
        <form className="ax-form" onSubmit={submit} noValidate>
          <Field label="Почта" type="email" name="email" autoComplete="username" inputMode="email"
            value={email} onChange={(e) => setEmail(e.target.value)} maxLength={254} required autoFocus />
          <PasswordField label="Пароль" name="password" autoComplete="current-password"
            aside={<Link to="/forgot" className="ax-label-link">Не помню пароль</Link>}
            value={password} onChange={(e) => setPassword(e.target.value)} required />
          {error && <Notice kind="error">{error}</Notice>}
          <button type="submit" className="ax-submit" disabled={busy || !email || !password}>
            {busy ? 'Проверяем…' : 'Войти'}
          </button>
        </form>
      )}
    </AuthShell>
  );
}

// ── Регистрация ──

export function RegisterPage() {
  const [params] = useSearchParams();
  const next = safeNext(params.get('next'));
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [agree, setAgree] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // После регистрации запрос /auth/me вернёт пользователя раньше, чем
  // сработает переход, — не показываем «вы уже вошли» в этот миг.
  const [created, setCreated] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { data } = await api.post<AuthMe>('/auth/register', { email, password, name, consent: agree });
      setCreated(true);
      queryClient.setQueryData<AuthMe>(AUTH_KEY, (old) => ({ ...data, mail_configured: old?.mail_configured ?? false }));
      await queryClient.invalidateQueries();
      navigate('/account?welcome=1', { replace: true });
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  };

  return (
    <AuthShell tabs="register">
      {user && !created ? <AlreadyIn name={user.name} next={next} /> : (
        <form className="ax-form" onSubmit={submit} noValidate>
          <Field label="Как вас называть" name="name" autoComplete="nickname" value={name}
            onChange={(e) => setName(e.target.value)} maxLength={64} required autoFocus />
          <Field label="Почта" type="email" name="email" autoComplete="email" inputMode="email"
            value={email} onChange={(e) => setEmail(e.target.value)} maxLength={254} required
            hint="Пришлём ссылку для подтверждения. Рассылок нет." />
          <PasswordField label="Пароль" name="new-password" autoComplete="new-password"
            value={password} onChange={(e) => setPassword(e.target.value)} required
            hint={<PasswordMeter password={password} />} />
          <div className="ax-consent">
            <label className="ax-check">
              <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
              <span>Даю согласие на обработку персональных данных на условиях ниже</span>
            </label>
            {/* Текст согласия виден целиком до отметки — не спрятан за ссылкой. */}
            <div className="ax-consent-text" tabIndex={0} aria-label="Текст согласия">
              <ConsentText />
            </div>
            <span className="ax-hint">
              Отдельной страницей: <Link to="/consent" target="_blank">согласие</Link> ·{' '}
              <Link to="/privacy" target="_blank">политика обработки данных</Link>
            </span>
          </div>
          {error && <Notice kind="error">{error}</Notice>}
          <button type="submit" className="ax-submit"
            disabled={busy || !agree || name.trim().length < 2 || !email || password.length < MIN_PASSWORD}>
            {busy ? 'Создаём…' : 'Создать аккаунт'}
          </button>
        </form>
      )}
    </AuthShell>
  );
}

// ── Не помню пароль ──

export function ForgotPage() {
  const { me } = useAuth();
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post('/auth/password/forgot', { email });
      setSent(true);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthShell title={sent ? 'Проверьте почту' : 'Новый пароль'}>
      {sent ? (
        <>
          <p className="ax-text">
            Если адрес <b>{email}</b> зарегистрирован, на него ушла ссылка для нового пароля. Она действует
            30 минут. Письма нет — загляните в «Спам».
          </p>
          <p className="ax-text"><Link to="/login">Ко входу</Link></p>
        </>
      ) : (
        <form className="ax-form" onSubmit={submit} noValidate>
          <p className="ax-text">Пришлём на почту ссылку, по которой можно задать новый пароль.</p>
          <Field label="Почта" type="email" name="email" autoComplete="username" inputMode="email"
            value={email} onChange={(e) => setEmail(e.target.value)} maxLength={254} required autoFocus />
          {me && !me.mail_configured && (
            <Notice kind="info">Почта на сервере не настроена: ссылка запишется в журнал сервера.</Notice>
          )}
          {error && <Notice kind="error">{error}</Notice>}
          <button type="submit" className="ax-submit" disabled={busy || !email}>
            {busy ? 'Отправляем…' : 'Прислать ссылку'}
          </button>
          <p className="ax-text"><Link to="/login">Вспомнил — ко входу</Link></p>
        </form>
      )}
    </AuthShell>
  );
}

// ── Новый пароль по ссылке ──

export function ResetPage() {
  const [params] = useSearchParams();
  const token = params.get('token') ?? '';
  const [password, setPassword] = useState('');
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post('/auth/password/reset', { token, password });
      setDone(true);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthShell title={done ? 'Пароль изменён' : 'Задайте новый пароль'}>
      {!token ? (
        <p className="ax-text">Ссылка неполная — откройте её из письма целиком или <Link to="/forgot">запросите новую</Link>.</p>
      ) : done ? (
        <p className="ax-text">Все прежние сессии закрыты. <Link to="/login">Войдите</Link> с новым паролем.</p>
      ) : (
        <form className="ax-form" onSubmit={submit} noValidate>
          <PasswordField label="Новый пароль" name="new-password" autoComplete="new-password"
            value={password} onChange={(e) => setPassword(e.target.value)} required autoFocus
            hint={<PasswordMeter password={password} />} />
          {error && <Notice kind="error">{error}</Notice>}
          <button type="submit" className="ax-submit" disabled={busy || password.length < MIN_PASSWORD}>
            {busy ? 'Сохраняем…' : 'Сохранить пароль'}
          </button>
        </form>
      )}
    </AuthShell>
  );
}

// ── Ссылки из писем: подтверждение почты и смена почты ──

function TokenPage({ endpoint, title, okText }: { endpoint: string; title: string; okText: string }) {
  const [params] = useSearchParams();
  const token = params.get('token') ?? '';
  const queryClient = useQueryClient();
  const [state, setState] = useState<'wait' | 'ok' | 'error'>('wait');
  const [error, setError] = useState<string | null>(null);
  // Ссылка одноразовая: второй запрос (StrictMode, повторный рендер) её
  // уже не примет и покажет ошибку поверх успеха.
  const sent = useRef(false);

  useEffect(() => {
    if (sent.current) return;
    sent.current = true;
    if (!token) {
      setState('error');
      setError('Ссылка неполная — откройте её из письма целиком.');
      return;
    }
    api.post(endpoint, { token })
      .then(() => {
        setState('ok');
        queryClient.invalidateQueries({ queryKey: AUTH_KEY });
      })
      .catch((err) => {
        setState('error');
        setError(errorText(err));
      });
  }, [endpoint, token, queryClient]);

  return (
    <AuthShell title={title}>
      {state === 'wait' && <p className="ax-text">Проверяем ссылку…</p>}
      {state === 'ok' && <p className="ax-text">{okText} <Link to="/account">В аккаунт</Link></p>}
      {state === 'error' && (
        <p className="ax-text">{error} Новую ссылку можно отправить из <Link to="/account">аккаунта</Link>.</p>
      )}
    </AuthShell>
  );
}

export function VerifyPage() {
  return <TokenPage endpoint="/auth/verify" title="Подтверждение почты" okText="Почта подтверждена, спасибо." />;
}

export function VerifyEmailChangePage() {
  return <TokenPage endpoint="/auth/email/confirm" title="Смена почты" okText="Готово: теперь это почта вашего аккаунта." />;
}
