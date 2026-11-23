# 深度登记 搜索索引双写延迟与删改可见性核验

规模：中型。使用者：搜索数据同步值班工程师。核心规则：按源版本重建目标可见状态，删除墓碑拦截迟到旧写入；延迟与缺失分开定责。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 双端采信 | 查看并运行双端采信 | `/api/streams` | `app/modules/m1_streams/rules.py` | `tests/test_m1.py` |
| M2 字段契约 | 查看并运行字段契约 | `/api/schema` | `app/modules/m2_schema/rules.py` | `tests/test_m2.py` |
| M3 版本裁决 | 查看并运行版本裁决 | `/api/versions` | `app/modules/m3_versions/rules.py` | `tests/test_m3.py` |
| M4 可见性重建 | 查看并运行可见性重建 | `/api/visibility` | `app/modules/m4_visibility/rules.py` | `tests/test_m4.py` |
| M5 延迟闸门 | 查看并运行延迟闸门 | `/api/latency` | `app/modules/m5_latency/rules.py` | `tests/test_m5.py` |
| M6 双写对账 | 查看并运行双写对账 | `/api/parity` | `app/modules/m6_parity/rules.py` | `tests/test_m6.py` |
| M7 回补归档 | 查看并运行回补归档 | `/api/backfills` | `app/modules/m7_backfills/rules.py` | `tests/test_m7.py` |

## 陷阱登记

| TRAP | 现象 | 朴素实现 | 本项目处理 | 处理位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-01 | 旧编码 | 默认解码失败 | 回退GB18030 | `app/modules/m1_streams/rules.py` | `tests/test_m1.py::test_legacy_encoding_real_sample` |
| TRAP-02 | BOM | 首列名多字符 | utf-8-sig | `app/modules/m1_streams/rules.py` | `tests/test_m1.py::test_bom_real_sample` |
| TRAP-03 | 带引号换行 | 拆成两条 | csv逻辑行 | `app/modules/m1_streams/rules.py` | `tests/test_m1.py::test_quoted_newline_is_one_record` |
| TRAP-05 | 列数不匹配 | 静默错列 | 隔离原行 | `app/modules/m1_streams/rules.py` | `tests/test_m1.py::test_bad_columns_real_sample` |
| TRAP-08 | 前导零ID | 编码变形 | 全程字符串 | `app/modules/m1_streams/rules.py` | `tests/test_m1.py::test_identifier_preserved_real_sample` |
| TRAP-14 | 重复键冲突 | 后写覆盖 | 保留首条并隔离冲突行 | `app/modules/m1_streams/rules.py` | `tests/test_m1.py::test_duplicate_conflict_real_sample` |
| TRAP-18 | 空态三态 | 一律成功 | 分别错误码 | `app/modules/m1_streams/rules.py` | `tests/test_m1.py::test_three_empty_states` |
| TRAP-26 | 旧版本提交 | 覆盖新结果 | 版本条件更新 | `app/store.py` | `tests/test_e2e.py::test_stale_review_409` |
| TRAP-06 | 全角版本 | 解析失败 | Decimal归一 | `app/values.py` | `tests/test_m2.py::test_fullwidth_version` |
| TRAP-07 | 缺版本 | 当零处理 | 空值隔离 | `app/values.py` | `tests/test_m2.py::test_real_sentinel_isolated` |
| TRAP-09 | 超大版本 | JSON精度损失 | 文本序列化 | `app/values.py` | `tests/test_m2.py::test_large_version_precise` |
| TRAP-13 | 删除后迟到旧写 | 文档复活 | 最大版本墓碑 | `app/modules/m3_versions/rules.py` | `tests/test_m3.py::test_tombstone_beats_late_old_write` |
| TRAP-23 | 延迟阈值边界 | 多判延迟 | 等于阈值通过 | `app/modules/m5_latency/rules.py` | `tests/test_m5.py::test_threshold_equal_pass` |
| TRAP-27 | 撤下被更新挤占 | 纯到达序推进 | 撤下类优先、类内到达序 | `app/release.py` | `tests/test_release.py::test_takedown_outranks_earlier_update` |
| TRAP-28 | 未入选冒充已同步 | 跳过行记通过 | 闸门置未入选且对账硬拦截 | `app/modules/m6_parity/rules.py` | `tests/test_release.py::test_reconcile_rejects_impersonation` |
| TRAP-29 | 重跑新增批次 | 时间戳进摘要 | 放行单内容寻址复用批次 | `app/release.py` | `tests/test_release.py::test_rerun_same_backlog_no_new_records` |
| TRAP-30 | 索引超前误删 | 删除一刀切 | INDEX_AHEAD转人工不占额度 | `app/release.py` | `tests/test_release.py::test_index_ahead_held_not_consuming_quota` |

## 对账规则

输入原始逻辑行=最终采纳来源行+隔离来源行+重复行+空白行+分段表头。派生记录用_sources保存完整来源，因此分组不丢行。业务预期合计与上游申报合计之差等于逐行差异之和。结果按输入摘要、规则版本及参数产生唯一批次，事务写入；同源重跑只复用已有批次。

## 放行单规则

积压=可见性重建后所有非一致文档，原始位置按(源时刻,文档号)全序编号。放行动作以版本裁决后的最终状态为准：撤下类(删除未确认、孤儿索引、源删除的落后/操作冲突)优先，更新类其次，类内按原始位置；索引超前转人工且不占额度。每次放行取策略序前release_quota个形成唯一前缀范围，release_id对放行单内容寻址、不含时间戳，同一积压同一参数重跑得到同一放行单与同一批次。延迟闸门为每行标注放行单字段并将未入选置为未入选、实通过置零；双写对账校验放行单平衡并硬拦截未入选记已同步；回补归档把release_id并入封存摘要；页面与导出读取同一批次内的放行单。

## 已知不覆盖

4MB以上文件需预先按业务键分批；不模拟生产支付与外部回调。人工复核只变更批次状态，不改写原始记录。
