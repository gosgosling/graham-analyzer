import { passwordScore } from './passwordScore';

test('короткий — ноль, однообразный — слабый, длинная фраза — отлично', () => {
  expect(passwordScore('short')).toBe(0);
  expect(passwordScore('aaaaabbbbbbb')).toBe(1);
  expect(passwordScore('зелёный чайник на окне у бабушки')).toBe(4);
  expect(passwordScore('зелёный чайник')).toBeGreaterThanOrEqual(2);
});
