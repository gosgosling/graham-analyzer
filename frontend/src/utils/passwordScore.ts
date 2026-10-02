export const MIN_PASSWORD = 10;

/** Страницы входа: на них нет шапки и подвала сайта. */
export const AUTH_PATHS = ['/login', '/register', '/forgot', '/reset', '/verify', '/verify-email'];

/**
 * Грубая оценка пароля 0–4: длина и разнообразие. Подсказка, пока человек
 * печатает; по-настоящему пароль проверяет сервер (длина, частые пароли).
 */
export function passwordScore(password: string): 0 | 1 | 2 | 3 | 4 {
  if (password.length < MIN_PASSWORD) return 0;
  const kinds = [/[a-zа-яё]/, /[A-ZА-ЯЁ]/, /\d/, /[^\w\sа-яё]/i, /\s/].filter((r) => r.test(password)).length;
  if (new Set(password.toLowerCase()).size < 5) return 1;
  let score = 1;
  if (password.length >= 14) score += 1;
  if (password.length >= 18 || kinds >= 3) score += 1;
  if (password.length >= 22 && kinds >= 2) score += 1;
  return Math.min(score, 4) as 1 | 2 | 3 | 4;
}
