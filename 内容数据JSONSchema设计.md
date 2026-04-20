# 内容数据 JSON Schema 设计

对应标准文件：
[教材结构化内容.schema.json](/home/chenyixuan/口语对练/教材结构化内容.schema.json)

## 1. 这份 schema 解决什么问题

这份 schema 用来统一 4 件事：

1. PDF 解析后的标准输出结构
2. prompt 生成后的结构化内容落点
3. 审核流转需要依赖的状态字段
4. JSON/Markdown 导出前的数据基线

它的定位不是“页面专用结构”，而是整个系统的 `canonical data model`。

## 2. 顶层对象结构

顶层固定包含 5 个字段：

```json
{
  "job": {},
  "book": {},
  "units": [],
  "review_records": [],
  "export_meta": {}
}
```

含义如下：

- `job`
  解析任务本身，记录解析状态和整体审核状态
- `book`
  教材元信息
- `units`
  每个单元的完整内容包
- `review_records`
  审核记录流水
- `export_meta`
  导出范围、导出时间、导出限制

## 3. 单元级内容包结构

`units` 数组中的每一项都是一个 `UnitPackage`：

```json
{
  "unit": {},
  "vocabulary": [],
  "sentence_patterns": [],
  "dialogue_samples": [],
  "unit_task": {},
  "unit_prompt": {}
}
```

这样设计的原因是：

- 一个单元就是一个审核单元
- 一个单元也是一个导出单元
- 页面展示天然以单元为中心

## 4. 分类字段约束

你刚对齐的关键要求已经写进 schema：

- `textbook_version`
- `textbook_name`
- `unit_code`
- `unit_name`

这 4 个字段被统一收进 `classification` 对象，并且要求出现在：

- `unit`
- `vocabulary`
- `sentence_patterns`
- `dialogue_samples`
- `unit_task`
- `unit_prompt`

这样做的目的很直接：

- 每个导出板块都能单独携带教材和单元分类
- 后续如果按板块拆分导出，不会丢失归属信息
- 审核时也能直接按分类过滤

## 5. 各板块字段约束

### 5.1 `VocabularyItem`

关键字段：

- `word`
- `part_of_speech`
- `meaning_zh`
- `example_sentences`

控制字段：

- `classification`
- `source_pages`
- `source_excerpt`
- `confidence`
- `generation_mode`
- `review_status`

说明：

- 词汇允许解析抽取，也允许 prompt 规范化整理
- 不允许无依据新增核心词汇

### 5.2 `SentencePattern`

关键字段：

- `pattern`
- `usage_note`
- `examples`

控制字段：

- `classification`
- `source_pages`
- `source_excerpt`
- `confidence`
- `generation_mode`
- `review_status`

约束：

- `examples` 必须是 `1-2` 条例句

### 5.3 `DialogueSample`

关键字段：

- `turns`

`turns` 中的每一轮固定包含：

- `turn_index`
- `speaker`
- `text_en`
- `text_zh`

控制字段：

- `classification`
- `source_pages`
- `source_excerpt`
- `confidence`
- `generation_mode`
- `review_status`

约束：

- 每个对话样例必须是 `10-15` 轮
- 每一轮都必须同时有英文和中文
- 对话内容应基于本单元词汇、句型和主题生成或整理

### 5.4 `UnitTask`

关键字段：

- `task_intro`
- `source_basis`

约束：

- `task_intro` 设计为 `8-40` 字符，用来承载“20 字左右”的任务介绍
- 必须能回溯到当前单元内容依据

### 5.5 `UnitPrompt`

关键字段：

- `unit_theme`
- `grammar_rules`
- `prompt_notes`
- `source_basis`

说明：

 - 这个板块就是你说的“提示”
 - `unit_theme` 用于承载单元主题抽取
 - `grammar_rules` 用于承载语法规则抽取
 - `prompt_notes` 预留给补充提示

## 6. 三类核心状态

### 6.1 解析状态 `ParseStatus`

枚举值：

- `uploaded`
- `parsing`
- `structuring`
- `generating`
- `reviewing`
- `completed`
- `failed`

用途：

- 控制任务页的状态展示
- 控制什么时候允许进入审核

### 6.2 生成模式 `GenerationMode`

枚举值：

- `extracted`
- `normalized`
- `derived`
- `manual`

含义：

- `extracted`
  直接从教材内容抽取
- `normalized`
  基于教材原文做规范化整理
- `derived`
  基于解析内容推导生成
- `manual`
  人工修改后的结果

这个字段很重要，因为它能明确区分：

- 哪些内容是教材原始信息
- 哪些内容是经过 prompt 整理
- 哪些内容是后续推导或人工修订

### 6.3 审核状态 `ReviewStatus`

枚举值：

- `pending`
- `approved`
- `rejected`
- `revised`

建议解释：

- `pending`
  尚未审核
- `approved`
  已审核通过
- `rejected`
  审核驳回，需要重做或修订
- `revised`
  已被人工修改，等待再次确认或视为修订态通过

## 7. 审核记录模型

系统中不只需要最终状态，还需要审核流水，所以单独定义了 `ReviewRecord`。

关键字段：

- `review_id`
- `target_type`
- `target_id`
- `review_status`
- `review_notes`
- `reviewer`
- `reviewed_at`

这样做的目的：

- 页面可以展示审核历史
- 导出前可以做拦截判断
- 后续接权限系统时不需要重做模型

## 8. 导出规则

`export_meta` 主要控制导出动作本身。

关键字段：

- `schema_version`
- `export_scope`
- `approved_only`
- `exported_at`
- `exported_by`
- `unit_ids`

当前建议的强约束是：

- 只有审核通过的内容才能导出
- `approved_only` 默认应为 `true`
- 如果导出范围是单元级，`unit_ids` 应明确列出单元 ID
- 导出时每个板块都应携带自己的 `classification`

## 9. 接口层如何使用这份 schema

建议接口直接围绕这份 schema 组织。

### 8.1 上传接口

只负责创建 `ParseJob`，不返回完整内容。

### 8.2 结果接口

返回完整顶层对象：

```json
{
  "job": {},
  "book": {},
  "units": [],
  "review_records": [],
  "export_meta": {}
}
```

### 8.3 审核接口

至少要支持：

- 更新某个内容项的 `review_status`
- 写入 `ReviewRecord`
- 更新人工修订后的字段

### 8.4 导出接口

导出前先校验：

1. 是否存在未审核内容
2. 是否存在驳回内容
3. `approved_only` 是否满足
4. schema 是否通过校验

## 10. 当前 schema 的取舍

这版 schema 目前有几个明确取舍：

1. 每个导出板块都重复携带 `classification`，用空间换独立导出能力
2. 对话样例已经改成逐轮 `turns` 结构，不再是整段文本
3. 重点句型的例句数量被收紧到 `1-2`
4. 单元级衍生内容目前收敛成 `unit_task` 和 `unit_prompt`
5. 审核记录放在顶层单独管理，而不是塞进每个内容块内部
6. 导出对象默认面向“审核后成品”，不是中间草稿

## 11. 下一步建议

可以直接基于这份 schema 继续做下面两项：

1. `REST API` 设计
2. 项目目录结构与代码骨架设计
