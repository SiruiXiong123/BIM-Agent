---
id: domain-schema-contract
title: Domain schema contract
category: decision
status: active
tags: [schema, pydantic, units]
created: "2026-07-17T12:31:39"
updated: "2026-07-18T13:01:32"
---

## compiled_truth

- Domain entities, executable rules, AI classifications, derived assessments, check results, and iterative-retrieval state use strict Pydantic v2 schemas with unknown fields rejected and assignment validation enabled where stateful.
- `Door` represents IFC facts in millimetres; `IfcDoor.OverallWidth` is never clear width. Clear width remains a separate deterministic `ClearWidthResolution` and missing width yields UNKNOWN.
- `IFCContext` is the task-relevant retrieval snapshot: subject, building context, door facts, structured evacuation classification, deterministic clear-width resolution, missing information, and data-quality warnings. It excludes raw geometry, classification prose reasoning, user queries, regulation evidence, and final compliance conclusions.
- `IFCContext` requires the clear-width resolution IFC GUID to match the subject IFC GUID. Door 15600 round-trips with overall width 3000 mm and unresolved clear width.
- Iterative retrieval has exactly three actions in the current phase: `search`, `finish`, and `insufficient_evidence`. Only `search` may carry a query and target document; terminal actions require both to be null.
- Evidence identity is deterministic as `<document_id>:<content_id>` and every item retains document, modality, page/asset provenance, score, retrievers, and retrieval hop. Query and terminal result evidence IDs must resolve to real evidence history entries.
- `IterativeRetrievalState` is resumable and validates unique available documents/evidence IDs, consecutive query hops, `hop == len(query_history)`, `hop <= max_hops`, document availability, and absence of future-hop evidence.
- The current sole retrieval target is `target_field="evacuation_door_clear_width_requirement"`; no duplicate task or search-concept fields are used.


## timeline

- time: 2026-07-17T12:31:39
  kind: decision
  summary: "Created this page: Domain schema contract"
  source: spec.md T1 implementation
  affects: [domain-schema-contract]

- time: 2026-07-17T12:31:39
  kind: decision
  summary: "Established the T1 schema, validation, unit, and result-status conventions"
  source: src/schemas and tests/test_schemas.py
  affects: [domain-schema-contract]

- time: 2026-07-17T12:50:10
  kind: decision
  summary: Expanded Door into comprehensive normalized and raw IFC information layers
  source: src/schemas/bim.py and tests/test_schemas.py
  affects: [domain-schema-contract]

- time: 2026-07-17T13:20:50
  kind: decision
  summary: Restricted Door to the semantic intersection of all three real IFC fixtures
  source: User decision and three-model IfcOpenShell audit
  affects: [domain-schema-contract]

- time: 2026-07-17T14:00:28
  kind: decision
  summary: Added the three-state string is_fire_exit business field
  source: User decision and src/schemas/bim.py
  affects: [domain-schema-contract]

- time: 2026-07-17T14:03:22
  kind: decision
  summary: Added flexible extra_info archive for model-specific door fields
  source: User decision and src/schemas/bim.py
  affects: [domain-schema-contract]

- time: 2026-07-17T14:34:18
  kind: decision
  summary: "Adopted millimetres, OverallWidth semantics, sourced extra_info, and separate AI/assessment schemas"
  source: User-approved architecture implementation
  affects: [domain-schema-contract]

- time: 2026-07-17T16:39:43
  kind: decision
  summary: Added standard door-to-space boundary facts to the Door contract
  source: User-approved IFC parser extension and three-fixture verification
  affects: [domain-schema-contract]

- time: 2026-07-17T17:03:09
  kind: decision
  summary: Unified the English classifier prompt and structured Pydantic output contract
  source: User-approved evacuation-door classification format
  affects: [domain-schema-contract]

- time: 2026-07-17T17:08:33
  kind: decision
  summary: Added standard building provenance and the reduced LLM classification input contract
  source: User-approved parser and classifier input extension
  affects: [domain-schema-contract]

