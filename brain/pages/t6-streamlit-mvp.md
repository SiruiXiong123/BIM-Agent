---
id: t6-streamlit-mvp
title: "T6 Streamlit Web MVP 初版方案"
category: decision
status: active
tags: [t6, streamlit, web, mvp]
created: "2026-07-18T20:06:06"
updated: "2026-07-19T01:07:13"
---

## compiled_truth

- T6 初版只采用 Streamlit，不同时引入 FastAPI；业务边界保持为 `src/review/models.py` 数据契约、`src/review/service.py` 编排 T1–T5、`app/main.py` 页面交互。
- 页面流程为：上传 IFC → T1 解析与 T2 分类 → 用户确认 uncertain 门和疏散人数 → T3 迭代检索 → T4 规则计算 → T5 中文结果与理由 → JSON 审计结果下载。
- `uncertain` 门默认不进入 T3；用户勾选后保留原始分类，并记录 `effective_classification=evacuation_door` 和 `classification_source=user_confirmation`。
- T2 默认最大并发 4；T3 按项目、建筑类型和任务分组，同组复用证据；T4 按证据指纹及门宽、楼层、人数等完整计算输入复用；T3/T4 组间与 T5 逐门理由生成默认最大并发均为 4，最终恢复原始门顺序并隔离单门错误。
- `BuildingEvidenceCache` 和 `T4ResultCache` 按一次 IFC 上传及 Streamlit 会话隔离；新上传必须清空旧 preparation、result 和两级缓存，禁止跨项目串用。
- T1/T2 `ReviewPreparation` 支持带哈希及分类器签名校验的本地快照，并通过 `?resume=<token>` 恢复模块 2；快照不持久化 T3/T4 会话缓存。
- 页面结果表只展示实际净宽、规范阈值和“合格/不合格”，不展示 `machine_result`；`machine_result` 仍保留在后端和下载 JSON 中用于确定性审计。
- 所有真实模型调用统一通过 `OpenAICompatibleJSONClient`：首次失败后最多重试 3 次，指数退避 0.5/1/2 秒；仅重试连接/超时、429、408/409、5xx 及 ALB HTML 400，确定性请求格式 400 不重试，SDK 内建重试关闭。
- GitHub 本地运行统一入口为 `python -m src.main`。入口先校验 Python、`.env`、嵌入模型与索引、BM25/FAISS 文件、原始表格/图片证据以及 `eval/primary_school_door_width_eval.ifc`，然后使用当前虚拟环境解释器启动 Streamlit 并打开浏览器；`python -m src.main --check` 只检查、不启动服务或调用模型。
- 规则沙箱使用 `sys.executable`，不得硬编码开发者本机 Python 路径。`.env` 不入库，`.env.example` 提供键模板；IFC/PDF 使用 Git LFS，运行产物、临时下载和索引清理备份不入库。
- `eval/primary_school_door_width_eval.ifc` 前 10 门的基准包含 4 扇确认疏散门；Door2610 应得到实际净宽 600mm、阈值 700mm、不合格，Door43970 应得到实际净宽 500mm、阈值 700mm、不合格。
- 该决策延续 [[regulation-hybrid-search]] 的 T3/T4 复用边界及 [[domain-schema-contract]] 的字段约束。


## timeline

- time: 2026-07-18T20:06:06
  kind: decision
  summary: "Created this page: T6 Streamlit Web MVP 初版方案"
  source: "2026-07-18用户确认写入初版决策"
  affects: [t6-streamlit-mvp]

- time: 2026-07-18T20:06:19
  kind: decision
  summary: "记录T6 Streamlit Web MVP的初版模块、流程、缓存边界与验收顺序"
  source: "2026-07-18用户要求将初版方案写入记忆"
  affects: [t6-streamlit-mvp]

- time: 2026-07-18T20:06:43
  kind: decision
  summary: "修正初版决策正文的UTF-8编码并保留原有内容"
  source: "2026-07-18 Brain CLI编码校验"
  affects: [t6-streamlit-mvp]

- time: 2026-07-18T20:11:16
  kind: evidence
  summary: "完成 T6.1 框架无关数据契约：准备、选择、逐门输入、进度、逐门结果和批量结果；新增10项契约测试，全套137项测试通过。"
  source: 2026-07-18 T6.1 implementation
  affects: [t6-streamlit-mvp]

- time: 2026-07-18T20:45:22
  kind: decision
  summary: "T6 初版架构决策与分阶段校验声明只保存在 Project Brain，不写入 spec.md；spec.md 只保留正式任务级目标、文件范围和整体验收。"
  source: "2026-07-18 用户纠正 T6 文档边界"
  affects: [t6-streamlit-mvp]

