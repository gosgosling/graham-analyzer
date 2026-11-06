import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Alert, Button, Checkbox, Select, Space, Table, Tag, Progress, Collapse } from 'antd';
import { createDumpJob, controlDumpJob, dumpOverview, dumpJobs, dumpJob, dumpItems, dumpEvents, dumpAudit, dumpCells, dumpDownloadUrl, type DumpItem, type DumpCell } from '../services/dumpImport.api';
import { formatApiErrorMessage } from '../utils/apiErrors';
import './DumpImport.css';

const labels: Record<string, string> = {
  pending: 'Ожидает', running: 'В работе', paused: 'Пауза', ready: 'Аудит готов', completed: 'Завершено', failed: 'Сбой', cancelled: 'Отменено', audited: 'Аудит готов', done: 'Перенесено', error: 'Ошибка', skipped: 'Исключено', add: 'Добавить', match: 'Совпадает', difference: 'Различие · сохранено прежнее', blocked: 'Ограничение',
};
const fieldNames: Record<string, string> = {
  revenue: 'Выручка', net_income: 'Чистая прибыль', net_income_reported: 'Прибыль отчётная', operating_profit: 'Операционная прибыль', equity: 'Капитал', total_assets: 'Активы', total_liabilities: 'Обязательства', current_assets: 'Оборотные активы', current_liabilities: 'Краткосрочные обязательства', cash_and_equivalents: 'Деньги', debt: 'Долг', operating_cash_flow: 'OCF', capex: 'CAPEX', finance_costs: 'Финансовые расходы', depreciation_amortization: 'Амортизация', shares_weighted_avg: 'Средневзвешенное число акций', non_controlling_interest: 'Неконтролирующая доля', goodwill: 'Гудвил', intangible_assets: 'Прочие НМА', lease_principal: 'Тело аренды', lease_interest: 'Проценты аренды', interest_paid: 'Проценты уплаченные', interest_received: 'Проценты полученные', debt_principal: 'Погашение долга', interest_income: 'Процентные доходы',
};
const badge = (s: string) => <Tag color={['error', 'failed'].includes(s) ? 'red' : ['done', 'completed', 'match'].includes(s) ? 'green' : s === 'difference' ? 'orange' : 'blue'}>{labels[s] || s}</Tag>;
const number = (v: string | null) => v == null ? '—' : Number(v).toLocaleString('ru-RU', { maximumFractionDigits: 6 });

