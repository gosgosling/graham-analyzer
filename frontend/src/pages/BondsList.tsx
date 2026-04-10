import React, { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getBonds } from '../services';
import { Bond } from '../types';
import './BondsList.css';

// ── Утилиты ────────────────────────────────────────────────────────────────

function formatNominal(nominal: number | null, currency: string): string {
    if (nominal == null) return '—';
    return `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(nominal)} ${currency}`;
}

function maturityClass(date: string | null, perpetual: boolean): 'expired' | 'soon' | 'ok' | '' {
    if (perpetual || !date) return '';
    const days = (new Date(date).getTime() - Date.now()) / 86_400_000;
    if (days < 0)   return 'expired';
    if (days < 365) return 'soon';
    return 'ok';
}

function couponLabel(qty: number | null, floating: boolean): string {
    if (floating) return 'Плавающий';
    if (!qty) return '—';
    const map: Record<number, string> = { 1: '1×/год', 2: '2×/год', 4: '4×/год', 12: 'Ежемесячно' };
    return map[qty] ?? `${qty}×/год`;
}

type TypeFilter = 'all' | 'fixed' | 'floating' | 'amortization' | 'perpetual';

const TYPE_PILLS: { key: TypeFilter; label: string }[] = [
    { key: 'all',          label: 'Все' },
    { key: 'fixed',        label: 'Фиксированный' },
    { key: 'floating',     label: 'Флоатеры' },
    { key: 'amortization', label: 'С амортизацией' },
    { key: 'perpetual',    label: 'Бессрочные' },
];

// ── Скелетон ────────────────────────────────────────────────────────────────

const Skeleton: React.FC = () => (
    <div className="bl-skeleton-wrap">
        <div className="bl-skeleton-head" />
        {Array.from({ length: 10 }).map((_, i) => (
            <div key={i} className="bl-skeleton-row">
                <div className="bl-skeleton-cell" style={{ width: '28%' }} />
                <div className="bl-skeleton-cell" style={{ width: '14%' }} />
                <div className="bl-skeleton-cell" style={{ width: '12%' }} />
                <div className="bl-skeleton-cell" style={{ width: '10%' }} />
                <div className="bl-skeleton-cell" style={{ width: '10%' }} />
                <div className="bl-skeleton-cell" style={{ width: '16%' }} />
            </div>
        ))}
    </div>
);

// ── Строка таблицы ───────────────────────────────────────────────────────────

const BondRow: React.FC<{ bond: Bond; onClick: () => void }> = ({ bond, onClick }) => {
    const mClass = maturityClass(bond.maturity_date, bond.perpetual_flag);
    return (
        <tr onClick={onClick}>
            <td>
                <div className="bl-cell-name">
                    <span className="bl-bond-name">{bond.name}</span>
                    <span className="bl-bond-ticker">{bond.ticker}</span>
                </div>
            </td>
            <td><span className="bl-isin">{bond.isin}</span></td>
            <td>
                {bond.perpetual_flag
                    ? <span className="bl-perpetual-chip">Бессрочная</span>
                    : bond.maturity_date
                        ? <span className={`bl-maturity ${mClass}`}>
                            {new Date(bond.maturity_date).toLocaleDateString('ru-RU')}
                          </span>
                        : '—'
                }
            </td>
            <td><span className="bl-nominal">{formatNominal(bond.nominal, bond.currency)}</span></td>
            <td><span className="bl-coupon">{couponLabel(bond.coupon_quantity_per_year, bond.floating_coupon_flag)}</span></td>
            <td>
                <div className="bl-badges">
                    {bond.floating_coupon_flag  && <span className="bl-badge floating">Флоатер</span>}
                    {bond.amortization_flag     && <span className="bl-badge amortization">Амортиз.</span>}
                    {bond.perpetual_flag        && <span className="bl-badge perpetual">Бессрочная</span>}
                </div>
            </td>
        </tr>
    );
};

// ── Компонент ──────────────────────────────────────────────────────────────

