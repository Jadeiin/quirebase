# 外部实现替换与 Provider 子模块深化方案

- 日期：2026-08-20
- 关联：`docs/research/2026-08-20-papis-backend-replacement.md`（依赖级调研）、
  `docs/architecture/deep-module-roadmap.md` 候选 4（Discovery Providers）、
  ADR 0001（受控外部集成）、ADR 0003（Provider 固定 allowlist）
- 状态：superseded by ADR 0005

> 本文保留为 2026-08-20 的设计输入。其关于 `search_metadata`、`lookup_metadata`、
> `MetadataClient`、`OnlineSearchClient` 与旧 MockTransport 注入签名的提案，已由
> `docs/adr/0005-deep-standalone-provider-runtime.md` 的 `ProviderRuntime`、单一有界传输
> Implementation 和 Library-owned business seam 取代，不再构成当前架构契约。

## TL;DR

- **先做结构性深化，再做依赖替换**：把每个 Provider 的 Search/Lookup 适配器、标识符解析、
  类型映射从 `search.py` / `lookup.py` / `providers.py` 三处集中式文件，收敛为
  `discovery/providers/` 下每 Provider 一个文件。公共接口 `search_metadata` /
  `lookup_metadata` 与 `httpx.MockTransport` 契约测试完全不变。此后任何依赖替换
  （包括未来的 `habanero`）都退化为单文件 diff。
- **接受 `python-slugify`**：替换 `documents/bundles.py` 的归档名 slug（纯进程内计算，
  Unicode 转写收益真实）。`generate_bibtex_key` 先用固定期望用例钉住现状，再决定是否换。
- **拒绝 `python-doi`**：内部实现仅约 5 行（删除测试不成立），上游更严格的校验会改变
  `parse_identifier` 自动检测与 PDF DOI 召回，域内关键路径的行为风险大于收益。
- **接受传输层统一迁移到 `httpx2`**：`httpx` 0.28.1 自 2024-12 起无发布（上游已事实停滞），
  Pydantic 接管的 `httpx2` 2.x 是活跃维护的延续分支，且 Starlette 1.6 的 `TestClient`
  已内建 "httpx2 优先、httpx 回退"导入并警告 httpx 路径弃用。Quirebase 全部触点
  （`discovery` 三个文件的同步 Client / MockTransport / 流式读取 / `HTTPError`，
  三个契约测试文件的 `MockTransport` 注入）与 httpx2 API 同构，迁移成本为
  机械替换。迁移后出站单栈不变式（ADR 0001）落在 `httpx2` 上，并重新打开
  `habanero` 评估。
- **已被后续导出决策修订**：bibliography interchange 的解析直接依赖最终落回
  `bibtexparser`（v2 beta，显式中间件栈、结构化姓名拆分、原生 writer + `@string`
  宏解析），TeX 编解码由 Inquiro 自有的 richtext 层基于 `pylatexenc` 直接承担，
  Web 数学公式投影由 `latex2mathml` 承担，`pybtex` / `latexcodec` 整体退场；
  `rispy` / `citeproc-py` / `pymupdf` 仍维持直接依赖，不经 `papis` 中转；
  不引入 `arxiv` PyPI 包替代现有 Atom 解析。
- **`habanero` 缓议但不再是拒绝**：其传输栈障碍随 httpx2 迁移消除；剩余障碍是
  它仅覆盖参数构造（不覆盖 JSON → `MetadataRecord` 领域映射）的低净收益，并且
  `habanero[bibtex]` 会额外引入当前不需要的第二套 BibTeX 引擎。触发条件重定义见阶段 5。

## 决策原则

以下原则来自 codebase-design（深模块 / 缝 / 适配器），与本仓库
`docs/architecture/modules.md` 的既有承诺一致：

1. **删除测试**：想象删除候选内部实现。若复杂度只在 N 个调用点各重现几行，它是浅实现，
   换库无增益；若复杂度会大面积重现，才值得用外部依赖吸收。
