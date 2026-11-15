# 字段与口径

全部 CSV 使用 UTF-8 BOM。证券代码为六位字符串，日期为 ISO 格式，金额统一为人民币元。各原始记录保留来源 URL 与原始 UTC 抓取时间。`data/raw` 保留上游原字段以便复核。

| 表 | 字段 | 口径与缺失规则 |
|---|---|---|
| ipo.csv | code/name/board | 股票代码、简称、科创板或创业板；不是全市场股票池 |
| ipo.csv | subscription_date/list_date | 申购日、上市日，不能混称发行日 |
| ipo.csv | issue_date | 法律发行日尚未独立核实，留空 |
| ipo.csv | issue_price/issue_pe | 发行价（元/股）、发行市盈率；缺失保持空值 |
| ipo.csv | proceeds | 原 IPO TOTAL_RAISE_FUNDS 为亿元，乘 1e8 转元 |
| ipo.csv | underwriter/industry | 上游承销商和行业；不是经过核验的历史行业成分或声誉排名 |
| ipo.csv | status/review_status | status 保留来源状态；review_status 尚未取得独立审核状态数据，留空 |
| refinancing_sample.csv | instrument | private_placement 为定增，convertible_bond 为可转债 |
| refinancing_sample.csv | code/bond_code | 正股代码与债券代码；定增没有 bond_code |
| refinancing_sample.csv | issue_date/issue_price | 来源发行日、发行价；转债发行价不是正股价格 |
| refinancing_sample.csv | conversion_price/face_value | 初始转股价、债券面值，单位元；定增无对应字段 |
| refinancing_sample.csv | proceeds | 定增原字段已是元；转债 ACTUAL_ISSUE_SCALE 为亿元，乘 1e8 |
| refinancing_sample.csv | investor_type/underwriter | 发行对象、承销商，按上游原文保留 |
| refinancing_sample.csv | announcement_date/reference_price_20d/discount | 原始公告日、前20日均价及折价仍缺失，不用申购日或最新行情补齐 |
| refinancing_sample.csv | status | issued_observed 表示观察到已发行记录，不表示全部申请和审核项目 |
| 各样本表 | source_url/retrieved_at | 原始来源和抓取时间，不使用本次处理时间替换 |
| cross_validation.csv | value_a/source_a/value_b/source_b | 东方财富与新浪的同一发行价字段；两个独立上游来源 |
| cross_validation.csv | tolerance/status | 绝对价差容忍度 0.005 元，match/mismatch 或尚未解析状态；未等同人工核验 |
| data_manifest.csv | rows/min_date/max_date/sha256 | CSV 行数、日期范围和原始字节摘要；文本证据无表格行数，rows 记为0、日期留空 |

本周已上市/发行清单不包括所有撤回、失败或退市样本，不可直接用于计算审核通过率。未独立核验的数据不能视作全部字段准确。
