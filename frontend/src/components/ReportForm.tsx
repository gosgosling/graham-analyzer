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
        // Атрибуты отчёта
        period_type: 'quarterly',
        fiscal_year: new Date().getFullYear(),
        fiscal_quarter: 4,
        accounting_standard: 'IFRS',
        consolidated: true,
        source: 'manual',
        // Даты
        report_date: '',
        filing_date: null,
        // Рыночные данные
        price_per_share: null,  // Цена на конец периода
        price_at_filing: null,  // Цена на дату публикации
        shares_outstanding: null,
        // Финансовые данные
        revenue: null,
        net_income: null,
        total_assets: null,
        current_assets: null,
        total_liabilities: null,
        current_liabilities: null,
        equity: null,
        dividends_per_share: null,
        dividends_paid: false,
        // Валюта
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
        
        if (formData.period_type === 'quarterly' && !formData.fiscal_quarter) {
            setError('Для квартальных отчётов необходимо указать квартал (1-4)');
            return;
        }
        
        if (formData.period_type === 'annual' && formData.fiscal_quarter) {
            // Для годовых отчётов убираем квартал
            setFormData(prev => ({ ...prev, fiscal_quarter: null }));
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
                    {/* Атрибуты отчёта */}
                    <div className="form-section">
                        <h3>Атрибуты отчёта</h3>
                        
                        <div className="form-row">
                            <label className="form-label required">
                                Тип периода:
                                <select
                                    name="period_type"
                                    value={formData.period_type}
                                    onChange={handleInputChange}
                                    className="form-input"
                                    required
                                >
                                    <option value="quarterly">Квартальный</option>
                                    <option value="annual">Годовой</option>
                                    <option value="semi_annual">Полугодовой</option>
                                </select>
                            </label>
                            
                            <label className="form-label required">
                                Финансовый год:
                                <input
                                    type="number"
                                    name="fiscal_year"
                                    value={formData.fiscal_year}
                                    onChange={handleInputChange}
                                    min="1900"
                                    max="2100"
                                    required
                                    className="form-input"
                                />
                            </label>
                        </div>
                        
                        {formData.period_type === 'quarterly' && (
                            <div className="form-row">
                                <label className="form-label required">
                                    Квартал:
                                    <select
                                        name="fiscal_quarter"
                                        value={formData.fiscal_quarter || ''}
                                        onChange={handleInputChange}
                                        className="form-input"
                                        required
                                    >
                                        <option value="">Выберите квартал</option>
                                        <option value="1">Q1 (Январь-Март)</option>
                                        <option value="2">Q2 (Апрель-Июнь)</option>
                                        <option value="3">Q3 (Июль-Сентябрь)</option>
                                        <option value="4">Q4 (Октябрь-Декабрь)</option>
                                    </select>
                                </label>
                            </div>
                        )}
                        
                        <div className="form-row">
                            <label className="form-label">
                                Стандарт отчётности:
                                <select
                                    name="accounting_standard"
                                    value={formData.accounting_standard}
                                    onChange={handleInputChange}
                                    className="form-input"
                                >
                                    <option value="IFRS">МСФО (IFRS)</option>
                                    <option value="RAS">РСБУ (RAS)</option>
                                    <option value="US_GAAP">US GAAP</option>
                                    <option value="UK_GAAP">UK GAAP</option>
                                    <option value="OTHER">Другой</option>
                                </select>
                            </label>
                            
                            <label className="form-label checkbox-label">
                                <input
                                    type="checkbox"
                                    name="consolidated"
                                    checked={formData.consolidated}
                                    onChange={handleInputChange}
                                    className="form-checkbox"
                                />
                                Консолидированная отчётность
                            </label>
                        </div>
                    </div>
                    
                    {/* Основные данные */}
                    <div className="form-section">
                        <h3>Даты и валюта</h3>
                        
                        <div className="form-row">
                            <label className="form-label required">
                                Дата окончания периода:
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
                                Дата публикации:
                                <input
                                    type="date"
                                    name="filing_date"
                                    value={formData.filing_date || ''}
                                    onChange={handleInputChange}
                                    className="form-input"
                                />
                            </label>
                        </div>
                        
                        <div className="form-row">
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
                        
                            {formData.currency === 'USD' && (
                                <label className="form-label required">
                                    Курс USD/RUB:
                                    <input
                                        type="number"
                                        name="exchange_rate"
                                        value={formData.exchange_rate || ''}
                                        onChange={handleInputChange}
                                        step="0.0001"
                                        placeholder="Например: 95.50"
                                        required
                                        className="form-input"
                                    />
                                </label>
                            )}
                        </div>
                    </div>
                    
                    {/* Рыночные данные */}
                    <div className="form-section">
                        <h3>Рыночные данные</h3>
                        
                        <div className="form-row">
                            <label className="form-label">
                                Цена акции на дату окончания периода:
                                <input
                                    type="number"
                                    name="price_per_share"
                                    value={formData.price_per_share || ''}
                                    onChange={handleInputChange}
                                    step="0.01"
                                    placeholder={`Цена на ${formData.report_date || 'конец периода'} (${formData.currency})`}
                                    className="form-input"
                                />
                                <small className="field-hint">Основная цена для расчёта мультипликаторов</small>
                            </label>
                            
                            <label className="form-label">
                                Цена акции на дату публикации:
                                <input
                                    type="number"
                                    name="price_at_filing"
                                    value={formData.price_at_filing || ''}
                                    onChange={handleInputChange}
                                    step="0.01"
                                    placeholder={`Цена на ${formData.filing_date || 'дату публикации'} (${formData.currency})`}
                                    className="form-input"
                                />
                                <small className="field-hint">Опционально, для анализа реакции рынка</small>
                            </label>
                        </div>
                        
                        <div className="form-row">
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
