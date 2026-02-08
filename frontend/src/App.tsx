import React from 'react';
import { BrowserRouter as Router, Routes, Route, Link, useLocation } from 'react-router-dom';
import './App.css';
import SecuritiesList from './pages/SecuritiesList';
import CompaniesList from './pages/CompaniesList';
import CompanyDetail from './pages/CompanyDetail';

function Navigation() {
  const location = useLocation();
  const isSecurities = location.pathname === '/';
  const isCompanies = location.pathname === '/companies' || location.pathname.startsWith('/company/');

  return (
    <div style={{ padding: '20px', borderBottom: '1px solid #e1e8ed', backgroundColor: '#f8f9fa' }}>
      <div style={{ maxWidth: '1400px', margin: '0 auto', display: 'flex', gap: '10px' }}>
        <Link to="/" style={{ textDecoration: 'none' }}>
          <button
            style={{
              padding: '10px 20px',
              backgroundColor: isSecurities ? '#3498db' : '#ecf0f1',
              color: isSecurities ? 'white' : '#2c3e50',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
              fontWeight: isSecurities ? '600' : '400',
              transition: 'all 0.2s ease'
            }}
          >
            📈 Ценные бумаги (MOEX)
          </button>
        </Link>
        <Link to="/companies" style={{ textDecoration: 'none' }}>
          <button
            style={{
              padding: '10px 20px',
              backgroundColor: isCompanies ? '#3498db' : '#ecf0f1',
              color: isCompanies ? 'white' : '#2c3e50',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
              fontWeight: isCompanies ? '600' : '400',
              transition: 'all 0.2s ease'
            }}
          >
            🏢 Компании (T Invest API)
          </button>
        </Link>
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
        </Routes>
      </div>
    </Router>
  );
}

export default App;
