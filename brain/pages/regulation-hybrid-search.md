---
id: regulation-hybrid-search
title: "规范混合检索架构"
category: decision
status: active
tags: [rag, lancedb, retrieval]
created: "2026-07-17T20:11:09"
updated: "2026-07-18T20:00:49"
---

## compiled_truth

- ?????? `FAISS + BM25 + RRF` ???????????????????????
- ??????? `target_field="evacuation_door_clear_width_requirement"`?????? task?????????? search concepts?
- ?? Query Rewriter ?? `target_field`??? `original_query`??? `IFCContext` ? `available_documents: list[str]`??????????? `query`?????? `target_document` ??? `reason`?
- `available_documents` ?????????? `document_id` ????DocumentCatalog ????? index_dir ? aliases??????????????????????????????????????????????????
- ?? query ??????????????????????????????????? PASS/FAIL???? OverallWidth ?? clear width?????? IFC ????????
- ?? Query Translator ????? schema ????? Query Rewriter ?????????????
- ?? ReAct ???? `search`?`finish`?`insufficient_evidence`???????????? query????? fetch?`SearchConfig.max_hops` ?? 3 ??????????
- DocumentCatalog ??????? document_id??????????????????????
- ??????? evidence_ids???????????????RRF ???????????????
- Streamlit ?????????????? spec.md ?? Web ?????


## timeline

- time: 2026-07-17T20:11:09
  kind: decision
  summary: "Created this page: 规范混合检索架构"
  source: "用户确认与2026-07-17实现"
  affects: [regulation-hybrid-search]

- time: 2026-07-17T20:11:09
  kind: decision
  summary: "确定离线三模态 LanceDB 混合检索的数据源与默认参数"
  source: "用户确认与实现验证"
  affects: [regulation-hybrid-search]

- time: 2026-07-17T20:19:32
  kind: decision
  summary: "检索默认参数只由 SearchConfig 定义，CLI 参数仅作为显式覆盖"
  source: "用户要求与代码修正"
  affects: [regulation-hybrid-search]

- time: 2026-07-17T20:22:18
  kind: decision
  summary: "metadata_json 仅保留标识、页码、资产路径、哈希与 faiss_id 等溯源字段，不再重复保存正文和 OCR 大文本"
  source: "用户要求与代码修正"
  affects: [regulation-hybrid-search]

- time: 2026-07-17T21:56:22
  kind: decision
  summary: "检索输入采用 subject/building_context/door_facts/assessment/missing_information/retrieval_intent，查询构建器只生成一个完整意图，拆分留给后续迭代检索"
  source: "用户决定与 Door 15600 验证"
  affects: [regulation-hybrid-search]

- time: 2026-07-17T21:59:25
  kind: reversal
  summary: "撤销 query_builder 中硬编码的中文翻译和语义扩写；query_text 只拼接结构化输入的原始值"
  source: "用户纠正"
  affects: [regulation-hybrid-search]

- time: 2026-07-17T22:12:00
  kind: reversal
  summary: "移除项目内 LanceDB 建库、检索、CLI、依赖、测试与 data/lancedb 派生索引；保留 FAISS/metadata 和检索输入构建，混合检索逻辑待重新设计"
  source: "用户决定"
  affects: [regulation-hybrid-search]

- time: 2026-07-17T22:20:46
  kind: decision
  summary: "新增独立 LLM query_translator：QueryBuilder 保留原文，翻译器输出同结构中文语义值，并由程序强制保持 door_id/candidate_k/top_k 不变"
  source: "用户决定与实现"
  affects: [regulation-hybrid-search]

- time: 2026-07-17T22:48:06
  kind: decision
  summary: "正式确认 FAISS + BM25 + RRF 三模态混合检索架构及 src/search 分层"
  source: "用户于2026-07-17确认"
  affects: [regulation-hybrid-search]

