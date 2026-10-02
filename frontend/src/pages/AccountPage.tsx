import React, { useState } from 'react';
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../services/companies.api';
import { AUTH_KEY, AuthMe, AuthUser, errorText, useAuth } from '../hooks/useAdmin';
import { Field, Notice, PasswordField, PasswordMeter } from './AuthPages';
import { MIN_PASSWORD } from '../utils/passwordScore';
import './Auth.css';
import './Account.css';

/**
 * Аккаунт — «ведомость»: одна колонка, строки «что — значение — изменить»
 * через тонкие линии. Правка открывается прямо в строке.
 */

interface SessionRow {
  current: boolean;
  created_at: string;
  last_seen_at: string;
  ip: string | null;
  user_agent: string | null;
}

type Status = { kind: 'error' | 'ok'; text: string } | null;

const day = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' }) : '—';

function when(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const time = d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
  if (d.toDateString() === today.toDateString()) return `сегодня, ${time}`;
  return `${d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })}, ${time}`;
}

/** «Chrome · Windows» из строки браузера — без библиотек, грубо, но читаемо. */
export function deviceLabel(ua: string | null): string {
  if (!ua) return 'Неизвестный браузер';
  const browser = /YaBrowser/.test(ua) ? 'Яндекс Браузер'
    : /Edg\//.test(ua) ? 'Edge'
      : /OPR\//.test(ua) ? 'Opera'
        : /Firefox\//.test(ua) ? 'Firefox'
          : /Chrome\//.test(ua) ? 'Chrome'
            : /Safari\//.test(ua) ? 'Safari' : 'Браузер';
  const os = /Android/.test(ua) ? 'Android'
    : /iPhone|iPad/.test(ua) ? 'iOS'
      : /Windows/.test(ua) ? 'Windows'
        : /Mac OS X/.test(ua) ? 'macOS'
          : /Linux/.test(ua) ? 'Linux' : '';
  return os ? `${browser} · ${os}` : browser;
}

function useSignedOut() {
  const queryClient = useQueryClient();
  return async () => {
    queryClient.setQueryData<AuthMe>(AUTH_KEY, (old) => ({
      user: null,
      expires_at: null,
      mail_configured: old?.mail_configured ?? false,
    }));
    await queryClient.invalidateQueries();
  };
}

/** Строка ведомости: подпись, значение, действие; по действию — форма в строке. */
function Row({ label, value, action, open, onToggle, children }: {
  label: string;
  value: React.ReactNode;
  action?: string;
  open?: boolean;
  onToggle?: () => void;
  children?: React.ReactNode;
}) {
  return (
    <div className={`acc-row${open ? ' is-open' : ''}`}>
      <span className="acc-k">{label}</span>
      <span className="acc-v">{value}</span>
      {action && onToggle ? (
        <button type="button" className="acc-act" onClick={onToggle} aria-expanded={open}>
          {open ? 'Отмена' : action}
        </button>
      ) : <span />}
      {open && <div className="acc-edit">{children}</div>}
    </div>
  );
}

function NameRow({ user, open, toggle }: { user: AuthUser; open: boolean; toggle: () => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(user.name);
  const [status, setStatus] = useState<Status>(null);
  const [busy, setBusy] = useState(false);
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setStatus(null);
    try {
      await api.patch('/auth/profile', { name });
      await queryClient.invalidateQueries({ queryKey: AUTH_KEY });
      toggle();
    } catch (err) {
      setStatus({ kind: 'error', text: errorText(err) });
    } finally {
      setBusy(false);
    }
  };
  return (
    <Row label="Имя на сайте" value={user.name} action="Изменить" open={open} onToggle={toggle}>
      <form className="acc-form" onSubmit={save}>
        <Field label="Новое имя" name="name" autoComplete="nickname" value={name}
          onChange={(e) => setName(e.target.value)} maxLength={64} autoFocus />
        {status && <Notice kind={status.kind}>{status.text}</Notice>}
        <button type="submit" className="acc-save" disabled={busy || name.trim() === user.name || name.trim().length < 2}>Сохранить</button>
      </form>
    </Row>
  );
}

