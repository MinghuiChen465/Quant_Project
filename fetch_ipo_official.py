"""批量定位IPO官方发行公告，提取有明确正文依据的发行T日与注册结论。"""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
from io import BytesIO
import json
import re
import unicodedata

import pandas as pd
from pypdf import PdfReader

from core import path
from fetch_public import PublicClient


def save_csv(frame, target):
    temporary = target.with_suffix('.tmp')
    frame.to_csv(temporary, index=False, encoding='utf-8-sig')
    temporary.replace(target)


def approval_evidence(text):
    for match in re.finditer(r'证监许可[^0-9]{0,4}(\d{4})[^0-9]{1,5}(\d+)号', text):
        quote = text[max(0, match.start() - 180):match.end() + 180]
        if re.search(r'不(?:予以?|同意)[^。；;]{0,20}注册', quote):
            continue
        if re.search(r'同意[^。；;]{0,60}注册', quote):
            return match, '同意注册', quote
        if '予以注册' in quote:
            return match, '予以注册', quote
        if '准予注册' in quote:
            return match, '准予注册', quote
        if '注册通过' in quote:
            return match, '注册通过', quote
        if '核准' in quote and '首次公开发行' in quote:
            return match, '核准发行', quote
    return None


def recover_cached_index(samples):
    """从已取得的官方索引响应提取较短公告，复用查询结果。"""
    lookup = samples.set_index('code').to_dict('index')
    target = path('data/raw/ipo_announcement_candidates.csv')
    records = pd.read_csv(target, dtype=str).to_dict('records') if target.exists() else []
    for file in path('data/cache').glob('*.json'):
        cached = json.loads(file.read_text(encoding='utf-8'))
        if not cached.get('source_url', '').endswith('/new/hisAnnouncement/query'):
            continue
        for item in cached.get('body', {}).get('announcements') or []:
            code = item['secCode']
            if code not in lookup:
                continue
            title = re.sub(r'<[^>]+>|\s+', '', item['announcementTitle'])
            if re.search('取消|作废|撤回', title):
                continue
            if '首次公开发行' not in title or not re.search(r'发行公告|发行结果公告|网上路演公告|中签率公告|提示性?公告|投资风险特别公告', title):
                continue
            date = item['adjunctUrl'].split('/')[1]
            day = pd.Timestamp(lookup[code]['online_issue_date'])
            if not day - pd.Timedelta(days=14) <= pd.Timestamp(date) <= pd.Timestamp(lookup[code]['list_date']):
                continue
            records.append({
                'code': code, 'title': title, 'announcement_date': date,
                'source_url': 'https://static.cninfo.com.cn/' + item['adjunctUrl'],
                'index_retrieved_at': cached['retrieved_at'],
                'size_kb': item.get('adjunctSize', 100000),
            })
    if not records:
        print('No cached IPO announcement index is available.', flush=True)
        return
    frame = pd.DataFrame(records).drop_duplicates('source_url')
    save_csv(frame, target)
    print(f'Cached index recovered: {len(frame)} documents, {frame.code.nunique()} issuers', flush=True)


