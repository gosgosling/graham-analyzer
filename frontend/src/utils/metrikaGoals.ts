/** Цели Яндекс Метрики — отдельно от счётчика, чтобы проверялись без браузера. */

/**
 * Цели — действия, по которым видно, что сайтом пользовались, а не только
 * открыли. Идентификаторы те же, что у целей «JavaScript-событие» в
 * настройках счётчика: без такой цели в Метрике событие не попадёт в отчёты.
 */
export const GOALS = {
  company: 'company_open',      // открыта карточка компании
  search: 'search_pick',        // выбрана компания в поиске
  screen: 'screen_filter',      // изменён отбор в скринере
  compare: 'compare_build',     // собрано сравнение из двух и больше компаний
  pdf: 'report_pdf',            // открыт исходный PDF отчёта
  register: 'register',         // зарегистрировался
} as const;

export type Goal = typeof GOALS[keyof typeof GOALS];

/**
 * Цели, которые видны по самому адресу: карточка, отбор в скринере,
 * сравнение. Отбор в скринере живёт в строке запроса, поэтому его смена на
 * той же странице — это и есть «изменил отбор»; первый заход на /screen —
 * ещё нет.
 */
export function routeGoals(url: string, previous: string | null): Goal[] {
  const [path, search = ''] = url.split('?');
  const [prevPath, prevSearch = ''] = (previous ?? '').split('?');
  const found: Goal[] = [];
  if (/^\/company\/\d+$/.test(path) && path !== prevPath) found.push(GOALS.company);
  if (path === '/screen' && prevPath === '/screen' && search !== prevSearch) found.push(GOALS.screen);
  if (path === '/compare' && search !== prevSearch) {
    const ids = (new URLSearchParams(search).get('ids') ?? '').split(',').filter(Boolean);
    if (ids.length >= 2 || new URLSearchParams(search).has('with')) found.push(GOALS.compare);
  }
  return found;
}
