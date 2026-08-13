# Quirebase：Python AGPL Clean Rewrite 计划

## 1. 目标与合规边界

在独立的 Quirebase 仓库中，以 Python 3.12+、FastAPI、Jinja2 和 HTMX 重写现有文献管理系统。新实现采用 AGPL-3.0-only，重新设计领域模型、模块边界和运行架构，避免延续旧系统难以扩展的 MVC、全局依赖注入和同步任务结构。

- PHP 5.11.3 GPLv3 源码和公开文档可用于确认行为、数据语义与兼容需求，但不得逐文件、逐函数翻译。
- `COMPARISON.md` 仅用于识别旧系统现状和高层产品演进方向；其中来自商业版二进制、反编译符号或字符串的名称、结构和实现细节不得进入规格、代码或测试。
- `go/` 目录不得提交、分发或作为实现输入；候选功能必须由公开资料、PHP GPL 源码或独立产品需求重新定义。
- 新代码、项目文档、包名、CLI、服务名和 UI 统一使用 `Quirebase` / `quirebase`，不得沿用旧产品品牌或视觉资产。
- 新代码采用 AGPL-3.0-only，并维护来源台账、依赖许可证清单、SPDX 标识和 SBOM；Web 界面持续显示源码入口，网络部署必须指向与运行版本完全对应的源码。
- 换用 Python 不会自动解除 GPL 义务。本项目属于基于合法 GPL 源码的 clean rewrite，不主张获得闭源或宽松授权所需的严格 clean-room 独立性。
- 首次公开发布前完成名称、商标、域名、包仓库和许可证复核；`Quirebase` 在此之前视为工作名称。

## 2. 架构与公共接口

### 模块化单体

- 领域模块划分为账号与权限、文献条目、附件/PDF、标签、项目、讨论、导入导出、检索和审计。
- 应用层只负责编排用例与事务，不依赖 FastAPI、SQLAlchemy 或具体外部程序。
- 基础设施层实现数据库、文件存储、搜索、后台任务、元数据来源和 OCR 等适配器。
- Web 层使用 FastAPI、Jinja2 和 HTMX；页面路由调用应用服务，不直接访问 ORM。
- 首期不开放第三方插件 SDK；使用 Python `Protocol`、领域事件和适配器注册表提供内部扩展点。

### 数据与搜索

- 使用 SQLAlchemy 2 和 Alembic，同时正式支持 SQLite 与 PostgreSQL。
- SQLite 面向个人和轻量部署，限制为单 worker；PostgreSQL 是团队部署的推荐方案。
- 所有业务查询通过仓储接口完成，禁止在 Web 层和领域层出现数据库方言判断。
- 定义统一 `SearchIndex` 端口：SQLite 使用 FTS5，PostgreSQL 使用原生全文检索；排序、过滤、权限裁剪和去音标行为由共享契约测试约束。
- 文件通过不可变对象存储端口管理；首期实现本地文件系统适配器，数据库只保存元数据、哈希和引用。
- 使用事务 outbox 记录领域事件，由 worker 消费索引、PDF 提取、缩略图和审计任务。

### 后台任务与 CLI

- Web 与 worker 分进程运行，共用持久化数据库任务队列。
- 任务具有状态、幂等键、重试策略、租约超时和错误记录；进程退出后可安全恢复。
- PostgreSQL 通过行锁支持多个并发 worker；SQLite 明确只允许运行一个 worker。
- CLI 命令固定为 `quirebase serve`、`worker`、`init-db`、`create-admin`、`doctor` 和 `reindex`。
- `doctor` 检查数据库、数据目录、权限及可选外部程序，并明确报告功能降级原因。

### 认证与授权

- MVP 支持本地账号和管理员邀请，不开放自行注册。
- 系统角色为 administrator/member；项目角色为 owner/editor/viewer。
- 使用 Argon2id 密码哈希、数据库会话、HttpOnly/SameSite Cookie、CSRF 防护、登录限速和全会话注销。
- 条目、附件、检索结果、讨论和导出统一经过授权服务，禁止仅在页面层隐藏无权数据。
- 审计日志记录登录、条目修改、文件操作、项目成员及权限变化。

### PDF 阅读、标记与批注