- time: 2026-07-17T23:14:40
  kind: decision
  summary: "采用证据驱动的多跳 ReAct 检索、人工确认不确定疏散门并复用同上下文证据"
  source: "用户于2026-07-17确认"
  affects: [regulation-hybrid-search]

- time: 2026-07-17T23:23:03
  kind: decision
  summary: "明确 search 使用证据驱动的完整问题改写、fetch_reference 仅定点取引用，并将 Web 交互后置"
  source: "用户于2026-07-17纠正"
  affects: [regulation-hybrid-search]

- time: 2026-07-17T23:27:58
  kind: decision
  summary: "当前迭代检索仅保留 search/finish/insufficient，引用通过下一轮 search 处理且放宽 query 句式约束"
  source: "用户于2026-07-17确认"
  affects: [regulation-hybrid-search]

- time: 2026-07-17T23:39:35
  kind: decision
  summary: "统一任务、目标字段和搜索概念命名并落实到检索 schema"
  source: "用户要求与2026-07-17代码迁移"
  affects: [regulation-hybrid-search]

- time: 2026-07-17T23:43:19
  kind: decision
  summary: "撤销重复的 task_name/target对象/search_concepts，仅保留单一 target_field"
  source: "用户质疑过度建模并要求简化"
  affects: [regulation-hybrid-search]

- time: 2026-07-17T23:51:15
  kind: decision
  summary: "实现 max_hops 单一配置源与基于真实索引目录的 DocumentCatalog"
  source: "src/search/config.py、document_catalog.py 及真实目录测试"
  affects: [regulation-hybrid-search]

- time: 2026-07-18T00:00:08
  kind: decision
  summary: "简化可用文档为字符串列表并实现首轮 Query Rewriter，移除独立翻译路径"
  source: "query_rewriter.py、query_rewrite prompt 与 Door 15600 真实模型验证"
  affects: [regulation-hybrid-search]

- time: 2026-07-18T00:06:26
  kind: decision
  summary: "迭代控制器采用单轮结构化决策边界：LLM仅返回动作与查询，程序校验证据ID、文档、重复查询和最大轮次，检索循环由后续service管理"
  source: "用户确认与controller.py实现"
  affects: [regulation-hybrid-search]

- time: 2026-07-18T00:09:17
  kind: decision
  summary: "history按实际返回hit数量记录result_count；本轮重复证据保留在查询关联中，全局evidence_history仅保存首次出现且不覆盖首次分数与轮次"
  source: "用户确认与history.py实现"
  affects: [regulation-hybrid-search]

- time: 2026-07-18T00:12:43
  kind: decision
  summary: "service串联首轮改写、按文档缓存的混合检索、history与单轮controller，在max_hops内终止并返回完整历史；模型和基础设施错误直接上抛"
  source: "用户确认与service.py实现"
  affects: [regulation-hybrid-search]

- time: 2026-07-18T00:17:13
  kind: evidence
  summary: "Door 15600真实三轮测试暴露：controller把规范要求误扩展为构件实际值查询并在max_hops继续search；语义重复未被精确去重识别；无信息图片因分模态RRF持续排名第一"
  source: artifacts/debug/door_15600_iterative_retrieval.json
  affects: [regulation-hybrid-search]

- time: 2026-07-18T00:28:32
  kind: evidence
  summary: "引用链目标均已入索引但被融合裁剪：南京table_000031为BM25表格第1/dense第29，中小学table_000012为BM25表格第1/dense第21；candidate_k=10与双路命中优先的RRF使两条精确BM25证据均未进入controller上下文"
  source: "Door 15600引用链定向检索诊断"
  affects: [regulation-hybrid-search]

- time: 2026-07-18T00:40:05
  kind: decision
  summary: "混合检索改为candidate_k=50/top_k=5：BM25与dense先跨文本表格图片形成各自全局排名，再执行一次RRF，融合后过滤明确不可用图片并最终截取"
  source: "用户确认与hybrid.py实现"
  affects: [regulation-hybrid-search]

