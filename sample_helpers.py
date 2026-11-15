"""第一周样本工具：统一再融资字段，并解析原有新浪发行价证据。"""
import numpy as np
import pandas as pd
import json
import hashlib
import re
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
    seo['event_id'] = 'pp_' + seo.FINANCE_CODE.astype(str)
    seo['pricing_principle'] = seo.PRICE_PRINCIPLE
    cb=pd.read_csv(files[1],dtype={'CONVERT_STOCK_CODE':str,'SECURITY_CODE':str})
    cb=cb[cb.CONVERT_STOCK_CODE.str.startswith(tuple(CONFIG['study']['code_prefixes']))].copy()
    cb=cb.rename(columns={'CONVERT_STOCK_CODE':'code','SECURITY_CODE':'bond_code','SECURITY_SHORT_NAME':'name',
                          'PUBLIC_START_DATE':'issue_date','ISSUE_PRICE':'issue_price','INITIAL_TRANSFER_PRICE':'conversion_price',
                          'PARTY_NAME':'underwriter','ISSUE_OBJECT':'investor_type'})
    cb['proceeds']=cb.ACTUAL_ISSUE_SCALE*1e8
    cb['face_value']=cb.PAR_VALUE
    cb['instrument']='convertible_bond'
    cb['event_id'] = 'cb_' + cb.bond_code
    cols=['event_id','code','name','bond_code','instrument','issue_date','issue_price','conversion_price','face_value',
          'proceeds','underwriter','investor_type','pricing_principle','source_url','retrieved_at']
    combined=pd.concat([seo.reindex(columns=cols),cb.reindex(columns=cols)],ignore_index=True)
    combined['board']=np.where(combined.code.str.startswith('688'),'科创板','创业板')
    combined['issue_date']=pd.to_datetime(combined.issue_date).dt.strftime('%Y-%m-%d')
    combined['announcement_date']=None
    combined['reference_price_20d']=np.nan
    combined['discount']=np.nan
    combined = enrich_refinancing(combined)
    combined['status']='issued_observed'
    combined.to_csv(path('data','processed','refinancing_sample.csv'),index=False,encoding='utf-8-sig')
    combined['year']=pd.to_datetime(combined.issue_date).dt.year
    combined.groupby(['year','board','instrument']).agg(n=('code','size'),proceeds=('proceeds','sum')).to_csv(path('report','refinancing_coverage.csv'),encoding='utf-8-sig')


