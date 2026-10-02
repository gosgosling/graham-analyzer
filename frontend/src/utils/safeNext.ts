/** Куда вернуть после входа: только наш путь, не чужой сайт.
 *  `//evil.com` и `/\evil.com` браузер понимает как другой домен. */
export function safeNext(raw: string | null): string {
  if (!raw || !raw.startsWith('/') || raw.startsWith('//') || raw.startsWith('/\\')) return '/companies';
  return raw;
}
