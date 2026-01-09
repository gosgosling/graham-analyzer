import React, { useState } from 'react';
import './App.css';
import SecuritiesList from './pages/SecuritiesList';
import CompaniesList from './pages/CompaniesList';

function App() {
  const [activeTab, setActiveTab] = useState<'securities' | 'companies'>('securities');

  return (
    <div className="App">
      <div style={{ padding: '20px', borderBottom: '1px solid #e1e8ed' }}>
        <button
          onClick={() => setActiveTab('securities')}
          style={{
            padding: '10px 20px',
            marginRight: '10px',
            backgroundColor: activeTab === 'securities' ? '#3498db' : '#ecf0f1',
            color: activeTab === 'securities' ? 'white' : '#2c3e50',
            border: 'none',
            borderRadius: '4px',
            cursor: 'pointer',
            fontWeight: activeTab === 'securities' ? '600' : '400'
          }}
        >
          Ценные бумаги (MOEX)
        </button>
        <button
          onClick={() => setActiveTab('companies')}
          style={{
            padding: '10px 20px',
            backgroundColor: activeTab === 'companies' ? '#3498db' : '#ecf0f1',
            color: activeTab === 'companies' ? 'white' : '#2c3e50',
            border: 'none',
            borderRadius: '4px',
            cursor: 'pointer',
            fontWeight: activeTab === 'companies' ? '600' : '400'
          }}
        >
          Компании (T Invest API)
        </button>
      </div>
      {activeTab === 'securities' ? <SecuritiesList /> : <CompaniesList />}
    </div>
  );
}

export default App;