- time: 2026-07-18T00:45:27
  kind: evidence
  summary: "两份文档的table FAISS均确认系统性metadata错位：用table_N自身当前文本查询时约0.95到0.99相似度命中table_N+1；目标表向量被下一条metadata标识，导致dense返回错误相邻表格"
  source: "表格向量自检：中小学table_000009至15、南京table_000016至18及30至32"
  affects: [regulation-hybrid-search]

- time: 2026-07-18T00:49:49
  kind: evidence
  summary: "全模态自检确认FAISS使用1..N的外部ID而metadata使用0..N-1：两文档text/table及南京image均整体偏移+1，末条向量返回ID=N且当前映射缺失；可用经集合验证的index_id到metadata_id转换层修复"
  source: "2026-07-18跨文档跨模态self-retrieval审计"
  affects: [regulation-hybrid-search]

- time: 2026-07-18T01:04:51
  kind: decision
  summary: "检索派生数据在元数据/索引源头清理低质量图片；查询改写同时输出中文 query 供 BM25 和英文 dense_query 供向量检索；FAISS 通过显式 ID 转换接口兼容 identity 与历史 +1 ID 偏移。"
  source: 2026-07-18 implementation and validation
  affects: [regulation-hybrid-search]

- time: 2026-07-18T01:04:51
  kind: evidence
  summary: "清洗南京索引图片 10→1；修复后 table_000031 dense 排名 29→2、table_000012 21→1；Door 15600 双语端到端首轮 table_000031 成为总排名第1且无低质量图片。后续控制器仍未按表8.2.3引用转向中小学规范，并在 max_hops 继续 search。"
  source: artifacts/debug/door_15600_bilingual_fixed.json
  affects: [regulation-hybrid-search]

- time: 2026-07-18T01:08:42
  kind: evidence
  summary: "直接审计原 IFC：Door 15600（GUID 0RehHQeQbAeRNfKMKM7Mht）的实例和 IfcDoorType 均无 FireRating、IsFireExit 或防火门标记；Pset_DoorCommon 仅有 Reference。控制器追问防火门是因召回表格包含防火门扣减150mm/普通门扣减100mm，且 ifc_context 将 fire_rating properties 标为缺失，模型遂把缺失的 IFC 事实错误转化为规范文档检索问题。"
  source: "test_sampe/00 - Primary school project (IFC).ifc and artifacts/debug/door_15600_bilingual_fixed.json"
  affects: [regulation-hybrid-search]

