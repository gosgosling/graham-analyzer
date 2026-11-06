import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import ReportMatrixViewport from './ReportMatrixViewport';

const columns = Array.from({ length: 10 }, (_, i) => ({ id: i + 1, label: `${2025 - i} · год` }));
let top = -300;
beforeEach(() => {
  top = -300;
  jest.spyOn(window, 'requestAnimationFrame').mockImplementation(callback => { callback(0); return 1; });
  jest.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => {});
  global.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
  jest.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function(this: HTMLElement) {
    return { top, bottom: top + 2000, left: 20, right: 620, width: 600, height: 2000, x: 20, y: top, toJSON: () => ({}) };
  });
  Object.defineProperties(HTMLElement.prototype, {
    clientWidth: { configurable: true, get: () => 600 },
    scrollWidth: { configurable: true, get: () => 2200 },
    offsetWidth: { configurable: true, get: () => 200 },
    offsetLeft: { configurable: true, get() { return Number((this as HTMLElement).dataset.reportId || 0) * 200; } },
    offsetHeight: { configurable: true, get() { return this.tagName === 'THEAD' ? 100 : (this as HTMLElement).classList.contains('crm-navigation') ? 48 : 2000; } },
  });
});
afterEach(() => jest.restoreAllMocks());

function show() {
  return render(<ReportMatrixViewport columns={columns}><table className="crm-table"><thead><tr><th className="crm-th-label">Показатель</th>{columns.map(c => <th key={c.id} data-report-id={c.id}>{c.label}</th>)}</tr></thead><tbody><tr><th className="crm-row-label">Выручка</th>{columns.map(c => <td key={c.id}><input aria-label={`Выручка ${c.id}`} defaultValue="123" /></td>)}</tr></tbody></table></ReportMatrixViewport>);
}

test('columns can be scrolled in the middle of the page without going to the final row', () => {
  show();
  const slider = screen.getByRole('slider', { name: 'Прокрутка столбцов отчётов' });
  const viewport = screen.getByRole('region', { name: 'Матрица отчётов' });
  expect(slider).toHaveAttribute('max', '1600');
  fireEvent.change(slider, { target: { value: '800' } });
  expect(viewport.scrollLeft).toBe(800);
  expect(slider).toHaveValue('800');
  expect(screen.getAllByRole('rowgroup')[0]).toHaveStyle({ transform: 'translateY(348px)' });
  expect(screen.getByRole('columnheader', { name: 'Показатель' })).toHaveStyle({ transform: 'translateX(800px)' });
  expect(screen.getByLabelText('Выручка 5')).toHaveValue('123');
});

test('period jump, paging buttons, and Shift wheel use the same horizontal position', () => {
  show();
  const viewport = screen.getByRole('region', { name: 'Матрица отчётов' });
  fireEvent.change(screen.getByLabelText('Перейти к отчёту'), { target: { value: '5' } });
  expect(viewport.scrollLeft).toBe(800);
  fireEvent.click(screen.getByRole('button', { name: 'К более старым отчётам' }));
  expect(viewport.scrollLeft).toBe(1200);
  fireEvent.wheel(viewport, { shiftKey: true, deltaY: 100 });
  expect(viewport.scrollLeft).toBe(1300);
  fireEvent.wheel(viewport, { deltaY: 100 });
  expect(viewport.scrollLeft).toBe(1300);
});

test('floating scrollbar disappears after leaving the matrix and restores on return', () => {
  show();
  const dock = screen.getByRole('group', { name: 'Навигация по столбцам' });
  expect(dock).not.toHaveAttribute('hidden');
  top = -2300;
  fireEvent.scroll(window);
  expect(dock).toHaveAttribute('hidden');
  top = -500;
  fireEvent.scroll(window);
  expect(dock).not.toHaveAttribute('hidden');
});
