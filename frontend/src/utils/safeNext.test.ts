import { safeNext } from './safeNext';

test('возвращает только на свои страницы', () => {
  expect(safeNext('/company/21?tab=valuation')).toBe('/company/21?tab=valuation');
  expect(safeNext(null)).toBe('/companies');
  expect(safeNext('https://evil.example')).toBe('/companies');
  expect(safeNext('//evil.example')).toBe('/companies');
  expect(safeNext('/\\evil.example')).toBe('/companies');
  expect(safeNext('javascript:alert(1)')).toBe('/companies');
});
