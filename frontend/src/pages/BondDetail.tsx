import React from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getBondByFigi } from '../services';
import { Bond } from '../types';
import './BondDetail.css';

// ── Утилиты ────────────────────────────────────────────────────────────────

function fmtDate(d: string | null): string {
    if (!d) return '—';
    return new Date(d).toLocaleDateString('ru-RU', { day: '2-digit', month: 'long', year: 'numeric' });
}

function fmtMoney(v: number | null, currency: string): string {
    if (v == null) return '—';
    return `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(v)} ${currency}`;
}

function fmtInt(v: number | null): string {
    if (v == null) return '—';
    return new Intl.NumberFormat('ru-RU').format(v);
}

function couponLabel(qty: number | null, floating: boolean): string {
    if (floating) return 'Плавающий';
    if (!qty) return '—';
    const map: Record<number, string> = { 1: '1 раз в год', 2: '2 раза в год', 4: '4 раза в год', 12: 'Ежемесячно' };
    return map[qty] ?? `${qty} раз в год`;
}

function maturityClass(date: string | null, perpetual: boolean): string {
    if (perpetual || !date) return '';
    const days = (new Date(date).getTime() - Date.now()) / 86_400_000;
    if (days < 0)   return 'expired';
    if (days < 365) return 'soon';
    return '';
}

// ── Строка внутри карточки ──────────────────────────────────────────────────

const Row: React.FC<{ label: string; value: React.ReactNode; valueClass?: string }> = ({
    label, value, valueClass = '',
}) => (
    <div className="bd-row">
        <span className="bd-label">{label}</span>
        <span className={`bd-value ${valueClass}`}>{value}</span>
    </div>
);

// ── Компонент ──────────────────────────────────────────────────────────────

const BondDetail: React.FC = () => {
    const { figi } = useParams<{ figi: string }>();
    const navigate = useNavigate();

    const { data: bond, isLoading, error } = useQuery<Bond>({
        queryKey: ['bond', figi],
        queryFn:  () => getBondByFigi(figi!),
        enabled:  !!figi,
    });

    const mClass = bond ? maturityClass(bond.maturity_date, bond.perpetual_flag) : '';

    return (
        <div className="bd-page">
            <div className="bd-inner">

                <button className="bd-back" onClick={() => navigate('/bonds')}>
                    ← Назад к списку
                </button>

                {isLoading ? (
                    <div className="bd-loading">
                        <div className="bd-spinner" />
                        <span>Загружаем данные облигации…</span>
                    </div>
                ) : error || !bond ? (
                    <div className="bd-error">
                        Облигация не найдена или произошла ошибка при загрузке.
                    </div>
                ) : (
                    <>
                        {/* ── Герой ── */}
                        <div className="bd-hero">
                            <div className="bd-hero-content">
                                <h1 className="bd-name">{bond.name}</h1>
                                <div className="bd-meta">
                                    <span className="bd-ticker">{bond.ticker}</span>
                                    <span className="bd-isin">ISIN: {bond.isin}</span>
                                </div>
                                <div className="bd-badges">
                                    {bond.floating_coupon_flag && (
                                        <span className="bd-badge floating">Плавающий купон</span>
                                    )}
                                    {bond.amortization_flag && (
                                        <span className="bd-badge amortization">С амортизацией</span>
                                    )}
                                    {bond.perpetual_flag && (
                                        <span className="bd-badge perpetual">Бессрочная</span>
                                    )}
                                </div>
                            </div>
                        </div>

                        {/* ── Карточки ── */}
                        <div className="bd-cards">

                            {/* Основные параметры */}
                            <div className="bd-card">
                                <div className="bd-card-title">Основные параметры</div>
                                <div className="bd-rows">
                                    <Row label="Номинал"
                                        value={fmtMoney(bond.nominal, bond.currency)} />
                                    <Row label="Дата погашения"
                                        valueClass={bond.perpetual_flag ? 'perpetual' : mClass}
                                        value={bond.perpetual_flag ? 'Бессрочная' : fmtDate(bond.maturity_date)} />
                                    <Row label="Дата размещения"
                                        value={fmtDate(bond.placement_date)} />
                                    <Row label="Купонных выплат"
                                        value={couponLabel(bond.coupon_quantity_per_year, bond.floating_coupon_flag)} />
                                    <Row label="Лот"
                                        value={`${bond.lot} шт.`} />
                                    <Row label="Валюта"
                                        value={bond.currency} />
                                </div>
                            </div>

                            {/* Эмитент */}
                            <div className="bd-card">
                                <div className="bd-card-title">Эмитент</div>
                                <div className="bd-rows">
                                    <Row label="Сектор"
                                        value={bond.sector || '—'} />
                                    <Row label="Страна риска"
                                        value={bond.country_of_risk_name || bond.country_of_risk || '—'} />
                                    <Row label="Биржа"
                                        value={bond.exchange || '—'} />
                                    <Row label="Объём выпуска"
                                        value={fmtInt(bond.issue_size)} />
                                </div>
                            </div>

                            {/* Идентификаторы */}
                            <div className="bd-card">
                                <div className="bd-card-title">Идентификаторы</div>
                                <div className="bd-rows">
                                    <Row label="FIGI"  value={bond.figi}  valueClass="mono" />
                                    <Row label="ISIN"  value={bond.isin}  valueClass="mono" />
                                    <Row label="Тикер" value={bond.ticker} valueClass="mono" />
                                </div>
                            </div>

                        </div>
                    </>
                )}

            </div>
        </div>
    );
};

export default BondDetail;
