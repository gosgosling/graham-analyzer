/**
 * Выгрузка таблиц карточки в Excel, CSV и TXT — прямо в браузере, без
 * сервера и сторонних библиотек.
 *
 * Excel — настоящий .xlsx: книга из одного листа, числа числами (их можно
 * складывать и строить графики), первая колонка и шапка закреплены. Файл
 * xlsx — это zip с XML внутри; сжатие не нужно, файлы кладутся как есть.
 *
 * CSV — для русского Excel: разделитель «;», дробная часть через запятую,
 * UTF-8 с BOM, иначе кириллица откроется кракозябрами.
 */

export type Cell = string | number | null;

export interface Sheet {
  /** Первая строка файла: компания, что за таблица, единицы. */
  title: string;
  header: string[];
  rows: { cells: Cell[]; group?: boolean }[];
}

export type ExportFormat = 'xlsx' | 'csv' | 'txt';

export const FORMAT_LABEL: Record<ExportFormat, string> = { xlsx: 'Excel', csv: 'CSV', txt: 'TXT' };

/** «1 234,5», «−12», «» — число без лишних нулей, как пишут по-русски. */
function ruNumber(v: number): string {
  return v.toLocaleString('ru-RU', { maximumFractionDigits: 6, useGrouping: false }).replace('−', '-');
}

// ── CSV ──