function EmailRow({ user, mailConfigured, open, toggle }: {
  user: AuthUser; mailConfigured: boolean; open: boolean; toggle: () => void;
}) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [status, setStatus] = useState<Status>(null);
  const [resent, setResent] = useState<Status>(null);
  const [busy, setBusy] = useState(false);
  const logNote = mailConfigured ? '' : ' (почта на сервере не настроена — ссылка в журнале сервера)';

  const resend = async () => {
    setResent(null);
    try {
      await api.post('/auth/verify/resend');
      setResent({ kind: 'ok', text: `Ссылка отправлена на ${user.email}${logNote}.` });
    } catch (err) {
      setResent({ kind: 'error', text: errorText(err) });
    }
  };
  const change = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setStatus(null);
    try {
      await api.post('/auth/email/change', { new_email: email, password });
      setPassword('');
      setStatus({ kind: 'ok', text: `Ссылка ушла на ${email}${logNote}. Почта сменится, когда вы по ней перейдёте.` });
    } catch (err) {
      setStatus({ kind: 'error', text: errorText(err) });
      setPassword('');
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Row
        label="Почта"
        value={(
          <>
            {user.email}
            {user.email_verified
              ? <span className="acc-tag acc-tag--ok">подтверждена</span>
              : (
                <>
                  <span className="acc-tag acc-tag--warn">не подтверждена</span>
                  <button type="button" className="acc-inline" onClick={resend}>прислать ссылку ещё раз</button>
                </>
              )}
          </>
        )}
        action="Изменить"
        open={open}
        onToggle={toggle}
      >
        <form className="acc-form" onSubmit={change}>
          <p className="acc-note">Пришлём ссылку на новый адрес. Пока по ней не перейдёте, вход — по прежней почте.</p>
          <Field label="Новая почта" type="email" name="email" autoComplete="email" inputMode="email"
            value={email} onChange={(e) => setEmail(e.target.value)} maxLength={254} autoFocus />
          <PasswordField label="Пароль — для подтверждения" name="current-password" autoComplete="current-password"
            value={password} onChange={(e) => setPassword(e.target.value)} />
          {status && <Notice kind={status.kind}>{status.text}</Notice>}
          <button type="submit" className="acc-save" disabled={busy || !email || !password}>Прислать ссылку</button>
        </form>
      </Row>
      {resent && <div className="acc-after"><Notice kind={resent.kind}>{resent.text}</Notice></div>}
    </>
  );
}

function PasswordRow({ user, open, toggle }: { user: AuthUser; open: boolean; toggle: () => void }) {
  const queryClient = useQueryClient();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [status, setStatus] = useState<Status>(null);
  const [busy, setBusy] = useState(false);
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setStatus(null);
    try {
      await api.post('/auth/password/change', { current_password: current, new_password: next });
      setCurrent('');
      setNext('');
      await queryClient.invalidateQueries({ queryKey: AUTH_KEY });
      await queryClient.invalidateQueries({ queryKey: ['auth-sessions'] });
      setStatus({ kind: 'ok', text: 'Пароль изменён. На остальных устройствах выполнен выход.' });
    } catch (err) {
      setStatus({ kind: 'error', text: errorText(err) });
    } finally {
      setBusy(false);
    }
  };
  return (
    <Row label="Пароль" value={user.password_changed_at ? `изменён ${day(user.password_changed_at)}` : 'задан'}
      action="Сменить" open={open} onToggle={toggle}>
      <form className="acc-form" onSubmit={save}>
        {/* Скрытая почта подсказывает менеджеру паролей, чей пароль меняется. */}
        <input type="email" name="username" autoComplete="username" value={user.email} readOnly hidden />
        <PasswordField label="Текущий пароль" name="current-password" autoComplete="current-password"
          value={current} onChange={(e) => setCurrent(e.target.value)} autoFocus />
        <PasswordField label="Новый пароль" name="new-password" autoComplete="new-password"
          value={next} onChange={(e) => setNext(e.target.value)} hint={<PasswordMeter password={next} />} />
        {status && <Notice kind={status.kind}>{status.text}</Notice>}
        <button type="submit" className="acc-save" disabled={busy || !current || next.length < MIN_PASSWORD}>Сменить пароль</button>
      </form>
    </Row>
  );
}

