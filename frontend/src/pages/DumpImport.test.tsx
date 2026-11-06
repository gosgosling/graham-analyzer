import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import DumpImport from './DumpImport';
import * as api from '../services/dumpImport.api';

jest.mock('react-router-dom', () => ({ Link: ({ children, to }: { children: React.ReactNode; to: string }) => <a href={to}>{children}</a> }), { virtual: true });
// Focus on workflow decisions; the old CRA Jest resolver cannot load AntD 6 export maps.
jest.mock('antd', () => ({
  Button: ({ children, onClick, disabled }: { children?: React.ReactNode; onClick?: () => void; disabled?: boolean }) => <button onClick={onClick} disabled={disabled}>{children}</button>,
  Space: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  Tag: ({ children }: { children?: React.ReactNode }) => <span>{children}</span>,
  Checkbox: ({ children, checked, onChange }: { children?: React.ReactNode; checked?: boolean; onChange?: React.ChangeEventHandler<HTMLInputElement> }) => <label><input type="checkbox" checked={checked} onChange={onChange} />{children}</label>,
  Select: () => <div />,
  Alert: ({ message }: { message: React.ReactNode }) => <div role="alert">{message}</div>,
  Table: () => <div />,
  Collapse: () => <div />,
  Progress: ({ percent }: { percent: number }) => <div role="progressbar" aria-valuenow={percent} />,
}));
jest.mock('../services/dumpImport.api', () => ({ dumpOverview: jest.fn(), dumpJobs: jest.fn(), dumpJob: jest.fn(), dumpItems: jest.fn(), dumpEvents: jest.fn(), dumpAudit: jest.fn(), dumpCells: jest.fn(), createDumpJob: jest.fn(), controlDumpJob: jest.fn(), dumpDownloadUrl: jest.fn() }));
const mocked = api as jest.Mocked<typeof api>;
const job: api.DumpJob = { id: 'job1', status: 'ready', phase: 'audit', created_at: '2026-11-06T00:00:00Z', updated_at: '2026-11-06T00:00:00Z', message: 'Аудит готов', total: 1, counts: { pending: 0, running: 0, audited: 1, done: 0, error: 0, skipped: 0 }, totals: { facts: 5, add: 3, matches: 1, differences: 1, blocked: 0, new_reports: 0 }, worker_alive: false, backup: null, retry_at: null };

beforeAll(() => {
  Object.defineProperty(window, 'matchMedia', { writable: true, value: jest.fn().mockImplementation(() => ({ matches: false, addListener: jest.fn(), removeListener: jest.fn(), addEventListener: jest.fn(), removeEventListener: jest.fn(), dispatchEvent: jest.fn() })) });
  global.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
  const original = window.getComputedStyle;
  window.getComputedStyle = (element: Element) => original(element);
});
beforeEach(() => {
  jest.clearAllMocks();
  mocked.dumpOverview.mockResolvedValue({ apply_allowed: true, policy_version: 1, worker_alive: false, rules: [], companies: [
    { ticker: 'TEST', name: 'Обычная', company_id: 1, kind: 'industrial', protected: false, excluded: false },
    { ticker: 'FULL', name: 'Защищена', company_id: 2, kind: 'industrial', protected: true, excluded: false },
    { ticker: 'HOLD', name: 'Холдинг', company_id: 3, kind: 'holding', protected: false, excluded: true },
  ] });
  mocked.dumpJobs.mockResolvedValue([]); mocked.dumpJob.mockResolvedValue(job);
  mocked.dumpItems.mockResolvedValue([]); mocked.dumpEvents.mockResolvedValue([]);
  mocked.createDumpJob.mockResolvedValue(job); mocked.controlDumpJob.mockResolvedValue(job);
});
function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(<QueryClientProvider client={client}><DumpImport /></QueryClientProvider>);
}

test('bulk selection excludes holdings and protected companies; first action only audits', async () => {
  show();
  await waitFor(() => expect(screen.getByRole('button', { name: 'Выбрать незаполненные компании' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Выбрать незаполненные компании' }));
  const start = await screen.findByRole('button', { name: 'Запустить загрузку и аудит (1)' });
  fireEvent.click(start);
  await waitFor(() => expect(mocked.createDumpJob).toHaveBeenCalledWith(['TEST'], true));
  expect(mocked.controlDumpJob).not.toHaveBeenCalled();
});

test('apply is a separate explicit action after the audit', async () => {
  mocked.dumpJobs.mockResolvedValue([job]);
  show();
  fireEvent.click(await screen.findByRole('button', { name: 'Создать бэкап и перенести готовые данные' }));
  await waitFor(() => expect(mocked.controlDumpJob).toHaveBeenCalledWith('job1', 'apply'));
  expect(mocked.createDumpJob).not.toHaveBeenCalled();
});

test('apply progress counts applied companies rather than already audited companies', async () => {
  const applying: api.DumpJob = { ...job, status: 'running', phase: 'apply', total: 5, counts: { ...job.counts, audited: 4, done: 1 } };
  mocked.dumpJobs.mockResolvedValue([applying]); mocked.dumpJob.mockResolvedValue(applying);
  show();
  await waitFor(() => expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '20'));
});