2. **缝的纪律**：一个适配器意味着假想的缝。`MetadataClient._get` /
   `OnlineSearchClient._get` 是唯一出站缝，承载超时、禁重定向、体积上限、404/429 语义
   与审计（ADR 0001）。任何第三方客户端必须坐在适配器**内部**充当参数构造器，
   不得替换该缝本身。
3. **接口即测试面**：`search_metadata` / `lookup_metadata` 两条业务缝及其
   MockTransport 契约测试是回归基线。Provider 子模块化与依赖替换都不得改变它们。
4. **领域映射无库可替**：Crossref/OpenAlex JSON → `MetadataRecord` 的映射
   （机构去重、期刊缩写、倒排索引摘要重建）是 Quirebase 的领域知识，
   `habanero` / `pyalex` 一类客户端并不拥有它。
5. **`papis` 本体不引入**：调研报告 4.1 节结论继续有效（GPL 传染面、`requests` 双栈、
   配置耦合、存储模型错配）。它只作为参考实现。

## 现状缝位（2026-08-20 审阅）

- `discovery/lookup.py`（791 行）与 `discovery/search.py`（891 行）各容纳 8 个 Provider
  的适配器；`discovery/providers.py`（174 行）集中装配注册表。一个 Provider 的变更
  需要横跨三个文件，违反 modules.md "co-locate identity, identifier aliases and
  parsing, capabilities, fixed endpoints and credential requirements" 的既定意图。
- 共享解析助手（`_first`、`_clean_markup`、`_date_parts`、
  `reconstruct_openalex_abstract`）在 `search.py` 间以私有名跨文件引用。
- **传输层触点（2026-08-20 复核）**：`httpx` 的直接使用仅集中在
  `discovery/lookup.py`（`MetadataClient`）、`discovery/search.py`
  （`OnlineSearchClient`）与 `discovery/imports.py`（类型引用）三个文件；
  测试侧为 `test_metadata_lookup.py` / `test_online_search.py` /
  `test_oa_e2e_lifecycle.py` 的 `httpx.MockTransport` / `httpx.Response`。
  `uv.lock` 中唯一直接依赖方是 quirebase 自身（Starlette 的 `full` extra 同时
  列出两者，运行时 TestClient 优先导入 `httpx2`）。所用 API 子集——
  同步 `Client(timeout=..., follow_redirects=False, transport=...)`、
  `client.stream("GET", ...)`、`BaseTransport` 注入、`MockTransport`、
  `Response(status_code, content=...)`、`HTTPError`——与 `httpx2` 2.12 同构
  （已实测验证）。
- DOI 知识分布：`DOI_PATTERN` + `normalize_doi`（discovery，共 5 行核心逻辑）、
  `PDF_DOI_PATTERN` + `first_doi_from_text`（pipeline，贪婪文本搜索，用途不同）。
  `tests/` 无直接引用 `normalize_doi` / `DOI_PATTERN` 的用例；行为由
  `test_metadata_lookup.py` / `test_online_search.py` 的 MockTransport 契约
  与 `test_identifiers_sync.py` 间接钉住。
- slug 知识分布：`documents/bundles.py` `_archive_name`（保留 CJK 的 `\w` 语义）与
  `library/identifiers.py` `generate_bibtex_key`（ASCII 剥离）。两者是**不同的命名策略**
  （可移植 zip 条目名 vs BibTeX 键稳定性），不应合并为一个共享 slug 模块——
  那正是 modules.md 拒绝的 generic shared-utilities package。

## 二次设计对比：Provider 子模块的形态

**设计 A：仅抽共享解析**。`search.py` / `lookup.py` 保持，私有助手移入
`discovery/_parsing.py`。零结构风险，但 Provider 变更仍跨两大文件加注册表，局部性无实质改善。

**设计 B：按 Search/Lookup 双轴拆分**。`discovery/search/crossref.py` 与
`discovery/lookup/crossref.py` 分立。尊重现有文件轴线，但同一 Provider 的方言知识
（字段名、类型映射、标识符解析）被再次劈成两半。

