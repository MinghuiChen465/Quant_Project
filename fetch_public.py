# 公开数据抓取：先检查缓存及 robots，再限速请求，保存原始响应、来源和抓取时间。
"""Rate-limited, cached public-source acquisition with robots checks and provenance."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import time
from urllib.parse import urlsplit, urlencode
from urllib.robotparser import RobotFileParser
import requests
from core import path, logger
import yaml

CONFIG = yaml.safe_load(path('config.yaml').read_text(encoding='utf-8'))

AGENT='AcademicQuantResearch/1.0'

class PublicClient:
    # 复用 HTTP 会话和 User-Agent，并保存限速时间与各网站 robots 规则缓存。
    def __init__(self):
        self.session=requests.Session()
        self.session.headers['User-Agent']=AGENT
        self.last=0
        self.rules={}
        self.timeout=CONFIG['fetch']['timeout_seconds']
        self.interval=CONFIG['fetch']['interval_seconds']
        self.retries=CONFIG['fetch']['retries']
        for folder in ['data/raw','data/processed','data/cache','report']:
            path(folder).mkdir(parents=True,exist_ok=True)
    # 先查本地响应缓存；未命中时检查访问规则、限速、重试并记录来源证据。
    def get(self,url,params=None,text_mode=False):
        full=url+('?' + urlencode(params) if params else '')
        # URL、查询参数及文本/JSON 模式共同决定缓存键，避免不同请求误用同一缓存。
        digest=hashlib.sha256((full+str(text_mode)).encode()).hexdigest()
        target=path('data','cache',digest+'.json')
        if target.exists(): return json.loads(target.read_text(encoding='utf-8'))
        origin='{0.scheme}://{0.netloc}'.format(urlsplit(url))
        if origin not in self.rules:
            response=self.session.get(origin+'/robots.txt',timeout=self.timeout)
            if response.status_code==404: text=''
            else:
                response.raise_for_status()
                text=response.text
            rules=RobotFileParser()
            rules.parse(text.splitlines())
            self.rules[origin]=rules
        if not self.rules[origin].can_fetch(AGENT,full): raise PermissionError('robots disallows '+url)
        for attempt in range(self.retries):
            # 网络请求至少间隔两秒；缓存命中直接返回，不再次发请求。
            time.sleep(max(0,self.interval-(time.monotonic()-self.last)))
            self.last=time.monotonic()
            try:
                response=self.session.get(url,params=params,timeout=self.timeout)
                response.raise_for_status()
                if text_mode:
                    response.encoding=response.apparent_encoding
                    body=response.text
                else: body=response.json()
                record={'source_url':response.url,'retrieved_at':datetime.now(timezone.utc).isoformat(),'body':body}
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
                return record
            except (requests.RequestException,ValueError):
                if attempt==self.retries-1: raise
                # 失败后指数退避；最多三次，请求持续失败时把异常交给调用方。
                time.sleep(2**attempt)

# 分页获取 2021—2025 年 IPO 原始记录，保留上游字段供后续统一转换。
def fetch_ipo(client):
    import pandas as pd
    records=[]
    for page in range(1,30):
        response=client.get('https://datacenter-web.eastmoney.com/api/data/v1/get',{
            'reportName':'RPTA_APP_IPOAPPLY','columns':'ALL','pageSize':500,'pageNumber':page,
            'sortColumns':'LISTING_DATE,SECURITY_CODE','sortTypes':'-1,-1',
            'filter':f"(LISTING_DATE>='{CONFIG['study']['start']}')(LISTING_DATE<='{CONFIG['study']['end']}')"})
        result=response['body'].get('result')
        if not result: raise ValueError('Missing data result: '+str(response['body'])[:300])
        for row in result['data']:
            row.update(source_url=response['source_url'],retrieved_at=response['retrieved_at'])
            records.append(row)
        if page>=int(result['pages']): break
    frame=pd.DataFrame(records)
    frame.to_csv(path('data','raw','ipo_eastmoney_original.csv'),index=False,encoding='utf-8-sig')
    print('IPO raw rows:',len(frame),'columns:',list(frame))

# 分别抓取定增与可转债清单；两种工具的发行日期字段不同。
def fetch_refinancing(client):
    import pandas as pd
    for name,sort,field in [('RPT_SEO_DETAIL','ISSUE_DATE','ISSUE_DATE'),('RPT_BOND_CB_LIST','PUBLIC_START_DATE','PUBLIC_START_DATE')]:
        rows=[]
        for page in range(1,30):
            response=client.get('https://datacenter-web.eastmoney.com/api/data/v1/get',{
                'reportName':name,'columns':'ALL','pageSize':500,'pageNumber':page,
                'sortColumns':sort,'sortTypes':'-1',
                'filter':f"({field}>='{CONFIG['study']['start']}')({field}<='{CONFIG['study']['end']}')"})
            result=response['body'].get('result')
            if not result: raise ValueError(str(response['body'])[:300])
            for row in result['data']:
                row.update(source_url=response['source_url'],retrieved_at=response['retrieved_at'])
                rows.append(row)
            if page>=int(result['pages']): break
        df=pd.DataFrame(rows)
        df.to_csv(path('data','raw',name+'.csv'),index=False,encoding='utf-8-sig')
        print(name,len(df),'columns',list(df))

# 每年选取两条目标板块记录，从新浪独立页面提取候选表；此步还不代表完成字段核验。
def fetch_crosscheck(client):
    import pandas as pd
    from io import StringIO
    df=pd.read_csv(path('data','raw','ipo_eastmoney_original.csv'),dtype={'SECURITY_CODE':str})
    df=df[df.SECURITY_CODE.str.startswith(tuple(CONFIG['study']['code_prefixes']))]
    samples=df.groupby(df.LISTING_DATE.str[:4],group_keys=False).head(2)
    records=[]
    for _,row in samples.iterrows():
        url=f'https://vip.stock.finance.sina.com.cn/corp/go.php/vISSUE_NewStock/stockid/{row.SECURITY_CODE}.phtml'
        try:
            response=client.get(url,text_mode=True)
            tables=pd.read_html(StringIO(response['body']))
            candidates=[t for t in tables if t.astype(str).apply(lambda s:s.str.contains('发行价格|发行价',regex=True)).any().any()]
            path('data','cache',f'sina_{row.SECURITY_CODE}.txt').write_text('\n\n'.join(t.to_string(index=False) for t in candidates),encoding='utf-8')
            records.append({'code':row.SECURITY_CODE,'source_a':row.source_url,'value_a':row.ISSUE_PRICE,'source_b':url,'status':'pending_parse','retrieved_at':response['retrieved_at']})
        except Exception as error:
            records.append({'code':row.SECURITY_CODE,'source_b':url,'status':'failed','error':str(error)})
    pd.DataFrame(records).to_csv(path('data','processed','cross_validation.csv'),index=False,encoding='utf-8-sig')
    print('Crosscheck candidates',len(records))

# 执行本模块的主流程；下方按数据处理和输出顺序逐步展开。
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('task',choices=['ipo','refinancing','crosscheck'])
    args=parser.parse_args()
    try: {'ipo':fetch_ipo,'refinancing':fetch_refinancing,'crosscheck':fetch_crosscheck}[args.task](PublicClient())
    except Exception as error:
        logger('fetch').exception('Public acquisition failed')
        path('report','acquisition_failure.txt').write_text(str(error),encoding='utf-8')
        raise

if __name__=='__main__': main()
