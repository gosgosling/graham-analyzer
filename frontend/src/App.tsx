import React from 'react';
import { BrowserRouter as Router, Routes, Route, Link, useLocation } from 'react-router-dom';
import './App.css';
import SecuritiesList from './pages/SecuritiesList';
import CompaniesList from './pages/CompaniesList';
import CompanyDetail from './pages/CompanyDetail';
import BondsList from './pages/BondsList';
import BondDetail from './pages/BondDetail';

type NavSection = 'securities' | 'companies' | 'bonds';

function Navigation() {
  const location = useLocation();

  const active: NavSection =
    location.pathname === '/' ? 'securities'
    : location.pathname.startsWith('/bond') ? 'bonds'
    : 'companies';

  const navBtn = (section: NavSection, to: string, label: string) => (
    <Link to={to} style={{ textDecoration: 'none' }}>
      <button
        style={{
          padding: '10px 20px',
          backgroundColor: active === section ? '#3498db' : '#ecf0f1',
          color: active === section ? 'white' : '#2c3e50',
          border: 'none',
          borderRadius: '4px',
          cursor: 'pointer',
          fontWeight: active === section ? '600' : '400',
          transition: 'all 0.2s ease',
        }}
      >
        {label}
      </button>
    </Link>
  );

  return (
    <div style={{ padding: '20px', borderBottom: '1px solid #e1e8ed', backgroundColor: '#f8f9fa' }}>
      <div style={{ maxWidth: '1400px', margin: '0 auto', display: 'flex', gap: '10px' }}>
        {navBtn('securities', '/', '📈 Ценные бумаги (MOEX)')}
        {navBtn('companies', '/companies', '🏢 Компании (T Invest)')}
        {navBtn('bonds', '/bonds', '📄 Облигации')}
      </div>
    </div>
  );
}

function App() {
  return (
    <Router>
      <div className="App">
        <Navigation />
        <Routes>
          <Route path="/" element={<SecuritiesList />} />
          <Route path="/companies" element={<CompaniesList />} />
          <Route path="/company/:companyId" element={<CompanyDetail />} />
          <Route path="/bonds" element={<BondsList />} />
          <Route path="/bond/:figi" element={<BondDetail />} />
        </Routes>
      </div>
    </Router>
  );
}

export default App;