**设计 C（选定）：按 Provider 单文件 + 注册表聚合**。
`discovery/providers/` 包，每 Provider 一个模块，导出该 Provider 的
`ProviderRegistration`（适配器实例、标识符解析器、端点、凭证声明、类型映射常量）；
`providers/registry.py` 仅聚合各注册项。共享解析助手移入包内私有 `_parsing.py`。

选择理由：`ProviderRegistration` 数据类已经存在，设计 C 只是把装配从集中式
`providers.py` 移回每个 Provider 自己的文件——这是 modules.md 已承诺的 co-location
的落地，而非新抽象。新增 Provider = 新增一个文件 + 聚合元组一行；
Provider API 变更 = 单文件 diff。删除测试通过：删掉某个 Provider 模块，
该 Provider 的全部方言知识随之消失，无跨文件残留。

## 分阶段方案

### 阶段 0a：传输层迁移到 `httpx2`（机械替换，先行合入）

事实依据（2026-08-20 核实）：

- `httpx` 0.28.1 最后发布于 2024-12-06，此后无版本、无安全维护；用户判断成立。
- `httpx2` 2.12.0（2026-08-18 发布）由 Pydantic Services 接管维护，BSD-3-Clause，
  自述为 HTTPX 的延续，API 广泛兼容；核心依赖 `httpcore2`、`anyio`、`truststore`。
- Starlette 1.6（当前锁定版本）`TestClient` 源码为 `import httpx2 as httpx`，
  失败才回退 `import httpx` 并对回退路径发 `StarletteDeprecationWarning`；
  其 `full` extra 已同时列出 `httpx2>=2.0.0` 与 `httpx>=0.27,<0.29`。
  生态正在整体迁向 httpx2。

迁移内容：

- `pyproject.toml`：`httpx>=0.28,<1` → `httpx2>=2.12,<3`；mypy overrides 增补
  `httpx2`（若使用 `httpx2` 的内建类型标注则不需要）。
- `src`：`lookup.py` / `search.py` / `imports.py` 的 `import httpx` → `import httpx2`
  （三个文件、约 12 处引用，全部为名字替换）。
- `tests`：三个契约测试文件的 `import httpx` 同步替换；`MockTransport` /
  `Response` 构造不变。其余测试经 Starlette `TestClient` 间接受益，
  弃用警告消失，无需改动。
- `THIRD_PARTY.md`：httpx2 条目替代 httpx。
- 验收：全测试套零行为差异；出站不变式（固定端点、超时、禁重定向、体积上限）
  由既有契约测试在 httpx2 上重新证明；确认 uv.lock 中 `httpx`/`httpcore`
  仅作为 Starlette `full` extra 的传递依赖存在（或随其升级消失）。

设计说明：这不是缝的更换——`MetadataClient._get` / `OnlineSearchClient._get`
仍是唯一出站缝，ADR 0001 不变式逐条保留；更换的只是缝后面的传输实现，
且 Quirebase 所用 API 子集两边同构。风险集中在 httpcore2 行为差异
（重定向/超时语义），契约测试的 404/429/重定向/体积上限用例恰好逐一覆盖。

### 阶段 0b：Provider 子模块化（无新依赖，无公共接口变化）

- 新建 `src/quirebase/discovery/providers/` 包：
  - `crossref.py`、`datacite.py`、`pubmed.py`、`pmc.py`、`arxiv.py`、
    `openlibrary.py`、`openalex.py`、`nasa_ads.py`、`ieee.py`：
    每文件含该 Provider 的 Search/Lookup 适配器、标识符解析与类型映射常量，
    导出一个 `ProviderRegistration`。
  - `registry.py`：聚合注册项，保留 `search_provider` / `identifier_provider` /
    `identifier_provider_names` 现有签名。
  - `_parsing.py`：`_first` / `_clean_markup` / `_date_parts` /
    `reconstruct_openalex_abstract` / `_collect_urls` 等共享助手（包内私有）。
