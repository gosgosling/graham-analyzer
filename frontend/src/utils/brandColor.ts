/**
 * Парсит #RRGGBB / #RGB в sRGB 0–255.
 */
export function parseHexRgb(hex: string): { r: number; g: number; b: number } | null {
  const raw = hex.replace('#', '').trim();
  if (!raw) return null;
  const full =
    raw.length === 3
      ? raw
          .split('')
          .map((c) => c + c)
          .join('')
      : raw;
  if (full.length !== 6) return null;
  const num = parseInt(full, 16);
  if (Number.isNaN(num)) return null;
  return { r: (num >> 16) & 255, g: (num >> 8) & 255, b: num & 255 };
}

/** Относительная яркость W3C (0…1). Выше ≈ светлее фон. */
export function relativeLuminance(hex: string): number {
  const rgb = parseHexRgb(hex);
  if (!rgb) return 0.35;
  const lin = (c: number) => {
    const x = c / 255;
    return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4);
  };
  const R = lin(rgb.r);
  const G = lin(rgb.g);
  const B = lin(rgb.b);
  return 0.2126 * R + 0.7152 * G + 0.0722 * B;
}

/**
 * Ч/б/серый бренд из API — в шапке показываем дефолтный фиолетовый градиент.
 * (низкая насыщенность: R≈G≈B, или почти чёрный/белый)
 */
export function isNeutralBrandForHero(hex: string | null | undefined): boolean {
  if (!hex || typeof hex !== 'string') return false;
  const s = hex.trim().toLowerCase();
  if (['black', 'white', 'gray', 'grey', 'silver'].includes(s)) return true;
  if (s === '#000' || s === '#000000') return true;
  if (s === '#fff' || s === '#ffffff') return true;

  const rgb = parseHexRgb(hex);
  if (!rgb) return false;
  const { r, g, b } = rgb;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const delta = max - min;
  const L = relativeLuminance(hex);
  if (L <= 0.1) return true;
  if (L >= 0.9) return true;
  if (delta <= 14) return true;
  return false;
}

/**
 * Светлый фирменный цвет / белый / серый — белый текст плохо читается.
 */
export function isLightBrandHex(hex: string | null | undefined): boolean {
  if (!hex || typeof hex !== 'string') return false;
  const s = hex.trim().toLowerCase();
  if (s === '#fff' || s === '#ffffff' || s === 'white') return true;
  if (s === '#f5f5f5' || s === '#eeeeee' || s === '#e0e0e0') return true;
  const L = relativeLuminance(hex);
  /* Порог чуть ниже: часть «серых» брендов в API всё ещё плохо читается с белым текстом */
  return L > 0.48;
}

/**
 * Затемняет hex-цвет для второго стопа градиента в шапке.
 */
export function shadeHex(hex: string, factor: number): string {
  const raw = hex.replace('#', '').trim();
  if (!raw) return '#333333';
  const full =
    raw.length === 3
      ? raw
          .split('')
          .map((c) => c + c)
          .join('')
      : raw;
  if (full.length !== 6) return hex;
  const num = parseInt(full, 16);
  if (Number.isNaN(num)) return hex;
  let r = (num >> 16) & 255;
  let g = (num >> 8) & 255;
  let b = num & 255;
  r = Math.min(255, Math.round(r * factor));
  g = Math.min(255, Math.round(g * factor));
  b = Math.min(255, Math.round(b * factor));
  return `#${((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1)}`;
}