- time: 2026-07-17T17:22:56
  kind: reversal
  summary: Replaced structured IfcBuilding identity with a minimal nullable building-type string
  source: User decision after reviewing non-semantic IfcBuilding names
  affects: [domain-schema-contract]

- time: 2026-07-17T17:22:56
  kind: decision
  summary: Adopted the minimal project-name then space-frequency building classifier
  source: User-approved three-fixture prototype rule
  affects: [domain-schema-contract]

- time: 2026-07-17T17:50:41
  kind: decision
  summary: Classifier prompt v2 gives explicit evacuation semantics in door names and types highest priority
  source: User decision and ten-door Qwen validation
  affects: [domain-schema-contract]

- time: 2026-07-17T21:56:21
  kind: decision
  summary: "分类批处理改为按 ifc_guid 将完整 EvacuationDoorClassification 嵌套回填到原门样本，形成单文件 ClassifiedEvacuationDoorRecord"
  source: "用户决定与实现"
  affects: [domain-schema-contract]

- time: 2026-07-17T23:46:26
  kind: decision
  summary: "新增 IFCContext 与严格的迭代检索状态、证据、查询和终止结果契约"
  source: "src/search/iterative/models.py 与 Door 15600 测试"
  affects: [domain-schema-contract]

- time: 2026-07-18T01:20:35
  kind: decision
  summary: "门语义分类的一次 LLM 调用同时输出疏散门分类与可空 is_fire_door；原 confidence 重命名为 evacuation_door_confidence，并新增可空 fire_door_confidence。两个判断复用同一 evidence，无法判断防火门时两个防火字段均为 null，并贯穿分类输出、RetrievalAssessment、IFCContext 和检索输入。"
  source: "src/schemas/assessment.py, prompt/evacuation_door_classification.py, src/search/models.py"
  affects: [domain-schema-contract, regulation-hybrid-search]

- time: 2026-07-18T01:28:42
  kind: decision
  summary: "保留 LLM 原始 is_fire_door=null，同时在 RetrievalAssessment 增加 effective_is_fire_door=false 与 fire_door_resolution=default_non_fire_door；检索缺失信息过滤已由默认策略解决的防火属性，控制器不得从规范文档查询具体 IFC 门的防火类型。"
  source: "用户确认与2026-07-18实现"
  affects: [domain-schema-contract, regulation-hybrid-search]

- time: 2026-07-18T01:41:24
  kind: evidence
  summary: "Door 15600宽度审计确认无单位解析错误：IFC4项目长度单位为米（scale-to-m=1），IfcDoor OverallWidth=3.0、Geometry.Width=3.0、门几何宽3.0000006m、关联IfcOpeningElement宽3.0m，且Opening surface=8.1m²与3.0×2.7一致；规范化为3000mm正确。"
  source: "test_sampe/00 - Primary school project (IFC).ifc direct IfcOpenShell geometry audit"
  affects: [domain-schema-contract]

- time: 2026-07-18T01:46:28
  kind: decision
  summary: "ClearWidthResolution采用两阶段确定性解析：无显式净宽时先标记pending_conversion_rule；检索证据同条同时包含防火门/其他门扣减值后，按effective_is_fire_door执行OverallWidth-deduction，写入扣减值、方法和evidence_ids，并从检索缺失项移除clear_width。"
  source: src/search/iterative/clear_width_enrichment.py and service.py
  affects: [domain-schema-contract, regulation-hybrid-search]

- time: 2026-07-18T02:05:20
  kind: reversal
  summary: "迭代检索移除target_field，改为单一动态task；当前任务为“收集能判断疏散门净宽是否符合适用规范的相关信息但不做任何判断”。不引入结构化requirements，decision/state/result仅新增去重累计的extra_info字符串列表。"
  source: "用户确认与2026-07-18实现"
  affects: [domain-schema-contract, regulation-hybrid-search]

- time: 2026-07-18T02:14:28
  kind: decision
  summary: "IterativeSearchDecision新增必传可空数值evacuation_door_minimum_clear_width_threshold_mm（毫米）；search/insufficient可为null，finish必须为非负具体数值，终态result同步携带。extra_info继续作为非必填判据相关信息列表。"
  source: "用户确认与src/search/iterative/models.py"
  affects: [domain-schema-contract, regulation-hybrid-search]

