import { useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import { useAuth } from '../hooks/useAdmin';
import { GOALS, Goal, routeGoals } from '../utils/metrikaGoals';

export { GOALS } from '../utils/metrikaGoals';

/**
 * Яндекс Метрика: сколько людей пришло, откуда и по каким запросам.
 *
 * Включается номером счётчика в сборке (REACT_APP_YM_ID); без него — ничего
 * не грузится, в разработке тоже. Вебвизор и карта кликов выключены: для
 * вопроса «по каким запросам находят сайт» запись действий посетителя не
 * нужна, а в политике конфиденциальности тогда пришлось бы описывать и её.
 *
 * Сайт одностраничный: переходы между страницами браузер не перезагружает,
 * поэтому каждый переход отправляется в счётчик отдельным просмотром.
 *
 * Администратор не считается: владелец сайта заходит чаще всех, и его
 * просмотры и цели размывали бы ответ на вопрос «что делают посетители».
 * Поэтому первый просмотр ждёт ответа «кто вошёл».
 */

export const YM_ID = Number(process.env.REACT_APP_YM_ID) || null;

type Ym = ((id: number, method: string, ...args: unknown[]) => void) & { a?: unknown[]; l?: number };

declare global {
  interface Window { ym?: Ym }
}

// Пока не ясно, кто вошёл, — не считаем; администратора — не считаем вовсе.
let counting = false;

function load(id: number) {
  if (window.ym) return;
  const ym: Ym = (...args: unknown[]) => { (ym.a = ym.a || []).push(args); };
  ym.l = Date.now();
  window.ym = ym;
  const script = document.createElement('script');
  script.async = true;
  script.src = 'https://mc.yandex.ru/metrika/tag.js';
  document.head.appendChild(script);
  ym(id, 'init', {
    defer: true,          // первый просмотр отправляем сами, как и остальные
    clickmap: false,
    trackLinks: true,
    accurateTrackBounce: true,
    webvisor: false,
  });
}

/** Отметить цель. Без счётчика и у администратора — ничего. */
export function goal(name: Goal): void {
  if (!YM_ID || !counting) return;
  window.ym?.(YM_ID, 'reachGoal', name);
}

export default function Metrika() {
  const { pathname, search } = useLocation();
  const { user, checking } = useAuth();
  const previous = useRef<string | null>(null);
  const admin = user?.role === 'admin';

  useEffect(() => {
    counting = Boolean(YM_ID) && !checking && !admin;
  }, [checking, admin]);

  // Исходный PDF открывается обычной ссылкой из нескольких мест страницы —
  // ловим их одним слушателем, а не в каждом компоненте.
  useEffect(() => {
    if (!YM_ID) return;
    const click = (e: MouseEvent) => {
      const link = (e.target as Element | null)?.closest?.('a[href]');
      if (link && /\/files\/reports\//.test(link.getAttribute('href') ?? '')) goal(GOALS.pdf);
    };
    document.addEventListener('click', click, true);
    return () => document.removeEventListener('click', click, true);
  }, []);

  useEffect(() => {
    if (!YM_ID || checking || admin) return;
    load(YM_ID);
    counting = true;
    const url = pathname + search;
    window.ym?.(YM_ID, 'hit', window.location.origin + url, {
      title: document.title,
      referer: previous.current ? window.location.origin + previous.current : document.referrer,
    });
    routeGoals(url, previous.current).forEach(goal);
    previous.current = url;
  }, [pathname, search, checking, admin]);
  return null;
}
