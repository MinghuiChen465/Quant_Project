"""打包本周提交内容，明确排除本机环境和运行缓存。"""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent


def main():
    target = ROOT.parent / (ROOT.name + '_submission.zip')
    excluded = {'.venv', '__pycache__', '.git', 'logs', 'tmp'}
    with ZipFile(target, 'w', compression=ZIP_DEFLATED) as archive:
        for file in sorted(ROOT.rglob('*')):
            relative = file.relative_to(ROOT)
            if file.is_file() and not excluded.intersection(relative.parts):
                archive.write(file, str(Path(ROOT.name) / relative))
    with ZipFile(target) as archive:
        if archive.testzip() is not None:
            raise RuntimeError('ZIP integrity check failed')
        print('Submission files:', len(archive.namelist()))
    print('Submission ZIP:', target)


if __name__ == '__main__':
    main()
