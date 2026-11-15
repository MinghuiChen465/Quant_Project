"""分页查询巨潮发行报告及转债发行公告，按明确事件证据筛选候选。"""
import re
import argparse

import pandas as pd

from core import path
from fetch_public import PublicClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--precise', action='store_true', help='用证券机构ID精确重查无候选事件')
    args = parser.parse_args()
    client = PublicClient()
    client.timeout = (5, 15)
    samples = pd.read_csv(path('data/processed/refinancing_sample.csv'), dtype={'code': str})
    codes = set(samples.code)
    output = path('data/raw/refinancing_announcement_candidates.csv')
    records = pd.read_csv(output, dtype=str).to_dict('records') if output.exists() else []
    queries = [('发行情况报告', f'{year}-01-01~{year}-12-31', '') for year in range(2021, 2027)]
    for row in samples.loc[samples.instrument.eq('convertible_bond')].itertuples():
        day = pd.Timestamp(row.issue_date)
        queries.append((row.code, f'{day - pd.Timedelta(days=30):%Y-%m-%d}~{day:%Y-%m-%d}', ''))
    if args.precise:
        stock_record = client.get('https://www.cninfo.com.cn/new/data/szse_stock.json')
        identifiers = {item['code']: item['orgId'] for item in stock_record['body']['stockList']}
        queries = []
        for row in samples.loc[samples.announcement_candidate_count.eq(0)].itertuples():
            if row.code not in identifiers:
                continue
            day = pd.Timestamp(row.issue_date)
            stock = f'{row.code},{identifiers[row.code]}'
            if row.instrument == 'convertible_bond':
                queries.append(('', f'{day - pd.Timedelta(days=30):%Y-%m-%d}~{day:%Y-%m-%d}', stock))
            else:
                queries.append(('发行情况报告', f'{day - pd.Timedelta(days=15):%Y-%m-%d}~{day + pd.Timedelta(days=100):%Y-%m-%d}', stock))
    for keyword, date_range, stock in queries:
        page = 1
        while True:
            response = client.get('https://www.cninfo.com.cn/new/hisAnnouncement/query', {
                'pageNum': page, 'pageSize': 30, 'column': 'szse', 'tabName': 'fulltext',
                'searchkey': keyword, 'seDate': date_range,
                'isHLtitle': 'true', 'sortName': 'time', 'sortType': 'desc',
                'stock': stock,
            }, method='POST')
            body = response['body']
            for item in body.get('announcements') or []:
                if item['secCode'] not in codes:
                    continue
                records.append({
                    'code': item['secCode'],
                    'title': re.sub('<[^>]+>', '', item['announcementTitle']),
                    'announcement_date': item['adjunctUrl'].split('/')[1],
                    'announcement_source_url': 'https://static.cninfo.com.cn/' + item['adjunctUrl'],
                    'retrieved_at': response['retrieved_at'],
                })
            temporary = output.with_suffix('.tmp')
            pd.DataFrame(records, columns=['code', 'title', 'announcement_date',
                'announcement_source_url', 'retrieved_at']).drop_duplicates('announcement_source_url').to_csv(
                    temporary, index=False, encoding='utf-8-sig')
            temporary.replace(output)
            print(f'{keyword}: page {page}, total={body.get("totalAnnouncement")}, matched={len(records)}', flush=True)
            if page * 30 >= body.get('totalAnnouncement', 0):
                break
            page += 1


if __name__ == '__main__':
    main()
