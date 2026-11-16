# 中信建投量化实习：Week 1

## 范围

- 数据源选型矩阵、仓库骨架、独立配置、日志、统一路径与依赖。
- IPO、定增、可转债公开清单抓取：限速、重试、缓存、robots 检查和来源时间记录。
- 2021—2025 年科创板、创业板基础样本，IPO 发行价独立来源抽样核验。
- 数据版本清单：文件、行数、日期范围、SHA-256。

## 直接运行

本机已经配置好本目录自己的 `.venv`。建议在 VS Code 中单独打开本文件夹：

```powershell
cd "D:\Development\Code\05_Internship_Projects\quant_internship_week1"
.\.venv\Scripts\python.exe run_week1.py
```

默认使用随包真实原始 CSV 和已保存的新浪来源文本，可以离线重建。成功后控制台打印样本量及 `validation: passed`，同时更新：

- `data/processed/ipo.csv`
- `data/processed/refinancing_sample.csv`
- `data/processed/cross_validation.csv`
- `data/processed/data_manifest.csv`
- `report/refinancing_coverage.csv`
- `report/run_summary.json`
- `logs/pipeline.log`

原始数据的抓取时间保留在每条记录中；本次离线重建不会伪装成重新抓取。

## 在其他电脑重建环境

安装 Python 3.14 后，在本目录运行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe run_week1.py
```

也可执行 `powershell -ExecutionPolicy Bypass -File .\setup.ps1`，仅对该次进程指定执行策略。`requirements.txt` 是直接依赖范围，`requirements-lock.txt` 是本机验证过的完整版本。

## 联网更新（可选）

```powershell
.\.venv\Scripts\python.exe run_week1.py --refresh
```

也可分步执行 `fetch_public.py ipo`、`fetch_public.py refinancing`、`fetch_public.py crosscheck`，最后运行 `run_week1.py`。独立抓取脚本读取 `config.yaml` 中的起止日期、限速、超时和重试参数；命中已有响应缓存时复用缓存。若确实需要重新请求同一地址，请先备份并移走对应缓存。

联网结果取决于外部网站的可用性、规则和接口。本版验证了离线重建，不将历史抓取成功等同于当前在线接口可用。请遵守来源网站条款；robots 检查不能代替完整条款审阅。

## 文件阅读顺序

IPO官方字段补充依次执行 `fetch_ipo_official.py index`、`fetch_ipo_official.py cached-index`、`fetch_ipo_official.py documents`，最后运行 `run_week1.py` 合并。索引查询使用多证券精确筛选，正文按各字段保存来源、页码和摘录。注册结论优先保留已取得的证监会批复，其余可由法定披露IPO公告载明的注册文号与结论补充，明确批复日期与公告披露时点分别记录。

1. `config.yaml`：本周研究区间和抓取参数。
2. `core.py`：统一路径、日志、CSV 与版本摘要。
3. `fetch_public.py`：原始数据获取与来源证据。
4. `run_week1.py`：IPO 清单规范化、运行检查与交付输出。
5. `sample_helpers.py`：定增/转债字段转换、新浪价格解析。
6. `data/field_dictionary.md`：字段、单位和缺失规则。
7. `report/第一周进度汇报.md`：可汇报进度和待补事项。

真实输入校验由 `run_week1.py` 执行。

