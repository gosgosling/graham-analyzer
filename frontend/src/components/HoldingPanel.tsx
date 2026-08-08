import React, { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import type { Company, FinancialReport, HoldingNav, StakeValuation } from '../types';
import {
  addHoldingStake,
  deleteHoldingStake,
  getCompanies,
  getHoldingNav,
  setCorporateDebt,
  type HoldingStakeInput,
} from '../services';
import { formatMln } from '../utils/format';
import './HoldingPanel.css';

/**
 * Оценка холдинга по NAV.
 *
 * У холдинга нет своих операций: выручка и прибыль в его отчётности —
 * результаты дочек, консолидированные целиком, хотя акционеру принадлежат
 * доли. Поэтому P/E и P/B здесь показывают чужой бизнес, а стоимость
 * складывается иначе: сумма долей минус долг корпоративного центра.
 *
 * Публичные доли считаются по карточкам дочек, которые уже есть в базе —
 * цена и количество акций берутся оттуда же, откуда для всех остальных
 * мультипликаторов. Непубличные активы оцениваются вручную.
 */

const EMPTY_FORM: HoldingStakeInput = {
  name: '',
  share_pct: 0,
  subsidiary_company_id: null,
  manual_valuation: null,
  valuation_note: null,
};

function fmtPct(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  return `${value.toLocaleString('ru-RU', { maximumFractionDigits: 1 })}%`;
}

const HoldingPanel: React.FC<{ company: Company; reports?: FinancialReport[] }> = ({
  company,
  reports,
}) => {
  const companyId = company.id!;
  const queryClient = useQueryClient();
  const [form, setForm] = useState<HoldingStakeInput>(EMPTY_FORM);
  const [debtInput, setDebtInput] = useState<string>('');
  const [showForm, setShowForm] = useState(false);

  const { data: nav, isLoading } = useQuery({
    queryKey: ['holding-nav', companyId],
    queryFn: () => getHoldingNav(companyId),
    enabled: Number.isFinite(companyId) && companyId > 0,
  });

  const { data: companies } = useQuery({
    queryKey: ['companies'],
    queryFn: () => getCompanies(),
    enabled: showForm,
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['holding-nav', companyId] });

  const addMutation = useMutation({
    mutationFn: (payload: HoldingStakeInput) => addHoldingStake(companyId, payload),
    onSuccess: () => {
      setForm(EMPTY_FORM);
      setShowForm(false);
      invalidate();
    },
    onError: (e: any) => window.alert(e?.response?.data?.detail ?? 'Не удалось добавить долю'),
  });

  const deleteMutation = useMutation({
    mutationFn: (stakeId: number) => deleteHoldingStake(companyId, stakeId),
    onSuccess: invalidate,
  });

  const debtMutation = useMutation({
    mutationFn: (value: number | null) => setCorporateDebt(companyId, value),
    onSuccess: invalidate,
  });

  /** Покрытие процентов — единственная метрика самого холдинга. */
  const coverage = useMemo(() => {
    const annual = (reports ?? [])
      .filter((r) => String(r.period_type).toLowerCase() === 'annual')
      .sort((a, b) => b.fiscal_year - a.fiscal_year);
    const latest = annual.find((r) => r.interest_coverage != null);
    return latest ? { value: latest.interest_coverage!, year: latest.fiscal_year } : null;
  }, [reports]);

  if (isLoading || !nav) return null;

  const incomplete = nav.total_stakes > 0 && nav.valued_stakes < nav.total_stakes;

  return (
    <div className="holding-panel">
      <div className="holding-header">
        <h2>Оценка холдинга</h2>
        <span className="holding-subtitle">
          сумма долей минус долг центра — консолидированные P/E и P/B здесь показывают дочек
        </span>
      </div>

      <div className="holding-summary">
        <SummaryCard label="Стоимость долей" value={formatMln(nav.stakes_value)} />
        <SummaryCard
          label="Долг корпцентра"
          value={nav.corporate_center_net_debt != null ? formatMln(nav.corporate_center_net_debt) : '—'}
          hint="из презентаций эмитента: в отчётности не выделен"
        />
        <SummaryCard label="NAV" value={formatMln(nav.nav)} emphasis />
        <SummaryCard label="Капитализация" value={formatMln(nav.market_cap)} />
        <SummaryCard
          label="Дисконт к NAV"
          value={fmtPct(nav.discount_pct)}
          emphasis
          hint={
            nav.discount_pct == null
              ? 'NAV не положителен — сравнивать не с чем'
              : 'на сколько рынок оценивает холдинг дешевле его долей'
          }
        />
        {coverage && (
          <SummaryCard
            label="Покрытие процентов"
            value={`${coverage.value.toLocaleString('ru-RU', { maximumFractionDigits: 2 })}×`}
            hint={`за ${coverage.year}: операционная прибыль к процентам, ≥ 5× — запас по Грэму`}
            level={coverage.value >= 5 ? 'good' : coverage.value >= 2 ? 'warn' : 'bad'}
          />
        )}
      </div>

      {incomplete && (
        <p className="holding-warning">
          Оценено {nav.valued_stakes} из {nav.total_stakes} долей — NAV занижен.
          У остальных не хватает данных в карточках дочек.
        </p>
      )}

      <table className="holding-table">
        <thead>
          <tr>
            <th>Актив</th>
            <th>Доля</th>
            <th>Стоимость дочки</th>
            <th>Стоимость доли</th>
            <th>Источник</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {nav.stakes.map((stake) => (
            <StakeRow
              key={stake.stake_id}
              stake={stake}
              onDelete={() => {
                if (window.confirm(`Удалить долю «${stake.name}»?`)) {
                  deleteMutation.mutate(stake.stake_id);
                }
              }}
            />
          ))}
          {nav.stakes.length === 0 && (
            <tr>
              <td colSpan={6} className="holding-empty">
                Долей пока нет. Добавьте дочек — публичные посчитаются по их карточкам.
              </td>
            </tr>
          )}
        </tbody>
      </table>

      <div className="holding-actions">
        <button type="button" className="holding-btn" onClick={() => setShowForm((v) => !v)}>
          {showForm ? 'Отмена' : '+ Доля'}
        </button>
        <label className="holding-debt">
          Чистый долг корпцентра, млн ₽:
          <input
            type="number"
            step="any"
            defaultValue={nav.corporate_center_net_debt ?? ''}
            onChange={(e) => setDebtInput(e.target.value)}
            placeholder="например: 330000"
          />
          <button
            type="button"
            className="holding-btn"
            disabled={debtMutation.isPending}
            onClick={() => debtMutation.mutate(debtInput === '' ? null : Number(debtInput))}
          >
            Сохранить
          </button>
        </label>
      </div>

      {showForm && (
        <form
          className="holding-form"
          onSubmit={(e) => {
            e.preventDefault();
            addMutation.mutate({
              ...form,
              name:
                form.name ||
                companies?.find((c) => c.id === form.subsidiary_company_id)?.name ||
                '',
            });
          }}
        >
          <label>
            Публичная дочка (из ваших карточек):
            <select
              value={form.subsidiary_company_id ?? ''}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  subsidiary_company_id: e.target.value ? Number(e.target.value) : null,
                  name: companies?.find((c) => c.id === Number(e.target.value))?.name ?? f.name,
                }))
              }
            >
              <option value="">— непубличный актив —</option>
              {(companies ?? [])
                .filter((c) => c.id !== companyId)
                .map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.ticker} · {c.name}
                  </option>
                ))}
            </select>
          </label>

          <label>
            Название:
            <input
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              placeholder="Медси"
              required
            />
          </label>

          <label>
            Доля владения, %:
            <input
              type="number"
              step="any"
              value={form.share_pct || ''}
              onChange={(e) => setForm((f) => ({ ...f, share_pct: Number(e.target.value) }))}
              required
            />
          </label>

          <label>
            Оценка всей дочки, млн ₽:
            <input
              type="number"
              step="any"
              value={form.manual_valuation ?? ''}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  manual_valuation: e.target.value === '' ? null : Number(e.target.value),
                }))
              }
              placeholder="только для непубличных"
              disabled={form.subsidiary_company_id != null}
            />
          </label>

          <button type="submit" className="holding-btn primary" disabled={addMutation.isPending}>
            Добавить
          </button>
        </form>
      )}
    </div>
  );
};

