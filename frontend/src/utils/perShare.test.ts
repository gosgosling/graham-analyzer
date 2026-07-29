import { formatPerShare, formatPerShareWithCurrency } from './perShare';

describe('formatPerShare', () => {
  it('обычная цена — два знака', () => {
    expect(formatPerShare(340.5)).toBe('340,5');
    expect(formatPerShare(62.335)).toBe('62,34');
  });

  it('копеечная бумага не превращается в ноль', () => {
    // ТГК-1: при двух знаках здесь был «0», а вместе с ним нулевые P/E и капитализация.
    expect(formatPerShare(0.004365)).toBe('0,004365');
    expect(formatPerShare(0.0042)).toBe('0,0042');
  });

  it('доли копейки — до шести знаков', () => {
    expect(formatPerShare(0.000345)).toBe('0,000345');
  });

  it('пусто — прочерк или заданный заменитель', () => {
    expect(formatPerShare(null)).toBe('—');
    expect(formatPerShare(undefined)).toBe('—');
    expect(formatPerShare(null, '-')).toBe('-');
  });

  it('валюта подставляется рядом со значением', () => {
    expect(formatPerShareWithCurrency(0.004365)).toBe('0,004365 ₽');
    expect(formatPerShareWithCurrency(12.5, 'USD')).toBe('12,5 USD');
    expect(formatPerShareWithCurrency(null)).toBe('—');
  });
});
