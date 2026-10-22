import { useEffect, useState } from 'react';

/** Ширина, на которой страницы переходят на телефонную раскладку. */
export const PHONE_QUERY = '(max-width: 760px)';

/**
 * Совпадает ли медиа-запрос — с подпиской на изменение (поворот телефона,
 * окно браузера уже). Нужен там, где телефону показывают другую разметку, а
 * не те же блоки по-другому: список вместо таблицы CSS не нарисует.
 */
export function useMediaQuery(query: string): boolean {
  const get = () => typeof window !== 'undefined' && !!window.matchMedia?.(query).matches;
  const [matches, setMatches] = useState(get);
  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return undefined;
    const mql = window.matchMedia(query);
    const update = () => setMatches(mql.matches);
    update();
    mql.addEventListener?.('change', update);
    return () => mql.removeEventListener?.('change', update);
  }, [query]);
  return matches;
}
