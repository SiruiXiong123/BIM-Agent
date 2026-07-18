"""Prompt for the first regulation-search query rewrite."""

QUERY_REWRITE_PROMPT = """
The input `task` is an information-collection task. Generate a regulation
search question that collects information needed for the later check. Do not
ask whether the IFC door passes, fails, complies, or satisfies a requirement,
and do not make any compliance judgment.
The query should collect both actual-value derivation rules and the applicable
benchmark or threshold needed for a later comparison.

你负责为建筑规范检索改写第一轮查询。

根据用户原始问题和 IFC 结构化事实，生成一个完整、自然、可直接用于
中文建筑规范检索的问题。问题应围绕 task、IFC 模型中门所属的建筑类型
以及所在楼层信息，说明当前对象和需要从规范中确认的
要求、适用条件、计算方法或所需数据。查询的目的是根据疏散门所属的
建筑类型、所在楼层信息寻找适用的
疏散门实际净宽计算规则和规范要求净宽阈值，而不是判断某个构件是否合规。
不得把总体宽度当成净宽度，不得补充输入中没有的事实，也不得直接判断合规。
只保留影响规范适用性、计算方法或阈值选择的 IFC 事实。
建筑类型和所在楼层必须保留。


target_document 已由程序根据用户问题和默认文档确定，必须原样返回。
仅输出以下 JSON，不要输出 Markdown 或其他文字：

{
  "query": "完整的中文自然语言检索问题，供BM25使用",
  "dense_query": "与query语义等价的完整英文自然语言问题，供dense检索使用",
  "target_document": "原样返回输入中的 target_document",
  "reason": "简要说明本轮查询关注什么"
}
""".strip()
