import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import MatrixWorkspaceControls, { useMatrixWorkspace } from './MatrixWorkspaceControls';

function Matrix() {
  const { workspace, setWorkspace } = useMatrixWorkspace();
  return <><MatrixWorkspaceControls active={workspace} onChange={setWorkspace} />
    <input aria-label="Прибыль" defaultValue="123" /></>;
}
let fullscreenElement: Element | null = null;
let enter: jest.Mock;
let exit: jest.Mock;
beforeEach(() => {
  fullscreenElement = null;
  Object.defineProperty(document, 'fullscreenElement', { configurable: true, get: () => fullscreenElement });
  enter = jest.fn(async () => {
    fullscreenElement = document.documentElement;
    document.dispatchEvent(new Event('fullscreenchange'));
  });
  exit = jest.fn(async () => {
    fullscreenElement = null;
    document.dispatchEvent(new Event('fullscreenchange'));
  });
  Object.defineProperty(document.documentElement, 'requestFullscreen', { configurable: true, value: enter });
  Object.defineProperty(document, 'exitFullscreen', { configurable: true, value: exit });
});

test('workspace keeps edited input mounted without expanding tiled browser automatically', () => {
  const { unmount } = render(<Matrix />);
  const input = screen.getByLabelText('Прибыль');
  fireEvent.change(input, { target: { value: '456' } });
  fireEvent.click(screen.getByRole('button', { name: 'Развернуть рабочую область' }));
  expect(document.body).toHaveClass('crm-workspace');
  expect(enter).not.toHaveBeenCalled();
  expect(screen.getByLabelText('Прибыль')).toBe(input);
  expect(input).toHaveValue('456');
  fireEvent.click(screen.getByRole('button', { name: 'Свернуть рабочую область' }));
  expect(document.body).not.toHaveClass('crm-workspace');
  expect(input).toHaveValue('456');
  fireEvent.click(screen.getByRole('button', { name: 'Развернуть рабочую область' }));
  unmount();
  expect(document.body).not.toHaveClass('crm-workspace');
});

test('browser Escape returns from fullscreen to compact workspace; navigation exits fullscreen', async () => {
  const { unmount } = render(<Matrix />);
  fireEvent.click(screen.getByRole('button', { name: 'Развернуть рабочую область' }));
  fireEvent.click(screen.getByRole('button', { name: 'На весь экран' }));
  await screen.findByRole('button', { name: 'Вернуть окно' });
  expect(enter).toHaveBeenCalledTimes(1);
  await act(async () => { await document.exitFullscreen(); });
  expect(document.body).toHaveClass('crm-workspace');
  expect(screen.getByRole('button', { name: 'На весь экран' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'На весь экран' }));
  await screen.findByRole('button', { name: 'Вернуть окно' });
  unmount();
  expect(exit).toHaveBeenCalledTimes(2);
});

test('rejected fullscreen keeps workspace and edited cells available', async () => {
  enter.mockRejectedValue(new Error('Denied'));
  render(<Matrix />);
  fireEvent.click(screen.getByRole('button', { name: 'Развернуть рабочую область' }));
  fireEvent.click(screen.getByRole('button', { name: 'На весь экран' }));
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Браузер не разрешил'));
  expect(document.body).toHaveClass('crm-workspace');
  expect(screen.getByLabelText('Прибыль')).toHaveValue('123');
});