export default function DumpImport() {
  const qc = useQueryClient();
  const [tickers, setTickers] = useState<string[]>([]);
  const [refresh, setRefresh] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [company, setCompany] = useState<string | null>(null);
  const [filter, setFilter] = useState('');
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const overview = useQuery({ queryKey: ['dump-overview'], queryFn: dumpOverview, refetchInterval: 5000 });
  const jobs = useQuery({ queryKey: ['dump-jobs'], queryFn: dumpJobs, refetchInterval: 3000 });
  const jobId = selected || jobs.data?.[0]?.id || null;
  const job = useQuery({ queryKey: ['dump-job', jobId], queryFn: () => dumpJob(jobId!), enabled: !!jobId, refetchInterval: 3000 });
  const items = useQuery({ queryKey: ['dump-items', jobId], queryFn: () => dumpItems(jobId!), enabled: !!jobId, refetchInterval: 3000 });
  const events = useQuery({ queryKey: ['dump-events', jobId], queryFn: () => dumpEvents(jobId!), enabled: !!jobId, refetchInterval: 3000 });
  const audit = useQuery({ queryKey: ['dump-audit', jobId, company], queryFn: () => dumpAudit(jobId!, company!), enabled: !!jobId && !!company, retry: false });
  const cells = useQuery({ queryKey: ['dump-cells', jobId, company, filter, page], queryFn: () => dumpCells(jobId!, company!, filter, (page - 1) * 100), enabled: !!jobId && !!company, retry: false });
  const invalidate = () => qc.invalidateQueries({ predicate: q => String(q.queryKey[0]).startsWith('dump-') });
  const action = useMutation({
    mutationFn: (a: string) => controlDumpJob(jobId!, a),
    onSuccess: () => { setError(null); invalidate(); }, onError: e => setError(formatApiErrorMessage(e, 'Ошибка запроса')),
  });
  const create = useMutation({ mutationFn: () => createDumpJob(tickers, refresh), onSuccess: j => { setSelected(j.id); setCompany(null); setError(null); invalidate(); }, onError: e => setError(formatApiErrorMessage(e, 'Ошибка запроса')) });
  const selectJob = (id: string) => { setSelected(id); setCompany(null); setPage(1); };
  const selectCompany = (ticker: string) => { setCompany(ticker); setPage(1); setFilter(''); };
  const data = job.data;
  const completed = data ? (data.phase === 'audit' ? data.counts.audited : 0) + data.counts.done + data.counts.error + data.counts.skipped : 0;
  const apiError = error || (overview.error ? formatApiErrorMessage(overview.error, 'Ошибка запроса') : jobs.error ? formatApiErrorMessage(jobs.error, 'Ошибка запроса') : null);

  return <main className="dump-import">
    <Link to="/admin">← Админка</Link>
    <h1>Импорт из дампа</h1>
    <p>Загрузка Data Foundry, сравнение с текущими отчётами и заполнение пропусков. Расчёты выполняются на сервере без LLM и расхода токенов.</p>
    {apiError && <Alert type="error" showIcon message={apiError} closable onClose={() => setError(null)} />}
    <section className="dump-card">
      <h2>Новая задача</h2>
      <Space wrap>
        <Button disabled={!overview.data} onClick={() => setTickers((overview.data?.companies || []).filter(c => !c.excluded && !c.protected).map(c => c.ticker))}>Выбрать незаполненные компании</Button>
        <Button onClick={() => setTickers([])}>Очистить</Button>
      </Space>
      <Select mode="multiple" showSearch optionFilterProp="label" aria-label="Компании для импорта" placeholder="Выберите компании" value={tickers} onChange={setTickers} className="dump-company-select" maxTagCount="responsive"
        options={(overview.data?.companies || []).map(c => ({ value: c.ticker, label: `${c.ticker} · ${c.name}${c.protected ? ' · защищена' : ''}${c.excluded ? ' · холдинг исключён' : ''}`, disabled: c.excluded }))} />
      <Space wrap>
        <Checkbox checked={refresh} onChange={e => setRefresh(e.target.checked)}>Загрузить свежие данные MCP перед аудитом</Checkbox>
        <Button type="primary" disabled={!tickers.length || overview.data?.worker_alive} loading={create.isPending} onClick={() => create.mutate()}>Запустить загрузку и аудит ({tickers.length})</Button>
      </Space>
      <p className="dump-note">Без галочки используется локальный снимок: отсутствие факта в нём ещё не означает отсутствие в источнике. Этот шаг не меняет отчёты компаний.</p>
      <Collapse items={[{ key: 'rules', label: 'Правила переноса', children: <ul>{overview.data?.rules.map(rule => <li key={rule}>{rule}</li>)}</ul> }]} />
      {overview.data && !overview.data.apply_allowed && <Alert type="info" message="Перенос в отчёты доступен только для локальной dev-базы. Загрузка и аудит доступны отдельно." />}
    </section>
    <section className="dump-card">
      <h2>Задачи и прогресс</h2>
      <Select aria-label="Задача импорта" className="dump-job-select" value={jobId || undefined} onChange={selectJob} placeholder="Задач пока нет" options={(jobs.data || []).map(j => ({ value: j.id, label: `${new Date(j.created_at).toLocaleString('ru-RU')} · ${labels[j.status] || j.status} · ${j.total} компаний` }))} />
      {data && <>
        <Space wrap>{badge(data.status)}<span>{data.phase === 'audit' ? 'Загрузка и аудит' : 'Перенос'}</span><span>{completed} / {data.total} компаний</span></Space>
        <Progress percent={data.total ? Math.round(completed / data.total * 100) : 0} status={data.status === 'failed' ? 'exception' : data.status === 'running' ? 'active' : 'normal'} />
        <p>{data.message}</p>
        {data.retry_at && <p>Повтор запроса к источнику после {new Date(data.retry_at).toLocaleString('ru-RU')}.</p>}
        <div className="dump-stats"><span>Фактов: <b>{data.totals.facts}</b></span><span>Добавить: <b>{data.totals.add}</b></span><span>Совпадений: <b>{data.totals.matches}</b></span><span>Различий: <b>{data.totals.differences}</b></span><span>Ограничений: <b>{data.totals.blocked}</b></span><span>Новых отчётов: <b>{data.totals.new_reports}</b></span></div>
        <Space wrap>
          {data.status === 'running' && <Button loading={action.isPending} onClick={() => action.mutate('pause')}>Пауза</Button>}
          {['paused', 'failed'].includes(data.status) && <Button loading={action.isPending} onClick={() => action.mutate('resume')}>Продолжить</Button>}
          {data.counts.error > 0 && data.status !== 'running' && <Button loading={action.isPending} onClick={() => action.mutate('retry')}>Повторить ошибки</Button>}
          {data.status === 'ready' && <Button type="primary" disabled={!overview.data?.apply_allowed || !data.totals.add} loading={action.isPending} onClick={() => action.mutate('apply')}>Создать бэкап и перенести готовые данные</Button>}
          {!['completed', 'cancelled'].includes(data.status) && <Button danger loading={action.isPending} onClick={() => action.mutate('cancel')}>Отменить задачу</Button>}
        </Space>
        <p className="dump-note">Пауза и отмена останавливают дальнейшую обработку после текущего запроса или компании. Перед записью проверяется, что данные не изменились после аудита.</p>
        {data.backup && <p>Резервная копия: <code>{String(data.backup.filename || data.backup.path || 'создана')}</code></p>}
        <Table<DumpItem> rowKey="ticker" size="small" dataSource={items.data || []} pagination={{ pageSize: 20 }} scroll={{ x: 1050 }}
          columns={[
            { title: 'Компания', dataIndex: 'ticker', render: (t: string, i) => <Button type="link" disabled={!i.summary} onClick={() => selectCompany(t)}>{t}</Button> },
            { title: 'Статус', dataIndex: 'status', render: badge },
            { title: 'Фактов', render: (_, i) => i.summary?.facts ?? '—' },
            { title: 'Добавить', render: (_, i) => i.summary?.add ?? '—' },
            { title: 'Различий', render: (_, i) => i.summary?.differences ?? '—' },
            { title: 'Полей без данных', render: (_, i) => i.summary?.missing_fields ?? '—' },
            { title: 'Периоды', render: (_, i) => i.summary ? `${i.summary.first_date || '—'} — ${i.summary.last_date || '—'}` : '—' },
            { title: 'Сообщение', dataIndex: 'message' },
          ]} />
        <Collapse items={[{ key: 'events', label: 'Журнал последних событий', children: <div className="dump-log">{events.data?.map(e => <div key={e.id}><time>{new Date(e.at).toLocaleTimeString('ru-RU')}</time> {e.message}</div>)}</div> }]} />
      </>}
    </section>
    {company && jobId && <section className="dump-card">
      <h2>{company}: аудит и сравнение</h2>
      {audit.error && <Alert type="error" message={formatApiErrorMessage(audit.error, 'Ошибка запроса')} />}
      {audit.data && <>
        <Space wrap><Link to={`/company/${audit.data.company_id}/reports-matrix`}>Открыть матрицу компании</Link>{['source', 'audit', ...((items.data || []).find(i => i.ticker === company)?.status === 'done' ? ['receipt'] : [])].map(k => <a key={k} href={dumpDownloadUrl(jobId, company, k)} target="_blank" rel="noreferrer">{k === 'source' ? 'Все исходные факты JSON' : k === 'audit' ? 'Полный аудит JSON' : 'Журнал переноса JSON'}</a>)}</Space>
        <p>Источник: {audit.data.source_origin}; версия {audit.data.source_version || 'не указана'}. {audit.data.source_completeness}</p>
        {audit.data.warnings.map(w => <p className="dump-note" key={w}>{w}</p>)}
        <p>Замечаний аудита проекта до: <b>{audit.data.audit_before.findings.length}</b>; в предлагаемом результате: <b>{audit.data.audit_projected.findings.length}</b>.</p>
        <Collapse items={[{ key: 'findings', label: 'Замечания аудита проекта', children: <Table rowKey={(r, i) => `${r.year}:${i}`} size="small" pagination={{ pageSize: 10 }} dataSource={audit.data.audit_projected.findings} columns={[{ title: 'Год', dataIndex: 'year' }, { title: 'Уровень', dataIndex: 'level', render: (v: string) => <Tag color={v === 'defect' ? 'red' : 'orange'}>{{ defect: 'Дефект', gap: 'Пропуск', suspect: 'Проверить' }[v] || v}</Tag> }, { title: 'Замечание', dataIndex: 'message' }]} /> }]} />
        <h3>Поля матрицы и покрытие источника</h3>
        <Table rowKey="field" size="small" pagination={false} dataSource={audit.data.coverage} columns={[
          { title: 'Поле', dataIndex: 'field', render: (s: string) => <>{fieldNames[s] || s}<br /><small>{s}</small></> },
          { title: 'В дампе', dataIndex: 'present', render: (v: boolean) => <Tag color={v ? 'green' : 'orange'}>{v ? 'Есть' : 'Не найдено'}</Tag> },
          { title: 'Фактов', dataIndex: 'facts' }, { title: 'Совместимых с форматом', dataIndex: 'usable_facts' }, { title: 'Сопоставление', dataIndex: 'mapped', render: (v: boolean) => v ? 'Есть' : 'Требуется отдельное сопоставление' }, { title: 'Коды источника', dataIndex: 'codes', render: (s: string[]) => s.join(', ') },
        ]} />
        <p>Метрики без соответствия полям: {audit.data.unmapped_metrics.join(', ') || 'нет'}. Все они сохранены в исходном JSON.</p>
        <p>Сохранено отдельно от столбцов: {Object.entries(audit.data.not_projected).map(([key, value]) => `${key}: ${value}`).join('; ') || 'нет'}. Замечаний по вариантам источника: {audit.data.issues.length}.</p>
        <h3>Значения: проект ↔ источник</h3>
        <Select aria-label="Фильтр значений" value={filter} onChange={s => { setFilter(s); setPage(1); }} options={['', 'add', 'difference', 'match', 'blocked'].map(s => ({ value: s, label: s ? labels[s] : 'Все значения' }))} style={{ minWidth: 260 }} />
        <p className="dump-note">Денежные значения — млн ₽; количество акций — штуки. Потоки приведены к накопительным периодам. Прочерк означает отсутствие значения, а не ноль.</p>
        <Table<DumpCell> rowKey={r => `${r.date}:${r.period_type}:${r.field}`} size="small" loading={cells.isLoading} dataSource={cells.data?.items || []} scroll={{ x: 1050 }} pagination={{ current: page, pageSize: 100, total: cells.data?.total || 0, showSizeChanger: false, onChange: setPage }} columns={[
          { title: 'Период', dataIndex: 'date' }, { title: 'Поле', dataIndex: 'field', render: (s: string) => fieldNames[s] || s },
          { title: 'Сейчас', dataIndex: 'current', render: number }, { title: 'Источник', dataIndex: 'source', render: number },
          { title: 'Разница', dataIndex: 'delta', render: number }, { title: 'Действие', dataIndex: 'action', render: badge },
          { title: 'Определение / причина', render: (_, r) => <>{r.definition}<br />{r.reason}</> },
        ]} />
        {cells.error && <Alert type="error" message={formatApiErrorMessage(cells.error, 'Ошибка запроса')} />}
      </>}
    </section>}
  </main>;
}
