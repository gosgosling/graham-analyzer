import type { MarketRow } from '../services/screen.api';
import { filterRows, industries } from './screenTableFilter';

const row = (ticker: string, name: string, profile: string, label: string): MarketRow => ({
  id: 1, ticker, name, profile, profile_label: label,
  passed: 0, checked: 0, clears: false, complete: true, safety: null, cells: [],
});

const rows = [
  row('LKOH', 'Лукойл', 'oil_gas_mining', 'Нефтегаз'),
  row('ROSN', 'Роснефть', 'oil_gas_mining', 'Нефтегаз'),
  row('SBER', 'Сбер Банк', 'bank', 'Банки'),
  row('LENT', 'Лента', 'retail_grocery', 'Продуктовый ритейл'),
  row('PHOR', 'ФосАгро', 'oil_gas_mining', 'Нефтегаз'),
];

describe('поиск в полной таблице', () => {
  it('находит по тикеру без учёта регистра', () => {
    expect(filterRows(rows, 'lkoh', '').map((r) => r.ticker)).toEqual(['LKOH']);
  });

  it('находит по части названия', () => {
    expect(filterRows(rows, 'нефт', '').map((r) => r.ticker)).toEqual(['ROSN']);
  });

  it('не спотыкается о «ё»', () => {
    expect(filterRows([row('X', 'Объединённая компания', 'bank', 'Банки')], 'объединен', '')).toHaveLength(1);
  });

  it('пустой запрос и пустая отрасль — без отбора', () => {
    expect(filterRows(rows, '  ', '')).toHaveLength(rows.length);
  });

  it('отрасль и запрос действуют вместе', () => {
    expect(filterRows(rows, 'л', 'oil_gas_mining').map((r) => r.ticker)).toEqual(['LKOH']);
  });
});

describe('список отраслей', () => {
  it('со счётчиками, самые многочисленные первыми', () => {
    expect(industries(rows)).toEqual([
      { key: 'oil_gas_mining', label: 'Нефтегаз', count: 3 },
      { key: 'bank', label: 'Банки', count: 1 },
      { key: 'retail_grocery', label: 'Продуктовый ритейл', count: 1 },
    ]);
  });
});
