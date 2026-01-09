import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { getCompanies } from '../services/api';
import { Company } from '../types';
import './SecuritiesList.css'; // Используем те же стили

const CompaniesList: React.FC = () => {
  const { data, isLoading, error } = useQuery({
    queryKey: ['companies'],
    queryFn: getCompanies
  });

  if (isLoading) {
    return (
      <div className="securities-container">
        <div className="loading">Загрузка данных компаний...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="securities-container">
        <div className="error">Ошибка: {error.message}</div>
      </div>
    );
  }

  return (
    <div className="securities-container">
      <h1 className="securities-title">Российские компании и компании Мосбиржи (T Invest API)</h1>
      <div className="table-wrapper">
        <table className="securities-table">
          <thead>
            <tr>
              <th>FIGI</th>
              <th>Тикер</th>
              <th>Название</th>
              <th>ISIN</th>
              <th>Сектор</th>
              <th>Валюта</th>
              <th>Лот</th>
              <th>Доступно для API</th>
            </tr>
          </thead>
          <tbody>
            {data && data.length > 0 ? (
              data.map((company: Company) => (
                <tr key={company.figi}>
                  <td className="ticker-cell">{company.figi}</td>
                  <td className="ticker-cell">{company.ticker}</td>
                  <td className="name-cell">{company.name}</td>
                  <td className="isin-cell">{company.isin || '-'}</td>
                  <td>{company.sector || '-'}</td>
                  <td className="currency-cell">{company.currency}</td>
                  <td className="lot-cell">{company.lot}</td>
                  <td className="status-cell">
                    <span className={`status-badge ${company.api_trade_available_flag ? 'active' : 'inactive'}`}>
                      {company.api_trade_available_flag ? 'Да' : 'Нет'}
                    </span>
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={8} style={{ textAlign: 'center', padding: '20px' }}>
                  Нет данных. Проверьте настройку TINKOFF_TOKEN в .env файле.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default CompaniesList;

