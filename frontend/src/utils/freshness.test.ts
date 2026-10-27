import { freshnessOf } from '../utils/freshness';

const today = new Date('2026-10-27T12:00:00');

test('оценка по годовому отчёту: возраст и путь цены, старая — помечается', () => {
  const f = freshnessOf({ label: 'отчёт 2025', year: 2025, since: '2026-02-27', price_then: 1.62 }, 1.19, today);
  expect(f?.text).toBe('Оценка — по отчёту за 2025 год, известному с 27.02.2026 (8 мес. назад). Цена с тех пор −27%.');
  expect(f?.stale).toBe(true);
});

test('оценка по «12 месяцам» после полугодия — свежая', () => {
  const f = freshnessOf({ label: 'LTM 1П2026', year: 2025, since: '2026-08-28', price_then: 6000 }, 6165, today);
  expect(f?.text).toBe('Оценка — по 12 месяцам по отчёту за 1П 2026, известному с 28.08.2026 (2 мес. назад). Цена с тех пор +3%.');
  expect(f?.stale).toBe(false);
});

test('без основы строки нет', () => {
  expect(freshnessOf(null, 100, today)).toBeNull();
});

test('слова по числу', () => {
  const { plural, yearsWord } = jest.requireActual('./freshness');
  expect(plural(182, ['наблюдение', 'наблюдения', 'наблюдений'])).toBe('наблюдения');
  expect(plural(111, ['наблюдение', 'наблюдения', 'наблюдений'])).toBe('наблюдений');
  expect(yearsWord(4)).toBe('4 года');
  expect(yearsWord(5)).toBe('5 лет');
  expect(yearsWord(21)).toBe('21 год');
});