- time: 2026-07-18T02:29:08
  kind: decision
  summary: "Door新增正整数occupant_load；IFC Parser优先读取门及直接相邻IfcSpace的OccupantLoad/OccupancyNumber/NumberOfOccupants等人数属性，多个取最大值，缺失时按业务默认100。字段贯穿分类输入、RetrievalDoorFacts和IFCContext，且不再列为missing_information。"
  source: "用户确认与src/ifc_parser.py、schemas/search models实现"
  affects: [domain-schema-contract, regulation-hybrid-search]

- time: 2026-07-18T02:44:48
  kind: note
  summary: "待用户确认的T3/T4方案：LLM从建筑级EvidenceBundle抽取带evidence_ids的结构化可执行规则草案；clear_width与width_threshold由确定性执行器按直接值或受限公式计算，最终采用clear_width >= width_threshold为PASS、否则FAIL，缺参为UNKNOWN。避免运行模型任意生成的Python。"
  source: 2026-07-18 executable rule design discussion
  affects: [domain-schema-contract, regulation-hybrid-search]

- time: 2026-07-18T09:58:20
  kind: note
  summary: "用户希望保留LLM动态生成Python以适配不同规范计算方式。推荐边界调整为固定ABI、动态函数体：LLM生成纯函数规则代码，程序执行AST白名单、证据常量校验、输入字段校验后，在独立进程用llm_env解释器限时执行；LLM不直接判定PASS/FAIL。"
  source: 2026-07-18 generated rule code discussion
  affects: [domain-schema-contract]

- time: 2026-07-18T10:03:10
  kind: note
  summary: "生成规则执行前增加确定性RuleInputResolver：LLM在规则草案中声明required_inputs及来源类型，Resolver通过字段注册表从IFC parser事实、门分类结果、确定性派生值、RAG证据参数和用户覆盖中组装带provenance的执行输入；不得再由LLM逐门自由构造数值，缺失输入返回UNKNOWN。"
  source: 2026-07-18 rule execution input discussion
  affects: [domain-schema-contract]

- time: 2026-07-18T10:06:13
  kind: decision
  summary: "确认可执行规则架构：LLM从建筑级EvidenceBundle生成固定calculate_rule(inputs)->dict接口的动态Python及required_inputs/参数/evidence_ids；确定性RuleInputResolver组装IFC、分类、规则参数和用户值；AST验证后使用llm_env隔离子进程执行；rule_engine仅负责数值校验与actual_clear_width_mm >= required_clear_width_mm的PASS/FAIL，缺参或执行失败为UNKNOWN。"
  source: "用户于2026-07-18确认按该方案实施"
  affects: [domain-schema-contract, regulation-hybrid-search]

- time: 2026-07-18T10:16:42
  kind: evidence
  summary: "可执行规则链路已落地：扩展rule schema；新增rule_extraction prompt、LLM extractor、输入注册表/Resolver、AST validator、llm_env隔离runner、证据哈希规则缓存、service及确定性rule_engine。测试验证Door 15600样例3000-100=2900mm对900mm为PASS，另一门800-100=700mm为FAIL且复用规则跳过LLM；非法import、硬编码规范数值、未声明输入均被拒绝。完整测试85 passed。"
  source: 2026-07-18 executable rule implementation and tests
  affects: [domain-schema-contract, regulation-hybrid-search]

- time: 2026-07-18T11:01:52
  kind: evidence
  summary: "Door 15600真实测试确认混合检索证据正确，可从debug evidence bundle断点复用并实现0次重复检索；规则LLM仍会内联每100人除数且未真正按耐火等级选表列，必须由参数/语义/AST校验拒绝，缺少耐火等级时不得输出唯一阈值。"
  source: artifacts/debug/door_15600_rule_resume.json
  affects: [rule-extraction, iterative-retrieval, debugging]

