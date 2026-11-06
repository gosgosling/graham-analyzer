"""Cache all discovered metrics/variants/history for one company from public MCP."""
import argparse,json,time
from pathlib import Path
import requests
URL='https://mcp.vrednyj-investor.ru/mcp'

def fetch(ticker,folder):
 folder.mkdir(parents=True,exist_ok=True)
 session=requests.Session();session.headers['Accept']='application/json, text/event-stream'
 version=None
 def rpc(name,args,label):
  nonlocal version
  filename=folder/(label+'.json')
  if filename.exists():data=json.loads(filename.read_text())
  else:
   for attempt in range(5):
    r=session.post(URL,json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':args}},timeout=(10,45))
    if r.status_code==429:
     delay=max(60,int(r.headers.get('Retry-After','60')));print('Rate limited; wait',delay,flush=True);time.sleep(delay);continue
    r.raise_for_status();envelope=r.json()
    if 'error' in envelope:raise RuntimeError(envelope['error'])
    result=envelope['result']
    if result.get('isError'):raise RuntimeError(result['content'])
    data=result.get('structuredContent') or json.loads(next(c['text'] for c in result['content'] if c['type']=='text'))
    if data.get('status') in ['invalid_request','version_expired']:raise RuntimeError(data)
    filename.write_text(json.dumps(data,ensure_ascii=False,indent=2));time.sleep(1.5);break
   else:raise RuntimeError('Rate limit persisted; cache retained')
  current=data.get('dataset',{}).get('version')
  if version and current and current!=version:raise RuntimeError('Dataset changed; start another folder')
  version=current or version
  return data
 def pages(name,args,label):
  result=[]
  for page in range(1000):
   data=rpc(name,args,label+'-'+str(page));result+=data.get('items',[])
   cursor=data.get('page',{}).get('next_cursor')
   if not cursor:break
   args={**args,'cursor':cursor}
  else:raise RuntimeError('Page cap reached')
  return result
 companies=pages('search_companies',{'query_text':ticker,'limit':100},'company')
 (folder/'companies.json').write_text(json.dumps(companies,ensure_ascii=False,indent=2))
 metrics={}
 for query in ['fin',ticker.lower(),'капитал','процент','амортизац','дивиденд','акци','lease','capex']:
  for metric in pages('find_metrics',{'query_text':query,'companies':[ticker],'limit':100},'metrics-'+query):metrics[metric['code']]=metric
 (folder/'all-metrics.json').write_text(json.dumps(list(metrics.values()),ensure_ascii=False,indent=2))
 print('METRICS',len(metrics),flush=True)
 facts={}
 for metric in metrics.values():
  if metric.get('details_truncated'):raise RuntimeError('Truncated metric '+metric['code'])
  for variant in metric.get('variants',[]):
   if variant['ticker']!=ticker:continue
   for fact in pages('get_series',{'companies':[ticker],'metrics':[metric['code']],'variants':[variant['selector']],'revisions':'all_verified','limit':100},'facts-'+metric['code']+'-'+variant['selector']):facts[fact['id']]=fact
  (folder/'all-facts.json').write_text(json.dumps(list(facts.values()),ensure_ascii=False,indent=2))
  print(metric['code'],len(facts),flush=True)
 (folder/'fetch-summary.json').write_text(json.dumps({'ticker':ticker,'dataset_version':version,'metrics':len(metrics),'facts':len(facts),'queries':['fin',ticker.lower(),'капитал','процент','амортизац','дивиденд','акци','lease','capex'],'completeness':'all discovered variants and pages; no authoritative bulk-export endpoint'},ensure_ascii=False,indent=2))
 print('DONE',len(metrics),len(facts),flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--ticker',required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args();fetch(args.ticker,args.output)
