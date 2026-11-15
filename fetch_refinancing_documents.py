"""下载候选发行公告并缓存正文，用代码、日期及价格匹配发行事件。"""
import base64
import hashlib
from io import BytesIO
import json
import re
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
from pypdf import PdfReader

from core import path
from fetch_public import PublicClient


def main():
    samples = pd.read_csv(path('data/processed/refinancing_sample.csv'), dtype=str)
    urls = samples.get('announcement_candidate_source_url', pd.Series(dtype=str)).dropna().unique()
    folder = path('data/cache/refinancing_documents')
    folder.mkdir(parents=True, exist_ok=True)
    client = PublicClient()
    client.timeout = (5, 20)
    failures = []
    consecutive_failures = 0
    def process_document(url):
        target = folder / (hashlib.sha256(url.encode()).hexdigest() + '.json')
        if target.exists():
            return None
        try:
            response = client.get(url, binary_mode=True)
            data = base64.b64decode(response['body'])
            reader = PdfReader(BytesIO(data))
            events = samples.loc[samples.announcement_candidate_source_url.eq(url)]
            pages = []
            for page in reader.pages[:30]:
                pages.append(page.extract_text() or '')
                text = re.sub(r'\s+', '', '\n'.join(pages))
                matched = []
                for event in events.itertuples():
                    day = pd.Timestamp(event.issue_date)
                    date_found = re.search(rf'{day.year}年0?{day.month}月0?{day.day}日', text)
                    price_found = str(event.code) in text and date_found
                    matched.append(bool(price_found))
                if len(pages) >= 10 and matched and all(matched):
                    break
            record = {
                'source_url': url, 'retrieved_at': response['retrieved_at'],
                'pdf_sha256': hashlib.sha256(data).hexdigest(),
                'total_pages': len(reader.pages), 'pages': pages,
            }
            temporary = target.with_suffix('.tmp')
            temporary.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
            temporary.replace(target)
            return None
        except Exception as error:
            return {'source_url': url, 'error': str(error)}

    # 仅重叠下载等待时间，PublicClient仍统一限制请求开始间隔。
    with ThreadPoolExecutor(max_workers=6) as executor:
        for index, error in enumerate(executor.map(process_document, urls, buffersize=6), 1):
            if error:
                failures.append(error)
                consecutive_failures += 1
                print(f'Document failed: {error}', flush=True)
            else:
                consecutive_failures = 0
            if index % 10 == 0:
                print(f'Documents {index}/{len(urls)}, errors={len(failures)}', flush=True)
            if consecutive_failures >= 5:
                executor.shutdown(wait=True, cancel_futures=True)
                break
    pd.DataFrame(failures, columns=['source_url', 'error']).to_csv(
        path('report/refinancing_document_fetch_errors.csv'), index=False, encoding='utf-8-sig')
    print(f'Cached documents: {len(list(folder.glob("*.json")))}/{len(urls)}', flush=True)


if __name__ == '__main__':
    main()
