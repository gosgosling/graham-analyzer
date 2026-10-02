import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
// Шрифты — из сборки, а не с Google: браузер посетителя не отдаёт свой IP
// зарубежному серверу (152-ФЗ, см. docs/PERSONAL_DATA.md). Только кириллица и латиница.
import '@fontsource/ibm-plex-sans/cyrillic-400.css';
import '@fontsource/ibm-plex-sans/latin-400.css';
import '@fontsource/ibm-plex-sans/cyrillic-500.css';
import '@fontsource/ibm-plex-sans/latin-500.css';
import '@fontsource/ibm-plex-sans/cyrillic-600.css';
import '@fontsource/ibm-plex-sans/latin-600.css';
import '@fontsource/ibm-plex-sans/cyrillic-700.css';
import '@fontsource/ibm-plex-sans/latin-700.css';
import '@fontsource/ibm-plex-serif/cyrillic-400.css';
import '@fontsource/ibm-plex-serif/latin-400.css';
import '@fontsource/ibm-plex-serif/cyrillic-500.css';
import '@fontsource/ibm-plex-serif/latin-500.css';
import '@fontsource/ibm-plex-serif/cyrillic-400-italic.css';
import '@fontsource/ibm-plex-serif/latin-400-italic.css';
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