def find_announcements(client, samples):
    target = path('data/raw/ipo_announcement_candidates.csv')
    records = pd.read_csv(target, dtype=str).to_dict('records') if target.exists() else []
    stock_data = client.get('https://www.cninfo.com.cn/new/data/szse_stock.json')
    identifiers = {row['code']: row['orgId'] for row in stock_data['body']['stockList']}
    samples = samples.sort_values('online_issue_date')
    for start in range(0, len(samples), 20):
        batch = samples.iloc[start:start + 20]
        selected = [f'{row.code},{identifiers[row.code]}' for row in batch.itertuples() if row.code in identifiers]
        if not selected:
            continue
        dates = pd.to_datetime(batch.online_issue_date)
        page = 1
        seen_pages = set()
        while True:
            response = client.get('https://www.cninfo.com.cn/new/hisAnnouncement/query', {
                'pageNum': page, 'pageSize': 30, 'column': 'szse', 'tabName': 'fulltext',
                'stock': ';'.join(selected), 'searchkey': '发行公告',
                'seDate': f'{dates.min() - pd.Timedelta(days=14):%Y-%m-%d}~{dates.max():%Y-%m-%d}',
                'isHLtitle': 'true', 'sortName': 'time', 'sortType': 'desc',
            }, method='POST')
            body = response['body']
            items = body.get('announcements') or []
            fingerprint = tuple(item['announcementId'] for item in items)
            if fingerprint in seen_pages:
                raise ValueError('Announcement pagination repeated a page')
            seen_pages.add(fingerprint)
            for item in items:
                title = re.sub(r'<[^>]+>|\s+', '', item['announcementTitle'])
                if item['secCode'] not in set(batch.code):
                    continue
                if not re.search(r'首次公开发行.*发行公告(?:[（(].*[)）])?$', title):
                    continue
                records.append({
                    'code': item['secCode'], 'title': title,
                    'announcement_date': item['adjunctUrl'].split('/')[1],
                    'source_url': 'https://static.cninfo.com.cn/' + item['adjunctUrl'],
                    'index_retrieved_at': response['retrieved_at'],
                })
            frame = pd.DataFrame(records, columns=['code', 'title', 'announcement_date', 'source_url', 'index_retrieved_at'])
            save_csv(frame.drop_duplicates('source_url'), target)
            if page * 30 >= body.get('totalAnnouncement', 0) or not items:
                break
            page += 1
        print(f'IPO index {min(start + 20, len(samples))}/{len(samples)}; candidates={len(frame.drop_duplicates("source_url"))}', flush=True)


def read_document(client, sample, candidate):
    url = candidate['source_url']
    target = path('data/cache/ipo_documents', hashlib.sha256(url.encode()).hexdigest() + '.json')
    if target.exists():
        cached = json.loads(target.read_text(encoding='utf-8'))
        text = re.sub(r'\s+', '', unicodedata.normalize('NFKC', ''.join(cached['pages'])))
        if approval_evidence(text) or len(cached['pages']) >= min(30, cached['total_pages']):
            return cached
    response = client.get(url, binary_mode=True)
    raw = base64.b64decode(response['body'])
    reader = PdfReader(BytesIO(raw))
    day = pd.Timestamp(sample['online_issue_date'])
    date_pattern = rf'{day.year}年0?{day.month}月0?{day.day}日'
    pages = []
    for page in reader.pages[:30]:
        pages.append(page.extract_text() or '')
        text = re.sub(r'\s+', '', unicodedata.normalize('NFKC', ''.join(pages)))
        if len(pages) >= 5 and re.search(date_pattern, text) and approval_evidence(text):
            break
    record = {
        'source_url': url, 'retrieved_at': response['retrieved_at'],
        'pdf_sha256': hashlib.sha256(raw).hexdigest(),
        'total_pages': len(reader.pages), 'pages': pages,
    }
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
    temporary.replace(target)
    return record