- `lookup.py` / `search.py` 保留 `Identifier`、`MetadataRecord`、`MetadataClient`、
  `OnlineSearchClient`、两个业务函数与错误类型（这些是缝，不动）。
- 验收：`search_metadata` / `lookup_metadata` 签名不变；
  `test_metadata_lookup.py` / `test_online_search.py` 零改动通过；
  `test_architecture.py` 包依赖策略不变（包内重组不产生新的跨包边）；
  `Identifier` / `MetadataRecord` / 错误类型的既有导入点（如
  `library/identifiers.py`）不变。
- 关联：roadmap 候选 4 的 internal locality 落地。

### 阶段 1：`python-slugify` 替换归档名 slug

- 范围：仅 `documents/bundles.py` 的 `_archive_name`（及其两个调用点
  `_item_archive_prefix` / `_revision_archive_name`）。纯进程内计算（依赖类别 1），
  不新增缝，不新增模块。
- 先行测试：以固定期望用例钉住新行为——纯 ASCII 标题、中文标题（转写后归档名）、
  变音符号、长度截断（80 上限）、全非法字符回退 fallback。用例来自真实 Item 语料。
- 行为说明：现状对中文标题保留 CJK 字符；`python-slugify` 默认转写为拉丁串。
  zip 条目名可移植性提升是有意的行为变化，需在用例中显式承认。
- 合规：`text-unidecode`（GPL-1.0-or-later OR Artistic-1.0-Perl）写入 `THIRD_PARTY.md`；
  AGPL-3.0-only 分发相容，SBOM 覆盖。
- 依赖版本：`python-slugify>=8,<9`。

### 阶段 2：`generate_bibtex_key` 现状钉住 + 可选内部替换

- 先行测试：`library/identifiers.py` `generate_bibtex_key` 补固定期望用例
  （中文作者/标题、变音符号作者、无作者、无年份、停用词首词、全数字标题）。
  现行为（ASCII 剥离 + 首词大写）被测试钉住后才允许动内部。
- 决策点：是否切换为 `slugify(..., allow_unicode=False)` 的转写行为
  （`café` → `Cafe` 而非 `caf`）。BibTeX key 是用户可见且历史存储于
  `Item.bibtex_id` 的稳定标识；切换只影响新生成的 key。默认保守：保持 ASCII 剥离
  语义，仅在产品确认后启用转写。
- 不把两个 slug 策略合并为共享模块（理由见"现状缝位"末条）。

### 阶段 3：DOI 工具层——拒绝引入 `python-doi`

- 删除测试不成立：`normalize_doi` 4 行、`DOI_PATTERN` 1 行；删除后复杂度不会
  在调用点大面积重现。引入 GPL-3.0 依赖换不来实现净删减。
- 行为风险：上游校验比 `10\.\d{4,9}/\S+` 严格，会改变 `parse_identifier`
  自动检测顺序的召回与 `pipeline` PDF DOI 提取，属于域内关键路径的隐性回归。
- 决定：DOI 解析/规范化保持为 discovery 内部实现；`DOI_PATTERN`（严格 fullmatch）
  与 `PDF_DOI_PATTERN`（贪婪文本搜索）职责不同，维持分离。
- 若未来上游出现宽松模式兼容的维护库，再评估。

### 阶段 4：Crossref——`habanero` 缓议，先做常量表参考

- 缓议理由（调研报告 4.2 基础上更新）：
  - 传输栈障碍已随阶段 0a 消除：`habanero` 2.9.2 依赖 `httpx2`，
    与迁移后的 Quirebase 出站栈一致。
  - 剩余障碍一：`habanero[bibtex]` 会额外引入当前不需要的第二套 BibTeX 依赖。
    缓解：不启用其 bibtex extra，仅用 Crossref 客户端能力。
  - 剩余障碍二（设计视角）：`habanero` 吸收的是参数构造与分页——这部分已被
    `MetadataClient` / `OnlineSearchClient` 集中并约束；真正的复杂度
    （JSON → `MetadataRecord` 映射）仍需自持。净代码删减有限，
    引入还须在其上重新施加 ADR 0001 不变式（限制其自带 Client，
    仅取参数构造，或注入受控 transport）。