- time: 2026-07-18T01:20:36
  kind: evidence
  summary: "Door 15600 v3真实分类得到 evacuation_door/0.85、is_fire_door=null、fire_door_confidence=null。三轮迭代检索仍反复查询其是否为防火门并在max_hops报错，证明仅增加可空事实字段不足以约束控制器；后续需区分规范证据缺失与IFC事实缺失。"
  source: artifacts/debug/door_15600_fire_door_schema_v3.json
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T01:28:42
  kind: evidence
  summary: "Door 15600采用effective非防火门后，控制器停止查询其是否为防火门，首轮命中南京table_000031，第二轮成功转向中小学规范；新增唯一显示标题到带page后缀document ID解析。第三轮仍因max_hops继续search而终止。"
  source: artifacts/debug/door_15600_effective_non_fire_v4_complete.json
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T01:46:28
  kind: evidence
  summary: "Door 15600真实运行首轮从南京table_000017提取150/100mm规则，确定性得到3000-100=2900mm；controller输入不再包含clear_width缺失且不再追问门净宽。模型一轮后finish，但仍提前声称合规，未继续取表8.2.3与疏散人数要求。"
  source: artifacts/debug/door_15600_derived_clear_width_v5.json
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T02:05:20
  kind: evidence
  summary: "Door 15600 collection-task v7首轮query已同时询问净宽计算和最小阈值且声明不做判断；controller未输出PASS/FAIL，但仍一轮finish，仅引用table_000017扣减规则，未跟随table_000031的表8.2.3引用。extra_info合法返回空列表。"
  source: artifacts/debug/door_15600_collection_task_v7.json
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T02:14:28
  kind: evidence
  summary: "Door15600阈值字段v8真实运行：controller连续三轮将阈值保持null并主动追问每100人表8.2.3数值，extra_info累计净宽2900mm；但target_document始终错误停留南京规范，max_hops时返回finish+null，被程序正确拒绝。"
  source: artifacts/debug/door_15600_required_threshold_v8.json
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T02:23:33
  kind: decision
  summary: "跨文档引用在离线metadata中显式建模为cross_document_references(target_document,target_locator)，经SearchHit和EvidenceHistoryItem传给控制器；state额外聚合pending_cross_document_references，实际在目标文档以locator检索后自动移除。"
  source: "用户确认与table_000031 metadata、history/controller实现"
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T02:23:33
  kind: evidence
  summary: "Door15600 v10验证跨文档链路成功：首轮南京table_000031携带中小学规范/表8.2.3引用，第二轮controller原样切换目标文档并查询表8.2.3，召回text_000092、text_000097和目标table_000012（第3）。最终因occupant_load缺失阈值仍为null，模型错误finish被schema拒绝。"
  source: artifacts/debug/door_15600_pending_reference_v10.json
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T02:29:08
  kind: evidence
  summary: "Door15600重新解析occupant_load=100；v11检索成功从南京引用切换中小学表8.2.3并finish阈值900mm，不再因人数缺失终止。但controller把表8.2.3每100人系数与8.2.4单门0.90m混合为900mm，且未处理耐火等级条件，阈值准确性仍需后续修正。"
  source: artifacts/debug/door_15600_default_occupant_100_v11.json
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T02:33:44
  kind: decision
  summary: "同一IFC模型内采用分层复用：规范原始证据可跨门复用；解析后的适用规则按建筑类型、楼层分组、用途、耐火等级、门分类等上下文签名缓存；门宽与PASS/FAIL仍逐门确定性计算。"
  source: "用户提出同模型首门检索结果复用，经架构讨论确认"
  affects: [regulation-hybrid-search]

- time: 2026-07-18T02:35:41
  kind: decision
  summary: "检索证据缓存提升为建筑级共享证据池：同一IFC建筑、同一检查任务、同一建筑用途及规范集合版本下，所有疏散门复用同一EvidenceBundle；楼层、门宽、防火属性和疏散人数不进入证据缓存键，只用于后续证据适用性解析和逐门计算。证据不足时增量检索并合并回共享池。"
  source: "用户明确希望同栋school内疏散门复用首个样本的检索证据"
  affects: [regulation-hybrid-search]

- time: 2026-07-18T02:40:59
  kind: evidence
  summary: "已实现src/search/iterative/building_evidence_cache.py：以project_id、building_type、task和文档集合构成建筑级键，首个已确认疏散门finish后缓存完整原始evidence_history/query_history；后续命中在构造LLM与检索器前返回。不同building不复用，非疏散门拒绝，insufficient结果不写缓存。完整测试79 passed。"
  source: 2026-07-18 building evidence cache implementation and tests
  affects: [regulation-hybrid-search]

