"""第一周独立入口：从随包真实原始数据构建样本清单、核验表与版本清单。"""
import argparse
import json

import numpy as np
import pandas as pd
import yaml

from core import path, logger, manifest, write_csv
from sample_helpers import normalize_refinancing, crosscheck


def build_ipo(config):
    """只建立发行样本清单，不计算第三周的收益标签或预测模型。"""
    raw = pd.read_csv(path('data/raw/ipo_eastmoney_original.csv'), dtype={'SECURITY_CODE': str})
    keep = raw.SECURITY_CODE.str.startswith(tuple(config['study']['code_prefixes']))
    df = raw.loc[keep].copy()
    mapping = {
        'SECURITY_CODE': 'code', 'SECURITY_NAME': 'name',
        'APPLY_DATE': 'subscription_date', 'LISTING_DATE': 'list_date',
        'ISSUE_PRICE': 'issue_price', 'AFTER_ISSUE_PE': 'issue_pe',
        'TOTAL_RAISE_FUNDS': 'proceeds', 'UNDERWRITER_ORG': 'underwriter',
        'ISSUE_STATE': 'status', 'INDUSTRY_NAME': 'industry',
    }
    df = df.rename(columns=mapping)
    df['board'] = np.where(df.code.str.startswith('688'), '科创板', '创业板')
    for col in ['subscription_date', 'list_date']:
        df[col] = pd.to_datetime(df[col], errors='coerce').dt.strftime('%Y-%m-%d')
    for col in ['issue_price', 'issue_pe', 'proceeds']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    # IPO 上游募资额单位为亿元；定增同名原始字段已经是元，不能一概乘倍数。
    df['proceeds'] *= 1e8
    df['issue_date'] = None  # 申购日不是已核实的法律发行日。
    df['review_status'] = None  # 已上市样本不能推断全部申请项目的审核状态。
    cols = list(mapping.values()) + ['board', 'issue_date', 'review_status', 'source_url', 'retrieved_at']
    df = df[cols].sort_values(['list_date', 'code'])
    df.to_csv(path('data/processed/ipo.csv'), index=False, encoding='utf-8-sig')
    return df


def validate_samples(ipo, refinancing, checks, config):
    """用真实数据检查字段、来源、日期、板块、单位和独立核验；不验证后续周研究。"""
    for name, frame, date_col in [('ipo', ipo, 'list_date'), ('refinancing', refinancing, 'issue_date')]:
        if frame.empty:
            raise ValueError(f'{name}: empty sample')
        if not frame.code.str.fullmatch(r'\d{6}').all():
            raise ValueError(f'{name}: invalid security code')
        if not frame.board.isin(config['study']['boards']).all():
            raise ValueError(f'{name}: unexpected board')
        dates = pd.to_datetime(frame[date_col], errors='coerce')
        if dates.isna().any() or not dates.between(pd.Timestamp(config['study']['start']), pd.Timestamp(config['study']['end'])).all():
            raise ValueError(f'{name}: invalid sample date')
        for field in ['source_url', 'retrieved_at']:
            if frame[field].isna().any():
                raise ValueError(f'{name}: missing {field}')
    if ipo.code.duplicated().any():
        raise ValueError('Duplicate IPO code')
    # 重新计算核验结果，不因历史 CSV 标记 match 就直接相信它。
    if not checks.empty:
        a = pd.to_numeric(checks.value_a, errors='coerce')
        b = pd.to_numeric(checks.value_b, errors='coerce')
        expected = (a-b).abs() <= config['crosscheck']['tolerance']
        if not expected.eq(checks.status.eq('match')).all():
            raise ValueError('Crosscheck status inconsistent with prices')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh', action='store_true', help='联网刷新 IPO、再融资和新浪候选证据；默认只使用随包真实数据')
    args = parser.parse_args()
    config = yaml.safe_load(path('config.yaml').read_text(encoding='utf-8'))
    for folder in ['data/raw', 'data/processed', 'data/cache', 'report']:
        path(folder).mkdir(parents=True, exist_ok=True)
    if args.refresh:
        from fetch_public import PublicClient, fetch_ipo, fetch_refinancing, fetch_crosscheck
        client = PublicClient()
        fetch_ipo(client)
        fetch_refinancing(client)
        fetch_crosscheck(client)
    ipo = build_ipo(config)
    normalize_refinancing()
    crosscheck()
    refinancing = pd.read_csv(path('data/processed/refinancing_sample.csv'), dtype={'code': str, 'bond_code': str})
    checks = pd.read_csv(path('data/processed/cross_validation.csv'), dtype={'code': str})
    validate_samples(ipo, refinancing, checks, config)
    # 所有原始、处理表及独立来源文本证据都生成摘要，便于提交时追踪版本。
    records = []
    for folder in ['data/raw', 'data/processed']:
        for file in sorted(path(folder).glob('*.csv')):
            if 'manifest' in file.name:
                continue
            frame = pd.read_csv(file, dtype=str).fillna('')
            date_col = next((c for c in ['list_date', 'issue_date', 'LISTING_DATE', 'ISSUE_DATE', 'PUBLIC_START_DATE', 'retrieved_at'] if c in frame), '')
            records.append(manifest(file, frame.to_dict('records'), date_col))
    for file in sorted(path('data/cache').glob('sina_*.txt')):
        records.append(manifest(file, [], ''))
    write_csv(path('data/processed/data_manifest.csv'), records, ['file', 'rows', 'min_date', 'max_date', 'sha256'])
    summary = {
        'study_start': config['study']['start'], 'study_end': config['study']['end'],
        'ipo': len(ipo), 'private_placement': int(refinancing.instrument.eq('private_placement').sum()),
        'convertible_bond': int(refinancing.instrument.eq('convertible_bond').sum()),
        'crosscheck_candidates': len(checks), 'crosscheck_matches': int(checks.status.eq('match').sum()),
        'crosscheck_scope': 'IPO发行价抽样；未完成再融资独立来源核验',
        'validation': 'passed', 'full_week1_acceptance': False,
    }
    path('report/run_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    logger('week1').info('Week1 samples rebuilt and validated: %s', summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
