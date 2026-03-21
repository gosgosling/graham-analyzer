import type { Company } from '../types';

const BRAND_CDN = 'https://invest-brands.cdn-tinkoff.ru';

const HAS_IMG_EXT = /\.(png|webp|jpe?g|svg)(\?.*)?$/i;

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
    add(raw);
    const low = raw.toLowerCase();
    if (low.includes('invest-brands.cdn-tinkoff.ru')) {
      const pathOnly = raw.split('?')[0];
      if (!HAS_IMG_EXT.test(pathOnly)) {
        const base = raw.split('?')[0].replace(/\/$/, '');
        const qs = raw.includes('?') ? `?${raw.split('?')[1]}` : '';
        add(`${base}x160.png${qs}`);
        add(`${base}x640.png${qs}`);
      }
    }
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