function Sessions() {
  const queryClient = useQueryClient();
  const { data } = useQuery({
    queryKey: ['auth-sessions'],
    queryFn: async () => (await api.get<SessionRow[]>('/auth/sessions')).data,
    staleTime: 30 * 1000,
  });
  const [status, setStatus] = useState<Status>(null);
  const others = (data ?? []).filter((s) => !s.current).length;
  const closeOthers = async () => {
    try {
      const { data: res } = await api.post<{ closed: number }>('/auth/logout-others');
      setStatus({ kind: 'ok', text: res.closed ? `Закрыто сессий: ${res.closed}.` : 'Других сессий не было.' });
      await queryClient.invalidateQueries({ queryKey: ['auth-sessions'] });
    } catch (err) {
      setStatus({ kind: 'error', text: errorText(err) });
    }
  };
  return (
    <>
      <h2 className="acc-h">Где вы вошли</h2>
      <table className="acc-devices">
        <tbody>
          {(data ?? []).map((s, i) => (
            <tr key={i}>
              <td>
                {deviceLabel(s.user_agent)}
                {s.current && <span className="acc-tag acc-tag--ok">это устройство</span>}
                {s.ip && <span className="acc-ip">{s.ip}</span>}
              </td>
              <td className="acc-when">{s.current ? 'сейчас' : when(s.last_seen_at)}</td>
            </tr>
          ))}
          <tr>
            <td colSpan={2}>
              <button type="button" className="acc-inline" onClick={closeOthers} disabled={others === 0}>
                Выйти на всех устройствах, кроме этого
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      {status && <div className="acc-after"><Notice kind={status.kind}>{status.text}</Notice></div>}
      <p className="acc-note">Сессия живёт до 12 часов и закрывается сама после 2 часов без дела.</p>
    </>
  );
}

function DeleteAccount({ isAdmin }: { isAdmin: boolean }) {
  const signedOut = useSignedOut();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState('');
  const [status, setStatus] = useState<Status>(null);
  const [busy, setBusy] = useState(false);
  const remove = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setStatus(null);
    try {
      await api.post('/auth/account/delete', { password });
      await signedOut();
      navigate('/companies', { replace: true });
    } catch (err) {
      setStatus({ kind: 'error', text: errorText(err) });
      setPassword('');
      setBusy(false);
    }
  };
  if (!open) {
    return <button type="button" className="acc-delete" onClick={() => setOpen(true)}>Удалить аккаунт</button>;
  }
  return (
    <form className="acc-form acc-form--danger" onSubmit={remove}>
      <p className="acc-note">
        Сразу и насовсем: почта, имя, пароль, сессии и отметка о согласии. Восстановить не получится.
        {isAdmin && ' Единственного администратора удалить нельзя.'}
      </p>
      <PasswordField label="Пароль — для подтверждения" name="current-password" autoComplete="current-password"
        value={password} onChange={(e) => setPassword(e.target.value)} autoFocus />
      {status && <Notice kind={status.kind}>{status.text}</Notice>}
      <div className="acc-buttons">
        <button type="submit" className="acc-save acc-save--danger" disabled={busy || !password}>Удалить навсегда</button>
        <button type="button" className="acc-inline" onClick={() => { setOpen(false); setPassword(''); setStatus(null); }}>Отмена</button>
      </div>
    </form>
  );
}

export default function AccountPage() {
  const { user, checking, me } = useAuth();
  const [params] = useSearchParams();
  const [open, setOpen] = useState<'name' | 'email' | 'password' | null>(null);
  if (checking) return null;
  if (!user) return <Navigate to="/login?next=/account" replace />;
  const toggle = (key: 'name' | 'email' | 'password') => () => setOpen((o) => (o === key ? null : key));
  const isAdmin = user.role === 'admin';
  return (
    <div className="acc">
      <h1 className="acc-name">{user.name}</h1>
      <p className="acc-sub">
        {isAdmin ? 'Администратор' : 'Участник'} с {day(user.created_at)}
        {isAdmin && <> · <Link to="/admin">служебные разделы</Link></>}
      </p>
      {params.get('welcome') === '1' && (
        <div className="acc-after acc-welcome">
          <Notice kind="ok">Аккаунт создан. На {user.email} ушла ссылка — подтвердите почту, когда будет минута.</Notice>
        </div>
      )}

      <h2 className="acc-h">Учётная запись</h2>
      <div className="acc-list">
        <NameRow key={`n-${user.name}`} user={user} open={open === 'name'} toggle={toggle('name')} />
        <EmailRow user={user} mailConfigured={me?.mail_configured ?? false} open={open === 'email'} toggle={toggle('email')} />
        <PasswordRow user={user} open={open === 'password'} toggle={toggle('password')} />
      </div>

      <Sessions />

      <h2 className="acc-h">Данные</h2>
      <p className="acc-text">
        Храним почту, имя, хэш пароля и список входов. Согласие на обработку дано {day(user.consent_at)}.{' '}
        <Link to="/privacy">Что и зачем</Link> · <Link to="/consent">текст согласия</Link>
      </p>
      <DeleteAccount isAdmin={isAdmin} />
    </div>
  );
}
