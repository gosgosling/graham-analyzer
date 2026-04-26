import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
// Токены ДОЛЖНЫ подключаться до index.css/App.css/компонент-CSS,
// чтобы CSS-переменные были доступны во всём приложении.
import './styles/tokens.css';
import './index.css';
import App from './App';
// Тёмные оверрайды подключаем после App, чтобы они имели больший
// приоритет каскада над компонент-CSS, ещё не мигрированными на токены.
import './styles/theme-dark-overrides.css';
import { ThemeProvider } from './contexts/ThemeContext';
import reportWebVitals from './reportWebVitals';

const queryClient = new QueryClient();

const root = ReactDOM.createRoot(
  document.getElementById('root') as HTMLElement
);
root.render(
  <React.StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </ThemeProvider>
  </React.StrictMode>
);

// If you want to start measuring performance in your app, pass a function
// to log results (for example: reportWebVitals(console.log))
// or send to an analytics endpoint. Learn more: https://bit.ly/CRA-vitals
reportWebVitals();
