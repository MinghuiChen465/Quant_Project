"""限速补取转债正股的腾讯未复权日行情，用于发行日收盘价双源核对。"""
import json

import pandas as pd

from core import path
from fetch_public import PublicClient


def main():
    samples = pd.read_csv(path('data/processed/refinancing_sample.csv'), dtype={'code': str})
    samples = samples.loc[samples.instrument.eq('convertible_bond')]
    client = PublicClient()
    client.timeout = (5, 15)
    folder = path('data/cache/refinancing_prices')
    folder.mkdir(parents=True, exist_ok=True)
    failures = []
    consecutive_failures = 0
    codes = sorted(samples.code.unique())
    for index, code in enumerate(codes, 1):
        target = folder / f'{code}.json'
        if target.exists():
            continue
        symbol = ('sh' if code.startswith('6') else 'sz') + code
        dates = pd.to_datetime(samples.loc[samples.code.eq(code), 'issue_date'])
        start = (dates.min() - pd.Timedelta(days=180)).strftime('%Y-%m-%d')
        end = dates.max().strftime('%Y-%m-%d')
        params = {'param': f'{symbol},day,{start},{end},2000,'}
        try:
            record = client.get('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get', params)
            data = record['body'].get('data', {}).get(symbol, {})
            if not data.get('day'):
                raise ValueError('Missing or mismatched daily prices')
            temporary = target.with_suffix('.tmp')
            temporary.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
            temporary.replace(target)
            consecutive_failures = 0
        except Exception as error:
            failures.append({'code': code, 'error': str(error)})
            consecutive_failures += 1
            print(f'FAILED {code}: {error}', flush=True)
            if isinstance(error, PermissionError):
                print('Stopped because source access was denied.', flush=True)
                break
            if consecutive_failures >= 5:
                print('Stopped after five consecutive source failures.', flush=True)
                break
        if index % 10 == 0:
            print(f'Prices {index}/{len(codes)}, errors={len(failures)}', flush=True)
    pd.DataFrame(failures, columns=['code', 'error']).to_csv(
        path('report/refinancing_price_fetch_errors.csv'), index=False, encoding='utf-8-sig')
    print(f'Cached securities: {len(list(folder.glob("*.json")))}/{len(codes)}', flush=True)


if __name__ == '__main__':
    main()