- time: 2026-07-18T20:54:20
  kind: evidence
  summary: "完成 ReviewService.prepare_ifc()：复用 T1 parse_ifc 与 T2 classify_evacuation_door，生成候选门、原始分类、置信度、用户确认标记和进度事件，不进入 T3-T5。学校 IFC 前10门验证为4扇疏散门、6扇 uncertain；全套139项测试通过。"
  source: 2026-07-18 T6 prepare_ifc implementation
  affects: [t6-streamlit-mvp]

- time: 2026-07-18T20:58:08
  kind: decision
  summary: "T6 前端允许用户填写正整数 N 或字符串 all：N 表示仅让 IFC 中按稳定原始顺序排列的前 N 扇门进入 T1/T2，all 表示处理全部门。UI 负责解析输入，ReviewService 接收 int 或 None，IFC parser 需要可选上限以避免先解析全部门。"
  source: "2026-07-18 用户新增样本数量选择要求"
  affects: [t6-streamlit-mvp]

- time: 2026-07-18T21:07:05
  kind: decision
  summary: "T6 准备页以可编辑表格展示门ID、OverallWidth、疏散门分类、置信度和疏散人数。confirmed evacuation_door 自动进入后续流程；uncertain 默认不选，用户可逐行勾选加入；人数可逐门覆盖，未修改时沿用默认值。用户点击 NEXT 后提交当前选择，即使未做任何操作也继续执行。"
  source: "2026-07-18 用户确认准备页交互设想"
  affects: [t6-streamlit-mvp]

- time: 2026-07-18T21:11:13
  kind: evidence
  summary: "完成后端门样本数量控制：parse_ifc 和 ReviewService.prepare_ifc 接收 max_doors 正整数或 None；限制在详细门提取前生效，结果记录 total_ifc_door_count、requested_max_doors 和实际 door_count。学校 IFC 验证 N=10 时总数57/处理10，None 时处理57；全套147项测试及5个subtests通过。"
  source: 2026-07-18 T6 sample limit implementation
  affects: [t6-streamlit-mvp]

- time: 2026-07-18T21:16:33
  kind: evidence
  summary: "完成 ReviewService.build_review_inputs：自动加入已确认疏散门，仅加入用户勾选的 uncertain 门，排除 non-evacuation；逐门应用人数/耐火等级覆盖并记录 user 来源，缺失防火门默认 false、缺失耐火等级默认一级。学校前10门验证无操作进入4门，勾选 Door 5432 后进入5门；全套155项测试及5个subtests通过。"
  source: 2026-07-18 T6 selection resolver implementation
  affects: [t6-streamlit-mvp]

- time: 2026-07-18T21:24:28
  kind: evidence
  summary: "完成 T6 到 T3 的 context_builder：DoorReviewCandidate 直接保留现有 ClassifiedEvacuationDoorRecord，build_ifc_context 应用用户确认和覆盖值后生成既有 IFCContext；原始分类不变，明确净宽与 OverallWidth 分离。学校前10门中5个有效输入转换成功，Door15600人数120进入上下文且clear_width保持null；全套158项测试及5个subtests通过。"
  source: 2026-07-18 T6 IFCContext adapter implementation
  affects: [t6-streamlit-mvp]

- time: 2026-07-18T21:32:05
  kind: evidence
  summary: "完成 run_t3_batch：优先使用LLM确认门作为代表执行T3，结果按UI原顺序返回，同项目同建筑证据通过BuildingEvidenceCache复用，逐门保留IFCContext并隔离错误。学校前10门加选Door5432回放真实证据：Door31668建立缓存，其余4门cache hit/跳过LLM，两个ready均true；全套164项测试及5个subtests通过。"
  source: 2026-07-18 T6 T3 batch runner implementation
  affects: [t6-streamlit-mvp]

- time: 2026-07-18T21:41:59
  kind: evidence
  summary: "T6 T4 batch runner completed: it consumes ordered T3 door runs, skips T3 failures or insufficient evidence, executes or exactly reuses T4 results through T4ResultCache, isolates per-door failures, preserves UI order, and emits T4 progress. School first-10 replay produced 3 executions and 1 cache hit for 4 confirmed evacuation doors; Door 43970 reused Door 2610 result and skipped LLM/sandbox. Full suite: 167 passed plus 5 subtests."
  source: 2026-07-18 T6 T4 batch runner implementation
  affects: [t6-streamlit-mvp]

- time: 2026-07-18T21:50:26
  kind: evidence
  summary: "完成 T6 T5 批处理层 run_t5_batch：逐门将 T4 成功结果交给既有详细理由生成器，组装 DoorReviewResult/ReviewBatchResult，保留 T3/T4 缓存状态；证据不足映射为 SKIPPED，上游或T5异常映射为单门ERROR且不终止批次。学校前10门中4个确认疏散门重放全部合格，Door43970保留双缓存命中；全套170项测试及5个subtests通过。"
  source: 2026-07-18 T6 T5 batch runner implementation
  affects: [t6-streamlit-mvp]

