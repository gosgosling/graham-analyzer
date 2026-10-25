import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';

/**
 * Заголовок вкладки браузера.
 *
 * Сервер дописывает заголовок в HTML под адрес (backend pages_router) — но
 * только при первой загрузке. Дальше переходы идут внутри приложения, и без
 * этого у всех вкладок, в истории и в закладках оставалось бы название той
 * страницы, с которой человек зашёл. Названия разделов — те же, что на
 * сервере, чтобы вкладка не меняла имя после загрузки скрипта.
 */

const SITE = 'Graham Analyzer';

const SECTIONS: Record<string, string> = {
  '/': 'Цена и стоимость российских акций',
  '/companies': 'Компании',
  '/screen': 'Скринер Грэма',
  '/market': 'Рынок',
  '/economy': 'Экономика России: бюджет, долг, инфляция',
  '/calendar': 'Календарь отчётности',
  '/valuation': 'Как считается стоимость',
  '/compare': 'Сравнение компаний',
  '/login': 'Вход',
  '/register': 'Регистрация',
  '/account': 'Кабинет',
  '/admin': 'Админ',
  '/privacy': 'Политика конфиденциальности',
  '/consent': 'Согласие на обработку данных',
};

export function setPageTitle(title: string | null | undefined) {
  document.title = title ? `${title} — ${SITE}` : SITE;
}

/** Своя страница задаёт заголовок сама: карточка компании — по её названию. */
export function usePageTitle(title: string | null | undefined) {
  useEffect(() => {
    if (title) setPageTitle(title);
  }, [title]);
}

/** Заголовки разделов по адресу; карточку компании пропускает — у неё свой. */
export function RouteTitle() {
  const { pathname } = useLocation();
  useEffect(() => {
    if (pathname.startsWith('/company/')) return;
    setPageTitle(SECTIONS[pathname.replace(/\/+$/, '') || '/'] ?? null);
  }, [pathname]);
  return null;
}
