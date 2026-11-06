from __future__ import annotations
import hashlib,json,shutil,sqlite3,time
from pathlib import Path
import requests
from app.config import BASE_DIR
from . import store

URL='https://mcp.vrednyj-investor.ru/mcp'

class RateLimited(RuntimeError):
 def __init__(self,seconds):
  self.seconds=seconds;super().__init__(f'Лимит источника: повтор через {seconds} сек. Страницы сохранены.')

def fetch(ticker,folder,event,check):
 folder.mkdir(parents=True,exist_ok=True)
 session=requests.Session();session.headers['Accept']='application/json, text/event-stream'
 version=None;calls=0
 def pages(tool,args,label):
  nonlocal version,calls
  result=[];cursors=set()
  for page in range(1000):
   check()
   if shutil.disk_usage(folder).free<1024**3:raise RuntimeError('Свободного места меньше 1 ГБ; загрузка остановлена')
   cache_key=hashlib.sha256((label+':'+str(page)).encode()).hexdigest()
   path=folder/(cache_key+'.json')
   if path.exists():data=json.loads(path.read_text())
   else:
    for attempt in range(3):
     check()
     try:
      response=session.post(URL,json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':tool,'arguments':args}},timeout=(10,45))
      if response.status_code==429:
       retry=response.headers.get('Retry-After','60');raise RateLimited(max(60,int(retry) if retry.isdigit() else 60))
      response.raise_for_status();envelope=response.json()
      if 'error' in envelope:raise RuntimeError(str(envelope['error']))
      raw=envelope['result']
      if raw.get('isError'):raise RuntimeError(str(raw.get('content')))
      data=raw.get('structuredContent') or json.loads(next(c['text'] for c in raw['content'] if c['type']=='text'))
      if data.get('status') in ['invalid_request','version_expired']:raise RuntimeError(data.get('message') or data['status'])
      store.write(path,data);calls+=1;time.sleep(1.5);break
     except (requests.Timeout,requests.ConnectionError):
      if attempt==2:raise
      time.sleep(2**attempt)
   current=data.get('dataset',{}).get('version')
   if version and current and current!=version:raise RuntimeError('Версия источника изменилась. Создайте новую задачу загрузки.')
   version=current or version;result+=data.get('items',[])
   event(f'{ticker}: {tool}, страница {page+1}; получено {len(result)} записей')
   cursor=data.get('page',{}).get('next_cursor')
   if not cursor:return result
   if cursor in cursors:raise RuntimeError('Источник повторил курсор страницы')
   cursors.add(cursor);args={**args,'cursor':cursor}
  raise RuntimeError('Достигнут предел страниц; полнота не подтверждена')
 metrics={}
 for query in ['fin',ticker.lower(),'bank','капитал','процент','амортизац','дивиденд','акци','lease','capex']:
  for metric in pages('find_metrics',{'query_text':query,'companies':[ticker],'limit':100},'metrics-'+query):metrics[metric['code']]=metric
 facts={}
 for metric in metrics.values():
  for variant in metric.get('variants',[]):
   if variant['ticker']!=ticker:continue
   for fact in pages('get_series',{'companies':[ticker],'metrics':[metric['code']],'variants':[variant['selector']],'revisions':'all_verified','limit':100},'facts-'+metric['code']+'-'+variant['selector']):facts[fact['id']]=fact
 result={'ticker':ticker,'facts':list(facts.values()),'metrics':list(metrics.values()),'version':version,
         'downloaded_at':store.now(),'origin':'MCP','truncated_metrics':[m['code'] for m in metrics.values() if m.get('details_truncated')],
         'completeness':'Все страницы найденных вариантов; сервер не предоставляет полного реестра или bulk export','calls':calls}
 store.write(folder/'source.json',result)
 store.write(store.ROOT/'sources'/ticker/'source.json',result)
 return result

def local(ticker):
 cached=store.ROOT/'sources'/ticker/'source.json'
 if cached.exists():
  result=json.loads(cached.read_text());result['origin']='Локальный снимок MCP от '+result.get('downloaded_at','?');return result
 root=BASE_DIR/'data'/'external'/'vrednyj-investor'
 candidates=list(root.glob('*/'+ticker.lower()+'-pilot/all-facts.json'))+list(root.glob('*/'+ticker.lower()+'-pilot/facts.json'))
 # Earlier pilot directories were named fixr/vseh/lsng, matching their ticker.
 if candidates:
  latest=max(candidates,key=lambda p:p.stat().st_mtime)
  metrics=latest.parent/'all-metrics.json'
  if not metrics.exists():metrics=latest.parent/'metrics.json'
  return {'ticker':ticker,'facts':json.loads(latest.read_text()),'metrics':json.loads(metrics.read_text()) if metrics.exists() else [],
          'origin':str(latest.relative_to(BASE_DIR)),'version':None,'completeness':'Локальный снимок; полнота не подтверждена','truncated_metrics':[]}
 archives=sorted(root.glob('*/public.sqlite'),key=lambda p:p.stat().st_mtime,reverse=True)
 if not archives:return {'ticker':ticker,'facts':[],'metrics':[],'origin':'Нет локального дампа','version':None,'truncated_metrics':[]}
 with sqlite3.connect(archives[0].resolve().as_uri()+'?mode=ro',uri=True) as db:
  facts=[json.loads(row[0]) for row in db.execute("SELECT payload FROM facts WHERE json_extract(payload,'$.ticker')=?",(ticker,))]
  codes={f['metric_code'] for f in facts}
  metrics=[json.loads(row[0]) for row in db.execute('SELECT payload FROM metrics') if json.loads(row[0]).get('code') in codes]
  version=db.execute("SELECT value FROM state WHERE key='dataset_version'").fetchone()
 return {'ticker':ticker,'facts':facts,'metrics':metrics,'origin':str(archives[0].relative_to(BASE_DIR)),
         'version':version[0] if version else None,'completeness':'Частичный локальный дамп; отсутствие факта не доказывает отсутствие в MCP','truncated_metrics':[]}
