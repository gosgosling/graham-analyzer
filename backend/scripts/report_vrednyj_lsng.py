"""Build the read-only LSNG comparison page and its Markdown audit."""
import html,json,re
from collections import Counter
from decimal import Decimal
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];P=ROOT/'data/external/vrednyj-investor/2026-11-02/lsng-pilot'

def main():
 before=json.loads((P/'before-lsng.json').read_text());after=json.loads((P/'after-lsng.json').read_text());result=json.loads((P/'synergy-import-result.json').read_text());facts=json.loads((P/'all-facts.json').read_text());metrics=json.loads((P/'all-metrics.json').read_text());comp=json.loads((P/'comparison.json').read_text());plan=json.loads((P/'synergy-plan.json').read_text())
 evidence={x['source_id']:x for x in json.loads((P/'difference-evidence.json').read_text())['items']};byid={x['id']:x for x in facts}
 source=(ROOT/'frontend/src/pages/CompanyReportsMatrix.tsx').read_text().split('const MATRIX_ROWS: MatrixRowDef[] = [',1)[1].split('\n];',1)[0]
 rows=[];labels={}
 for m in re.finditer(r"\{\s*key:\s*'([^']+)'(.*?)\}",source,re.S):
  key,body=m.groups();label=re.search(r"label:\s*'([^']+)'",body);kind=re.search(r"kind:\s*'([^']+)'",body)
  only=re.search(r'only:\s*\[([^]]+)\]',body);hide=re.search(r'hideFor:\s*\[([^]]+)\]',body)
  labels[key]=label[1]
  if (only and "'industrial'" not in only[1]) or (hide and "'industrial'" in hide[1]):continue
  rows.append((key,label[1],kind[1]))
 from app.services.analysis.vrednyj_synergy import CODES
 reverse={field:[code for code,_ in codes] for field,codes in CODES.items()};reverse['net_income_reported']=reverse['net_income']
 financial=[r for r in rows if r[2] in ['number','int'] and r[0] not in ['fiscal_year','fiscal_quarter','exchange_rate','price_per_share','price_at_filing']]
 found={x['metric_code'] for x in facts};covered=[r for r in financial if set(reverse.get(r[0],[]))&found]
 oldids={x['id'] for x in before};old_dates={x['report_date'] for x in before};diff=[x for x in comp if x['status']=='difference_preserved_qwen']
 nold=sum(str(x['id']) in oldids for x in result['added_cells']);nnew=len(result['added_cells'])-nold
 e=lambda x:html.escape(str(x))
 def fmt(x):
  if x is None:return '—'
  try:return f'{Decimal(str(x)):,.3f}'.replace(',',' ')
  except Exception:return str(x)
 def count(rows,key):return sum(r.get(key) is not None for r in rows)
 notes={
  ('2021-12-31','net_income'):'Подтверждено: дамп взял пересчитанный 2021 год из отчёта за 2022 (стр. 10); Qwen — исходный отчёт за 2021. Обе версии существуют.',
  ('2021-12-31','net_income_reported'):'Та же версия пересчёта прибыли; не отдельное экономическое расхождение.',
  ('2016-12-31','revenue'):'66 207,886 подтверждено в сравнительной колонке 2016 года отчёта за 2017, стр. 11. Причина отличия от Qwen пока не установлена.',
 }
 def explanation(r):
  return notes.get((r['report_date'],r['field']),'Дамп использует сравнительную колонку более позднего отчёта. Пересчёт/переклассификация возможны, но конкретная причина не проверена; Qwen сохранён.')
 def evidence_text(r,markup=False):
  parts=[]
  for identity in r['provenance']:
   ev=evidence.get(byid[identity]['source_id'])
   if not ev:continue
   label=ev['title']+'; стр. '+str(ev.get('locator',{}).get('page','?'))
   parts.append('<a href="'+e(ev['official_url'])+'">'+e(label)+'</a>' if markup else label)
  return '<br>'.join(parts) if markup else '; '.join(parts)
 intro=[
 '# Ленэнерго: синергия Qwen и Data Foundry', '', '2 ноября 2026. Только локальный dev; company_id=64, LSNG. Прод не изменялся.', '',
 f'Источник: {len(facts)} фактов по {len(metrics)} метрикам, история 2006–2025. До: 17 годовых отчётов Qwen. После: 49 отчётов (20 годовых, 17 полугодовых, 12 квартальных). Добавлено 32 отчёта и 361 финансовая ячейка: {nold} в прежние отчёты, {nnew} в новые.', '',
 'Все ранее непустые финансовые значения Qwen сохранены. В пересекающихся ячейках 136 совпадений и 16 расхождений; два расхождения повторяют NI в net_income_reported. Это сравнение, а не оценка точности 136/152: оба источника могут выбирать одну и ту же неподходящую строку.', '',
 'Все 957 фактов сохранены в extraction_notes и в all-facts.json. 25 фактов на 1 января хранятся отдельно внутри заметок последнего отчёта: им не присвоены выдуманные отчётные периоды. Полные альтернативы не отбрасывались. Новые сведения не получают ручную верификацию.', '',
 '## Что получилось объединить', '', '| Поле | Было заполнено / 17 | Стало заполнено / 49 |', '|---|---:|---:|']
 keys=['revenue','net_income','equity','operating_profit','operating_cash_flow','debt','capex','depreciation_amortization','finance_costs','shares_weighted_avg']
 intro += [f'| {labels.get(k,k)} | {count(before,k)} | {count(after,k)} |' for k in keys]
 intro += ['', 'Пример за 2024: к прежним Qwen-данным добавлены операционная прибыль 22 211,784 млн ₽, капитал 199 187,863 млн ₽ и OCF 60 441,884 млн ₽. CAPEX, аренда, амортизация и долг из прежних отчётов сохранены.', '',
 '## Все расхождения, млн ₽', '', '| Период | Поле | Qwen | Дамп | Дамп − Qwen | Причина / статус | Источник дампа |', '|---|---|---:|---:|---:|---|---|']
 intro += [f"| {r['report_date']} | {labels.get(r['field'],r['field'])} | {fmt(r['qwen_before'])} | {fmt(r['dump'])} | {fmt(r['delta'])} | {explanation(r)} | {evidence_text(r)} |" for r in diff]
 intro += ['', '## Чего нет в полученном дампе LSNG', '',
 'Среди 20 найденных метрик нет финансовых расходов/процентов, процентного долга, CAPEX, амортизации, тела и процентов аренды, погашения долга, процентов полученных, денежных вложений, гудвила и прочих НМА, НКД, дивидендов и количества акций. EPS есть, но это не количество акций. Инвестиционный денежный поток есть, но его нельзя приравнивать к CAPEX.', '',
 f'Из {len(financial)} числовых финансовых и акционерных строк интерфейса industrial {len(covered)} имеют соответствие в этой выгрузке (NI и отчётная NI — две строки интерфейса, но одна метрика). Это не процент точности или полноты всех отчётов. Подробная таблица по каждой строке — в HTML.', '',
 'Не найдено ни одного факта за 2026 год. Последний доступный период — 31.12.2025. Капитал собственников дан лишь в четырёх точках, одна на 01.01.2021; в других периодах есть общий капитал, что не гарантирует совместимость с владельческим определением проекта. Прибыль — преимущественно прибыль всей группы.', '',
 '## Проверенные нюансы качества', '',
 '- Прибыль 2021: Qwen 15 453,067 млн ₽, дамп 13 187,814 млн ₽. В отчёте за 2022 (PDF стр. 10 и 56) вторая цифра явно помечена «2021 (пересчитано)». Это разные версии, не доказанная ошибка Qwen.',
 '- Выручка 2016: Qwen 59 022,324 млн ₽, дамп 66 207,886 млн ₽. Цифра дампа визуально подтверждена в отчёте за 2017 (PDF стр. 11), причина расхождения пока не доказана.',
 '- Совпадение прибыли ещё не доказывает нужную семантику: в сравнительной колонке 2016 года отчёта за 2017 прибыль группы 7 702,883 млн ₽, прибыль собственников 7 656,707 млн ₽. Qwen и fin.net_income используют первую. Нормализованную прибыль по методике Грэма источник автоматически не даёт.',
 '- Одновременное сохранение исходных Qwen-значений и добавление пересчитанных строк источника может смешивать версии одного периода. Такое объединение — непроверенный dev-эксперимент; перед аналитическим использованием нужна согласованная версия отчёта целиком.', '',
 '## Вывод о полезности', '',
 'Дамп полезен как второй источник и автоматическая заготовка: в прежних 17 отчётах он закрыл 33 пропуска, добавил 32 отсутствовавших периода и дал проверяемые источники для расхождений. В паре Qwen + дамп охват существенно выше, чем у каждого по отдельности.', '',
 'Для полного автоматического заполнения нашей модели он недостаточен: не хватает детализации долга, процентов, CAPEX/аренды, акционерных показателей и владельческой прибыли/капитала. Он хорошо покрывает базовые формы и историю, но не заменяет извлечение примечаний и нормализацию. До массового объединения нужны правила для пересчитанных сравнительных данных и согласованности версии.', '',
 '## Сохранность и файлы', '',
 '- Бэкап: backups/postgres/graham_analyzer_20261102_135743.dump; аккаунты отдельно в закрытом дампе.',
 f"- {result['other_reports_unchanged']} отчётов других компаний сверены поколоночно и не изменены. Все исходные непустые финансовые ячейки LSNG сохранены.",
 '- Исходные факты, метрики, источники расхождений, снимки до/после и журнал: data/external/vrednyj-investor/2026-11-02/lsng-pilot/.',
 '- Проверенные PDF: /home/devops/Reports/LSNG/LSNG_2021.pdf, LSNG_2022.pdf, LSNG_2017.pdf. Источники и страницы доступны в сравнительной HTML-таблице.'
 ]
 (ROOT/'docs/LSNG-DUMP-SYNERGY-2026-11-02.md').write_text('\n'.join(intro)+'\n')
 h=['''<!doctype html><html lang="ru"><meta charset="utf-8"><title>Ленэнерго · Qwen + дамп</title><style>
 body{font:14px system-ui,sans-serif;background:#f5f7fb;color:#243449;margin:28px}h1{font-size:29px}h2{margin-top:36px}p{line-height:1.6;max-width:1150px}.cards{display:flex;gap:12px;flex-wrap:wrap}.card{border:1px solid #d5deea;background:white;border-radius:10px;padding:16px 25px}.card b{display:block;font-size:27px}.scroll{max-height:74vh;overflow:auto;background:white;border:1px solid #cbd5e1}table{border-spacing:0;width:100%;font-size:13px}th,td{padding:10px 12px;border-bottom:1px solid #dde5ee;border-right:1px solid #edf1f6;text-align:right;white-space:nowrap}th{position:sticky;top:0;background:#e7eef8;z-index:2}td:first-child,th:first-child{position:sticky;left:0;background:white;text-align:left;z-index:1;min-width:220px;max-width:350px;white-space:normal}th:first-child{background:#e7eef8;z-index:3}.note{white-space:normal;text-align:left;min-width:250px;max-width:480px}.warn{background:#fff1ca;border-radius:8px;padding:14px 18px}.missing{color:#a44235}.ok{color:#176348}code,small{font-size:11px;color:#5d6c7e}nav{display:flex;gap:18px;margin:25px 0;flex-wrap:wrap}a{color:#245ca7}summary{cursor:pointer;padding:15px;background:#e7eef8;font-weight:600}</style>
 <h1>Россети Ленэнерго · Qwen + дамп</h1><p>2 ноября 2026 · локальный dev · LSNG, company_id=64. Денежные значения — <b>млн ₽</b>, EPS — ₽/акцию. Прочерк означает неизвестное значение, не ноль.</p>''']
 h.append('<div class="cards">'+''.join(f'<div class="card"><b>{a}</b>{b}</div>' for a,b in [('17 → 49','отчётов'),('361','добавленная финансовая ячейка'),('136 / 16','совпадений / расхождений'),('957 / 20','фактов / метрик источника')])+'</div>')
 h.append(f'<p>Добавлено {nold} ячейки в прежние отчёты и {nnew} в новые. Все прежние заполненные значения Qwen оставлены. Все факты дампа, включая альтернативы, сохранены. Ни одна другая компания не изменена.</p><p class="warn">Главный нюанс: исходные и пересчитанные версии могут различаться. Например, прибыль 2021 — 15 453,067 у Qwen и 13 187,814 в дампе: второе число подтверждено как пересчитанное в отчёте за 2022. Прибыль/капитал группы не всегда равны владельческим строкам матрицы. Это эксперимент, компания остаётся непроверенной.</p>')
 h.append('<nav><a href="#differences">Расхождения</a><a href="#coverage">Поля матрицы и пропуски</a><a href="#metrics">20 метрик источника</a><a href="#added">361 добавление</a><a href="#matrix">Матрица после объединения</a><a href="#raw">Все 957 фактов</a><a href="#conclusion">Вывод</a></nav>')
 def start(headers):h.append('<div class="scroll"><table><thead><tr>'+''.join('<th>'+e(x)+'</th>' for x in headers)+'</tr></thead><tbody>')
 def end():h.append('</tbody></table></div>')
 h.append('<h2 id="differences">1. Все 16 расхождений · Qwen сохранён</h2><p>14 отдельных расхождений плюс два повторения прибыли в net_income_reported. Сравнение не показывает автоматически, какая версия верна.</p>')
 start(['Период / поле','Qwen','Дамп','Дамп − Qwen','Разница, %','Разбор','Документ дампа'])
 for r in diff:
  h.append('<tr><td>'+e(r['report_date'])+'<br>'+e(labels[r['field']])+'<br><code>'+r['field']+'</code></td>'+''.join('<td>'+e(fmt(r[x]))+'</td>' for x in ['qwen_before','dump','delta'])+'<td>'+e(r['relative_pct'] or '—')+'</td><td class="note">'+e(explanation(r))+'</td><td class="note">'+evidence_text(r,True)+'</td></tr>')
 end()
 h.append('<h2 id="coverage">2. Поля нашей матрицы · до и после</h2><p>Только числовые финансовые и акционерные строки industrial: '+str(len(covered))+' из '+str(len(financial))+' имеют соответствие в выгрузке. Это не оценка точности и не доля заполнения каждой даты. Банковские строки, вычисляемые показатели, цены, даты и служебные поля не входят в этот счёт.</p>')
 start(['Поле матрицы','Было / 17','Стало / 49','Код в дампе','Фактов / дат','Что это означает'])
 for key,label,kind in financial:
  fs=[f for f in facts if f['metric_code'] in reverse.get(key,[])]
  note='Есть в источнике; дополнены только пустые поля.' if fs else 'В полученном дампе LSNG не найдено; прежние данные Qwen сохранены.'
  if key in ['net_income','net_income_reported']:note+=' fin.net_income — прибыль группы; не всегда владельческая, не нормализована.'
  if key=='equity':note+=' Капитал владельцев — лишь 4 факта, один на 1 января; прочие точки заполнены общим капиталом с пометкой.'
  h.append('<tr><td>'+e(label)+'<br><code>'+key+'</code></td><td>'+str(count(before,key))+'</td><td>'+str(count(after,key))+'</td><td class="note">'+e(', '.join(sorted({f['metric_code'] for f in fs})) or '—')+'</td><td>'+str(len(fs))+' / '+str(len({f['period']['end'] for f in fs}))+'</td><td class="note">'+e(note)+'</td></tr>')
 end()
 h.append('<h2 id="metrics">3. Всё, что отдал источник</h2><p>957 фактов, 20 метрик. Даты 2006–2025, данных за 2026 нет. Из 957 фактов 25 относятся к 1 января и сохранены как отдельные исходные точки, а не как выдуманные годовые отчёты.</p>')
 start(['Метрика','Фактов','Дат','Первая дата','Последняя дата','Куда сохранено'])
 all_codes={code for codes in CODES.values() for code,_ in codes}
 for m in metrics:
  fs=[f for f in facts if f['metric_code']==m['code']];ends=sorted({f['period']['end'] for f in fs})
  h.append('<tr><td>'+e(m['name_ru'])+'<br><code>'+m['code']+'</code></td><td>'+str(len(fs))+'</td><td>'+str(len(ends))+'</td><td>'+e(ends[0] if ends else '—')+'</td><td>'+e(ends[-1] if ends else '—')+'</td><td class="note">'+('Поля карточки + исходные факты' if m['code'] in all_codes else 'Исходные факты в extraction_notes; отдельного столбца матрицы нет')+'</td></tr>')
 end()
 h.append('<h2 id="added">4. Все 361 добавленная ячейка</h2>');start(['Период / поле','Значение','В какой отчёт'])
 for r in result['added_cells']:
  h.append('<tr><td>'+r['report_date']+'<br>'+e(labels[r['field']])+'</td><td>'+e(fmt(r['value']))+'</td><td>'+('Прежний Qwen' if str(r['id']) in oldids else 'Новый из дампа')+'</td></tr>')
 end()
 h.append('<h2 id="matrix">5. Финансовые значения после объединения</h2><p>Потоки в матрице — с начала года. Значения без специального столбца (EPS, PBT и т.д.) доступны в исходных фактах ниже.</p>');start(['Поле']+[r['report_date'] for r in after])
 for key,label,kind in financial:
  h.append('<tr><td>'+e(label)+'<br><code>'+key+'</code></td>'+''.join('<td>'+e(fmt(r.get(key)))+'</td>' for r in after)+'</tr>')
 end()
 h.append('<h2 id="raw">6. Все исходные факты</h2><details><summary>Развернуть 957 строк с альтернативами</summary>');start(['Метрика','Начало','Конец','value, полные единицы','reported_value','Масштаб','Единица','Статус','Fact ID / source ID'])
 for f in sorted(facts,key=lambda f:(f['metric_code'],f['period']['end'],f['period'].get('start') or '',f['id'])):
  cells=[f['metric_code'],f['period'].get('start') or 'на дату',f['period']['end'],f['value'],f.get('reported_value'),f.get('scale_multiplier'),f['unit'],f['review_status'],f['id']+' / '+f['source_id']]
  h.append('<tr>'+''.join('<td>'+e(v if v is not None else '—')+'</td>' for v in cells)+'</tr>')
 end();h.append('</details><h2 id="conclusion">Вывод</h2><p><b>Дамп полезен как второй источник:</b> он закрыл 33 пропуска в уже существовавших отчётах и добавил 32 периода. Особенно полезны история баланса, выручка, операционная прибыль и OCF. Qwen дополняет его деталями из примечаний.</p><p><b>Полностью заменить сбор отчётности он пока не может.</b> В этой выгрузке нет CAPEX, амортизации, процентов, долга и его расшифровок, аренды, дивидендов и количества акций. Для покрытия процентов и полноценного FCF данных дампа недостаточно. EPS и инвестиционный поток не заменяют эти строки.</p><p><b>До массовой интеграции нужны правила версий.</b> Сравнительные колонки могут быть пересчитаны; нельзя автоматически объявлять их расхождение ошибкой Qwen или смешивать с исходными строками. Владельческие показатели и нормализация прибыли также требуют отдельного разбора. Все новые сведения оставлены непроверенными.</p><p>Бэкап: graham_analyzer_20261102_135743.dump. Сохранность остальных 1368 отчётов проверена поколоночно. Приложение и прод этой страницей не изменяются.</p></html>')
 target=ROOT/'docs/LSNG-DUMP-SYNERGY-2026-11-02.html';target.write_text(''.join(h));print(target);print('Financial fields:',len(financial),'covered',len(covered),'raw facts',len(facts))

if __name__=='__main__':main()
