"""按发行年份补取搜狐未复权日成交额与成交量，用于20日加权均价。"""
import json
import argparse

import pandas as pd

from core import path
from fetch_public import PublicClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lookback-days', type=int, default=90)
    parser.add_argument('--pricing-dates', action='store_true', help='补取公告定价基准日前的历史窗口')
    args = parser.parse_args()
    if args.lookback_days < 1:
        parser.error('lookback-days must be positive')
    samples = pd.read_csv(path('data/processed/refinancing_sample.csv'), dtype={'code': str})
    samples['year'] = pd.to_datetime(samples.issue_date).dt.year
    folder = path('data/cache/refinancing_turnover')
    if args.pricing_dates:
        folder = path('data/cache/refinancing_pricing_windows')
    folder.mkdir(parents=True, exist_ok=True)
    client = PublicClient()
    client.timeout = (5, 15)
    groups = [(code, f'{code}_{year}', pd.to_datetime(events.issue_date))
              for (code, year), events in samples.groupby(['code', 'year'])]
    if args.pricing_dates:
        pending = samples.loc[samples.pricing_reference_date.notna() & samples.pricing_date_reference_price_20d.isna()]
        groups = [(row.code, row.event_id, pd.to_datetime(pd.Series([row.pricing_reference_date])))
                  for row in pending.itertuples()]
    failures = []
    consecutive_failures = 0
    for index, (code, window, dates) in enumerate(groups, 1):
        target = folder / f'{window}.json'
        if target.exists():
            continue
        params = {
            'code': 'cn_' + code,
            'start': (dates.min() - pd.Timedelta(days=args.lookback_days)).strftime('%Y%m%d'),
            'end': dates.max().strftime('%Y%m%d'),
            'stat': 1, 'order': 'A', 'period': 'd', 'rt': 'json',
        }
        try:
            record = client.get('https://q.stock.sohu.com/hisHq', params)
            body = record['body']
            if not isinstance(body, list) or not body or body[0].get('status') != 0 or not body[0].get('hq'):
                raise ValueError('Missing daily turnover data')
            temporary = target.with_suffix('.tmp')
            temporary.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
            temporary.replace(target)
            consecutive_failures = 0
        except Exception as error:
            failures.append({'code': code, 'window': window, 'error': str(error)})
            consecutive_failures += 1
            print(f'FAILED {code}/{window}: {error}', flush=True)
            if consecutive_failures >= 5:
                print('Stopped after five consecutive source failures.', flush=True)
                break
        if index % 10 == 0:
            print(f'Turnover {index}/{len(groups)}, errors={len(failures)}', flush=True)
    suffix = 'pricing' if args.pricing_dates else 'turnover'
    pd.DataFrame(failures, columns=['code', 'window', 'error']).to_csv(
        path(f'report/refinancing_{suffix}_fetch_errors.csv'), index=False, encoding='utf-8-sig')
    print(f'Cached windows: {len(list(folder.glob("*.json")))}/{len(groups)}', flush=True)


if __name__ == '__main__':
    main()
