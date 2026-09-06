# PDF 导入批注模式实施规划

状态：规划稿，不包含功能实现。

目标是为 PDF 导入增加批注策略，并按“先剥离、后解析导入”的顺序落地：

1. 剥离 PDF 中的原生批注，但不创建 Quirebase Annotation。
2. 解析支持的原生批注，转换为规范化 Annotation，同时剥离源 PDF 中的原生批注，避免阅读器重复显示。

当前行为保留为默认策略：保留源 PDF 批注，阅读器将其作为只读原生批注显示。

## 现状与约束

- PDF 导入入口是 `web.views.discovery.preview_pdf_import`，业务流程位于 `library.imports`。
- PDF 暂存、File Revision 创建、检查和缩略图生成由 `documents` Module 与 DBOS workflow 负责。
- `documents.pdf` 已使用 PyMuPDF，可复用 PDF 校验、文本提取、页几何和批注导出能力。
- `PdfAnnotation` 是严格校验的规范化存储模型，支持 highlight、underline、strikeout、note、free_text、ink、rectangle、ellipse、line、arrow。
- EmbedPDF 当前会把源 PDF 批注锁为只读；如果源批注和规范化批注同时存在，用户会看到重复标记。
- ADR 0010 当前明确规定源 PDF 批注不导入数据库。解析导入阶段开始前必须修订该 ADR，说明导入模式是有意支持的策略，以及导入时为何要剥离源批注。
- File Revision 是不可变业务对象。剥离不能直接覆盖已存对象，应生成新的 PDF 对象并在检查 workflow 的事务提交时切换引用。

## 统一的导入策略

不要使用两个互相矛盾的布尔值，建议定义一个 `pdf_annotation_mode`：

| 模式 | PDF 中的原生批注 | `pdf_annotations` | 适用场景 |
| --- | --- | --- | --- |
| `preserve` | 保留，只读显示 | 不创建 | 现有默认行为 |
| `strip` | 删除并保存为派生 PDF | 不创建 | 只想导入干净正文 |
| `import` | 解析后删除 | 创建私有规范化批注 | 想继续在 Quirebase 中编辑/检索批注 |

`import` 模式必须同时剥离源批注，否则 EmbedPDF 会同时显示原生批注和数据库批注。三种模式在 UI 上使用单选或下拉选择，并明确提示“解析导入会移除 PDF 内嵌批注外壳，但不会移除已经扁平化到页面内容里的标记”。

## 阶段一：剥离模式

### 1. 领域与入口

- 在 Library 的 PDF 导入接口中增加 `pdf_annotation_mode`，默认 `preserve`，避免改变现有调用者行为。
- `ImportBatch` 增加可空的 `pdf_annotation_mode` 字段；非 PDF 批次为 `NULL`，旧 PDF 批次按 `preserve` 解释。
- Web 表单增加三个策略选项，并将值传给 `stage_pdf_import_batch`。
- DBOS 入参和 workflow attributes 都携带策略，便于恢复和运维定位。修改 workflow 签名时保留默认值 `preserve`，使已存在的旧 durable input 可以继续恢复。

### 2. PDF 处理

在 `documents.pdf` 增加内部操作：

- 遍历每页的 PDF Annotation 对象；使用副本列表删除，避免迭代删除导致遗漏。
- 输出到临时 PDF，再通过 ObjectStore 生成新的 PDF object key。
- 重新执行校验、文本提取、页几何和缩略图生成，确保 File Revision 元数据对应派生文件。
- 明确定义剥离范围：第一阶段只处理 `page.annots()` 返回的 markup/注释对象；Link、Widget 等特殊对象是否处理需要单独确认，不能把“删除所有 PDF 交互对象”默认为批注剥离。

### 3. Workflow 与对象生命周期

- `inspect_imported_pdf` 根据策略决定是否生成派生对象。
- `preserve` 继续使用暂存 object key；`strip` 使用新 object key。
- `commit_imported_revision` 在同一 datasource transaction 中写入派生 object key、页信息和缩略图信息。
- 成功提交后异步清理旧暂存对象；失败或取消时同时清理派生对象和缩略图，避免泄漏。
- workflow attributes 记录原始和派生 object keys，使维护任务可以识别未完成 workflow 的对象保留关系。

### 4. 阶段一验收

- 导入一个包含原生批注的 PDF，`strip` 后阅读器中不再显示这些原生批注。
- 正文文本、页数、页尺寸、旋转和 crop box 不变。
- `pdf_annotations` 不新增记录。
- 批次重试、取消、丢弃和 workflow 失败不会误删其他批次或已提交 Revision 的对象。
- 未选择策略时行为与现有 `preserve` 完全一致。

## 阶段二：解析并导入模式

### 1. 解析边界

