/**
 * Отрезок, выделенный на графике цены.
 *
 * Считать его глазами человек не будет — он поверит подписи. Поэтому здесь
 * проверяются не рисование, а арифметика и края: какие дни попали в отрезок и
 * что считается за начало и конец.
 */
import { priceSpan } from './priceSpan';

const series = [
  { date: '2026-03-25', price: 100 },
  { date: '2026-03-27', price: 106.87 },
  { date: '2026-04-15', price: 90 },
  { date: '2026-06-29', price: 73.67 },
  { date: '2026-07-10', price: 80 },
];

describe('priceSpan', () => {
  it('считает изменение между краями, а не между крайними точками ряда', () => {
    const span = priceSpan(series, '2026-03-27', '2026-06-29');

    expect(span?.from.date).toBe('2026-03-27');
    expect(span?.to.date).toBe('2026-06-29');
    expect(span?.delta).toBeCloseTo(-33.2, 2);
    expect(span?.change).toBeCloseTo(-0.3107, 4);
  });

  it('тянуть можно в любую сторону', () => {
    const forward = priceSpan(series, '2026-03-27', '2026-06-29');
    const backward = priceSpan(series, '2026-06-29', '2026-03-27');

    expect(backward).toEqual(forward);
  });

  it('обе границы входят в отрезок', () => {
    const span = priceSpan(series, '2026-03-25', '2026-07-10');

    expect(span?.days).toBe(5);
    expect(span?.from.price).toBe(100);
    expect(span?.to.price).toBe(80);
  });

  it('края, попавшие на нерабочий день, съезжают внутрь отрезка', () => {
    // 26 марта в ряду нет — отрезок начинается со следующего торгового дня.
    const span = priceSpan(series, '2026-03-26', '2026-06-30');

    expect(span?.from.date).toBe('2026-03-27');
    expect(span?.to.date).toBe('2026-06-29');
  });

  it('коридор берётся по всему отрезку, а не по его краям', () => {
    const span = priceSpan(series, '2026-03-25', '2026-07-10');

    expect(span?.min).toBe(73.67);
    expect(span?.max).toBe(106.87);
  });

  it('одна точка отрезком не считается', () => {
    // Иначе щелчок без протяжки показывал бы «0 ₽ · 0%» как результат выбора.
    expect(priceSpan(series, '2026-03-27', '2026-03-27')).toBeNull();
    expect(priceSpan(series, '2026-05-01', '2026-05-02')).toBeNull();
  });

  it('копеечная бумага не теряет знаков', () => {
    // ТГК-2: изменение целиком лежит в четвёртом знаке.
    const penny = [
      { date: '2026-01-01', price: 0.00255 },
      { date: '2026-06-01', price: 0.0153 },
    ];

    expect(priceSpan(penny, '2026-01-01', '2026-06-01')?.delta).toBeCloseTo(0.01275, 6);
  });

  it('от нулевой цены доля не считается', () => {
    const halted = [
      { date: '2026-01-01', price: 0 },
      { date: '2026-06-01', price: 5 },
    ];
    const span = priceSpan(halted, '2026-01-01', '2026-06-01');

    expect(span?.delta).toBe(5);
    expect(span?.change).toBeNull();
  });
});
