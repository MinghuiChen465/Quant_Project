"""第一周样本工具：统一再融资字段，并解析原有新浪发行价证据。"""
import numpy as np
import pandas as pd
from core import path
import yaml
CONFIG=yaml.safe_load(path('config.yaml').read_text(encoding='utf-8'))

# 统一定增与可转债字段，输出再融资样本及年度覆盖统计。
def normalize_refinancing():
    files=[path('data','raw','RPT_SEO_DETAIL.csv'),path('data','raw','RPT_BOND_CB_LIST.csv')]
    if not all(file.exists() for file in files): return
    seo=pd.read_csv(files[0],dtype={'SECURITY_CODE':str})
    seo=seo[seo.SECURITY_CODE.str.startswith(tuple(CONFIG['study']['code_prefixes'])) & seo.SEO_TYPE.eq(1)].copy()
    seo=seo.rename(columns={'SECURITY_CODE':'code','SECURITY_NAME_ABBR':'name','ISSUE_DATE':'issue_date',
                            'ISSUE_PRICE':'issue_price','TOTAL_RAISE_FUNDS':'proceeds','LEAD_UNDER_WRITER':'underwriter','ISSUE_OBJECT':'investor_type'})
    seo['instrument']='private_placement'
    cb=pd.read_csv(files[1],dtype={'CONVERT_STOCK_CODE':str,'SECURITY_CODE':str})
    cb=cb[cb.CONVERT_STOCK_CODE.str.startswith(tuple(CONFIG['study']['code_prefixes']))].copy()
    cb=cb.rename(columns={'CONVERT_STOCK_CODE':'code','SECURITY_CODE':'bond_code','SECURITY_SHORT_NAME':'name',
                          'PUBLIC_START_DATE':'issue_date','ISSUE_PRICE':'issue_price','INITIAL_TRANSFER_PRICE':'conversion_price',
                          'PARTY_NAME':'underwriter','ISSUE_OBJECT':'investor_type'})
    cb['proceeds']=cb.ACTUAL_ISSUE_SCALE*1e8
    cb['face_value']=cb.PAR_VALUE
    cb['instrument']='convertible_bond'
    cols=['code','name','bond_code','instrument','issue_date','issue_price','conversion_price','face_value',
          'proceeds','underwriter','investor_type','source_url','retrieved_at']
    combined=pd.concat([seo.reindex(columns=cols),cb.reindex(columns=cols)],ignore_index=True)
    combined['board']=np.where(combined.code.str.startswith('688'),'科创板','创业板')
    combined['issue_date']=pd.to_datetime(combined.issue_date).dt.strftime('%Y-%m-%d')
    combined['announcement_date']=None
    combined['reference_price_20d']=np.nan
    combined['discount']=np.nan
    combined['status']='issued_observed'
    combined.to_csv(path('data','processed','refinancing_sample.csv'),index=False,encoding='utf-8-sig')
    combined['year']=pd.to_datetime(combined.issue_date).dt.year
    combined.groupby(['year','board','instrument']).agg(n=('code','size'),proceeds=('proceeds','sum')).to_csv(path('report','refinancing_coverage.csv'),encoding='utf-8-sig')

# 从已缓存的新浪文本提取发行价，更新交叉核验结果。
def crosscheck():
    import re
    file=path('data','processed','cross_validation.csv')
    if not file.exists(): return
    original=pd.read_csv(file,dtype={'code':str})
    records=[]
    for _,row in original.iterrows():
        txt=path('data','cache',f'sina_{row.code}.txt')
        record=row.to_dict()
        record['field']='issue_price'
        record['tolerance']=CONFIG['crosscheck']['tolerance']
        if txt.exists():
            match=re.search(r'发行价\(元\)\s+([0-9.]+)',txt.read_text(encoding='utf-8'))
            if match:
                record['value_b']=float(match[1])
                record['status']='match' if abs(float(row.value_a)-float(match[1]))<=CONFIG['crosscheck']['tolerance'] else 'mismatch'
        records.append(record)
    pd.DataFrame(records).to_csv(file,index=False,encoding='utf-8-sig')