export function toCsv(sheet: Sheet): string {
  const esc = (c: Cell) => {
    if (c == null) return '';
    const s = typeof c === 'number' ? ruNumber(c) : c;
    return /[;"\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [
    [sheet.title],
    sheet.header,
    ...sheet.rows.map((r) => r.cells),
  ].map((cells) => cells.map(esc).join(';'));
  return `﻿${lines.join('\r\n')}\r\n`;
}

// ── TXT ──

/** Ровные колонки: подписи слева, числа по правому краю. */
export function toTxt(sheet: Sheet): string {
  const show = (c: Cell) => (c == null ? '' : typeof c === 'number'
    ? c.toLocaleString('ru-RU', { maximumFractionDigits: 6 }).replace(/ | /g, ' ')
    : c);
  const table = [sheet.header, ...sheet.rows.map((r) => r.cells.map(show))];
  const n = Math.max(...table.map((r) => r.length));
  const widths = Array.from({ length: n }, (_, i) => Math.max(...table.map((r) => (r[i] ?? '').length)));
  const line = (cells: string[], group = false) => {
    if (group) return cells[0];
    return cells.map((c, i) => (i === 0 ? c.padEnd(widths[0]) : (c ?? '').padStart(widths[i]))).join('  ').trimEnd();
  };
  const rule = '─'.repeat(widths.reduce((a, b) => a + b, 0) + 2 * (n - 1));
  const body = sheet.rows.map((r) => (r.group
    ? `\n${line(r.cells.map(show), true)}`
    : line(r.cells.map(show))));
  return [sheet.title, '', line(sheet.header), rule, ...body, ''].join('\n');
}

// ── XLSX ──

const xmlEsc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

function colName(i: number): string {
  let s = '';
  for (let n = i + 1; n > 0; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + ((n - 1) % 26)) + s;
  return s;
}

function sheetXml(sheet: Sheet): string {
  // Стили: 0 — обычный, 1 — жирный (шапка и группы), 2 — заголовок файла.
  const cell = (c: Cell, ref: string, style = 0) => {
    const s = style ? ` s="${style}"` : '';
    if (c == null || c === '') return style ? `<c r="${ref}"${s}/>` : '';
    if (typeof c === 'number') return `<c r="${ref}"${s}><v>${c}</v></c>`;
    return `<c r="${ref}"${s} t="inlineStr"><is><t xml:space="preserve">${xmlEsc(c)}</t></is></c>`;
  };
  const all: { cells: Cell[]; style: number }[] = [
    { cells: [sheet.title], style: 2 },
    { cells: sheet.header, style: 1 },
    ...sheet.rows.map((r) => ({ cells: r.cells, style: r.group ? 1 : 0 })),
  ];
  const rows = all.map((r, ri) => `<row r="${ri + 1}">${r.cells.map((c, ci) => cell(c, `${colName(ci)}${ri + 1}`, r.style)).join('')}</row>`);
  const labelW = Math.min(60, Math.max(18, ...sheet.rows.map((r) => String(r.cells[0] ?? '').length + 2)));
  const n = sheet.header.length;
  return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    + '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    + '<sheetViews><sheetView workbookViewId="0">'
    + '<pane xSplit="1" ySplit="2" topLeftCell="B3" activePane="bottomRight" state="frozen"/>'
    + '</sheetView></sheetViews>'
    + `<cols><col min="1" max="1" width="${labelW}" customWidth="1"/>${n > 1 ? `<col min="2" max="${n}" width="12" customWidth="1"/>` : ''}</cols>`
    + `<sheetData>${rows.join('')}</sheetData>`
    + '</worksheet>';
}

const STYLES = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
  + '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
  + '<fonts count="3"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font>'
  + '<font><b/><sz val="13"/><name val="Calibri"/></font></fonts>'
  + '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
  + '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
  + '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
  + '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
  + '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
  + '<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
  + '</styleSheet>';

function workbookFiles(sheet: Sheet, sheetName: string): [string, string][] {
  // Имя листа: до 31 символа и без []:*?/\
  const name = xmlEsc(sheetName.replace(/[[\]:*?/\\]/g, ' ').slice(0, 31));
  return [
    ['[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
      + '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
      + '<Default Extension="xml" ContentType="application/xml"/>'
      + '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
      + '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
      + '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
      + '</Types>'],
    ['_rels/.rels', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
      + '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
      + '</Relationships>'],
    ['xl/workbook.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      + '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
      + `<sheets><sheet name="${name}" sheetId="1" r:id="rId1"/></sheets></workbook>`],
    ['xl/_rels/workbook.xml.rels', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
      + '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
      + '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
      + '</Relationships>'],
    ['xl/worksheets/sheet1.xml', sheetXml(sheet)],
    ['xl/styles.xml', STYLES],
  ];
}

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

export function crc32(data: Uint8Array): number {
  let c = 0xffffffff;
  for (let i = 0; i < data.length; i += 1) c = CRC_TABLE[(c ^ data[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

/** Zip без сжатия (метод «stored»): xlsx большего не требует. */
export function zipStored(files: [string, Uint8Array][]): Uint8Array {
  const enc = new TextEncoder();
  const local: Uint8Array[] = [];
  const central: Uint8Array[] = [];
  let offset = 0;
  for (const [path, data] of files) {
    const name = enc.encode(path);
    const crc = crc32(data);
    const head = new DataView(new ArrayBuffer(30));
    head.setUint32(0, 0x04034b50, true);
    head.setUint16(4, 20, true);
    head.setUint16(6, 0x0800, true); // имена в UTF-8
    head.setUint16(8, 0, true);
    head.setUint16(10, 0, true);
    head.setUint16(12, 0x21, true); // 01.01.1980
    head.setUint32(14, crc, true);
    head.setUint32(18, data.length, true);
    head.setUint32(22, data.length, true);
    head.setUint16(26, name.length, true);
    local.push(new Uint8Array(head.buffer), name, data);

    const dir = new DataView(new ArrayBuffer(46));
    dir.setUint32(0, 0x02014b50, true);
    dir.setUint16(4, 20, true);
    dir.setUint16(6, 20, true);
    dir.setUint16(8, 0x0800, true);
    dir.setUint16(14, 0x21, true);
    dir.setUint32(16, crc, true);
    dir.setUint32(20, data.length, true);
    dir.setUint32(24, data.length, true);
    dir.setUint16(28, name.length, true);
    dir.setUint32(42, offset, true);
    central.push(new Uint8Array(dir.buffer), name);
    offset += 30 + name.length + data.length;
  }
  const dirSize = central.reduce((a, b) => a + b.length, 0);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true);
  end.setUint16(8, files.length, true);
  end.setUint16(10, files.length, true);
  end.setUint32(12, dirSize, true);
  end.setUint32(16, offset, true);
  const parts = [...local, ...central, new Uint8Array(end.buffer)];
  const out = new Uint8Array(parts.reduce((a, b) => a + b.length, 0));
  let pos = 0;
  for (const p of parts) {
    out.set(p, pos);
    pos += p.length;
  }
  return out;
}

export function toXlsx(sheet: Sheet, sheetName: string): Uint8Array {
  const enc = new TextEncoder();
  return zipStored(workbookFiles(sheet, sheetName).map(([p, s]) => [p, enc.encode(s)]));
}

// ── Скачивание ──

const MIME: Record<ExportFormat, string> = {
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  csv: 'text/csv;charset=utf-8',
  txt: 'text/plain;charset=utf-8',
};

export function downloadSheet(sheet: Sheet, format: ExportFormat, fileBase: string, sheetName: string): void {
  const body: BlobPart = format === 'xlsx' ? toXlsx(sheet, sheetName) : format === 'csv' ? toCsv(sheet) : toTxt(sheet);
  const blob = new Blob([body], { type: MIME[format] });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${fileBase.replace(/[\\/:*?"<>|]+/g, ' ').trim()}.${format}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/**
 * Число из подписи ячейки: «1 234,5», «−12,0%», «0,45×», «1,2 трлн». Если
 * в подписи не только число (единицы, «убыток»), возвращаем текст как есть.
 */
export function parseCellText(text: string): Cell {
  const t = text.replace(/[   ]/g, ' ').trim();
  if (!t || t === '—' || t === '–' || t === '-') return null;
  // Крестик в листе — «не выплачивали», а не знак умножения.
  if (t === '×') return 'нет';
  const m = t.match(/^([−+-]?)\s*(\d[\d ]*(?:,\d+)?)\s*(%|×|x|₽|\$)?$/);
  if (!m) return t;
  const v = Number(m[2].replace(/ /g, '').replace(',', '.'));
  if (!Number.isFinite(v)) return t;
  return m[1] === '−' || m[1] === '-' ? -v : v;
}