def enrich_refinancing(samples):
    """以发行事件匹配历史行情和公告索引，附口径、时间窗口及证据。"""
    if samples.event_id.duplicated().any():
        raise ValueError('Duplicate refinancing event ID')
    announcements_file = path('data/raw/refinancing_announcement_candidates.csv')
    announcements = pd.read_csv(announcements_file, dtype={'code': str}) if announcements_file.exists() else pd.DataFrame()
    records = []
    for row in samples.to_dict('records'):
        issue_date = pd.Timestamp(row['issue_date'])
        code = row['code']
        row.update({
            'reference_price_basis': '发行日前20个有成交交易日未复权成交额/成交量',
            'reference_price_status': 'missing_history',
            'reference_window_start': None, 'reference_window_end': None,
            'reference_observations': 0, 'reference_price_source_url': None,
            'reference_price_retrieved_at': None,
            'underlying_close_on_issue': np.nan, 'underlying_price_date': None,
            'underlying_price_source_url': None, 'underlying_price_retrieved_at': None,
            'underlying_price_crosscheck': 'not_checked',
            'underlying_crosscheck_source_url': None,
            'conversion_value_on_issue': np.nan,
            'announcement_type': None, 'announcement_source_url': None,
            'announcement_retrieved_at': None,
            'announcement_match_status': 'no_candidate',
            'announcement_candidate_count': 0,
            'pricing_reference_date': None, 'pricing_reference_date_source_url': None,
            'official_reference_price_20d': np.nan, 'official_reference_price_source_url': None,
            'pricing_date_reference_price_20d': np.nan,
            'pricing_date_reference_price_basis': '公告定价基准日前20个有成交交易日未复权成交额/成交量',
            'pricing_date_window_start': None, 'pricing_date_window_end': None,
            'pricing_date_price_source_url': None,
            'pricing_date_price_retrieved_at': None,
            'announcement_evidence_page': None,
            'issue_date_evidence_status': 'not_checked',
        })
        history = None
        turnover_file = path(f'data/cache/refinancing_turnover/{code}_{issue_date.year}.json')
        if turnover_file.exists():
            evidence = json.loads(turnover_file.read_text(encoding='utf-8'))
            history = pd.DataFrame(evidence['body'][0]['hq'])
            history['date'] = pd.to_datetime(history[0])
            history['close'] = pd.to_numeric(history[2], errors='coerce')
            history['volume'] = pd.to_numeric(history[7], errors='coerce') * 100
            history['amount'] = pd.to_numeric(history[8], errors='coerce') * 10000
            history = history.sort_values('date').drop_duplicates('date')
            window = history.loc[(history.date < issue_date) & (history.volume > 0)].tail(20)
            row['reference_observations'] = len(window)
            row['reference_price_status'] = 'insufficient_history'
            if len(window) == 20 and window.amount.notna().all():
                price = window.amount.sum() / window.volume.sum()
                # 单位核验：成交均价必须位于窗口最低价与最高价之间。
                low = pd.to_numeric(window[5], errors='coerce').min()
                high = pd.to_numeric(window[6], errors='coerce').max()
                if not low <= price <= high:
                    raise ValueError(f'{code}: turnover units inconsistent with prices')
                row.update({
                    'reference_price_20d': price,
                    'reference_window_start': window.date.min().strftime('%Y-%m-%d'),
                    'reference_window_end': window.date.max().strftime('%Y-%m-%d'),
                    'reference_price_status': 'computed_unadjusted_vwap',
                    'reference_price_source_url': evidence['source_url'],
                    'reference_price_retrieved_at': evidence['retrieved_at'],
                })
            same_day = history.loc[(history.date == issue_date) & (history.volume > 0)]
            if row['instrument'] == 'convertible_bond' and len(same_day) == 1:
                row.update({
                    'underlying_close_on_issue': float(same_day.iloc[0]['close']),
                    'underlying_price_date': row['issue_date'],
                    'underlying_price_source_url': evidence['source_url'],
                    'underlying_price_retrieved_at': evidence['retrieved_at'],
                })
        tencent_file = path(f'data/cache/refinancing_prices/{code}.json')
        if row['instrument'] == 'convertible_bond' and tencent_file.exists():
            evidence = json.loads(tencent_file.read_text(encoding='utf-8'))
            symbol = ('sh' if code.startswith('6') else 'sz') + code
            day = [item for item in evidence['body']['data'][symbol]['day'] if item[0] == row['issue_date']]
            if len(day) == 1 and float(day[0][5]) > 0:
                close = float(day[0][2])
                if pd.notna(row['underlying_close_on_issue']):
                    row['underlying_crosscheck_source_url'] = evidence['source_url']
                    row['underlying_price_crosscheck'] = 'match' if abs(close - row['underlying_close_on_issue']) <= 0.011 else 'mismatch'
                    if row['underlying_price_crosscheck'] == 'mismatch':
                        raise ValueError(f'{code}: independent close prices disagree')
                else:
                    row['underlying_close_on_issue'] = close
                    row['underlying_price_date'] = row['issue_date']
                    row['underlying_price_source_url'] = evidence['source_url']
                    row['underlying_price_retrieved_at'] = evidence['retrieved_at']
        if row['instrument'] == 'convertible_bond' and pd.notna(row['underlying_close_on_issue']) and row['conversion_price'] > 0:
            row['conversion_value_on_issue'] = row['face_value'] * row['underlying_close_on_issue'] / row['conversion_price']
        if not announcements.empty:
            candidates = announcements.loc[announcements.code.eq(code)].copy()
            dates = pd.to_datetime(candidates.announcement_date)
            if row['instrument'] == 'private_placement':
                title_match = candidates.title.str.contains('发行情况报告', regex=False) & ~candidates.title.str.contains('首次公开|可转换|可转债', regex=True)
                date_match = dates.between(issue_date - pd.Timedelta(days=15), issue_date + pd.Timedelta(days=100))
                full_report = title_match & ~candidates.title.str.contains('提示|核查|法律意见|保荐', regex=True)
                if (full_report & date_match).any():
                    title_match = full_report
                announcement_type = '发行情况报告书披露日'
            else:
                titles = candidates.title.str.replace(r'\s+', '', regex=True)
                title_match = titles.str.contains(r'(?:可转换公司债券|可转债)发行公告(?:[（(].*[)）])?$', regex=True)
                date_match = dates.between(issue_date - pd.Timedelta(days=30), issue_date)
                original = title_match & ~titles.str.contains('更正|修订', regex=True)
                if (original & date_match).any():
                    title_match = original
                announcement_type = '转债发行公告披露日'
            candidates = candidates.loc[title_match & date_match].drop_duplicates('announcement_source_url')
            row['announcement_candidate_count'] = len(candidates)
            row['announcement_match_status'] = 'ambiguous' if len(candidates) > 1 else 'no_candidate'
            if len(candidates) == 1:
                candidate = candidates.iloc[0]
                row['announcement_candidate_date'] = candidate.announcement_date
                row['announcement_candidate_source_url'] = candidate.announcement_source_url
                row['announcement_candidate_title'] = candidate.title
                row['announcement_match_status'] = 'unique_candidate_pending_document_check'
                document_file = path('data/cache/refinancing_documents',
                    hashlib.sha256(candidate.announcement_source_url.encode()).hexdigest() + '.json')
                if document_file.exists():
                    document = json.loads(document_file.read_text(encoding='utf-8'))
                    pages = [re.sub(r'\s+', '', page) for page in document['pages']]
                    text = '\n'.join(pages)
                    dates_found = {f'{int(y):04d}-{int(m):02d}-{int(d):02d}'
                        for y, m, d in re.findall(r'(\d{4})年(\d{1,2})月(\d{1,2})日', text)}
                    dates_found.update(f'{int(y):04d}-{int(m):02d}-{int(d):02d}'
                        for y, m, d in re.findall(r'(\d{4})[-./](\d{1,2})[-./](\d{1,2})', text))
                    prices_found = [float(value.replace(',', ''))
                        for value in re.findall(r'([\d,]+(?:\.\d+)?)元[/／]股', text)]
                    prices_found.extend(float(value) for value in re.findall(
                        r'(?:发行价格|发行价)(?:为|确定为)?(?:人民币)?[:：]?([0-9]+(?:\.[0-9]+)?)元', text))
                    price_matches = any(abs(price - row['issue_price']) < 0.0001 for price in prices_found)
                    if row['instrument'] == 'convertible_bond':
                        price_matches = '100元' in text or bool(re.search(r'100\.0+元', text))
                    money_values = [(float(value.replace(',', '')), unit) for value, unit in
                        re.findall(r'(\d[\d,]*(?:\.\d+)?)(万元|亿元|元)', text)]
                    multipliers = {'元': 1, '万元': 10000, '亿元': 100000000}
                    proceeds_matches = any(abs(value * multipliers[unit] - row['proceeds']) <= max(1, row['proceeds'] * 0.000001)
                        for value, unit in money_values)
                    date_matches = row['issue_date'] in dates_found
                    # 巨潮索引已按证券代码匹配发行人，部分报告正文仅印公司名称。
                    if price_matches and (date_matches or proceeds_matches):
                        row['announcement_date'] = candidate.announcement_date
                        row['announcement_type'] = announcement_type
                        row['announcement_source_url'] = candidate.announcement_source_url
                        row['announcement_retrieved_at'] = document['retrieved_at']
                        row['announcement_match_status'] = 'issuer_date_price_matched' if date_matches else 'issuer_price_proceeds_matched_date_pending'
                        row['issue_date_evidence_status'] = 'present_in_document' if date_matches else 'not_found_proceeds_matched'
                        row['announcement_evidence_page'] = next((i + 1 for i, page in enumerate(pages)
                            if re.search(rf'{issue_date.year}年0?{issue_date.month}月0?{issue_date.day}日', page)), None)
                        date_match = (
                            re.search(r'定价基准日[^。]{0,60}?(\d{4})年(\d{1,2})月(\d{1,2})日', text)
                            if row['instrument'] == 'private_placement' else None
                        )
                        if date_match:
                            year, month, day = map(int, date_match.groups())
                            row['pricing_reference_date'] = f'{year:04d}-{month:02d}-{day:02d}'
                            row['pricing_reference_date_source_url'] = candidate.announcement_source_url
                        price_match = (
                            re.search(r'(?:前20|前二十)个交易日(?:公司)?股票交易均价(?:为|是|：|:)(?:人民币)?([0-9]+\.[0-9]+)元', text)
                            if row['instrument'] == 'private_placement' else None
                        )
                        if price_match:
                            row['official_reference_price_20d'] = float(price_match[1])
                            row['official_reference_price_source_url'] = candidate.announcement_source_url
                    else:
                        row['announcement_match_status'] = 'document_event_not_confirmed'
        pricing_history = history
        pricing_source_url = row['reference_price_source_url']
        pricing_retrieved_at = row['reference_price_retrieved_at']
        pricing_file = path('data/cache/refinancing_pricing_windows', row['event_id'] + '.json')
        if pricing_file.exists():
            pricing_record = json.loads(pricing_file.read_text(encoding='utf-8'))
            pricing_history = pd.DataFrame(pricing_record['body'][0]['hq'])
            pricing_history['date'] = pd.to_datetime(pricing_history[0])
            pricing_history['volume'] = pd.to_numeric(pricing_history[7], errors='coerce') * 100
            pricing_history['amount'] = pd.to_numeric(pricing_history[8], errors='coerce') * 10000
            pricing_history = pricing_history.sort_values('date').drop_duplicates('date')
            pricing_source_url = pricing_record['source_url']
            pricing_retrieved_at = pricing_record['retrieved_at']
        if pricing_history is not None and row['pricing_reference_date']:
            cutoff = pd.Timestamp(row['pricing_reference_date'])
            pricing_window = pricing_history.loc[(pricing_history.date < cutoff) & (pricing_history.volume > 0)].tail(20)
            if len(pricing_window) == 20 and pricing_window.amount.notna().all():
                row['pricing_date_reference_price_20d'] = pricing_window.amount.sum() / pricing_window.volume.sum()
                row['pricing_date_window_start'] = pricing_window.date.min().strftime('%Y-%m-%d')
                row['pricing_date_window_end'] = pricing_window.date.max().strftime('%Y-%m-%d')
                row['pricing_date_price_source_url'] = pricing_source_url
                row['pricing_date_price_retrieved_at'] = pricing_retrieved_at
        records.append(row)
    result = pd.DataFrame(records)
    issues_file = path('data/raw/refinancing_date_issues.csv')
    if issues_file.exists():
        issues = pd.read_csv(issues_file, dtype=str)
        if issues.event_id.duplicated().any() or not issues.event_id.isin(result.event_id).all():
            raise ValueError('Invalid refinancing date issue mapping')
        result = result.merge(issues, on='event_id', how='left', validate='one_to_one')
    else:
        result['date_review_note'] = None
        result['date_review_source_url'] = None
    result['discount_basis'] = '1-发行价/发行日前20个有成交交易日未复权VWAP'
    eligible = result.instrument.eq('private_placement') & result.reference_price_20d.gt(0) & result.date_review_note.isna()
    result.loc[eligible, 'discount'] = 1 - result.loc[eligible, 'issue_price'] / result.loc[eligible, 'reference_price_20d']
    result['reference_price_missing'] = result.instrument.eq('private_placement') & result.reference_price_20d.isna()
    result['underlying_price_missing'] = result.instrument.eq('convertible_bond') & result.underlying_close_on_issue.isna()
    result['announcement_missing'] = result.announcement_date.isna()
    result['pricing_date_price_missing'] = result.instrument.eq('private_placement') & result.pricing_date_reference_price_20d.isna()
    pending = result.loc[result.reference_price_missing | result.underlying_price_missing | result.announcement_missing | result.pricing_date_price_missing | result.date_review_note.notna()]
    pending.to_csv(path('report/refinancing_enrichment_pending.csv'), index=False, encoding='utf-8-sig')
    result.to_csv(path('report/refinancing_enrichment_audit.csv'), index=False, encoding='utf-8-sig')
    return result

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
