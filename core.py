"""第一周基础设施：统一路径、日志、CSV 输出和数据版本。"""

from pathlib import Path
import csv
import hashlib
import logging
ROOT = Path(__file__).resolve().parent

def path(*parts):
    return ROOT.joinpath(*parts)

def logger(name):
    path('logs').mkdir(exist_ok=True)
    log = logging.getLogger(name)
    if not log.handlers:
        handler = logging.FileHandler(path('logs', 'pipeline.log'), encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
    return log

def write_csv(file, rows, fields):
    file = Path(file)
    file.parent.mkdir(parents=True, exist_ok=True)
    with file.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)

def manifest(file, rows, date_field):
    file = Path(file).resolve()
    dates = sorted(r[date_field] for r in rows if r.get(date_field))
    return {'file': str(file.relative_to(ROOT)), 'rows': len(rows),
            'min_date': dates[0] if dates else '', 'max_date': dates[-1] if dates else '',
            'sha256': hashlib.sha256(file.read_bytes()).hexdigest()}