- 浏览器固定使用 PDF.js 6.x 渲染 canvas、text layer、原 PDF annotation layer、链接和目录；PDF.js viewport 是浏览器坐标与 PDF user-space 坐标转换的唯一依据。
- worker 统一使用 AGPL-3.0-only 的 PyMuPDF 校验文件、提取全文、生成缩略图和导出标准批注；不采用依赖系统 Poppler/C++ 构建链的 `python-poppler`，也不并行维护 `pypdfium2` 与 `pypdf` 两套服务端实现。
- 高亮按标准 QuadPoints 保存为一个逻辑批注和多个跨行/跨页 segment；便签保存页码及 PDF user-space 锚点。缩放、旋转和 DPR 改变时仅重新投影 overlay，不修改持久化坐标。
- 批注默认私有，可显式共享到单个项目；读取、修改、删除、导出都重新进行文献及项目权限检查，并用版本号防止并发静默覆盖。
- 原始 PDF 使用内容寻址的不可变修订保存，永不写回。worker 使用 PyMuPDF 把 Highlight、Text 标准批注写入临时导出副本，24 小时后清理。
- PDF 内容接口支持同源授权、Range、ETag 和 inline disposition；禁用 PDF JavaScript，不加载任意跨域 PDF。

## 3. 分阶段实施

### 阶段 0：规格与来源治理

- 把 PHP 行为整理为领域术语、用例、输入输出、错误语义和黑盒验收测试，避免继承旧类名与控制器结构。
- 为每项需求记录来源：PHP GPL 源码、公开文档、独立产品需求或待确认。
- 从实施输入中排除商业版二进制的符号、SQL、路由和内部组件信息。
- 建立依赖许可证检查、SBOM、贡献者声明和提交模板。

### 阶段 1：可运行骨架

- 建立 Python 包、配置加载、结构化日志、数据库迁移、应用工厂、HTML 布局和 CLI。
- 支持 Windows、macOS、Linux 上通过 wheel 或 pipx 安装并直接运行。
- 使用各平台标准用户数据目录，将数据库、配置、日志和文献文件与程序安装目录分离。
- 建立 SQLite/PostgreSQL CI 矩阵和端到端启动测试。

### 阶段 2：文献管理闭环

- 条目 CRUD：标题、摘要、日期、出版物、作者、编辑、关键词、标识符和自定义字段。
- PDF/附件上传、内容校验、哈希去重、下载和浏览器内查看。
- BibTeX、RIS 导入导出；导入先预检，再以事务提交并返回逐条错误。
- 标签、项目、项目成员、项目条目、讨论和基础审计。
- SQLite FTS5/PostgreSQL 全文检索，包括关键词、作者、标签、项目和权限过滤。
- PDF 文本提取、缩略图和索引由 worker 异步执行；处理失败不得影响原始文件访问。
- 完成 PDF.js 阅读器、四色文本高亮、定位便签、私有/项目共享、乐观并发控制和标准可编辑批注导出。

### 阶段 3：团队与运维完善

- 完成邀请、成员管理、项目权限、会话管理、备份恢复、完整性检查和重建索引。
- 提供任务重试、失败任务管理、健康检查和基础指标。
- 完成三平台安装文档，以及 SQLite 单机和 PostgreSQL 团队部署示例。
- 对上传、导入、HTML 渲染、文件路径、SSRF、越权和并发修改进行安全加固。

### 阶段 4：旧数据迁移与后续能力

- 提供 PHP 5.11.3 旧库只读迁移工具：读取数据库、PDF 和附件，生成迁移报告后写入新库，绝不原地修改旧数据。
- 后续再评估 PDF 标注、本地 OCR、外部元数据源、公共 REST API、OIDC、邮件、MCP、AI 和多库支持。
- 每项后续能力必须通过独立需求重新设计，不得从商业版实现材料推导接口。

## 4. MVP 范围与验收

MVP 包含：

- 本地账号、管理员邀请、系统角色和项目级权限。
- 文献、作者、关键词、标签、项目、PDF/附件和讨论。
- BibTeX/RIS 导入导出。
- 双数据库、全文检索、异步 PDF 处理和审计。
- Jinja2/HTMX 响应式 Web UI。
- Windows、macOS、Linux 原生 Python 安装和运行。

MVP 不包含：

- 旧库迁移、旧 URL 或旧 UI 兼容。
- OCR、手绘/区域批注、扁平化批注、Office 转换和在线元数据源。
- 开放注册、邮件找回、LDAP、OIDC 或 SAML。
- 公共 REST API、插件 SDK、MCP、AI、PWA 和多库托管。
- 商业版的许可证校验、计费或 call-home 功能。