- time: 2026-07-18T13:02:31
  kind: evidence
  summary: "按spec.md审计当前进度：T1领域模型和T2三份真实IFC解析已完成；T3的检索、VLM规则抽取、校验、沙箱和缓存代码已实现，但最新通用引用改造后尚未完成Door 15600真实规则生成验证，因此正式里程碑仍停在已完成T2、正在T3；T4尚未满足3种门型和5组宽度验收，T5/T6未实现。"
  source: "2026-07-18 spec.md与当前源码/测试审计"
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T13:11:09
  kind: note
  summary: "完成T3无需用户补充业务信息：Door 15600 v4已有扣减规则原图、表8.2.3原图、人数100、首层楼层带和默认一级耐火等级。剩余工程缺口是让规则debug CLI兼容纯检索报告的result结构、正确标注多模态rule_extraction调用以便重放，并以真实VLM生成一个通过schema/证据/AST校验的ExecutableRule；T3验收止于规则生成与可执行性验证，不要求在本阶段报告PASS/FAIL。"
  source: "2026-07-18 T3完成条件审计"
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T13:33:12
  kind: reversal
  summary: "撤回T3真实规则调试中新增的参数证据自动绑定、标量来源重绑、字面量改写、额外证据筛选和扩展静态校验；这些逻辑把VLM输出问题错误扩大为后处理架构。恢复单一模态边界：text发送正文，table/image仅发送定位元数据与原图，绝不发送其OCR content或summary。"
  source: "用户于2026-07-18纠正T3修复方向"
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T14:13:04
  kind: reversal
  summary: "重新划分T3/T4边界：T3仅保留多模态证据充分性判断与证据不足时的查询改写/多跳检索；T3 VLM只输出实际净宽计算证据和规范阈值计算证据的就绪布尔值、证据ID及必要的下一轮查询，不再判断阈值类型、抽取规范参数、声明规则输入或生成Python。原Rule Extraction VLM及规则生成/执行职责移入T4后续设计。"
  source: "用户于2026-07-18明确要求解耦T3和T4"
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T14:20:38
  kind: evidence
  summary: "已完成T3/T4边界重构：IterativeRetrievalResult与BuildingEvidenceBundle作为T3输出持久化两组calculation_ready及证据ID，BuildingEvidenceResolution在首次检索和缓存命中时统一返回两项判断；T4入口在任一判断为false时于规则生成VLM调用前拒绝。Door15600 T3 debug新增显式t3_summary，spec.md同步重写，完整测试109 passed。"
  source: 2026-07-18 T3 evidence-sufficiency refactor and pytest
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T14:26:13
  kind: evidence
  summary: "重构后Door15600真实T3验证成功：2轮检索、3次模型调用、累计10条证据，最终actual_clear_width_calculation_ready=true（南京table_000017，首轮第1）且required_clear_width_calculation_ready=true（中小学table_000012第二轮第1，并引用text_000092/000097）；跨文档桥接table_000031首轮第3。T3返回finish，不进入T4。"
  source: artifacts/debug/door_15600_t3_evidence_sufficiency_real.json
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T14:34:33
  kind: decision
  summary: "T3最终证据输出收缩：每条证据以iter标记首次检索轮次，新检索结果每轮仅保留Top 3进入证据池；Controller及T3终态契约移除found_evidence，避免将模型生成的数值结论传给后续模块。旧retrieved_at_hop仅作为历史报告读取兼容。"
  source: "用户于2026-07-18明确要求"
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T14:40:03
  kind: evidence
  summary: "已实现T3证据输出收缩：EvidenceHistoryItem新输出iter并兼容读取旧retrieved_at_hop；SearchConfig默认Top K由5改为3；found_evidence从Controller Prompt、Decision和终态Result移除，旧模型字段在校验前丢弃。完整测试110 passed。Door15600真实复测确认关键证据均留在Top3（首轮table_000017/table_000031，第二轮table_000012/text_000092/text_000097），但第二轮VLM返回finish+required_ready=false且缺reason，被严格schema拒绝，属于独立Controller稳定性问题。"
  source: "2026-07-18 implementation; artifacts/debug/door_15600_t3_top3_iter.json"
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T14:54:30
  kind: evidence
  summary: "T3正式完成并通过Door15600真实验收：Controller新增最多3次的schema/state修复重试且不消耗检索hop；完整测试111 passed。最终真实报告2轮Top3检索、6条带iter证据、无found_evidence/无retrieved_at_hop，action=finish，actual与required两项ready均为true；实际证据table_000017，阈值证据table_000012/text_000092/text_000097。"
  source: artifacts/debug/door_15600_t3_complete.json
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T15:08:05
  kind: decision
  summary: "T4重构为证据去重校验、逐字段直接值或脚本规划、受限执行回填和确定性比较四层；沿用actual_clear_width_mm与required_clear_width_mm作为最终数值字段，脚本仅存在于中间计划，最终按actual>=required判定。"
  source: "用户于2026-07-18提出T4新设计，经现有schema与沙箱边界审查确认"
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T16:54:56
  kind: decision
  summary: "检索边界的防火门状态收敛为单一布尔is_fire_door：上游分类无法确认时进入T3前统一解析为false，Query Rewriter与Controller不再看到raw/effective/resolution并列字段。T3每轮严格执行检索、证据充分性判断、用本轮missing_evidence替换下一轮missing_information；删除T3内OverallWidth扣减计算及其旧字段与测试夹具。全量测试114 passed。"
  source: "用户于2026-07-18明确要求与实现验证"
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T17:00:03
  kind: evidence
  summary: "单一is_fire_door与逐轮missing_information更新后，Door15600真实T3复测正常执行3轮但最终insufficient：检索已在首轮Top2取得含100/150mm扣减规则的南京table_000017，并在第二轮Top1取得中小学表8.2.3的table_000012；VLM未把table_000017右侧说明栏识别为实际净宽计算证据，最终actual_ready=false。required_ready在第二轮修复响应中曾为true，但最终响应漏引table_000012，仅引用会转引表8.2.3的text证据，被契约降为false。missing_information已确认从初始缺口更新为本轮missing_evidence。"
  source: artifacts/debug/door_15600_t3_fire_missing_contract.json
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T17:15:21
  kind: reversal
  summary: "多模态证据边界调整：table/image的visual_evidence文本块除定位字段外同时发送索引中的content与summary，随后仍发送detail=high的原图；text证据保持只发送正文。OCR与摘要用于辅助VLM定位和理解，原图仍随同提供。"
  source: "用户于2026-07-18确认并实现"
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T17:15:21
  kind: evidence
  summary: "加入视觉content/summary后Door15600真实T3复测成功：2轮检索、3次LLM调用、6条证据，首轮table_000031排名1，第二轮table_000012排名1；终态finish，actual与required两项ready均为true。table_000031实际发送字段包含evidence_id/document_id/page/title/cross_document_references/modality/content/summary，content长度1058、summary长度884。全量测试114 passed。"
  source: artifacts/debug/door_15600_t3_visual_content_summary.json
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T17:19:53
  kind: evidence
  summary: "按当前spec.md审计T4：ExecutableRule schema、VLM抽取、输入白名单解析、AST校验、隔离执行、规则缓存和确定性PASS/FAIL均已有代码及单测；但T4正式验收未完成。最新真实规则生成报告door_15600_t3_real_rule_generation_v5在代码/表选择校验失败，唯一成功的door_15600_rule_replay_success是重放旧规则且得到错误阈值900mm，不能作为当前验收。尚缺使用最新T3 table_000031+table_000012证据生成2900/700并PASS的真实链路，以及至少3种门型和5组宽度组合的验收矩阵。"
  source: "2026-07-18 spec.md与src/rules当前源码审计"
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T18:26:51
  kind: reversal
  summary: "撤销T4通用规则规划器：不再抽完整表头、构造跨楼层/耐火等级lookup、声明运行时输入参数或缓存规则计划；删除planner、input_registry、input_resolver和rule_cache。"
  source: "用户于2026-07-18纠正过度设计并要求删除"
  affects: [regulation-hybrid-search]

