import React, { useState } from 'react';
import { FinancialReportCreate } from '../types';
import './ReportForm.css';

interface ReportFormProps {
    companyId: number;
    companyName: string;
    onSubmit: (reportData: FinancialReportCreate) => Promise<void>;
    onCancel: () => void;
}

const ReportForm: React.FC<ReportFormProps> = ({ companyId, companyName, onSubmit, onCancel }) => {
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);
    
    const [formData, setFormData] = useState<FinancialReportCreate>({
        company_id: companyId,
        report_date: '',
        price_per_share: null,
        shares_outstanding: null,
        revenue: null,
        net_income: null,
        total_assets: null,
        current_assets: null,
        total_liabilities: null,
        current_liabilities: null,
        equity: null,
        dividends_per_share: null,
        dividends_paid: false,
        currency: 'RUB',
        exchange_rate: null,
    });

    const handleInputChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
        const { name, value, type } = e.target;
        
        if (type === 'checkbox') {
            const checked = (e.target as HTMLInputElement).checked;
            setFormData(prev => ({ ...prev, [name]: checked }));
        } else if (type === 'number') {
            setFormData(prev => ({ ...prev, [name]: value ? parseFloat(value) : null }));
        } else {
            setFormData(prev => ({ ...prev, [name]: value }));
        }
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError(null);
        
        // Валидация
        if (!formData.report_date) {
            setError('Дата отчета обязательна');
            return;
        }
        
        if (formData.currency === 'USD' && !formData.exchange_rate) {
            setError('Для отчетов в USD необходимо указать курс доллара');
            return;
        }
        
        setIsSubmitting(true);
        
        try {
            await onSubmit(formData);
        } catch (err: any) {
            setError(err.response?.data?.detail || 'Ошибка при сохранении отчета');
        } finally {
            setIsSubmitting(false);
        }
    };

    return (
        <div className="report-form-overlay">
            <div className="report-form-container">
                <div className="report-form-header">
                    <h2>Добавить финансовый отчет</h2>
                    <p className="company-name">Компания: {companyName}</p>
                </div>
                
                {error && <div className="error-message">{error}</div>}
                
                <form onSubmit={handleSubmit} className="report-form">
                    {/* Основные данные */}
                    <div className="form-section">
                        <h3>Основные данные</h3>
                        
                        <div className="form-row">
                            <label className="form-label required">
                                Дата отчета:
                                <input
                                    type="date"
                                    name="report_date"
                                    value={formData.report_date}
                                    onChange={handleInputChange}
                                    required
                                    className="form-input"
                                />
                            </label>
                            
                            <label className="form-label">
                                Валюта:
                                <select
                                    name="currency"
                                    value={formData.currency}
                                    onChange={handleInputChange}
                                    className="form-input"
                                >
                                    <option value="RUB">RUB</option>
                                    <option value="USD">USD</option>
                                </select>
                            </label>
                        </div>
                        
                        {formData.currency === 'USD' && (
                            <div className="form-row">
                                <label className="form-label required">
                                    Курс USD/RUB:
                                    <input
                                        type="number"
                                        name="exchange_rate"
                                        value={formData.exchange_rate || ''}
                                        onChange={handleInputChange}
                                        step="0.0001"
                                        placeholder="Например: 75.5"
                                        required
                                        className="form-input"
                                    />
                                </label>
                            </div>
                        )}
                    </div>
                    
                    {/* Рыночные данные */}
                    <div className="form-section">
                        <h3>Рыночные данные</h3>
                        
                        <div className="form-row">
                            <label className="form-label">
                                Цена акции:
                                <input
                                    type="number"
                                    name="price_per_share"
                                    value={formData.price_per_share || ''}
                                    onChange={handleInputChange}
                                    step="0.01"
                                    placeholder="0.00"
                                    className="form-input"
                                />
                            </label>
                            
                            <label className="form-label">
                                Количество акций:
                                <input
                                    type="number"
                                    name="shares_outstanding"
                                    value={formData.shares_outstanding || ''}
                                    onChange={handleInputChange}
                                    placeholder="0"
                                    className="form-input"
                                />
                            </label>
                        </div>
                    </div>
                    
                    {/* Отчет о прибылях и убытках */}
                    <div className="form-section">
                        <h3>Отчет о прибылях и убытках</h3>
                        
                        <div className="form-row">
                            <label className="form-label">
                                Выручка:
                                <input
                                    type="number"
                                    name="revenue"
                                    value={formData.revenue || ''}
                                    onChange={handleInputChange}
                                    step="0.01"
                                    placeholder="0.00"
                                    className="form-input"
                                />
                            </label>
                            
                            <label className="form-label">
                                Чистая прибыль:
                                <input
                                    type="number"
                                    name="net_income"
                                    value={formData.net_income || ''}
                                    onChange={handleInputChange}
                                    step="0.01"
                                    placeholder="0.00"
                                    className="form-input"
                                />
                            </label>
                        </div>
                    </div>
                    
                    {/* Балансовые показатели */}
                    <div className="form-section">
                        <h3>Балансовые показатели</h3>
                        
                        <div className="form-row">
                            <label className="form-label">
                                Всего активов:
                                <input
                                    type="number"
                                    name="total_assets"
                                    value={formData.total_assets || ''}
                                    onChange={handleInputChange}
                                    step="0.01"
                                    placeholder="0.00"
                                    className="form-input"
                                />
                            </label>
                            
                            <label className="form-label">
                                Текущие активы:
                                <input
                                    type="number"
                                    name="current_assets"
                                    value={formData.current_assets || ''}
                                    onChange={handleInputChange}
                                    step="0.01"
                                    placeholder="0.00"
                                    className="form-input"
                                />
                            </label>
                        </div>
                        
                        <div className="form-row">
                            <label className="form-label">
                                Всего обязательств:
                                <input
                                    type="number"
                                    name="total_liabilities"
                                    value={formData.total_liabilities || ''}
                                    onChange={handleInputChange}
                                    step="0.01"
                                    placeholder="0.00"
                                    className="form-input"
                                />
                            </label>
                            
                            <label className="form-label">
                                Текущие обязательства:
                                <input
                                    type="number"
                                    name="current_liabilities"
                                    value={formData.current_liabilities || ''}
                                    onChange={handleInputChange}
                                    step="0.01"
                                    placeholder="0.00"
                                    className="form-input"
                                />
                            </label>
                        </div>
                        
                        <div className="form-row">
                            <label className="form-label">
                                Собственный капитал:
                                <input
                                    type="number"
                                    name="equity"
                                    value={formData.equity || ''}
                                    onChange={handleInputChange}
                                    step="0.01"
                                    placeholder="0.00"
                                    className="form-input"
                                />
                            </label>
                        </div>
                    </div>
                    
                    {/* Дивиденды */}
                    <div className="form-section">
                        <h3>Дивиденды</h3>
                        
                        <div className="form-row">
                            <label className="form-label checkbox-label">
                                <input
                                    type="checkbox"
                                    name="dividends_paid"
                                    checked={formData.dividends_paid}
                                    onChange={handleInputChange}
                                    className="form-checkbox"
                                />
                                Дивиденды выплачивались в этом периоде
                            </label>
                        </div>
                        
                        {formData.dividends_paid && (
                            <div className="form-row">
                                <label className="form-label">
                                    Дивиденд на акцию:
                                    <input
                                        type="number"
                                        name="dividends_per_share"
                                        value={formData.dividends_per_share || ''}
                                        onChange={handleInputChange}
                                        step="0.0001"
                                        placeholder="0.0000"
                                        className="form-input"
                                    />
                                </label>
                            </div>
                        )}
                    </div>
                    
                    {/* Кнопки */}
                    <div className="form-actions">
                        <button
                            type="button"
                            onClick={onCancel}
                            className="btn btn-cancel"
                            disabled={isSubmitting}
                        >
                            Отмена
                        </button>
                        <button
                            type="submit"
                            className="btn btn-submit"
                            disabled={isSubmitting}
                        >
                            {isSubmitting ? 'Сохранение...' : 'Сохранить отчет'}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
};

export default ReportForm;