const SummaryCard: React.FC<{
  label: string;
  value: string;
  hint?: string;
  emphasis?: boolean;
  level?: 'good' | 'warn' | 'bad';
}> = ({ label, value, hint, emphasis, level }) => (
  <div
    className={`holding-card${emphasis ? ' emphasis' : ''}${level ? ` level-${level}` : ''}`}
    title={hint}
  >
    <div className="holding-card-label">{label}</div>
    <div className="holding-card-value">{value}</div>
    {hint && <div className="holding-card-hint">{hint}</div>}
  </div>
);

const StakeRow: React.FC<{ stake: StakeValuation; onDelete: () => void }> = ({ stake, onDelete }) => (
  <tr className={stake.stake_value == null ? 'holding-row-unvalued' : undefined}>
    <td>
      {stake.subsidiary_company_id ? (
        <Link to={`/company/${stake.subsidiary_company_id}`}>{stake.name}</Link>
      ) : (
        stake.name
      )}
      {stake.ticker && <span className="holding-ticker">{stake.ticker}</span>}
    </td>
    <td className="num">{fmtPct(stake.share_pct)}</td>
    <td className="num">{stake.company_value != null ? formatMln(stake.company_value) : '—'}</td>
    <td className="num strong">
      {stake.stake_value != null ? formatMln(stake.stake_value) : <span className="holding-missing">{stake.missing}</span>}
    </td>
    <td>{stake.source === 'market' ? 'рынок' : stake.source === 'manual' ? 'оценка' : '—'}</td>
    <td>
      <button type="button" className="holding-btn small" onClick={onDelete}>
        ✕
      </button>
    </td>
  </tr>
);

export default HoldingPanel;
