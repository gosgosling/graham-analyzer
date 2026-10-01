import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getCompanies } from '../services';
import type { Company } from '../types';
import ThemeToggle from './ThemeToggle';
import './SiteHeader.css';

/**
 * Шапка сайта: три раздела для читателя, поиск компании, тема и вход в
 * служебные страницы. Всё, чем пользуется только аналитик (загрузка отчётов,
 * парсинг, бэкап), живёт за кнопкой «Админ», а не в общем меню. Календарь
 * отчётности — для всех: когда выйдет следующий отчёт, важно и читателю.
 */

type Section = 'ideas' | 'companies' | 'calendar' | 'method' | 'admin' | null;

/** Служебные страницы — подсвечивают кнопку «Админ». */
const ADMIN_PATHS = ['/admin', '/bonds', '/bond/', '/mass-parse', '/disclosure'];

function sectionOf(pathname: string): Section {
  if (pathname === '/' || ADMIN_PATHS.some((p) => pathname.startsWith(p))) return 'admin';
  if (pathname.startsWith('/screen')) return 'ideas';
  if (pathname.startsWith('/calendar')) return 'calendar';
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
      <input
        ref={inputRef}
        type="search"
        className="sh-search-input"
        placeholder="Компания или тикер"
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

export default function SiteHeader() {
  const { pathname } = useLocation();
  const active = sectionOf(pathname);
  const link = (key: Exclude<Section, null>, to: string, label: string) => (
    <Link to={to} className={`sh-link${active === key ? ' is-on' : ''}`} aria-current={active === key ? 'page' : undefined}>
      {label}
    </Link>
  );

  return (
    <header className="sh">
      <div className="sh-inner">
        <div className="sh-left">
          <Link to="/companies" className="sh-brand" aria-label="Graham Analyzer — на главную">
            <span className="sh-mark" aria-hidden>G</span>
            <span className="sh-name">Graham Analyzer</span>
          </Link>
          <nav className="sh-nav" aria-label="Разделы сайта">
            {link('ideas', '/screen', 'Идеи')}
            {link('companies', '/companies', 'Компании')}
            {link('calendar', '/calendar', 'Календарь отчётности')}
            {link('method', '/valuation', 'Как считается стоимость')}
          </nav>
        </div>
        <div className="sh-right">
          <CompanySearch />
          <ThemeToggle compact />
          <Link to="/admin" className={`sh-admin${active === 'admin' ? ' is-on' : ''}`}>Админ</Link>
        </div>
      </div>
    </header>
  );
}