- time: 2026-07-18T11:15:28
  kind: note
  summary: "用户提出在Search前增加项目输入解析接口：occupant_load保持唯一字段，IFC缺失时接收用户值、用户未填则默认100；建筑耐火等级同样先尝试IFC、再接收用户值、未填拟默认一级。实现前需增加来源provenance，因为当前occupant_load默认100与IFC真实100不可区分；并需确认默认一级属于有利假设的风险标记策略。"
  source: "2026-07-18 Door 15600安全契约与输入默认策略讨论"
  affects: [input-resolution, ifc-context, rule-execution, iterative-retrieval]

- time: 2026-07-18T11:21:16
  kind: decision
  summary: "确认规则输入与代码契约调整：采用B类自动参数提升，将LLM公式中可由证据验证的规范数字（如每100人的100）自动转换为带evidence_ids的输入参数；建筑耐火等级在Search前按IFC提取、用户补充、缺省一级的顺序解析并保留来源；暂不增加门耐火极限字段；可执行规则必须是通用规则，运行时根据fire_resistance_grade和楼层动态选择表8.2.3单元格。"
  source: "用户于2026-07-18确认"
  affects: [ifc-parser, input-resolution, rule-extraction, rule-validation, iterative-retrieval]

- time: 2026-07-18T11:42:14
  kind: evidence
  summary: "完成B类规则契约实现与Door 15600断点验证：证据支持的每100人公式常量可提升为参数；Search前按IFC、用户输入、默认值解析occupant_load与fire_resistance_grade；表8.2.3按storey_band和fire_resistance_grade动态选值。全量测试94 passed；保存的真实LLM响应离线重放得到actual_clear_width_mm=2900、required_clear_width_mm=900、PASS，且retrieval_calls=0。"
  source: artifacts/debug/door_15600_rule_replay_success.json
  affects: [src/rules/extractor.py, src/search/input_resolver.py, src/ifc_parser.py]

- time: 2026-07-18T11:45:24
  kind: decision
  summary: "疏散门宽度当前规则的width_threshold应由表8.2.3按occupant_load、storey_band和fire_resistance_grade计算；不得自动把证据池中其他条文抽取的0.90m门宽下限与表值做max合并。其他最低宽度约束只有在任务明确要求且通过适用性过滤后才能作为独立规则处理。"
  source: "用户对Door 15600重放结果中max(700,900)的纠正"
  affects: [rule-extraction, rule-compilation, evidence-applicability]

- time: 2026-07-18T12:06:17
  kind: evidence
  summary: "阈值链路已改为threshold_resolution三态契约：direct要求value_mm，calculated要求null value_mm和required_inputs，unresolved不能生成ExecutableRule；检索控制器允许calculated状态finish。删除了程序搜索900mm、固定解析表8.2.3和max合并的旧编译器，LLM必须输出证据参数与计算代码，程序仅验证输入、参数、证据和AST后执行。Door 15600受控规则测试得到2900mm对700mm；94项测试通过。真实模型已正确输出calculated且无900/max，但其生成器表达式、缺少扣减参数及表头错位被安全边界拒绝。"
  source: "src/schemas/rule.py,src/rules/extractor.py,artifacts/debug/door_15600_threshold_resolution_v3.json"
  affects: [rule-extraction, iterative-retrieval, rule-validation, debugging]

- time: 2026-07-18T12:10:34
  kind: decision
  summary: "LLM/VLM证据输入按模态分流：text证据发送文本；table和image证据不得把OCR/Markdown content或summary作为证据正文，而应解析asset_path并把对应原图作为多模态图片块发送给VLM，同时保留evidence_id、document_id、page、title和modality用于引用。非text证据原图缺失时不得静默回退为文本。该规则应用于读取evidence_history的迭代控制器和规则抽取器。"
  source: "用户于2026-07-18确认非text检索证据必须发送原图"
  affects: [openai-compatible-client, evidence-serialization, iterative-controller, rule-extraction]