- time: 2026-07-18T18:26:51
  kind: decision
  summary: "T4收缩为两次当前门直接脚本生成：每次VLM仅接收T3 initial_query、单一target_field及该字段证据，输出无参数calculate_value；AST校验、隔离执行及actual>=required比较保持确定性。"
  source: "2026-07-18用户确认与实现"
  affects: [regulation-hybrid-search]

- time: 2026-07-18T18:26:51
  kind: evidence
  summary: "简化后聚焦测试17项、全量测试107项通过；真实Door15600暂未重跑，因为现存T3报告initial query未包含OverallWidth=3000mm、非防火门、一级耐火等级和occupant_load=100，需下一步单独调整initial query生成。"
  source: "2026-07-18 pytest与旧T3报告审计"
  affects: [regulation-hybrid-search]

- time: 2026-07-18T18:33:40
  kind: decision
  summary: "T4保持共享证据与逐门事实分离：服务将当前门IFCContext确定性转换为精简计算上下文，并与字段证据共同传给脚本生成VLM；不把逐门事实写入BuildingEvidenceBundle。"
  source: "用户于2026-07-18确认"
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T18:35:31
  kind: evidence
  summary: "已接通T4逐门计算上下文：服务从IFCContext构造精简强类型上下文，按actual/required目标裁剪后与对应证据共同发送给VLM；聚焦测试10项、全量测试108项通过。"
  source: "2026-07-18实现与pytest验证"
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T18:43:17
  kind: evidence
  summary: "发现T4实际净宽直接值路径尚未贯通：current_door_context虽含explicit_clear_width_mm，但Prompt未明确优先直接使用；T3/T4 schema又强制实际净宽证据ID非空，导致IFC已有明确净宽时仍被迫依赖规范换算证据。"
  source: "2026-07-18用户审查T4 Prompt与源码契约"
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T18:53:00
  kind: reversal
  summary: "T4 MVP不再由服务对explicit_clear_width_mm做确定性短路；actual与required两个字段均由VLM先选择direct_value或python_script。实际净宽上下文额外暴露原始IFC extra_info以兼容模型特有净宽字段名，同时禁止直接把OverallWidth视为净宽。"
  source: "用户于2026-07-18修正MVP方案并完成实现"
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T18:53:22
  kind: evidence
  summary: "T4双字段direct_value/python_script契约已通过11项聚焦测试和109项全量测试；测试覆盖两个字段均直接返回值、两个字段均生成脚本、原始IFC extra_info进入实际净宽VLM上下文及确定性最终比较。"
  source: "2026-07-18 pytest验证"
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T18:57:07
  kind: evidence
  summary: "真实Door15600 T4双模式运行完成：actual首轮生成3000-100脚本并得2900；required首轮正确选择表8.2.3生成700脚本，但因使用int()被AST白名单拒绝，两次修复后模型改为直接引用text_000097的900，最终输出2900>=900 PASS，未达到既定700目标。"
  source: artifacts/debug/door_15600_t4_direct_or_script_real.json
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T19:02:11
  kind: evidence
  summary: "T4 AST白名单加入int后真实Door15600仅2次VLM调用即成功：actual脚本3000-100=2900，required脚本按表8.2.3计算int(0.70*1000)=700，最终2900>=700 PASS。该实验同时暴露逐函数白名单对MVP造成无意义修复重试，后续应考虑改为仅禁止危险能力。"
  source: artifacts/debug/door_15600_t4_int_allowed_real.json
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T19:17:53
  kind: decision
  summary: "T5 MVP收缩为单次证据驱动详细理由生成：输入T4权威计算结果、转换后的逐门上下文、计算模式/脚本和T4实际使用的T3原始证据；输出仅detailed_reason与evidence_ids，不生成Markdown、不重新计算或改变结论。"
  source: "用户于2026-07-18确认并实现"
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T19:17:53
  kind: evidence
  summary: "T4新增field_evidence_ids统一保存direct/script逐字段来源；T5聚焦测试14项、全量测试112项通过。真实Door15600 T5调用依据2900/700与四条T4实际引用证据生成中文详细理由并返回合法证据ID。"
  source: "2026-07-18 pytest与真实VLM验证"
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T19:20:31
  kind: decision
  summary: "T5最终JSON新增result字段，但PASS/FAIL唯一真值仍由T4确定性actual>=required比较产生；T5程序从check_result.result原样复制，VLM只生成detailed_reason与evidence_ids。"
  source: "用户于2026-07-18确认并实现"
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T19:23:05
  kind: decision
  summary: "T5展示层采用固定状态映射：T4继续以PASS/FAIL保存确定性机器结果，T5程序将PASS映射为合格、FAIL映射为不合格，并把同一中文结果传给详细理由VLM；VLM不生成或修改result。全量测试113 passed。"
  source: "用户于2026-07-18确认与实现验证"
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T19:27:52
  kind: evidence
  summary: "虚构Door15600仅将OverallWidth覆盖为700mm后完成真实T3/T4/T5验证：T3两轮检索且actual/required readiness均为true；T4生成700-100脚本得实际净宽600mm，按表8.2.3计算阈值700mm，确定性结果FAIL；T5固定映射输出不合格并生成一致的证据理由。调试覆盖不修改原始IFC/JSONL，全量测试114 passed。"
  source: "artifacts/debug/door_15600_width700_t3.json, door_15600_width700_t4.json, door_15600_width700_t5.json"
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T19:38:35
  kind: note
  summary: "用户提出在T3建筑级证据复用之上增加T4结果复用：同项目、同建筑类型、同疏散门任务命中T3缓存后，若当前门所有T4计算相关上下文也相同则跳过T4 VLM。安全实现不能只比较门宽、楼层、人数，还需覆盖防火门状态、耐火等级、显式净宽/extra_info及来源字段；缓存应排除door_id并在命中时为新门重建确定性CheckResult。该功能尚未实现。"
  source: "2026-07-18用户方案讨论"
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T19:44:10
  kind: decision
  summary: "已实现T4批内结果缓存src/rules/result_cache.py：键由T3证据指纹及门宽、显式净宽/来源、防火门状态、建筑/楼层、耐火等级/来源、人数/来源组成，明确排除door_id与ifc_extra_info。命中后跳过T4 VLM和脚本沙箱，复用计算产物并为当前door_id确定性重建CheckResult；任一纳入字段变化则正常执行T4。只缓存无执行错误且具有完整PASS/FAIL的结果。全量测试127 passed。"
  source: "2026-07-18用户确认与实现验证"
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T19:56:57
  kind: evidence
  summary: "小学真实IFC解析顺序前10扇门完成T1-T5分阶段验证：T1/T2全部10扇schema与身份匹配通过，IFC共57门且解析无错误；分类中4扇confirmed evacuation_door、6扇uncertain按边界等待用户确认。T3由Door31668真实2轮检索一次并被其余3扇复用，关键排名首轮table_000031第1/table_000017第2，第二轮table_000012第1。T4三组唯一上下文执行并缓存，Door43970复用Door2610结果；四扇分别得到1500/700、2900/700、1100/700、1100/700且均PASS。T5四次输出合格，数值、映射和证据边界校验全部通过；全量测试127 passed。"
  source: artifacts/debug/primary_school_first10_t1_to_t5_summary.json
  affects: [regulation-hybrid-search, domain-schema-contract]

- time: 2026-07-18T20:00:49
  kind: note
  summary: "T6规划建议待用户确认：当前MVP优先使用Streamlit单体UI直接调用独立application/review service，不同时引入FastAPI。T3/T4缓存必须放在每个上传会话的session state中，DocumentCatalog等只读重资源才可全局缓存；页面流程为IFC上传、解析与分类、uncertain门人工勾选、批量检查进度、结果/证据详情和JSON下载。若未来需要多客户端、独立部署或任务队列，再增加FastAPI边界。"
  source: "2026-07-18 T6架构讨论"
  affects: [regulation-hybrid-search, domain-schema-contract]
