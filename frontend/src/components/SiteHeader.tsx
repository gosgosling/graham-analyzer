import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { getCompanies } from '../services';
import type { Company } from '../types';
import ThemeToggle from './ThemeToggle';
import { ScalesIcon } from './BrandMark';
import { AUTH_PATHS } from '../utils/passwordScore';
import { AUTH_KEY, AuthMe, AuthUser, useAuth } from '../hooks/useAdmin';
import { api } from '../services/companies.api';
import './SiteHeader.css';

/**
 * Шапка сайта в две строки: знак, поиск по центру (главное действие —
 * найти компанию), тема и аккаунт; ниже — разделы вкладками.
 * Всё, чем пользуется только аналитик (загрузка отчётов, парсинг, бэкап),
 * живёт за кнопкой «Админ», которую видит только администратор. Календарь
 * отчётности — для всех: когда выйдет следующий отчёт, важно и читателю.
 */

type Section = 'ideas' | 'companies' | 'market' | 'calendar' | 'method' | 'admin' | null;

/** Служебные страницы — подсвечивают кнопку «Админ». */
const ADMIN_PATHS = ['/admin', '/securities', '/bonds', '/bond/', '/mass-parse', '/disclosure'];

function sectionOf(pathname: string): Section {
  if (ADMIN_PATHS.some((p) => pathname.startsWith(p))) return 'admin';
  if (pathname.startsWith('/screen')) return 'ideas';
  if (pathname.startsWith('/calendar')) return 'calendar';
  if (pathname.startsWith('/market')) return 'market';
  if (pathname.startsWith('/valuation')) return 'method';
  if (pathname.startsWith('/compan')) return 'companies';
  return null;
}

const MAX_RESULTS = 8;

