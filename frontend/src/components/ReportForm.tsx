import React, { useState, useCallback, useEffect } from 'react';
import { ConfigProvider, DatePicker } from 'antd';
import ruRU from 'antd/locale/ru_RU';
import dayjs, { Dayjs } from 'dayjs';
import 'dayjs/locale/ru';
import { FinancialReportCreate } from '../types';
import {
    getMoexPrice,
    getMoexShares,
    getMoexDividends,
    MoexPriceResult,
    MoexSharesResult,
    MoexDividendsResult,
} from '../services/api';
import './ReportForm.css';

dayjs.locale('ru');

/**
 * Преобразует ответ FastAPI/Pydantic об ошибке в строку (для alert / UI / setState).
 * 422: detail — строка, массив {type, loc, msg, ...} или один такой объект.
 */
function formatApiErrorMessage(err: any, fallback: string): string {
    const detail = err?.response?.data?.detail;
    if (detail === undefined || detail === null || detail === '') {
        return typeof err?.message === 'string' && err.message ? err.message : fallback;
    }
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
        const s = detail
            .map((e: any) => {
                if (e && typeof e === 'object') {
                    const field = Array.isArray(e.loc) ? e.loc.slice(1).join(' → ') : '';
                    const msg = e.msg ?? 'неверное значение';
                    return field ? `${field}: ${msg}` : msg;
                }
                return String(e);
            })
            .join('\n');
        return s || fallback;
    }
    if (typeof detail === 'object' && detail !== null && 'msg' in detail) {
        const e = detail as { loc?: unknown[]; msg?: string };
        const field = Array.isArray(e.loc) ? e.loc.slice(1).join(' → ') : '';
        const msg = e.msg ?? 'неверное значение';
        return field ? `${field}: ${msg}` : msg;
    }
    return fallback;
}

function extractErrorMessage(err: any): string {
    return formatApiErrorMessage(err, 'Ошибка при сохранении отчёта');
}

function isPlausibleFiscalYear(y: number | null | undefined): boolean {
    if (y == null || Number.isNaN(Number(y))) return false;
    return y >= 1900 && y <= 2100;
}

interface ReportFormProps {
    companyId: number;
    companyName: string;
    /** Тикер (SECID) на Мосбирже для автоматической загрузки цены и акций */
    ticker?: string;
    /** Если передан — форма работает в режиме редактирования, поля предзаполняются */
    initialValues?: Partial<FinancialReportCreate>;
    /** ID редактируемого отчёта (для заголовка и метаданных) */
    reportId?: number;
    onSubmit: (reportData: FinancialReportCreate) => Promise<void>;
    onCancel: () => void;
}

interface PriceFetchState {
    loading: boolean;
    result: MoexPriceResult | null;
    error: string | null;
}

interface SharesFetchState {
    loading: boolean;
    result: MoexSharesResult | null;
    error: string | null;
    /** true — поле уже было заполнено вручную, авто-значение применено как подсказка */
    applied: boolean;
}

interface DividendsFetchState {
    loading: boolean;
    result: MoexDividendsResult | null;
    error: string | null;
}

/** Показывает статус загрузки количества акций */
const SharesFetchBadge: React.FC<{ state: SharesFetchState }> = ({ state }) => {
    if (state.loading) {
        return <span className="price-badge loading">⟳ Загрузка из реестра Мосбиржи...</span>;
    }
    if (state.error) {
        return (
            <span className="price-badge error">
                ✗ {state.error} — введите вручную
            </span>
        );
    }
    if (state.result && state.applied) {
        return (
            <span className="price-badge ok">
                ✓ {state.result.secname} · {state.result.issuesize.toLocaleString('ru-RU')} акций
                <span className="badge-note"> · актуальное значение из реестра MOEX, уточните по отчёту</span>
            </span>
        );
    }
    return null;
};

