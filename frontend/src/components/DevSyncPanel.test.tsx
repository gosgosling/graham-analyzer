import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import DevSyncPanel from './DevSyncPanel';
import * as api from '../services/admin.api';

jest.mock('../services/admin.api', () => ({ getDevSyncStatus: jest.fn(), prepareDevSync: jest.fn(), applyDevSync: jest.fn() }));
const mocked = api as jest.Mocked<typeof api>;
const ready: api.DevSyncStatus = { enabled: true, status: 'ready', id: 'snapshot', preview: {
  added: 3, updated: 2, removed: 1, companies: [], tables: [], verified_dev: 10, verified_prod: 10,
} };
function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(<QueryClientProvider client={client}><DevSyncPanel /></QueryClientProvider>);
}
beforeEach(() => {
  jest.clearAllMocks();
  mocked.getDevSyncStatus.mockResolvedValue({ enabled: true, status: 'idle' });
  mocked.prepareDevSync.mockResolvedValue({ enabled: true, status: 'preparing' });
  mocked.applyDevSync.mockResolvedValue({ enabled: true, status: 'applying' });
});

test('first action only downloads and compares; applying is separate', async () => {
  show();
  fireEvent.click(await screen.findByRole('button', { name: 'Получить снимок прода и сравнить' }));
  await waitFor(() => expect(mocked.prepareDevSync).toHaveBeenCalledTimes(1));
  expect(mocked.applyDevSync).not.toHaveBeenCalled();
  expect(screen.queryByRole('button', { name: 'Создать бэкап и синхронизировать dev' })).not.toBeInTheDocument();
});

test('ready snapshot shows removals and applies exactly the reviewed snapshot', async () => {
  mocked.getDevSyncStatus.mockResolvedValue(ready);
  show();
  expect(await screen.findByText(/В dev есть отчёты, которых нет на проде/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Создать бэкап и синхронизировать dev' }));
  await waitFor(() => expect(mocked.applyDevSync.mock.calls[0]?.[0]).toBe('snapshot'));
});

test('production and busy jobs cannot trigger local replacement', async () => {
  mocked.getDevSyncStatus.mockResolvedValue({ enabled: false, status: 'unavailable', message: 'Откройте локальную админку dev' });
  show();
  expect(await screen.findByText(/Откройте локальную админку dev/)).toBeInTheDocument();
  expect(screen.queryByRole('button')).not.toBeInTheDocument();
});

test('active job disables duplicate requests', async () => {
  mocked.getDevSyncStatus.mockResolvedValue({ enabled: true, status: 'preparing' });
  show();
  expect(await screen.findByRole('button', { name: 'Получение снимка…' })).toBeDisabled();
});