在 `documents.pdf` 增加内部解析器，输出与 `AnnotationCreate` 等价但不依赖 Web/Pydantic 请求模型的中间结构：

- 支持当前规范化模型的十种类型。
- 使用已有 crop-box、本地底部原点坐标约定，覆盖页面旋转和 crop box。
- `info.content` 映射到 `body`；FreeText 的可见文字映射到 payload.text。
- 高亮/下划线/删除线保存 segment rectangles；若 PDF 没有选中文字，`selected_text` 可为空，不能把近似文本当成精确文本。
- PDF 作者、原始日期和原生 xref 不能直接映射到当前 User/Annotation 模型，MVP 归属当前导入用户、scope 设为 private。
- Unsupported 类型不进入数据库；记录 warning/diagnostic，不能因为一个不支持的 Stamp、Polygon 或 Widget 使整份 PDF 导入失败。

### 2. 导入时机与幂等性

- `import` 模式复用阶段一的“生成派生 PDF”路径，并在 inspection 结果中携带解析后的规范化批注中间结构。
- `commit_imported_revision` 在同一事务中把 File Revision 从 pending 更新为 ready，并创建 `PdfAnnotation` 行。
- 只有从 pending 首次转为 ready 时创建批注；重复执行看到 ready 后跳过，保证 DBOS 重试不会产生重复 Annotation。
- 批注 ID 使用新生成的 Quirebase UUID，不复用 PDF 原生对象 ID。
- 如果后续需要保留源作者/xref/provenance，应另建字段或导入来源表，不把第三方信息塞进当前严格 payload。

### 3. 预览与诊断

建议在 PDF Import Batch 的候选记录中保存轻量 annotation summary（总数、支持数、不支持类型），完整 payload 只在确认导入时使用；这样不会把大量几何和正文复制进预览页面。

诊断至少包含：文件名、页码、原生 subtype、处理结果（imported/skipped）和原因。`import` 模式允许带 warning 提交；结构损坏、密码保护和无法读取的 PDF 仍然是阻断错误。

### 4. ADR 与权限

- 更新 ADR 0010：源批注默认只读仍成立，但 `import` 模式会把可映射批注转成规范化记录并剥离源对象。
- 明确导入批注的作者是执行导入的 User，默认 private；不自动猜测 Project scope。
- 审计事件建议增加 `pdf.import.annotations`，detail 中记录 mode、imported count、skipped count。

## 建议的代码改动面

### Library / Web

- `library.imports`: `PdfImportAnnotationMode`、批次字段读写、提交时把 mode 传给 Documents。
- `web.views.discovery`、`templates/import.html`: 表单参数解析、默认值和提示文案。
- `models.py` + Alembic migration：`ImportBatch.pdf_annotation_mode` 及必要约束。

### Documents

- `documents.pdf`: 原生批注枚举/解析、剥离、派生 PDF 输出。
- `documents.workflows`: inspection result、派生对象生命周期、规范化批注事务写入。
- `documents.revisions`: 让 `attach_staged_pdf` 能传递导入策略；保持 Documents 对 PDF 文件和 Annotation 的所有权。
- `documents.__init__`：只导出真正需要跨 Module 调用的 use case/result，不暴露 PyMuPDF 对象。

### 测试

- `tests/test_pdf_service.py`：剥离后无原生批注、正文/几何保持不变、旋转/crop box、各支持类型解析和不支持类型诊断。
- `tests/test_library_ui.py`：三种 mode 的批次持久化、预览、重试和确认导入。
- `tests/test_workflows.py`：派生对象清理、workflow 重试幂等、pending→ready 事务和取消路径。
- `tests/test_frontend_assets.py` / route contract：表单字段、默认策略和 native fallback。
- PostgreSQL/迁移契约测试：新字段默认值、旧批次解释为 preserve。

## 推荐实施顺序

1. 先写并评审 ADR 0010 更新草案，以及 `pdf_annotation_mode` 的语义。
2. 实现阶段一 `strip`，完成对象生命周期和回归测试。
3. 在真实论文 PDF 集合上验证剥离后的文本、页几何、旋转和文件大小。
4. 实现阶段二解析器，只覆盖已有十种规范化类型，其他类型先诊断跳过。
5. 接入 inspection transaction，完成批注写入幂等测试。
6. 最后开放 UI 的 `import` 选项；若解析质量不足，保留 `preserve` 和 `strip`，不强制升级旧行为。

## 需要在实现前确认的产品决策

- “剥离批注”是否包括 Link、Widget、Popup、Stamp 等非文字标记对象？
- `import` 模式是否永远剥离源批注（推荐是）？
- 导入的批注是否只允许 private，还是需要在确认页选择 Project？
- 不支持的类型是仅提示 warning，还是要求用户选择“继续导入/取消”？
- 是否需要保留 PDF 原作者、创建时间和原生 xref 作为 provenance？
