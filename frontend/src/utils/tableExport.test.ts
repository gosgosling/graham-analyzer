import { TextDecoder as NodeDecoder, TextEncoder as NodeEncoder } from 'util';
import { crc32, parseCellText, toCsv, toTxt, toXlsx, type Sheet } from './tableExport';

// В jsdom нет TextEncoder — в браузере он есть всегда.
Object.assign(globalThis, { TextEncoder: NodeEncoder, TextDecoder: NodeDecoder });

const sheet: Sheet = {
  title: 'Тест; отчётность',
  header: ['Показатель', '2024', '2025'],
  rows: [
    { cells: ['Баланс'], group: true },
    { cells: ['Выручка', 1234.5, null] },
    { cells: ['Чистый долг', -12, 'н/д'] },
  ],
};

test('CSV для русского Excel: BOM, «;», запятая в дробях, кавычки при «;»', () => {
  const csv = toCsv(sheet);
  expect(csv.startsWith('﻿"Тест; отчётность"')).toBe(true);
  expect(csv).toContain('Выручка;1234,5;\r\n');
  expect(csv).toContain('Чистый долг;-12;н/д');
});

test('TXT: числа выровнены по правому краю', () => {
  const lines = toTxt(sheet).split('\n');
  const rev = lines.find((l) => l.startsWith('Выручка'))!;
  const debt = lines.find((l) => l.startsWith('Чистый долг'))!;
  expect(rev.indexOf('1 234,5') + '1 234,5'.length).toBe(debt.indexOf('-12') + '-12'.length);
});

test('XLSX — zip с подписью PK и листом внутри', () => {
  const bytes = toXlsx(sheet, 'Лист');
  expect(bytes[0]).toBe(0x50);
  expect(bytes[1]).toBe(0x4b);
  const text = new TextDecoder().decode(bytes);
  expect(text).toContain('xl/worksheets/sheet1.xml');
  expect(text).toContain('<v>1234.5</v>');
  expect(text).toContain('state="frozen"');
});

test('crc32 по эталону', () => {
  expect(crc32(new TextEncoder().encode('123456789'))).toBe(0xcbf43926);
});

test('числа из подписей ячеек', () => {
  expect(parseCellText('1 234,5')).toBe(1234.5);
  expect(parseCellText('−12,0%')).toBe(-12);
  expect(parseCellText('+5%')).toBe(5);
  expect(parseCellText('0,87')).toBe(0.87);
  expect(parseCellText('—')).toBeNull();
  expect(parseCellText('> 50')).toBe('> 50');
  expect(parseCellText('×')).toBe('нет');
});
