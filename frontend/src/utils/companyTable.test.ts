import { money, sortBy } from './companyTable';

test('деньги в млн ₽ — коротко и с разрядом по величине', () => {
  expect(money(3_702_201)).toBe('3,70 трлн');
  expect(money(559_000)).toBe('559 млрд');
  expect(money(3_488)).toBe('3,5 млрд');
  expect(money(-378_949)).toBe('−379 млрд');
  expect(money(840)).toBe('840 млн');
  expect(money(null)).toBe('—');
});

test('пустые значения внизу в обе стороны', () => {
  const rows = [{ t: 'A', v: 5 }, { t: 'B', v: null }, { t: 'C', v: 9 }, { t: 'D', v: 1 }];
  const order = (dir: 'asc' | 'desc') => sortBy(rows, (r) => r.v, dir).map((r) => r.t).join('');
  expect(order('desc')).toBe('CADB');
  expect(order('asc')).toBe('DACB');
});