验收标准：

- SQLite 与 PostgreSQL 通过相同的仓储、权限、搜索和应用用例契约测试。
- 两名用户无法读取、搜索、下载或导出无权访问的项目数据。
- PDF 任务可在进程终止后恢复，重复执行不会产生重复附件或索引。
- MediaBox/CropBox、0/90/180/270 度旋转、混合页尺寸和不同缩放/DPR 下，PDF 坐标往返及 overlay 位置通过视觉回归；导出副本包含标准 Highlight/Text（阅读器按 Contents 显示弹窗）且原文件 SHA-256 不变。
- BibTeX/RIS round-trip 保留 MVP 支持字段，并对不支持字段生成报告。
- 文件上传覆盖超限、伪造 MIME、重复内容、路径穿越和损坏 PDF 场景。
- 并发编辑能够检测版本冲突，不静默覆盖数据。
- 三个平台完成全新安装、初始化、启动 Web/worker、上传 PDF、检索和备份恢复冒烟测试。
- PHP 服务不参与新系统运行；移除 PHP 运行时后，新应用仍能完整工作。

## 5. 已确定的默认决策

- 项目工作名为 `Quirebase`，Python 包、CLI 和服务前缀为 `quirebase`。
- 新实现已经迁至独立的 `quirebase` 仓库，与仅作为合规参考输入的旧源码隔离。
- 项目采用 AGPL-3.0-only，以匹配 PyMuPDF 的开源许可并确保网络部署提供对应源码；旧 PHP 代码仍保持其原许可证，不宣称对其重新许可。
- SQLite 和 PostgreSQL 均为首期正式支持目标，SQLite 限制单 worker。
- UI 采用服务端 HTML，不在首期建设 SPA。
- 路由和接口按领域用例重新设计，不兼容旧系统路由。
- 旧数据库迁移属于第二阶段；MVP 通过新建、BibTeX 和 RIS 获得数据。
- 跨平台支持指 wheel/pipx 安装与运行，首期不承诺单文件可执行程序或图形安装器。
- PDF 技术栈固定为浏览器端 PDF.js + 服务端 PyMuPDF；不使用 `python-poppler`、`pypdfium2` 或 `pypdf`。

## 6. 当前实施状态

- 已完成阶段 0 与阶段 1 的可运行骨架、来源策略、AGPL 源码入口、SQLite/PostgreSQL 迁移、认证、权限和持久化 worker。
- 已完成阶段 2 的条目/PDF 闭环、PDF.js 阅读器、私有/项目批注、PyMuPDF 提取/缩略图/标准批注导出，以及不可变原文件存储。
- 已完成 SQLite FTS5 与 PostgreSQL `tsvector`/GIN 搜索适配器；条目创建和 PDF 提取会更新索引，CLI 支持完整重建。
- 已完成 BibTeX/RIS 预检、事务式确认导入和按当前用户权限导出。
- 已完成条目编辑、自定义字段、补充附件、标签、讨论、邀请、会话、项目成员管理、登录限速、安全响应头和上传加固。
- 已完成成功、失败和限速登录审计，以及单会话撤销、当前会话注销和带 CSRF 防护的全会话注销。
- 已完成失败任务重试、指标、过期导出清理、SQLite/PostgreSQL 备份恢复、对象校验、跨平台 CI 和 PostgreSQL 搜索契约测试。
- 已完成基于 PMC 官方开放数据服务的真实 OA 论文语料测试：固定许可证记录、字节数和 SHA-256，覆盖 PyMuPDF 全页渲染及 PDF.js 全页文本/绘图解析，并由 CI 每周执行。
- 已完成旧数据只读预检/事务迁移、幂等映射和 JSON 报告；旧账号密码不迁移，所有权显式映射到新账号。
- DOI（Crossref/DataCite）、PMID（NCBI）和 arXiv 联网元数据查询已经实现固定 HTTPS 主机、超时、响应限量、无重定向、审计和预检确认；任意网络搜索及自动全文下载仍不开放。
- OCR、OIDC、邮件、公共 API、MCP、AI 和插件 SDK 已完成架构评估并记录 ADR，按 MVP 边界延期，不作为首个完整重写版本的未完成项。
