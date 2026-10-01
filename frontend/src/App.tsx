import React, { useMemo } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { ConfigProvider, theme as antdTheme } from 'antd';
import ruRU from 'antd/locale/ru_RU';
import './App.css';
import SecuritiesList from './pages/SecuritiesList';
import CompaniesList from './pages/CompaniesList';
import CompanyDetail from './pages/CompanyDetail';
import CompanyReportsMatrix from './pages/CompanyReportsMatrix';
import BondsList from './pages/BondsList';
import BondDetail from './pages/BondDetail';
import MassParse from './pages/MassParse';
import ReportCalendar from './pages/ReportCalendar';
import DisclosureCoverage from './pages/DisclosureCoverage';
import MarketMultiple from './pages/MarketMultiple';
import MarketScreen from './pages/MarketScreen';
import SiteHeader from './components/SiteHeader';
import SiteFooter from './components/SiteFooter';
import AdminPage from './pages/AdminPage';
import { useTheme } from './contexts/ThemeContext';

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
        // Значения дублируют токены из tokens.css: Ant Design читает свою
        // палитру из JS и до CSS-переменных не достаёт. Светлая половина
        // раньше жила на Flat UI (#3498db, #27ae60, #e67e22) и расходилась
        // с остальным интерфейсом — теперь обе половины из одной шкалы.
        colorPrimary: isDark ? '#60a5fa' : '#2563eb',
        colorInfo:    isDark ? '#60a5fa' : '#2563eb',
        colorSuccess: isDark ? '#34d399' : '#16a34a',
        colorWarning: isDark ? '#fbbf24' : '#d97706',
        colorError:   isDark ? '#f87171' : '#dc2626',
        colorBgBase:      isDark ? '#11161d' : '#ffffff',
        colorBgContainer: isDark ? '#171c25' : '#ffffff',
        colorBgElevated:  isDark ? '#222937' : '#ffffff',
        colorBgLayout:    isDark ? '#0e1217' : '#f6f8fb',
        colorTextBase:    isDark ? '#e6e9ef' : '#1e293b',
        colorBorder:      isDark ? 'rgba(255,255,255,0.10)' : '#e3e9ef',
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
          <SiteHeader />
          <Routes>
            <Route path="/" element={<SecuritiesList />} />
            <Route path="/companies" element={<CompaniesList />} />
            <Route path="/company/:companyId" element={<CompanyDetail />} />
            <Route path="/company/:companyId/reports-matrix" element={<CompanyReportsMatrix />} />
            <Route path="/bonds" element={<BondsList />} />
            <Route path="/bond/:figi" element={<BondDetail />} />
            <Route path="/mass-parse" element={<MassParse />} />
            <Route path="/disclosure" element={<DisclosureCoverage />} />
            <Route path="/calendar" element={<ReportCalendar />} />
            <Route path="/valuation" element={<MarketMultiple />} />
            <Route path="/screen" element={<MarketScreen />} />
            <Route path="/admin" element={<AdminPage />} />
          </Routes>
          <SiteFooter />
        </div>
      </Router>
    </ThemedAntDConfig>
  );
}

export default App;
