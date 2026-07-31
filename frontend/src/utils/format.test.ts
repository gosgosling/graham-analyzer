import { formatMln } from './format';

describe('formatMln', () => {
  it('до тысячи миллионов — в млн, с одним знаком', () => {
    expect(formatMln(842.37)).toBe('842,4 млн ₽');
    expect(formatMln(0)).toBe('0 млн ₽');
  });

  it('от миллиарда и триллиона — с укрупнением масштаба', () => {
    expect(formatMln(1_500)).toBe('1.50 млрд ₽');
    expect(formatMln(2_400_000)).toBe('2.40 трлн ₽');
  });

  it('отрицательные значения (убыток, чистый долг) считаются по модулю', () => {
    expect(formatMln(-1_500)).toBe('-1.50 млрд ₽');
    expect(formatMln(-12.5)).toBe('-12,5 млн ₽');
  });

  it('валюта задаётся вызывающим — отчёты бывают не только в рублях', () => {
    expect(formatMln(1_500, 'USD')).toBe('1.50 млрд USD');
  });

  it('null в валюте — только масштаб (единица стоит в заголовке колонки)', () => {
    expect(formatMln(1_500, null)).toBe('1.50 млрд');
    expect(formatMln(42, null)).toBe('42 млн');
  });

  it('пустое значение — прочерк', () => {
    expect(formatMln(null)).toBe('—');
    expect(formatMln(undefined)).toBe('—');
    expect(formatMln(NaN)).toBe('—');
  });
});