function CompanySearch() {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);

  // Список тот же, что на странице компаний: ключ общий, запрос один.
  const { data: companies } = useQuery({
    queryKey: ['companies'],
    queryFn: getCompanies,
    staleTime: 10 * 60 * 1000,
    enabled: open || query.length > 0,
  });

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q || !companies) return [];
    const scored = companies
      .map((c: Company) => {
        const ticker = (c.ticker ?? '').toLowerCase();
        const name = (c.name ?? '').toLowerCase();
        const score = ticker === q ? 0 : ticker.startsWith(q) ? 1 : name.startsWith(q) ? 2 : name.includes(q) ? 3 : -1;
        return { c, score };
      })
      .filter((x) => x.score >= 0)
      .sort((a, b) => a.score - b.score || (a.c.ticker ?? '').localeCompare(b.c.ticker ?? ''));
    return scored.slice(0, MAX_RESULTS).map((x) => x.c);
  }, [companies, query]);

  // «/» с любого места страницы ставит курсор в поиск — как на биржах.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      const typing = target.closest('input, textarea, select, [contenteditable="true"]');
      if (e.key === '/' && !typing) {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    const close = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  const go = (company: Company | undefined) => {
    if (!company?.id) return;
    navigate(`/company/${company.id}`);
    setQuery('');
    setOpen(false);
    inputRef.current?.blur();
  };

  return (
    <div className="sh-search" ref={rootRef}>
      <svg className="sh-search-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        strokeWidth="2" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
      <input
        ref={inputRef}
        type="search"
        className="sh-search-input"
        placeholder="Найти компанию: тикер или название"
        aria-label="Найти компанию"
        value={query}
        onFocus={() => setOpen(true)}
        onChange={(e) => {
          setQuery(e.target.value);
          setCursor(0);
          setOpen(true);
        }}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') {
            e.preventDefault();
            setCursor((c) => Math.min(c + 1, Math.max(results.length - 1, 0)));
          } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setCursor((c) => Math.max(c - 1, 0));
          } else if (e.key === 'Enter') {
            go(results[cursor]);
          } else if (e.key === 'Escape') {
            setOpen(false);
            inputRef.current?.blur();
          }
        }}
      />
      <kbd className="sh-search-key" aria-hidden>/</kbd>
      {open && query.trim() && (
        <ul className="sh-search-results" role="listbox">
          {results.length === 0 ? (
            <li className="sh-search-empty">{companies ? 'Ничего не нашлось' : 'Загружаем список…'}</li>
          ) : (
            results.map((c, i) => (
              <li key={c.id} role="option" aria-selected={i === cursor}>
                <button
                  type="button"
                  className={`sh-search-item${i === cursor ? ' is-on' : ''}`}
                  onMouseEnter={() => setCursor(i)}
                  onClick={() => go(c)}
                >
                  <span className="sh-search-ticker">{c.ticker}</span>
                  <span className="sh-search-name">{c.name}</span>
                </button>
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}

/** Меню вошедшего: аккаунт и выход. Админу служебное — отдельной кнопкой рядом. */
function AccountMenu({ user }: { user: AuthUser }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { pathname } = useLocation();

  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    if (!open) return undefined;
    const close = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', esc);
    return () => {
      document.removeEventListener('mousedown', close);
      document.removeEventListener('keydown', esc);
    };
  }, [open]);

  const logout = async () => {
    try {
      await api.post('/auth/logout');
    } finally {
      queryClient.setQueryData<AuthMe>(AUTH_KEY, (old) => ({
        user: null,
        expires_at: null,
        mail_configured: old?.mail_configured ?? false,
      }));
      await queryClient.invalidateQueries();
      if (pathname.startsWith('/account') || ADMIN_PATHS.some((p) => pathname.startsWith(p))) navigate('/companies');
    }
  };

  return (
    <div className="sh-account" ref={rootRef}>
      <button type="button" className={`sh-account-btn${open ? ' is-on' : ''}`} aria-haspopup="menu"
        aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <span className="sh-avatar" aria-hidden>{user.name.slice(0, 1).toUpperCase()}</span>
        <span className="sh-account-name">{user.name}</span>
        <span className="sh-caret" aria-hidden>▾</span>
      </button>
      {open && (
        <div className="sh-menu" role="menu">
          <div className="sh-menu-head">
            <div className="sh-menu-name">{user.name}</div>
            <div className="sh-menu-mail">{user.email}</div>
          </div>
          <Link to="/account" className="sh-menu-item" role="menuitem">Аккаунт</Link>
          <button type="button" className="sh-menu-item" role="menuitem" onClick={logout}>Выйти</button>
        </div>
      )}
    </div>
  );
}

export default function SiteHeader() {
  const { user, checking } = useAuth();
  const { pathname, search } = useLocation();
  const active = sectionOf(pathname);
  // После входа — обратно туда, где был; со страниц входа — никуда не возвращаем.
  const here = pathname + search;
  const next = AUTH_PATHS.includes(pathname) ? '' : `?next=${encodeURIComponent(here)}`;
  // Высота липкой шапки — в CSS-переменную на корне документа. По ней таблицы
  // во всю высоту окна (матрица отчётов) считают, сколько им места: шапка на
  // узком экране переносится в несколько строк, и число в CSS устарело бы.
  const headerRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const el = headerRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return undefined;
    const root = document.documentElement;
    const publish = () => root.style.setProperty('--site-header-h', `${Math.round(el.getBoundingClientRect().height)}px`);
    publish();
    const observer = new ResizeObserver(publish);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  const link = (key: Exclude<Section, null>, to: string, label: string) => (
    <Link to={to} className={`sh-link${active === key ? ' is-on' : ''}`} aria-current={active === key ? 'page' : undefined}>
      {label}
    </Link>
  );

  return (
    <header className="sh" ref={headerRef}>
      <div className="sh-row">
        <Link to="/companies" className="sh-brand" aria-label="Graham Analyzer — на главную">
          <ScalesIcon />
          <span className="sh-brand-text">
            <span className="sh-name">Graham Analyzer</span>
            <span className="sh-tagline">рынок голосует, весы взвешивают</span>
          </span>
        </Link>
        <CompanySearch />
        <div className="sh-actions">
          <ThemeToggle compact />
          {user && user.role === 'admin' && (
            <Link to="/admin" className={`sh-admin${active === 'admin' ? ' is-on' : ''}`}>Админ</Link>
          )}
          {user ? <AccountMenu user={user} /> : !checking && (
            <div className="sh-auth">
              <Link to={`/login${next}`} className="sh-login">Войти</Link>
              <Link to={`/register${next}`} className="sh-register">Регистрация</Link>
            </div>
          )}
        </div>
      </div>
      <nav className="sh-tabs" aria-label="Разделы сайта">
        {link('ideas', '/screen', 'Скринер')}
        {link('companies', '/companies', 'Компании')}
        {link('market', '/market', 'Рынок')}
        {link('calendar', '/calendar', 'Календарь отчётности')}
        <span className="sh-tabs-gap" aria-hidden />
        {link('method', '/valuation', 'Как считается стоимость')}
      </nav>
    </header>
  );
}