const BondsList: React.FC = () => {
    const navigate = useNavigate();
    const [search, setSearch]       = useState('');
    const [typeFilter, setTypeFilter] = useState<TypeFilter>('all');

    const { data: bonds, isLoading, error } = useQuery<Bond[]>({
        queryKey: ['bonds'],
        queryFn:  getBonds,
        staleTime: 5 * 60_000,
    });

    const filtered = useMemo(() => {
        if (!bonds) return [];
        const q = search.trim().toLowerCase();
        return bonds.filter(b => {
            if (q && ![b.name, b.ticker, b.isin, b.sector].some(s => s?.toLowerCase().includes(q))) return false;
            if (typeFilter === 'floating'     && !b.floating_coupon_flag) return false;
            if (typeFilter === 'amortization' && !b.amortization_flag)    return false;
            if (typeFilter === 'perpetual'    && !b.perpetual_flag)        return false;
            if (typeFilter === 'fixed'        && (b.floating_coupon_flag || b.perpetual_flag)) return false;
            return true;
        });
    }, [bonds, search, typeFilter]);

    // Статистика
    const stats = useMemo(() => {
        if (!bonds) return null;
        return {
            total:   bonds.length,
            float:   bonds.filter(b => b.floating_coupon_flag).length,
            amort:   bonds.filter(b => b.amortization_flag).length,
            perp:    bonds.filter(b => b.perpetual_flag).length,
        };
    }, [bonds]);

    // ── Рендер ──

    return (
        <div className="bl-page">
            <div className="bl-inner">

                {/* Герой-шапка */}
                <div className="bl-hero">
                    <div className="bl-hero-body">
                        <div>
                            <h1 className="bl-title">Облигации</h1>
                            <p className="bl-subtitle">Российские облигации из T-Invest API</p>
                        </div>
                        {stats && (
                            <div className="bl-stats">
                                <div className="bl-stat">
                                    <span className="bl-stat-value">{stats.total.toLocaleString('ru-RU')}</span>
                                    <span className="bl-stat-label">Всего</span>
                                </div>
                                <div className="bl-stat">
                                    <span className="bl-stat-value">{stats.float}</span>
                                    <span className="bl-stat-label">Флоатеры</span>
                                </div>
                                <div className="bl-stat">
                                    <span className="bl-stat-value">{stats.amort}</span>
                                    <span className="bl-stat-label">Амортиз.</span>
                                </div>
                                <div className="bl-stat">
                                    <span className="bl-stat-value">{stats.perp}</span>
                                    <span className="bl-stat-label">Бессрочные</span>
                                </div>
                            </div>
                        )}
                    </div>
                </div>

                {/* Фильтры */}
                <div className="bl-filters">
                    <input
                        type="text"
                        className="bl-search"
                        placeholder="Поиск по названию, тикеру, ISIN или сектору…"
                        value={search}
                        onChange={e => setSearch(e.target.value)}
                    />
                    <div className="bl-type-pills">
                        {TYPE_PILLS.map(p => (
                            <button
                                key={p.key}
                                className={`bl-pill${typeFilter === p.key ? ' active' : ''}`}
                                onClick={() => setTypeFilter(p.key)}
                            >
                                {p.label}
                            </button>
                        ))}
                    </div>
                </div>

                {/* Основной контент */}
                {isLoading ? (
                    <Skeleton />
                ) : error ? (
                    <div className="bl-error">
                        Не удалось загрузить облигации. Проверьте TINKOFF_TOKEN на сервере.
                    </div>
                ) : !bonds || bonds.length === 0 ? (
                    <div className="bl-no-token">
                        <div className="bl-no-token-icon">🔑</div>
                        <h3>Облигации недоступны</h3>
                        <p>
                            Настройте <code>TINKOFF_TOKEN</code> в файле <code>.env</code> для загрузки данных из T-Invest API.
                        </p>
                    </div>
                ) : (
                    <>
                        <div className="bl-results-bar">
                            <span className="bl-results-count">
                                Показано <strong>{filtered.length}</strong> из {bonds.length} облигаций
                            </span>
                        </div>

                        {filtered.length === 0 ? (
                            <div className="bl-empty">
                                <div className="bl-empty-icon">🔍</div>
                                <div className="bl-empty-text">Ничего не найдено</div>
                                <div className="bl-empty-sub">Попробуйте изменить параметры поиска или фильтра</div>
                            </div>
                        ) : (
                            <div className="bl-table-wrap">
                                <table className="bl-table">
                                    <thead>
                                        <tr>
                                            <th>Название / Тикер</th>
                                            <th>ISIN</th>
                                            <th>Дата погашения</th>
                                            <th>Номинал</th>
                                            <th>Купон</th>
                                            <th>Тип</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {filtered.map(bond => (
                                            <BondRow
                                                key={bond.figi}
                                                bond={bond}
                                                onClick={() => navigate(`/bond/${bond.figi}`)}
                                            />
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </>
                )}

            </div>
        </div>
    );
};

export default BondsList;
