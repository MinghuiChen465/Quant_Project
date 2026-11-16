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
    # 明确采用上游网上发行日期，独立于申购日字段保留，并标注核验层级。
    df['online_issue_date'] = pd.to_datetime(raw.loc[keep, 'ONLINE_ISSUE_DATE'], errors='coerce').dt.strftime('%Y-%m-%d')
    df['issue_date'] = None
    df['issue_date_basis'] = None
    df['issue_date_source_url'] = None
    df['review_status'] = None
    df['review_status_date'] = None
    df['review_status_source_url'] = None
    df['review_document_no'] = None
    evidence = pd.read_csv(path('data/raw/ipo_official_evidence.csv'), dtype=str)
    if evidence.code.duplicated().any():
        raise ValueError('Duplicate IPO evidence code')
    if not evidence.code.isin(df.code).all():
        raise ValueError('IPO evidence contains unknown code')
    fields = ['issue_date', 'issue_date_basis', 'issue_date_source_url', 'review_status',
              'review_status_date', 'review_status_source_url', 'review_document_no',
              'review_status_as_of', 'review_evidence_type', 'official_evidence_retrieved_at',
              'official_evidence_sha256', 'issue_date_evidence_page', 'review_status_evidence_page',
              'issue_date_evidence_quote', 'review_status_evidence_quote',
              'issue_date_evidence_sha256', 'issue_date_evidence_retrieved_at', 'issue_date_document_title',
              'review_status_evidence_sha256', 'review_status_evidence_retrieved_at', 'review_status_document_title']
    for field in fields:
        if field not in evidence:
            evidence[field] = None
        df[field] = df.code.map(evidence.set_index('code')[field])
    original_decisions = df.review_status_source_url.fillna('').str.startswith('https://www.csrc.gov.cn/')
    df.loc[original_decisions, 'review_evidence_type'] = 'csrc_registration_decision'
    separate_sources = df.issue_date_source_url.fillna('').ne(df.review_status_source_url.fillna(''))
    df.loc[separate_sources, ['official_evidence_sha256', 'official_evidence_retrieved_at']] = None
    cols = list(mapping.values()) + ['board', 'online_issue_date'] + fields + ['source_url', 'retrieved_at']
    df = df[cols].sort_values(['list_date', 'code'])
    df.to_csv(path('data/processed/ipo.csv'), index=False, encoding='utf-8-sig')
    pending = df.loc[df.issue_date.isna() | df.review_status.isna(),
                     ['code', 'name', 'board', 'list_date', 'online_issue_date']].copy()
    pending['issue_date_pending'] = df.loc[pending.index, 'issue_date'].isna()
    pending['review_status_pending'] = df.loc[pending.index, 'review_status'].isna()
    pending.to_csv(path('report/ipo_official_pending.csv'), index=False, encoding='utf-8-sig')
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
    priced = refinancing.reference_price_20d.notna()
    if not refinancing.loc[priced, 'reference_price_20d'].gt(0).all():
        raise ValueError('Nonpositive refinancing reference price')
    if not refinancing.loc[priced, 'reference_observations'].eq(20).all():
        raise ValueError('Incomplete refinancing reference window')
    if not (pd.to_datetime(refinancing.loc[priced, 'reference_window_end']) <
            pd.to_datetime(refinancing.loc[priced, 'issue_date'])).all():
        raise ValueError('Refinancing reference includes issue date or future data')
    underlying = refinancing.underlying_close_on_issue.notna()
    if not refinancing.loc[underlying, 'underlying_price_date'].eq(refinancing.loc[underlying, 'issue_date']).all():
        raise ValueError('Underlying price date differs from issue date')
    for value, source in [('reference_price_20d', 'reference_price_source_url'),
                          ('underlying_close_on_issue', 'underlying_price_source_url'),
                          ('announcement_date', 'announcement_source_url')]:
        if refinancing.loc[refinancing[value].notna(), source].isna().any():
            raise ValueError(f'Refinancing {value}: missing evidence source')
    for field, source in [('issue_date', 'issue_date_source_url'), ('review_status', 'review_status_source_url')]:
        present = ipo[field].notna()
        if ipo.loc[present, source].isna().any():
            raise ValueError(f'IPO {field}: missing independent evidence')
    issued = ipo.issue_date.notna()
    if (pd.to_datetime(ipo.loc[issued, 'issue_date']) > pd.to_datetime(ipo.loc[issued, 'list_date'])).any():
        raise ValueError('IPO issue date follows listing date')
    dated = ipo.review_status_date.notna() & ipo.issue_date.notna()
    if (pd.to_datetime(ipo.loc[dated, 'review_status_date']) > pd.to_datetime(ipo.loc[dated, 'issue_date'])).any():
        raise ValueError('IPO registration decision follows issue date')
    observed = ipo.review_status_as_of.notna() & ipo.review_status_date.notna()
    if (pd.to_datetime(ipo.loc[observed, 'review_status_date']) > pd.to_datetime(ipo.loc[observed, 'review_status_as_of'])).any():
        raise ValueError('IPO decision date follows evidence disclosure')
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
    for folder in ['refinancing_prices', 'refinancing_turnover', 'refinancing_documents', 'refinancing_pricing_windows', 'ipo_documents']:
        for file in sorted(path('data/cache', folder).glob('*.json')):
            records.append(manifest(file, [], ''))
    write_csv(path('data/processed/data_manifest.csv'), records, ['file', 'rows', 'min_date', 'max_date', 'sha256'])
    summary = {
        'study_start': config['study']['start'], 'study_end': config['study']['end'],
        'ipo': len(ipo), 'private_placement': int(refinancing.instrument.eq('private_placement').sum()),
        'ipo_online_issue_dates': int(ipo.online_issue_date.notna().sum()),
        'ipo_official_issue_dates': int(ipo.issue_date.notna().sum()),
        'ipo_official_review_statuses': int(ipo.review_status.notna().sum()),
        'ipo_csrc_original_decisions': int(ipo.review_evidence_type.eq('csrc_registration_decision').sum()),
        'ipo_announcement_registration_evidence': int(ipo.review_evidence_type.isin(['official_issue_announcement', 'official_ipo_announcement']).sum()),
        'ipo_explicit_registration_dates': int(ipo.review_status_date.notna().sum()),
        'refinancing_reference_prices': int(refinancing.reference_price_20d.notna().sum()),
        'refinancing_document_matched_announcements': int(refinancing.announcement_date.notna().sum()),
        'convertible_underlying_issue_closes': int(refinancing.underlying_close_on_issue.notna().sum()),
        'private_placement_reference_prices': int((refinancing.instrument.eq('private_placement') & refinancing.reference_price_20d.notna()).sum()),
        'private_placement_pricing_date_vwaps': int((refinancing.instrument.eq('private_placement') & refinancing.pricing_date_reference_price_20d.notna()).sum()),
        'private_placement_announcements': int((refinancing.instrument.eq('private_placement') & refinancing.announcement_date.notna()).sum()),
        'convertible_announcements': int((refinancing.instrument.eq('convertible_bond') & refinancing.announcement_date.notna()).sum()),
        'convertible_bond': int(refinancing.instrument.eq('convertible_bond').sum()),
        'crosscheck_candidates': len(checks), 'crosscheck_matches': int(checks.status.eq('match').sum()),
        'crosscheck_scope': 'IPO发行价抽样；新增IPO公告证据与再融资公告为自动解析，待人工抽样复核',
        'validation': 'passed', 'full_week1_acceptance': False,
    }
    path('report/run_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    logger('week1').info('Week1 samples rebuilt and validated: %s', summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