/**
 * Панель дивидендов с Мосбиржи:
 * - показывает каждую найденную выплату отдельной строкой
 * - чётко предупреждает что данные могут быть неполными
 * - поле для ввода итогового значения остаётся всегда редактируемым
 */
const DividendsInfoPanel: React.FC<{
    state: DividendsFetchState;
    onApply: (total: number) => void;
}> = ({ state, onApply }) => {
    if (state.loading) {
        return (
            <div className="dividends-info-panel loading">
                <span>⟳ Загружаю данные о дивидендах с Мосбиржи...</span>
            </div>
        );
    }
    if (state.error) {
        return (
            <div className="dividends-info-panel warning">
                <span>✗ {state.error}</span>
                <span className="div-panel-hint">Введите сумму дивиденда на акцию вручную ниже.</span>
            </div>
        );
    }
    if (!state.result) return null;

    const { total, payments_count, period_from, period_till, currency, payments } = state.result;

    return (
        <div className={`dividends-info-panel ${payments_count > 0 ? 'found' : 'not-found'}`}>
            <div className="div-panel-header">
                <strong>Данные Мосбиржи</strong>
                <span className="div-panel-period">{period_from} — {period_till}</span>
            </div>

            {payments_count === 0 ? (
                <div className="div-panel-empty">
                    ⚠ Выплат с датой закрытия реестра в этом периоде не найдено.
                    <span className="div-panel-hint">
                        Это нормально для квартальных отчётов. Если дивиденды всё же выплачивались —
                        введите значение вручную в поле ниже.
                    </span>
                </div>
            ) : (
                <>
                    <table className="div-panel-table">
                        <thead>
                            <tr>
                                <th>Дата закрытия реестра</th>
                                <th>Выплата, {currency}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {payments.map(p => (
                                <tr key={p.registryclosedate}>
                                    <td>{p.registryclosedate}</td>
                                    <td>{p.value}</td>
                                </tr>
                            ))}
                            {payments_count > 1 && (
                                <tr className="div-panel-total-row">
                                    <td><strong>Итого</strong></td>
                                    <td><strong>{total}</strong></td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                    <div className="div-panel-actions">
                        <button
                            type="button"
                            className="btn-apply-dividends"
                            onClick={() => onApply(total)}
                        >
                            Применить сумму {total} {currency}
                        </button>
                        <span className="div-panel-hint">
                            Не видите какую-то выплату? Данные Мосбиржи могут запаздывать —
                            исправьте итоговое значение вручную в поле ниже.
                        </span>
                    </div>
                </>
            )}
        </div>
    );
};

/** Показывает статус загрузки цены и индикатор корректировки даты */
const PriceFetchBadge: React.FC<{ state: PriceFetchState; requestedDate: string }> = ({ state, requestedDate }) => {
    if (state.loading) {
        return <span className="price-badge loading">⟳ Загрузка цены с Мосбиржи...</span>;
    }
    if (state.error) {
        return <span className="price-badge error">✗ {state.error}</span>;
    }
    if (state.result) {
        const adjusted = state.result.is_adjusted;
        return (
            <span className={`price-badge ${adjusted ? 'adjusted' : 'ok'}`}>
                {adjusted
                    ? `⚠ Биржа закрыта ${requestedDate} → цена за ${state.result.actual_date}`
                    : `✓ Цена за ${state.result.actual_date} (${state.result.board})`
                }
            </span>
        );
    }
    return null;
};

const ReportForm: React.FC<ReportFormProps> = ({ companyId, companyName, ticker, initialValues, reportId, onSubmit, onCancel }) => {
    const isEditMode = !!reportId;
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);

    // Состояния загрузки цен
    const [priceReportState, setPriceReportState] = useState<PriceFetchState>({ loading: false, result: null, error: null });
    const [priceFilingState, setPriceFilingState] = useState<PriceFetchState>({ loading: false, result: null, error: null });

    // Состояние загрузки количества акций
    const [sharesState, setSharesState] = useState<SharesFetchState>({
        loading: false, result: null, error: null, applied: false,
    });

    // Состояние загрузки дивидендов
    const [dividendsState, setDividendsState] = useState<DividendsFetchState>({
        loading: false, result: null, error: null,
    });

    const defaultValues: FinancialReportCreate = {
        company_id: companyId,
        period_type: 'quarterly',
        fiscal_year: new Date().getFullYear(),
        fiscal_quarter: 4,
        accounting_standard: 'IFRS',
        consolidated: true,
        source: 'manual',
        report_date: '',
        filing_date: null,
        price_per_share: null,
        price_at_filing: null,
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
    };
    // В режиме редактирования накладываем initialValues поверх дефолтов
    const [formData, setFormData] = useState<FinancialReportCreate>(
        initialValues ? { ...defaultValues, ...initialValues, company_id: companyId } : defaultValues,
    );

    /** Загружает количество акций с Мосбиржи */
    const fetchShares = useCallback(async () => {
        if (!ticker) return;
        setSharesState({ loading: true, result: null, error: null, applied: false });
        try {
            const result = await getMoexShares(ticker);
            setSharesState({ loading: false, result, error: null, applied: true });
            // Подставляем только если поле пустое
            setFormData(prev => ({
                ...prev,
                shares_outstanding: prev.shares_outstanding ?? result.issuesize,
            }));
        } catch (err: any) {
            const msg = formatApiErrorMessage(err, 'Не удалось получить данные из Мосбиржи');
            setSharesState({ loading: false, result: null, error: msg, applied: false });
        }
    }, [ticker]);

    // Авто-загрузка акций при открытии формы
    useEffect(() => {
        if (ticker) {
            fetchShares();
        }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [ticker]);

    /** Загружает дивиденды с Мосбиржи за указанный период и подставляет в поля */
    const fetchDividends = useCallback(async (
        year: number,
        pType: string,
        quarter: number | null,
    ) => {
        if (!ticker) return;
        setDividendsState({ loading: true, result: null, error: null });
        try {
            const result = await getMoexDividends(
                ticker,
                year,
                pType,
                quarter ?? undefined,
            );
            setDividendsState({ loading: false, result, error: null });
            // Не перезаписываем поле автоматически — пользователь применяет сумму сам
            // через кнопку "Применить" или вводит вручную.
            // Только если поле ещё пустое и MOEX нашёл данные — предзаполняем как стартовое значение.
            if (result.total > 0) {
                setFormData(prev => ({
                    ...prev,
                    dividends_paid: true,
                    // Предзаполняем ТОЛЬКО если поле пустое
                    dividends_per_share: prev.dividends_per_share ?? result.total,
                }));
            }
        } catch (err: any) {
            const msg = formatApiErrorMessage(err, 'Не удалось получить данные с Мосбиржи');
            setDividendsState({ loading: false, result: null, error: msg });
        }
    }, [ticker]);

    // Авто-загрузка дивидендов при смене года или типа/квартала периода
    useEffect(() => {
        if (!ticker) return;
        if (!isPlausibleFiscalYear(formData.fiscal_year)) {
            setDividendsState({ loading: false, result: null, error: null });
            return;
        }
        // Для quarterly ждём пока выбран квартал
        if (formData.period_type === 'quarterly' && !formData.fiscal_quarter) return;
        fetchDividends(
            formData.fiscal_year,
            formData.period_type,
            formData.fiscal_quarter ?? null,
        );
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [ticker, formData.fiscal_year, formData.period_type, formData.fiscal_quarter]);

    /** Загружает цену с Мосбиржи и подставляет в поле */
    const fetchPrice = useCallback(async (
        dateValue: string,
        field: 'price_per_share' | 'price_at_filing',
        setState: React.Dispatch<React.SetStateAction<PriceFetchState>>,
    ) => {
        if (!ticker || !dateValue) return;

        setState({ loading: true, result: null, error: null });
        try {
            const result = await getMoexPrice(ticker, dateValue);
            setState({ loading: false, result, error: null });
            setFormData(prev => ({ ...prev, [field]: result.price }));
        } catch (err: any) {
            const msg = formatApiErrorMessage(err, 'Не удалось получить цену');
            setState({ loading: false, result: null, error: msg });
        }
    }, [ticker]);

    const parseReportDate = (d: Dayjs | null): string =>
        d && d.isValid() ? d.format('YYYY-MM-DD') : '';

    const onReportDateChange = useCallback(
        (d: Dayjs | null) => {
            const value = parseReportDate(d);
            setFormData(prev => ({ ...prev, report_date: value }));
            if (value && ticker) {
                fetchPrice(value, 'price_per_share', setPriceReportState);
            }
        },
        [ticker, fetchPrice],
    );

    const onFilingDateChange = useCallback(
        (d: Dayjs | null) => {
            const value = parseReportDate(d);
            setFormData(prev => ({ ...prev, filing_date: value || null }));
            if (value && ticker) {
                fetchPrice(value, 'price_at_filing', setPriceFilingState);
            }
        },
        [ticker, fetchPrice],
    );
    
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
        
        // Очищаем fiscal_quarter для не-квартальных отчётов синхронно,
        // не через setFormData (который асинхронен), а в локальной копии данных
        const submitData: FinancialReportCreate = {
            ...formData,
            fiscal_quarter: formData.period_type === 'quarterly' ? formData.fiscal_quarter : null,
        };

        setIsSubmitting(true);
        
        try {
            await onSubmit(submitData);
        } catch (err: any) {
            setError(extractErrorMessage(err));
        } finally {
            setIsSubmitting(false);
        }
    };

    return (
        <ConfigProvider locale={ruRU}>
        <div className="report-form-overlay">
            <div className="report-form-container">
                <div className="report-form-header">
                    <h2>{isEditMode ? 'Редактировать финансовый отчёт' : 'Добавить финансовый отчёт'}</h2>
                    <p className="company-name">Компания: {companyName}</p>
                    {isEditMode && <p className="report-edit-hint">ID отчёта: {reportId}</p>}
                </div>
                
                {error && (
                    <div className="error-message" style={{ whiteSpace: 'pre-line' }}>
                        {error}
                    </div>
                )}
                
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
                                <DatePicker
                                    className="report-form-date-picker"
                                    value={formData.report_date ? dayjs(formData.report_date) : null}
                                    onChange={onReportDateChange}
                                    format="DD.MM.YYYY"
                                    placeholder="Выберите дату"
                                    allowClear={false}
                                    style={{ width: '100%' }}
                                    popupStyle={{ zIndex: 1100 }}
                                    getPopupContainer={() => document.body}
                                />
                            </label>
                            
                            <label className="form-label">
                                Дата публикации:
                                <DatePicker
                                    className="report-form-date-picker"
                                    value={formData.filing_date ? dayjs(formData.filing_date) : null}
                                    onChange={onFilingDateChange}
                                    format="DD.MM.YYYY"
                                    placeholder="Необязательно"
                                    allowClear
                                    style={{ width: '100%' }}
                                    popupStyle={{ zIndex: 1100 }}
                                    getPopupContainer={() => document.body}
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

                        {!ticker && (
                            <div className="price-fetch-notice">
                                ℹ️ Тикер не определён — цены нужно ввести вручную
                            </div>
                        )}

                        <div className="form-row">
                            {/* Цена на дату окончания периода */}
                            <div className="form-label">
                                <div className="price-label-row">
                                    <span>Цена акции на конец периода, {formData.currency}:</span>
                                    {ticker && formData.report_date && (
                                        <button
                                            type="button"
                                            className="btn-fetch-price"
                                            disabled={priceReportState.loading}
                                            onClick={() => fetchPrice(formData.report_date, 'price_per_share', setPriceReportState)}
                                        >
                                            {priceReportState.loading ? '⟳' : '↺ MOEX'}
                                        </button>
                                    )}
                                </div>
                                <input
                                    type="number"
                                    name="price_per_share"
                                    value={formData.price_per_share || ''}
                                    onChange={handleInputChange}
                                    step="0.01"
                                    placeholder="Загружается автоматически..."
                                    className={`form-input ${priceReportState.loading ? 'input-loading' : ''}`}
                                />
                                <PriceFetchBadge state={priceReportState} requestedDate={formData.report_date} />
                                <small className="field-hint">Основная цена для расчёта мультипликаторов</small>
                            </div>

                            {/* Цена на дату публикации */}
                            <div className="form-label">
                                <div className="price-label-row">
                                    <span>Цена акции на дату публикации, {formData.currency}:</span>
                                    {ticker && formData.filing_date && (
                                        <button
                                            type="button"
                                            className="btn-fetch-price"
                                            disabled={priceFilingState.loading}
                                            onClick={() => fetchPrice(formData.filing_date!, 'price_at_filing', setPriceFilingState)}
                                        >
                                            {priceFilingState.loading ? '⟳' : '↺ MOEX'}
                                        </button>
                                    )}
                                </div>
                                <input
                                    type="number"
                                    name="price_at_filing"
                                    value={formData.price_at_filing || ''}
                                    onChange={handleInputChange}
                                    step="0.01"
                                    placeholder="Загружается автоматически..."
                                    className={`form-input ${priceFilingState.loading ? 'input-loading' : ''}`}
                                />
                                <PriceFetchBadge state={priceFilingState} requestedDate={formData.filing_date ?? ''} />
                                <small className="field-hint">Опционально, для анализа реакции рынка</small>
                            </div>
                        </div>
                        
                        <div className="form-row">
                            <div className="form-label">
                                <div className="price-label-row">
                                    <span>Количество акций в обращении, шт.:</span>
                                    {ticker && (
                                        <button
                                            type="button"
                                            className="btn-fetch-price"
                                            disabled={sharesState.loading}
                                            onClick={fetchShares}
                                        >
                                            {sharesState.loading ? '⟳' : '↺ MOEX'}
                                        </button>
                                    )}
                                </div>
                                <input
                                    type="number"
                                    name="shares_outstanding"
                                    value={formData.shares_outstanding || ''}
                                    onChange={handleInputChange}
                                    placeholder={sharesState.loading ? 'Загрузка...' : '0'}
                                    className={`form-input ${sharesState.loading ? 'input-loading' : ''}`}
                                />
                                <SharesFetchBadge state={sharesState} />
                            </div>
                        </div>
                    </div>
                    
                    {/* Отчет о прибылях и убытках */}
                    <div className="form-section">
                        <h3>
                            Отчёт о прибылях и убытках
                            <span className="section-units-hint">млн {formData.currency}</span>
                        </h3>
                        
                        <div className="form-row">
                            <label className="form-label">
                                Выручка, млн {formData.currency}:
                                <input
                                    type="number"
                                    name="revenue"
                                    value={formData.revenue || ''}
                                    onChange={handleInputChange}
                                    step="1"
                                    placeholder="например: 1459000"
                                    className="form-input"
                                />
                                <small className="field-hint">Введите сумму в миллионах</small>
                            </label>
                            
                            <label className="form-label">
                                Чистая прибыль, млн {formData.currency}:
                                <input
                                    type="number"
                                    name="net_income"
                                    value={formData.net_income || ''}
                                    onChange={handleInputChange}
                                    step="1"
                                    placeholder="например: 50000"
                                    className="form-input"
                                />
                                <small className="field-hint">Введите сумму в миллионах</small>
                            </label>
                        </div>
                    </div>
                    
                    {/* Балансовые показатели */}
                    <div className="form-section">
                        <h3>
                            Балансовые показатели
                            <span className="section-units-hint">млн {formData.currency}</span>
                        </h3>
                        
                        <div className="form-row">
                            <label className="form-label">
                                Всего активов, млн {formData.currency}:
                                <input
                                    type="number"
                                    name="total_assets"
                                    value={formData.total_assets || ''}
                                    onChange={handleInputChange}
                                    step="1"
                                    placeholder="например: 500000"
                                    className="form-input"
                                />
                            </label>
                            
                            <label className="form-label">
                                Оборотные активы, млн {formData.currency}:
                                <input
                                    type="number"
                                    name="current_assets"
                                    value={formData.current_assets || ''}
                                    onChange={handleInputChange}
                                    step="1"
                                    placeholder="например: 200000"
                                    className="form-input"
                                />
                            </label>
                        </div>
                        
                        <div className="form-row">
                            <label className="form-label">
                                Всего обязательств, млн {formData.currency}:
                                <input
                                    type="number"
                                    name="total_liabilities"
                                    value={formData.total_liabilities || ''}
                                    onChange={handleInputChange}
                                    step="1"
                                    placeholder="например: 250000"
                                    className="form-input"
                                />
                            </label>
                            
                            <label className="form-label">
                                Краткосрочные обязательства, млн {formData.currency}:
                                <input
                                    type="number"
                                    name="current_liabilities"
                                    value={formData.current_liabilities || ''}
                                    onChange={handleInputChange}
                                    step="1"
                                    placeholder="например: 80000"
                                    className="form-input"
                                />
                            </label>
                        </div>
                        
                        <div className="form-row">
                            <label className="form-label">
                                Собственный капитал, млн {formData.currency}:
                                <input
                                    type="number"
                                    name="equity"
                                    value={formData.equity || ''}
                                    onChange={handleInputChange}
                                    step="1"
                                    placeholder="например: 250000"
                                    className="form-input"
                                />
                            </label>
                        </div>
                    </div>
                    
                    {/* Дивиденды */}
                    <div className="form-section">
                        <h3>Дивиденды</h3>

                        {/* Информационная панель с данными Мосбиржи */}
                        {ticker && (
                            <div className="dividends-fetch-row">
                                <DividendsInfoPanel
                                    state={dividendsState}
                                    onApply={(total) => setFormData(prev => ({
                                        ...prev,
                                        dividends_paid: true,
                                        dividends_per_share: total,
                                    }))}
                                />
                                <button
                                    type="button"
                                    className="btn-fetch-price"
                                    disabled={dividendsState.loading || (formData.period_type === 'quarterly' && !formData.fiscal_quarter)}
                                    onClick={() => fetchDividends(
                                        formData.fiscal_year,
                                        formData.period_type,
                                        formData.fiscal_quarter ?? null,
                                    )}
                                    title="Обновить данные с Мосбиржи"
                                >
                                    {dividendsState.loading ? '⟳' : '↺ MOEX'}
                                </button>
                            </div>
                        )}

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
                                <div className="form-label">
                                    <div className="price-label-row">
                                        <span>Итого дивиденд на акцию, {formData.currency}:</span>
                                    </div>
                                    <input
                                        type="number"
                                        name="dividends_per_share"
                                        value={formData.dividends_per_share || ''}
                                        onChange={handleInputChange}
                                        step="0.0001"
                                        placeholder="0.0000"
                                        className="form-input"
                                    />
                                    <small className="field-hint">
                                        Суммарный дивиденд на акцию за весь период. Если Мосбиржа
                                        показала не все выплаты — введите полную сумму вручную.
                                    </small>
                                </div>
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
                            {isSubmitting
                                ? 'Сохранение...'
                                : isEditMode
                                ? 'Обновить отчёт'
                                : 'Сохранить отчёт'}
                        </button>
                    </div>
                </form>
            </div>
        </div>
        </ConfigProvider>
    );
};

export default ReportForm;
