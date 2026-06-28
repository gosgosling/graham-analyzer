/** Разбор detail из ответа FastAPI (строка, объект или массив 422). */
export function formatApiErrorMessage(err: unknown, fallback: string): string {
  const ax = err as { response?: { data?: { detail?: unknown } }; message?: string };
  const detail = ax?.response?.data?.detail;
  if (detail === undefined || detail === null || detail === '') {
    return typeof ax?.message === 'string' && ax.message ? ax.message : fallback;
  }
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const s = detail
      .map((e: unknown) => {
        if (e && typeof e === 'object') {
          const item = e as { loc?: unknown[]; msg?: string };
          const field = Array.isArray(item.loc) ? item.loc.slice(1).join(' → ') : '';
          const msg = (item.msg ?? 'неверное значение').replace(/^Value error,\s*/i, '');
          return field ? `${field}: ${msg}` : msg;
        }
        return String(e);
      })
      .join('\n');
    return s || fallback;
  }
  if (typeof detail === 'object' && detail !== null && 'msg' in detail) {
    const e = detail as { loc?: unknown[]; msg?: string };
    const field = Array.isArray(e.loc) ? e.loc.slice(1).join(' → ') : '';
    const msg = (e.msg ?? 'неверное значение').replace(/^Value error,\s*/i, '');
    return field ? `${field}: ${msg}` : msg;
  }
  return fallback;
}
