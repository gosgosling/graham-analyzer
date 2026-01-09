import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { getSecurities } from '../services/api';
import { Security } from '../types';
import './SecuritiesList.css';

const SecuritiesList: React.FC = () => {
  const { data, isLoading, error } = useQuery({
    queryKey: ['securities'],
    queryFn: getSecurities
  });

  // Функция для форматирования чисел
  const formatPrice = (price: number | null): string => {
    if (price === null) return '-';
    return price.toLocaleString('ru-RU', { 
      minimumFractionDigits: 2, 
      maximumFractionDigits: 2 
    });
  };

  // Функция для форматирования даты
  const formatDate = (date: string | null): string => {
    if (!date) return '-';
    return date;
  };

  if (isLoading) {
    return (
      <div className="securities-container">
        <div className="loading">Загрузка данных...</div>
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
      <h1 className="securities-title">Список ценных бумаг</h1>
      <div className="table-wrapper">
        <table className="securities-table">
          <thead>
            <tr>
              <th>Тикер</th>
              <th>Название</th>
              <th>Цена</th>
              <th>ISIN</th>
              <th>Валюта</th>
              <th>Лот</th>
              <th>Статус</th>
              <th>Дата</th>
            </tr>
          </thead>
          <tbody>
            {data?.map((security: Security) => (
              <tr key={security.secid}>
                <td className="ticker-cell">{security.secid}</td>
                <td className="name-cell">{security.shortname}</td>
                <td className="price-cell">{formatPrice(security.prevprice)}</td>
                <td className="isin-cell">{security.isin}</td>
                <td className="currency-cell">{security.currencyid}</td>
                <td className="lot-cell">{security.lotsize}</td>
                <td className="status-cell">
                  <span className={`status-badge ${security.status === 'A' ? 'active' : 'inactive'}`}>
                    {security.status === 'A' ? 'Активна' : 'Неактивна'}
                  </span>
                </td>
                <td className="date-cell">{formatDate(security.prevdate)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default SecuritiesList;