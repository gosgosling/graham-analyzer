import type { Company } from '../types';

const BRAND_CDN = 'https://invest-brands.cdn-tinkoff.ru';

const IMG_EXT = /\.(png|webp|jpe?g|svg)(\?.*)?$/i;

/**
 * Уже есть суффикс размера (…x160.png, …x640.webp)?
 *
 * Размеры перечислены явно, и «x» именно строчная: шаблон вида `x\d{2,4}`
 * без флага регистра ловил ISIN `RU000A103X66` за хвост «X66» и решал, что
 * размер уже указан, — логотип после этого не находился никогда.
 */
const HAS_SIZE_SUFFIX = /x(160|320|640)\.(png|webp|jpe?g|svg)(\?.*)?$/;

/**
 * Варианты с суффиксом размера для CDN Тинькофф.
 *
 * CDN публикует только объекты с размером: `RU000A103X66x160.png` отдаётся,
 * а `RU000A103X66.png` — 403 AccessDenied. T-Invest API при этом возвращает
 * ссылку без суффикса, и она лежит в `brand_logo_url` у всех компаний.
 * Имя объекта не всегда равно ISIN (`mtsnewx160.png`, `segezhax160.png`),
 * поэтому суффикс подставляется в само имя из API, а не собирается из ISIN.
 */
function withSizeSuffixes(url: string, add: (u: string) => void): void {
  const [pathOnly, query] = url.split('?');
  const qs = query ? `?${query}` : '';
  if (HAS_SIZE_SUFFIX.test(pathOnly)) {
    add(url);
    return;
  }
  const match = pathOnly.match(IMG_EXT);
  const base = match ? pathOnly.slice(0, pathOnly.length - match[0].length) : pathOnly.replace(/\/$/, '');
  const ext = match ? match[0] : '.png';
  add(`${base}x160${ext}${qs}`);
  add(`${base}x640${ext}${qs}`);
}

/** SBERP → SBER (логотип на CDN у префов часто по «обычному» тикеру) */
function deprefMoexTicker(ticker: string): string | null {
  const t = ticker.trim().toUpperCase();
  if (t.length < 5 || !t.endsWith('P')) return null;
  const base = t.slice(0, -1);
  if (!/^[A-Z0-9._-]{2,19}$/.test(base)) return null;
  return base;
}

function addCdnKeys(id: string, add: (u: string) => void): void {
  const k = id.trim().toUpperCase();
  if (!/^[A-Z0-9._-]{2,}$/.test(k)) return;
  add(`${BRAND_CDN}/${k}x160.png`);
  add(`${BRAND_CDN}/${k}x640.png`);
}

/** Варианты URL логотипа: API, CDN по base-тикеру (префы), ISIN, тикер; размеры x160/x640 */
export function getCompanyLogoCandidates(company: Company): string[] {
  const out: string[] = [];
  const add = (u: string) => {
    const t = u.trim();
    if (t && !out.includes(t)) out.push(t);
  };

  const raw = company.brand_logo_url?.trim();
  if (raw) {
    // Сначала размерные варианты: ссылка из API без суффикса даёт 403,
    // и без этого первая попытка гарантированно тратится впустую.
    if (raw.toLowerCase().includes('invest-brands.cdn-tinkoff.ru')) {
      withSizeSuffixes(raw, add);
    }
    add(raw);
  }

  const ticker = company.ticker?.trim() ?? '';
  const baseTicker = deprefMoexTicker(ticker);
  if (baseTicker) {
    addCdnKeys(baseTicker, add);
  }

  const isin = company.isin?.trim().toUpperCase();
  if (isin && /^[A-Z0-9]{4,}$/.test(isin)) {
    addCdnKeys(isin, add);
  }

  if (ticker) {
    const t = ticker.toUpperCase();
    if (/^[A-Z0-9._-]{1,20}$/.test(t)) {
      addCdnKeys(t, add);
    }
  }

  return out;
}