def parse_evidence(sample, candidate, document):
    pages = [re.sub(r'\s+', '', unicodedata.normalize('NFKC', page)) for page in document['pages']]
    text = '\n'.join(pages)
    row = {
        'code': sample['code'], 'issue_date': None, 'issue_date_basis': None,
        'issue_date_source_url': None, 'review_status': None, 'review_status_date': None,
        'review_status_source_url': None, 'review_document_no': None,
        'review_status_as_of': None, 'review_evidence_type': None,
        'official_evidence_retrieved_at': document['retrieved_at'],
        'official_evidence_sha256': document['pdf_sha256'],
        'issue_date_evidence_page': None, 'review_status_evidence_page': None,
        'issue_date_evidence_quote': None, 'review_status_evidence_quote': None,
        'evidence_note': '自动解析官方IPO公告，待人工抽样复核',
    }
    expected_price = float(sample['issue_price'])
    prices = [float(value.replace(',', '')) for value in re.findall(r'(\d[\d,]*(?:\.\d+)?)元[/／]股', text)]
    price_matches = any(abs(price - expected_price) < 0.0001 for price in prices)
    day = pd.Timestamp(sample['online_issue_date'])
    date_pattern = rf'{day.year}年0?{day.month}月0?{day.day}日'
    if price_matches or sample['code'] in text or sample['name'] in text:
        for page_number, page in enumerate(pages, 1):
            for match in re.finditer(date_pattern, page):
                quote = page[max(0, match.start() - 90):match.end() + 90]
                if '网上' in quote and ('申购' in quote or '发行' in quote):
                    row['issue_date'] = day.strftime('%Y-%m-%d')
                    row['issue_date_basis'] = '官方IPO公告明确的网上发行T日'
                    row['issue_date_source_url'] = candidate['source_url']
                    row['issue_date_evidence_page'] = page_number
                    row['issue_date_evidence_quote'] = quote
                    break
            if row['issue_date']:
                break
    for page_number, page in enumerate(pages, 1):
        approved = approval_evidence(page)
        if approved:
            match, status, quote = approved
            row['review_status'] = status
            row['review_document_no'] = f'证监许可〔{match[1]}〕{match[2]}号'
            row['review_status_source_url'] = candidate['source_url']
            row['review_status_as_of'] = candidate['announcement_date']
            row['review_evidence_type'] = 'official_ipo_announcement'
            row['review_status_evidence_page'] = page_number
            row['review_status_evidence_quote'] = quote
            explicit_dates = re.findall(
                r'(\d{4})年(\d{1,2})月(\d{1,2})日,?(?:获|获得|取得|收到|经)(?:中国证券监督管理委员会|中国证监会)', quote)
            explicit_dates += re.findall(
                r'(?:中国证券监督管理委员会|中国证监会)于(\d{4})年(\d{1,2})月(\d{1,2})日', quote)
            explicit_dates += re.findall(
                r'(\d{4})年(\d{1,2})月(\d{1,2})日,(?:中国证券监督管理委员会|中国证监会)(?:印发|出具|签发|作出)', quote)
            registration_dates = {f'{int(y):04d}-{int(m):02d}-{int(d):02d}' for y, m, d in explicit_dates}
            if len(registration_dates) == 1:
                registration_date = next(iter(registration_dates))
                if registration_date <= min(sample['online_issue_date'], candidate['announcement_date']):
                    row['review_status_date'] = registration_date
            break
    return row