- time: 2026-07-18T21:53:26
  kind: decision
  summary: "最终 Streamlit 结果表不展示 machine_result 列，只展示用户可理解的 display_result（合格/不合格）；machine_result 仍保留在后端 ReviewBatchResult 和可下载 JSON 中，用于确定性审计、调试与状态映射。"
  source: "2026-07-18 用户确认最终展示列"
  affects: [t6-streamlit-mvp]

- time: 2026-07-18T21:59:27
  kind: evidence
  summary: "完成统一后端入口 ReviewService.run_review：接收 ReviewPreparation、ReviewSelection 和会话级 BuildingEvidenceCache/T4ResultCache，依次调用 build_review_inputs、T3、T4、T5，复用独立 review_client 并转发进度，最后发出 COMPLETE 事件和 ReviewBatchResult。阶段 runner 可注入以支持回放测试。学校前10门统一入口重放为10门准备、4门进入、4门合格，Door43970保留T3/T4双缓存命中；全套172项测试及5个subtests通过。"
  source: 2026-07-18 T6 unified ReviewService.run_review implementation
  affects: [t6-streamlit-mvp]

- time: 2026-07-18T22:06:03
  kind: evidence
  summary: "新增 eval/primary_school_door_width_eval.ifc 作为页面与端到端失败样本：复制小学IFC语义结构，仅将 Door2610 OverallWidth 从1200改为700mm、Door43970从1200改为600mm。源文件哈希保持不变；副本IFC4、57门、445204实体，逐实体差异仅2条目标IfcDoor；parse_ifc无错误。eval/README.md记录来源、修改和哈希。"
  source: "2026-07-18 用户要求构造小学门宽评估IFC"
  affects: [t6-streamlit-mvp]

- time: 2026-07-18T22:41:24
  kind: decision
  summary: "将Streamlit前端三个模块及其初版验收标准写入T6当前决策正文"
  source: "2026-07-18用户确认前端初版决策"
  affects: [t6-streamlit-mvp]

- time: 2026-07-18T23:10:54
  kind: evidence
  summary: "Streamlit上传与准备页面已完成运行验收：Streamlit 1.41.1、NumPy 1.26.4、IfcOpenShell 0.8.5兼容，localhost:8501返回HTTP 200，页面控件正常渲染且浏览器控制台无错误。"
  source: "2026-07-18 本地运行与浏览器验收"
  affects: [t6-streamlit-mvp]

- time: 2026-07-18T23:21:55
  kind: evidence
  summary: "完成Streamlit门确认与参数修改模块：表格式展示门ID、OverallWidth、分类、置信度、疏散人数和加入选项；确定疏散门固定加入、uncertain可勾选、非疏散门禁选，人数覆盖只作用于进入流程的门；NEXT生成ReviewSelection但不提前执行T3。移除data_editor/PyArrow依赖，采用逐行原生控件。全套189项测试及5个subtests通过。"
  source: 2026-07-18 T6 Streamlit module 2 implementation
  affects: [t6-streamlit-mvp]

- time: 2026-07-19T00:02:16
  kind: decision
  summary: "加入T2默认并发4和T1/T2可恢复快照边界"
  source: "2026-07-18用户要求避免重复LLM并将分类改为并发4"
  affects: [t6-streamlit-mvp]

- time: 2026-07-19T00:02:16
  kind: evidence
  summary: "完成并验证T2并发分类与模块2恢复链接：默认最大并发4、输出仍保持IFC顺序；评估IFC前10门通过既有分类材料恢复为4疏散门/6待确认，Door2610=700mm、Door43970=600mm；模块2页面无LLM调用，完整测试197项及5个subtests通过。"
  source: 2026-07-18 implementation and browser verification
  affects: [t6-streamlit-mvp]

- time: 2026-07-19T00:21:41
  kind: decision
  summary: "完成T3-T5缓存分组并发和Streamlit最终执行结果模块"
  source: 2026-07-19 final T6 implementation
  affects: [t6-streamlit-mvp]

- time: 2026-07-19T00:42:43
  kind: decision
  summary: "加入统一模型请求的三次指数退避重试策略"
  source: "2026-07-19 用户确认最多重试3次"
  affects: [t6-streamlit-mvp]

- time: 2026-07-19T00:54:54
  kind: decision
  summary: Restore UTF-8 truth and record portable launcher
  source: 2026-07-19 GitHub readiness work
  affects: [t6-streamlit-mvp]

- time: 2026-07-19T01:07:13
  kind: evidence
  summary: "完成根目录中文README、MIT LICENSE和开发测试依赖文件；README覆盖快速启动、eval验收、目录、架构、部署边界、技术栈与常见问题。"
  source: 2026-07-19 GitHub README implementation
  affects: [t6-streamlit-mvp]