- time: 2026-07-18T12:13:45
  kind: evidence
  summary: "新增EvidenceMediaResolver：按references根目录将table/image证据的asset_path严格解析为原始图片，校验路径边界、文件存在性和MIME类型；缺失或非法时显式失败，不回退OCR或summary。真实表8.2.3定位成功，全量99项测试通过。"
  source: "src/search/evidence_media.py与tests/test_evidence_media.py"
  affects: [domain-schema-contract, regulation-hybrid-search]

- time: 2026-07-18T12:22:42
  kind: evidence
  summary: "完成多模态证据输入链路：ReACT控制器与规则抽取器不再序列化完整evidence_history；text仅发送content与证据定位元数据，table/image通过EvidenceMediaResolver读取原图并发送Base64 image_url，只发送证据定位元数据而排除OCR content和summary，原图缺失显式失败。OpenAI兼容客户端新增多模态JSON接口，调试日志省略Base64。全量102项测试通过。"
  source: "src/ai/multimodal_evidence.py、openai_compatible_client.py、controller.py、rules/extractor.py"
  affects: [domain-schema-contract, regulation-hybrid-search]

- time: 2026-07-18T12:29:59
  kind: evidence
  summary: "Door 15600全链路真实重跑（未复用证据）执行1次混合检索和5次VLM调用：多模态输入正确发送5张南京表格原图且未发送OCR/summary，确定性clear_width已得到3000-100=2900mm；但ReACT把实际净宽可计算误判为阈值证据完整，在hop1提前finish，未跟随pending cross-document reference检索中小学规范表8.2.3。规则VLM随后臆造未召回的表证据ID和错误矩阵，并因缺少扣减参数被ExecutableRule校验拒绝，未产生最终比较。"
  source: artifacts/debug/door_15600_full_multimodal_rerun.json
  affects: [domain-schema-contract, regulation-hybrid-search]

- time: 2026-07-18T12:35:42
  kind: decision
  summary: "迭代检索终止条件改为强制区分实际净宽与规范要求净宽：分别维护actual_clear_width_mm和required_clear_width_mm；pending跨文档引用仅作为下一轮查询线索，不要求全部处理完毕。是否finish重点由这两个目标值及其证据是否已解决决定。"
  source: "用户于2026-07-18确认的ReACT终止语义"
  affects: [domain-schema-contract, regulation-hybrid-search]

- time: 2026-07-18T12:40:04
  kind: decision
  summary: "ReACT检索阶段不填写实际净宽或阈值数值，而分别判断actual_clear_width_evidence_ready与required_clear_width_evidence_ready，并为两者提供独立真实evidence_ids。仅两者均为true时进入规则抽取/匹配；达到max_hops但任一仍为false时返回insufficient_evidence，不调用规则抽取。pending跨文档引用不作为硬终止条件。"
  source: "用户于2026-07-18确认的检索与规则模块边界"
  affects: [domain-schema-contract, regulation-hybrid-search]

- time: 2026-07-18T12:56:15
  kind: evidence
  summary: "完成ReACT证据就绪重构并以Door 15600真实验证：检索决策/结果改为actual_clear_width_calculation_ready与required_clear_width_calculation_ready及各自evidence_ids；实际净宽就绪由程序根据ClearWidthResolution确定，两个均true才finish，max_hops仍未就绪则insufficient。显式表号查询增加精确定位优先通道，见表文本无原表时不得判阈值证据充分。真实运行2次混合检索：hop1召回南京扣减表后true/false，hop2将中小学规范table_000012表8.2.3原图排Top1并发送VLM，随后true/true并finish。全量104项测试通过。"
  source: artifacts/debug/door_15600_react_readiness_rerun_v4.json
  affects: [domain-schema-contract, regulation-hybrid-search]

- time: 2026-07-18T13:01:32
  kind: decision
  summary: "显式引用导航不得写死具体规范编号或局限于某张表；检索层统一解析表、条、章、图、附录和附件定位符，引用编号与目标文档必须来自已召回证据。规则抽取提示与校验文案也移除表8.2.3常量，按证据定义的通用查表计算处理。"
  source: "用户关于避免主模块过拟合的要求及2026-07-18通用引用定位重构"
  affects: [domain-schema-contract, regulation-hybrid-search]
