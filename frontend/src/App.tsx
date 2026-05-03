import React, { useMemo } from 'react';
import { BrowserRouter as Router, Routes, Route, Link, useLocation } from 'react-router-dom';
import { ConfigProvider, theme as antdTheme } from 'antd';
import ruRU from 'antd/locale/ru_RU';
import './App.css';
import SecuritiesList from './pages/SecuritiesList';
import CompaniesList from './pages/CompaniesList';
import CompanyDetail from './pages/CompanyDetail';
import CompanyReportsMatrix from './pages/CompanyReportsMatrix';
import BondsList from './pages/BondsList';
import BondDetail from './pages/BondDetail';
import ThemeToggle from './components/ThemeToggle';
import { useTheme } from './contexts/ThemeContext';

type NavSection = 'securities' | 'companies' | 'bonds';

function Navigation() {
  const location = useLocation();

  const active: NavSection =
    location.pathname === '/' ? 'securities'
    : location.pathname.startsWith('/bond') ? 'bonds'
    : 'companies';

  const navBtn = (section: NavSection, to: string, label: string) => (
    <Link to={to} className="app-nav-link">
      <button
        type="button"
        className={`app-nav-btn${active === section ? ' is-active' : ''}`}
      >
        {label}
      </button>
    </Link>
  );

  return (
    <nav className="app-nav">
      <div className="app-nav-inner">
        <div className="app-nav-tabs">
          {navBtn('securities', '/', '📈 Ценные бумаги (MOEX)')}
          {navBtn('companies', '/companies', '🏢 Компании (T-Invest)')}
          {navBtn('bonds', '/bonds', '📄 Облигации')}
        </div>
        <div className="app-nav-actions">
          <ThemeToggle />
        </div>
      </div>
    </nav>
  );
}

/**
 * Прокси Ant Design под текущую тему: переключаем алгоритм
 * (default ↔ dark) и ключевые токены, чтобы AntD-компоненты
 * (Modal, Select, DatePicker, Table, Form…) не были «островом
 * белого» в тёмной теме.
 */
function ThemedAntDConfig({ children }: { children: React.ReactNode }) {
  const { resolved } = useTheme();

  const config = useMemo(() => {
    const isDark = resolved === 'dark';
    return {
      algorithm: isDark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
      token: {
        colorPrimary: isDark ? '#60a5fa' : '#3498db',
        colorInfo:    isDark ? '#60a5fa' : '#3498db',
        colorSuccess: isDark ? '#34d399' : '#27ae60',
        colorWarning: isDark ? '#fbbf24' : '#e67e22',
        colorError:   isDark ? '#f87171' : '#b91c1c',
        colorBgBase:      isDark ? '#11161d' : '#ffffff',
        colorBgContainer: isDark ? '#171c25' : '#ffffff',
        colorBgElevated:  isDark ? '#222937' : '#ffffff',
        colorBgLayout:    isDark ? '#0e1217' : '#f5f7fa',
        colorTextBase:    isDark ? '#e6e9ef' : '#2c3e50',
        colorBorder:      isDark ? 'rgba(255,255,255,0.10)' : '#e1e8ed',
        colorBorderSecondary: isDark ? 'rgba(255,255,255,0.06)' : '#eef2f6',
        borderRadius: 8,
        fontFamily:
          "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, 'Helvetica Neue', sans-serif",
      },
    };
  }, [resolved]);

  return (
    <ConfigProvider locale={ruRU} theme={config}>
      {children}
    </ConfigProvider>
  );
}

function App() {
  return (
    <ThemedAntDConfig>
      <Router>
        <div className="App">
          <Navigation />
          <Routes>
            <Route path="/" element={<SecuritiesList />} />
            <Route path="/companies" element={<CompaniesList />} />
            <Route path="/company/:companyId" element={<CompanyDetail />} />
            <Route path="/company/:companyId/reports-matrix" element={<CompanyReportsMatrix />} />
            <Route path="/bonds" element={<BondsList />} />
            <Route path="/bond/:figi" element={<BondDetail />} />
          </Routes>
        </div>
      </Router>
    </ThemedAntDConfig>
  );
}

export default App;