- 先行动作（零依赖，papis 方案 B）：对照 `papis/crossref.py` 的
  `CROSSREF_TYPES` / filter / sort 常量表，审计并补齐
  `CANONICAL_REFERENCE_TYPE_MAP` 的 Crossref 类型别名缺口；
  参照 `papis/bibtex.py` 补齐 `REFERENCE_TYPE_TO_BIBTEX` / `REFERENCE_TYPE_TO_CSL`。
  落点在阶段 0b 之后的 `discovery/providers/crossref.py` 单文件内。
- 进入试点（`HabaneroCrossrefAdapter`，落点 `providers/crossref.py`）的触发条件：
  1. 出现手写参数构造难以覆盖的 Crossref 能力需求（如游标深分页、
     polite-pool 限流头处理的实测缺口）；或
  2. Crossref API dialect 变更导致手写参数构造的维护成本持续上升；且
  3. 试点以替换搜索路径开始，`MockTransport` 契约用例不变，响应解析仍归
     Quirebase 的 `MetadataRecord` 映射。
  第二 BibTeX 引擎已因不启用 bibtex extra 而不再是阻塞项。

### 明确不做

- 不引入 `papis` 本体（调研报告 4.1）。
- 不引入 PyPI `arxiv` 包：现有 Atom 解析已覆盖 `arxiv:doi` / `journal_ref` / 分类，
  替换是行为换依赖，得不偿失。
- 不引入 `beautifulsoup4` / `lxml`：Inquiro 用标准库 `HTMLParser` 解析仅含 `i`、`b`、
  `sup`、`sub` 的行内白名单，复杂度尚不足以证明通用 DOM 依赖的必要性。
- 不将 `bibtexparser` / `pylatexenc` / `latex2mathml` / `rispy` / `citeproc-py`
  经任何中间层间接依赖。
- 不为 OpenAlex 引入 `pyalex` 一类客户端（同样绕过受控出站缝，理由同 `habanero`
  缓议；httpx2 迁移不改变这一条——问题在绕缝，不在传输库名）。

## 验收与守护

| 守护点 | 手段 |
| --- | --- |
| 公共缝不变 | `test_metadata_lookup.py` / `test_online_search.py` 在阶段 0b、4 零改动 |
| 包依赖方向不变 | `tests/test_architecture.py` 策略表无需新增跨包边 |
| slug / bibtex key 行为 | 阶段 1、2 的固定期望用例先行合入 |
| 许可证 | `THIRD_PARTY.md` 增补 `python-slugify` / `text-unidecode`；`httpx` 条目替换为 `httpx2` |
| 替换不绕过出站缝 | 架构测试补充：`inquiro` 禁止导入 `requests` / `httpx`（httpx2 之外的第二传输栈；可并入现有 FORBIDDEN 检查） |
| 传输栈单一 | 阶段 0a 后 `uv.lock` 中 `httpx2` 为唯一直接 HTTP 依赖；`httpx` 若存在仅作为 Starlette `full` extra 传递项 |

## 与既有文档的关系

- 本方案是调研报告第 6 节"方案 A"的修订：保留 `python-slugify` 试点，
  下调 `python-doi` 优先级为"拒绝"、`habanero` 为"缓议"（其传输栈障碍已因
  阶段 0a 的 httpx2 迁移消除），并前置阶段 0a/0b 结构深化，
  使后续任何替换的最小 diff 单位从"三大文件"降为"单 Provider 文件"。
- 阶段 0b 即 roadmap 候选 4 的实施；完成后在 deep-module-roadmap.md 勾连。
- 阶段 0a 的传输层迁移建议随后以独立 ADR 记录（修订 ADR 0001 的出站实现基线：
  不变式不变，实现栈从 httpx 改为 httpx2）。