def collect_evidence(client, samples):
    candidates = pd.read_csv(path('data/raw/ipo_announcement_candidates.csv'), dtype=str)
    target = path('data/raw/ipo_official_evidence.csv')
    existing = pd.read_csv(target, dtype=str).set_index('code').to_dict('index')
    for previous in existing.values():
        for prefix in ['issue_date', 'review_status']:
            title = previous.get(prefix + '_document_title')
            if pd.notna(title) and re.search('取消|作废|撤回', title):
                for field in list(previous):
                    if field.startswith(prefix) or (prefix == 'review_status' and field.startswith('review_')):
                        previous[field] = None
                previous['official_evidence_sha256'] = None
                previous['official_evidence_retrieved_at'] = None
        for prefix in ['issue_date', 'review_status']:
            url = previous.get(prefix + '_source_url')
            if pd.isna(url):
                continue
            cached_file = path('data/cache/ipo_documents', hashlib.sha256(url.encode()).hexdigest() + '.json')
            if cached_file.exists():
                cached = json.loads(cached_file.read_text(encoding='utf-8'))
                previous[prefix + '_evidence_sha256'] = cached['pdf_sha256']
                previous[prefix + '_evidence_retrieved_at'] = cached['retrieved_at']
    tasks = []
    for sample in samples.to_dict('records'):
        current = existing.get(sample['code'], {})
        if pd.notna(current.get('issue_date')) and pd.notna(current.get('review_status')):
            continue
        matches = candidates.loc[candidates.code.eq(sample['code'])].copy()
        dates = pd.to_datetime(matches.announcement_date)
        day = pd.Timestamp(sample['online_issue_date'])
        matches = matches.loc[dates.between(day - pd.Timedelta(days=14), pd.Timestamp(sample['list_date']))]
        matches = matches.loc[~matches.title.str.contains('取消|作废|撤回', regex=True)]
        original = matches.loc[~matches.title.str.contains('更正|修订', regex=True)]
        if not original.empty:
            matches = original
        if not matches.empty:
            if 'size_kb' in matches:
                matches['size_kb'] = pd.to_numeric(matches.size_kb, errors='coerce').fillna(100000)
                matches['priority'] = 2
                matches.loc[matches.title.str.contains('发行结果公告', regex=False), 'priority'] = 1
                concise = matches.title.str.contains(r'招股意向书提示性?公告|上市提示公告$', regex=True)
                matches.loc[concise, 'priority'] = 0
                matches = matches.sort_values(['priority', 'size_kb', 'announcement_date'])
            choices = matches.head(3).to_dict('records')
            formal = matches.loc[matches.title.str.contains(r'首次公开发行.*发行公告(?:[（(].*[)）])?$', regex=True)]
            used_urls = {item['source_url'] for item in choices}
            choices.extend(item for item in formal.to_dict('records') if item['source_url'] not in used_urls)
            tasks.append((sample, choices))
    errors = []

    def process(task):
        sample, choices = task
        result = {'code': sample['code']}
        document_errors = []
        for candidate in choices:
            try:
                document = read_document(client, sample, candidate)
                row = parse_evidence(sample, candidate, document)
                for field, value in row.items():
                    if pd.notna(value) and pd.isna(result.get(field)):
                        result[field] = value
                if row['issue_date'] and result.get('issue_date_source_url') == candidate['source_url']:
                    result['issue_date_evidence_sha256'] = document['pdf_sha256']
                    result['issue_date_evidence_retrieved_at'] = document['retrieved_at']
                    result['issue_date_document_title'] = candidate['title']
                if row['review_status'] and result.get('review_status_source_url') == candidate['source_url']:
                    result['review_status_evidence_sha256'] = document['pdf_sha256']
                    result['review_status_evidence_retrieved_at'] = document['retrieved_at']
                    result['review_status_document_title'] = candidate['title']
                if result.get('issue_date') and result.get('review_status'):
                    break
            except Exception as error:
                document_errors.append({'source_url': candidate['source_url'], 'error': str(error)})
        error = None
        if document_errors:
            error = {'code': sample['code'], 'source_url': document_errors[0]['source_url'],
                     'error': json.dumps(document_errors, ensure_ascii=False)}
        return result, error

    with ThreadPoolExecutor(max_workers=6) as executor:
        for index, (row, error) in enumerate(executor.map(process, tasks, buffersize=6), 1):
            if error:
                errors.append(error)
                print(f'IPO document error: {error}', flush=True)
            if row and (row.get('issue_date') or row.get('review_status')):
                previous = existing.get(row['code'], {})
                if pd.notna(previous.get('issue_date')):
                    row = {field: value for field, value in row.items() if not field.startswith('issue_date')}
                if pd.notna(previous.get('review_status')):
                    row = {field: value for field, value in row.items()
                           if not field.startswith('review_')}
                for field, value in row.items():
                    if field != 'code' and pd.notna(value) and pd.isna(previous.get(field)):
                        previous[field] = value
                existing[row['code']] = previous
                frame = pd.DataFrame([{'code': code, **values} for code, values in existing.items()])
                save_csv(frame, target)
            if index % 10 == 0:
                print(f'IPO documents {index}/{len(tasks)}; evidence rows={len(existing)}, errors={len(errors)}', flush=True)
    save_csv(pd.DataFrame(errors, columns=['code', 'source_url', 'error']), path('report/ipo_official_fetch_errors.csv'))
    print(f'IPO evidence rows={len(existing)}; errors={len(errors)}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('task', choices=['index', 'cached-index', 'documents'])
    args = parser.parse_args()
    samples = pd.read_csv(path('data/processed/ipo.csv'), dtype={'code': str})
    path('data/cache/ipo_documents').mkdir(parents=True, exist_ok=True)
    client = PublicClient()
    client.timeout = (5, 20)
    if args.task == 'index':
        find_announcements(client, samples)
    elif args.task == 'cached-index':
        recover_cached_index(samples)
    else:
        collect_evidence(client, samples)


if __name__ == '__main__':
    main()
