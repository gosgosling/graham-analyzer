import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getCompanies, createFinancialReport } from '../services/api';
import { Company, FinancialReportCreate } from '../types';
import ReportForm from '../components/ReportForm';
import './SecuritiesList.css'; // Используем те же стили

const CompaniesList: React.FC = () => {
  const [selectedCompany, setSelectedCompany] = useState<Company | null>(null);
  const [showForm, setShowForm] = useState(false);
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ['companies'],
    queryFn: getCompanies
  });

  const createReportMutation = useMutation({
    mutationFn: createFinancialReport,
    onSuccess: () => {
      // Обновляем список отчетов после успешного создания
      queryClient.invalidateQueries({ queryKey: ['reports'] });
      setShowForm(false);
      setSelectedCompany(null);
      alert('Отчет успешно добавлен!');
    },
    onError: (error: any) => {
      console.error('Error creating report:', error);
      alert('Ошибка при создании отчета: ' + (error.response?.data?.detail || error.message));
    }
  });

  const handleAddReport = (company: Company) => {
    setSelectedCompany(company);
    setShowForm(true);
  };

  const handleFormSubmit = async (reportData: FinancialReportCreate) => {
    await createReportMutation.mutateAsync(reportData);
  };

  const handleFormCancel = () => {
    setShowForm(false);
    setSelectedCompany(null);
  };

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
              <th>Действия</th>
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
                  <td className="action-cell">
                    <button
                      onClick={() => handleAddReport(company)}
                      className="btn-add-report"
                      title="Добавить финансовый отчет"
                      disabled={!company.id}
                    >
                      + Отчет
                    </button>
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={9} style={{ textAlign: 'center', padding: '20px' }}>
                  Нет данных. Проверьте настройку TINKOFF_TOKEN в .env файле.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      
      {/* Модальное окно с формой */}
      {showForm && selectedCompany && selectedCompany.id && (
        <ReportForm
          companyId={selectedCompany.id}
          companyName={selectedCompany.name}
          onSubmit={handleFormSubmit}
          onCancel={handleFormCancel}
        />
      )}
    </div>
  );
};

export default CompaniesList;

