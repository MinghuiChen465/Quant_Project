# 字段与口径

全部 CSV 使用 UTF-8 BOM。证券代码为六位字符串，日期为 ISO 格式，金额统一为人民币元。各原始记录保留来源 URL 与原始 UTC 抓取时间。`data/raw` 保留上游原字段以便复核。

| 表 | 字段 | 口径与缺失规则 |
|---|---|---|
| ipo.csv | code/name/board | 股票代码、简称、科创板或创业板；不是全市场股票池 |
| ipo.csv | subscription_date/list_date | 申购日、上市日，不能混称发行日 |
| ipo.csv | online_issue_date | 东方财富原始 ONLINE_ISSUE_DATE，网上发行日期，保留独立字段；913条有值 |
| ipo.csv | issue_date/issue_date_basis/issue_date_source_url | 采用官方IPO公告明确的网上发行T日口径，保留对应公告链接及日期原文；与上游网上发行日期对照，无法确认时留空 |
| ipo.csv | issue_price/issue_pe | 发行价（元/股）、发行市盈率；缺失保持空值 |
| ipo.csv | proceeds | 原 IPO TOTAL_RAISE_FUNDS 为亿元，乘 1e8 转元 |
| ipo.csv | underwriter/industry | 上游承销商和行业；不是经过核验的历史行业成分或声誉排名 |
| ipo.csv | status/review_status | status保留上游状态；review_status依据证监会原始批复或法定披露IPO公告明确载明的注册结论，当前值包括同意注册、予以注册和注册通过，保留原文证据 |
| ipo.csv | review_status_date/review_status_source_url/review_document_no | 证据明确记载的注册日期、独立来源链接及文号；日期仅从原始批复或公告明确表述提取，未明确时留空，当前63条有值 |
| ipo.csv | review_status_as_of/review_evidence_type | 公告证据的披露时点与证据类型；csrc_registration_decision为证监会原始批复，official_ipo_announcement为法定披露IPO公告，旧值official_issue_announcement表示发行公告；披露日单列保存 |
| ipo.csv | issue_date_evidence_page/review_status_evidence_page及对应quote | 日期与注册结论各自所在PDF页码及原文摘录，便于人工抽样核对 |
| ipo.csv | issue_date_evidence_sha256/review_status_evidence_sha256及对应retrieved_at | 各字段证据文件的SHA-256摘要及UTC获取时间；日期和状态可分别来自不同公告，按各自来源对应 |
| ipo_official_evidence.csv | code及补充字段 | 独立证据索引，包含原有手工记录与本轮自动提取记录；保留来源类型、摘录与文号，待人工抽样复核；运行入口按代码一对一合并 |
| refinancing_sample.csv | instrument | private_placement 为定增，convertible_bond 为可转债 |
| refinancing_sample.csv | code/bond_code | 正股代码与债券代码；定增没有 bond_code |
| refinancing_sample.csv | issue_date/issue_price | 来源发行日、发行价；转债发行价不是正股价格 |
| refinancing_sample.csv | conversion_price/face_value | 初始转股价、债券面值，单位元；定增无对应字段 |
| refinancing_sample.csv | proceeds | 定增原字段已是元；转债 ACTUAL_ISSUE_SCALE 为亿元，乘 1e8 |
| refinancing_sample.csv | investor_type/underwriter | 发行对象、承销商，按上游原文保留 |
| refinancing_sample.csv | event_id | 定增采用原始FINANCE_CODE，转债采用债券代码标识发行事件 |
| refinancing_sample.csv | announcement_date/announcement_type/announcement_source_url | 定增采用发行情况报告书披露日，转债采用发行公告披露日；巨潮索引定位后须通过正文代码、日期及价格匹配；不确定记录留空 |
| refinancing_sample.csv | announcement_match_status/announcement_evidence_page | 发行人按官方索引证券代码匹配，再核对正文价格及日期或募资额；记录自动匹配状态及日期所在PDF页码，保留候选、歧义及不匹配状态供人工复核 |
| refinancing_sample.csv | issue_date_evidence_status/date_review_note/date_review_source_url | 标记上游日期是否在正文出现，以及已发现的日期疑点；日期出现不等同已核实其法律含义。已知日期冲突记录暂缓折价输出 |
| refinancing_sample.csv | reference_price_20d/reference_price_basis | 研究基准价，发行日前20个有成交交易日的未复权总成交额/总成交量；搜狐成交额万元转元，成交量手转股；仅20条有效记录齐备才计算 |
| refinancing_sample.csv | reference_window_start/reference_window_end/reference_observations | 实际20日窗口起止与有效记录数，严格排除发行当日；停牌日不计入有成交日 |
| refinancing_sample.csv | pricing_principle/pricing_reference_date | 保留上游定价原则原文；定价基准日从已匹配官方正文提取，并附独立来源 |
| refinancing_sample.csv | official_reference_price_20d | 官方正文明确给出数值时才提取的定价基准日前20日均价；研究基准价单独保留；不通过发行底价除以80%反推 |
| refinancing_sample.csv | pricing_date_reference_price_20d/pricing_date_window_start/pricing_date_window_end | 以公告提取的定价基准日为截止日，使用历史成交额与成交量重建的未复权20日VWAP；20个有效交易日齐备才填写，并保留行情来源；未处理公告要求的窗口内除权除息调整 |
| refinancing_sample.csv | discount/discount_basis | 定增研究折价=1-发行价/发行日前20日未复权VWAP；负值表示溢价；缺价格基准留空。未作除权除息调整，不能视作公告法定折价口径 |
| refinancing_sample.csv | underlying_close_on_issue/underlying_price_date | 转债发行当日未复权正股收盘价；仅精确匹配日期且有成交时填写，缺值留空 |
| refinancing_sample.csv | underlying_price_crosscheck | 腾讯与搜狐同日收盘价的双源数值比对状态；有两源时使用0.011元容差；单源记录标not_checked |
| refinancing_sample.csv | conversion_value_on_issue | 面值×发行日正股收盘价/初始转股价，单位元/张，任一必要字段缺失时留空 |
| refinancing_sample.csv | *_source_url/*_retrieved_at | 补充价格各自保留接口链接与UTC采集时间；PDF正文缓存另附原始PDF SHA-256摘要 |
| refinancing_sample.csv | status | issued_observed 表示观察到已发行记录，不表示全部申请和审核项目 |
| 各样本表 | source_url/retrieved_at | 原始来源和抓取时间，不使用本次处理时间替换 |
| cross_validation.csv | value_a/source_a/value_b/source_b | 东方财富与新浪的同一发行价字段；两个独立上游来源 |
| cross_validation.csv | tolerance/status | 绝对价差容忍度 0.005 元，match/mismatch 或尚未解析状态；未等同人工核验 |
| data_manifest.csv | rows/min_date/max_date/sha256 | CSV 行数、日期范围和原始字节摘要；文本证据无表格行数，rows 记为0、日期留空 |

本周已上市/发行清单不包括所有撤回、失败或退市样本，不可直接用于计算审核通过率。未独立核验的数据不能视作全部字段准确。
