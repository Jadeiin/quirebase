# Export preference storage

本文研究 Quirebase 是否应在前端保存每个用户的导出偏好。结论是：现阶段适合把
低敏感、体积很小的导出选项保存在 `localStorage`，但必须按账号隔离、校验数据并在
存储不可用时退化为页面默认值。若产品要求跨浏览器或跨设备同步，服务端用户设置才
应成为真源，`localStorage` 最多作为缓存。

## 当前前端约束

`src/quirebase/assets/app.js` 使用 Alpine CSP build，并通过组件 `init()` 和 `$watch()`
组织状态；`package.json` 未安装 Alpine Persist plugin。设置页、Item 和 Library 模板通过
`data-export-preferences-key` 向组件提供基于稳定 User ID 的非秘密 account scope；用户名
可能变化，因此不作为持久化键。

Alpine 官方说明 `$watch` 会在属性变化时调用回调，因此手写一个小型、带校验和异常处理
的存储适配器可以沿用现有代码风格。[Alpine Persist][alpine-persist] 也能自动使用
`localStorage`、支持自定义 key，但它并不替代账号隔离、schema 校验、异常处理和迁移。
仅为这一组布尔值和枚举引入插件没有明显必要。

## 方案比较

| 方案 | 生命周期与范围 | 优点 | 局限 | 结论 |
| --- | --- | --- | --- | --- |
| `localStorage` | 按 origin 保存并跨浏览器会话保留；隐私浏览结束时通常清除 | 不随 HTTP 请求发送；无需后端迁移；适合少量设置 | 只存在当前浏览器 profile/设备；同 origin 下不会自动按登录账号隔离；用户可清除，浏览器也可能拒绝或驱逐数据 | 当前推荐 |
| `sessionStorage` | 同时按 origin 和浏览器 tab 分区；page session 结束即清除 | tab 隔离，适合临时表单状态 | 关闭 tab 后偏好消失，无法满足“记住导出偏好” | 不推荐 |
| Cookie | 可设过期时间并由服务端读取 | 请求到达前服务端可见 | Cookie 随每个匹配请求发送，通常单个约 4 KB；`document.cookie` 是同步 API；扩大不必要的数据传输和服务端暴露面 | 不推荐用于导出偏好 |
| 服务端用户设置 | 由已认证用户记录拥有，页面加载或 API 请求时读取 | 可跨浏览器/设备同步；天然按账号授权；可集中重置和审计 | 需要 schema/迁移/API/数据库写入；有网络延迟，离线不可用；服务端保留更多用户行为数据 | 有跨设备需求时推荐为真源 |

`localStorage` 与 `sessionStorage` 都是同步 API；MDN 提醒大量读写会阻塞其他
JavaScript。不过导出偏好只有数个布尔值和短字符串，一次初始化读取、变化后一次写入的
规模足够小。不要在每次渲染或输入事件中反复读取存储。

“服务端能够跨设备同步”是架构推论：Web Storage 的规范范围是当前 origin 下的浏览器
存储，并没有账号或设备同步语义；把设置关联到已认证用户的服务端记录，才使其他设备能
取回同一份值。

## 推荐 key 与 schema

推荐 key：

```text
quirebase:export-preferences:v1:account:<opaque-account-scope>
```

- `quirebase` 防止与同 origin 的其他应用冲突；
- `export-preferences` 表明能力所有权；
- `v1` 让不兼容 schema 可以并存并显式迁移；
- `opaque-account-scope` 防止同一浏览器中先后登录的账号互相加载偏好。它只用于分区，
  不能是访问令牌、session ID、电子邮件或其他秘密/敏感标识。

值使用 JSON 字符串，并同时携带 payload 版本，以便解析后验证：

```json
{
  "schemaVersion": 1,
  "citation": {
    "format": "csl",
    "style": "apa",
    "includeAbstract": true,
    "preserveCase": false,
    "includeIdentifiers": false,
    "includeCustomFields": false,
    "encoding": "unicode",
    "journalMode": "full",
    "doiPolicy": "include",
    "urlPolicy": "include",
    "excludedFields": "",
    "sortBy": "input",
    "citationKeyFormula": "auth.capitalize + year + shorttitle(1).capitalize",
    "citationKeyForceAscii": true
  },
  "document": {
    "includeAnnotations": false,
    "includeSupplements": false
  }
}
```

读取时只能接受已知字段和类型：格式限制为受支持枚举，style 必须是有长度上限的字符串，
checkbox 字段必须是真正的 boolean。忽略未知字段，缺失字段用当前产品默认值补齐。不要
在偏好中存 Item ID、查询内容、导出内容、注释内容或凭据。

当前实现只有账户设置页的 `userSettings` 组件写入或重置上述 schema；
`libraryWorkspace`、`itemExport` 和 `itemDownload` 只读取并通过隐藏字段或查询参数提交。
现场格式选择只影响本次操作，不写回。新增可选字段继续使用 v1：旧值缺失时补默认值，
不执行迁移也不删除旧值。它是 best-effort 的当前浏览器缓存；任何读取、解析或写入失败
都会继续使用页面和服务端默认值。

`citationKeyFormula` 属于 Citation Key 组，随 BibTeX/BibLaTeX 导出以
`citation_key_formula` / `citation_key_force_ascii` 提交（批量导出走表单隐藏字段，
条目导出走查询参数）。公式只对没有存储 `bibtex_id` 的条目生效；已有键的条目保持原键，
重复键仍由导出时的 `a`、`b` 后缀消歧。公式语法错误在账户设置页通过
`/api/citation-key-preview` 即时预览反馈；只有验证成功的公式才写入浏览器缓存。导出入口
仍把公式参数视为不可信输入并执行独立语法验证，以 `ValidationFailure` 拒绝无效公式，
但不会重新计算已有的 `bibtex_id`。

设置页按能力分组并只显示当前默认格式实际支持的字段：`style` 只属于 CSL；`encoding`、
`preserveCase`、`includeIdentifiers` 和 `includeCustomFields` 只属于 BibTeX/BibLaTeX；
`journalMode`、DOI/URL policy、字段排除和排序属于 BibTeX、BibLaTeX、RIS 与 EndNote。
Citation Key 与文档下载各自独立成组，不伪装成某个现场格式选项。切换默认格式只改变可见
分组，不清除其他格式已经保存的设置。

早期 v1 数据可能包含 boolean `abbreviateJournal`。它保留为读取兼容别名：仅当数据中没有
合法的 `journalMode` 且该值为 `true` 时，读取为 `prefer_abbreviated`。新 UI 只写入
`journalMode`；HTTP Interface 同样只接受 `journal_mode`，旧 boolean 参数不再存在。重置
设置可以删除该旧字段，除此之外普通保存会保留它，符合 v1 不主动删除旧值的承诺。

## 初始化、写入与异常处理

建议流程：

1. 先构造代码内默认值；
2. 在 `init()` 中用 `try` 包住对 `window.localStorage` 的访问、`getItem()`、
   `JSON.parse()` 和迁移；
3. 合并通过 schema 校验的值；损坏、未知版本或不合法值直接回退默认值；
4. 完成 hydration 后再注册 `$watch`，避免默认值在初始化期间覆盖已保存值；
5. 写入时对整个小对象执行一次 `JSON.stringify()` 和 `setItem()`，并用 `try...catch`
   包住写入；
6. `SecurityError`、`QuotaExceededError` 或任何不可用情况都只关闭偏好持久化，导出功能
   继续使用内存状态。偏好保存失败不应阻止下载或复制。

只检查 `window.localStorage` 是否存在并不充分。MDN 说明浏览器可能保留该属性但因用户
设置、隐私模式或零 quota 使其不可用，并给出了实际写入/删除探针。Quirebase 可以采用
同一思路，或直接让首次真实读写承担探测职责。不要假设无痕模式、禁用 Cookie 或存储
空间不足时一定可写。

浏览器存储默认是 best-effort，用户可以清除，浏览器在存储压力下也可能驱逐；因此这些
偏好必须始终有可靠默认值，不能成为业务数据或导出正确性的唯一来源。

## 迁移与回滚

当前导出选项扩展仅增加具有明确默认值的字段，因此继续使用 v1，不运行迁移。以下流程只
适用于未来真正不兼容的 schema 变更。

每个不兼容变更增加 key 和 payload 的版本，例如 `v1` 到 `v2`。初始化时先读当前版本；
没有当前版本时，按明确的旧版本列表查找并运行纯函数迁移：

```text
read v2 -> validate -> use
missing v2 -> read v1 -> validate -> migrate -> write v2 -> remove v1
```

只有新 key 写入成功后才删除旧 key。WHATWG 的 `setItem()` 算法在值无法存储时先抛出
`QuotaExceededError`，之后才更新 map，因此失败时旧版本仍可作为回退。无法识别的未来
版本不能猜测转换；使用默认值并保留原值，避免旧版前端破坏新版数据。

字段仅新增且默认值明确时仍可保持同一 schema 版本；字段改名、类型变化、语义反转或枚举
含义变化时必须升级版本。Alpine Persist 官方也特别提醒：持久化变量类型变化后需要清除
旧值或更换 key，这与显式版本迁移的要求一致。

## 隐私与多账号边界

- Web Storage 按 origin 而不是 Quirebase 用户分区。在共享浏览器 profile 上，不带账号
  scope 的 key 会把 A 用户的选择展示给之后登录的 B 用户。
- `localStorage` 不会像 Cookie 一样自动随请求上传，但同 origin 的前端脚本可以读取它；
  因而只保存低敏感设置，不能把“留在浏览器”当作安全边界。
- 隐私浏览结束、用户清除站点数据、浏览器策略禁用存储或发生驱逐后，偏好可能消失。
- 本地方案不跨 profile、浏览器或设备。若用户明确期望“我的设置到处一致”，应使用服务端
  用户设置；可以在本地缓存最后一次成功读取的服务端版本，但服务端决定冲突和版本。
- 应提供“恢复导出默认设置”。如果产品需要共享设备上的更强隐私，可在 logout 时删除当前
  account scope 的 key；代价是无法跨登录会话保留本地偏好。

## Claim-to-source mapping

| 结论或事实 | 官方来源 |
| --- | --- |
| `localStorage` 按 Document origin 提供并跨浏览器会话保存；隐私浏览的最后一个 tab 关闭后清除 | [MDN `Window.localStorage`, description][mdn-local] |
| 获取 `localStorage` 可因无效 origin 或用户阻止持久化而抛 `SecurityError`；阻止 Cookie 也可能被解释为阻止持久化 | [MDN `Window.localStorage`, exceptions][mdn-local-exceptions] |
| `sessionStorage` 同时按 origin 和 tab 分区，page session 在 reload/restore 后仍在，关闭 tab/window 后清除 | [MDN `Window.sessionStorage`, description][mdn-session] |
| Web Storage 属性存在不代表可用；隐私模式可能给零 quota；应通过受控写入并处理 `QuotaExceededError` 检测 | [MDN Using the Web Storage API, testing for availability][mdn-availability] |
| Web Storage 是同步 API，大量读写可能阻塞 UI | [MDN Web Storage API, concepts and usage][mdn-web-storage] |
| Web Storage 每 origin 通常最多 5 MiB local + 5 MiB session；超限抛 `QuotaExceededError`，写入应使用 `try...catch` | [MDN Storage quotas, Web Storage][mdn-quota] |
| 浏览器存储默认 best-effort，可能被用户删除或在存储压力下驱逐；隐私浏览结束时通常删除 | [MDN Storage quotas, persistence and eviction][mdn-eviction] |
| 现代存储 API 不会把数据发给服务端；Cookie 通常单个约 4 KB 且随每个请求发送 | [MDN HTTP cookies, data storage][mdn-cookies]；[WHATWG HTML, Web storage introduction][whatwg-web-storage] |
| `document.cookie` 是同步 API，跨进程读取或 I/O 可能阻塞主线程 | [MDN `Document.cookie`, note][mdn-document-cookie] |
| `setItem()` 无法保存时抛 `QuotaExceededError`，规范算法在成功可存储后才更新 map | [WHATWG HTML, Storage interface][whatwg-setitem] |
| Alpine `$watch` 在属性变化时调用回调；Persist 用 watcher 写入 `localStorage`，支持自定义 key，类型变化需清旧值或换 key | [Alpine `$watch`][alpine-watch]；[Alpine Persist][alpine-persist] |

[alpine-persist]: https://alpinejs.dev/plugins/persist
[alpine-watch]: https://alpinejs.dev/magics/watch
[mdn-availability]: https://developer.mozilla.org/en-US/docs/Web/API/Web_Storage_API/Using_the_Web_Storage_API#testing_for_availability
[mdn-cookies]: https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Cookies#data_storage
[mdn-document-cookie]: https://developer.mozilla.org/en-US/docs/Web/API/Document/cookie#notes
[mdn-eviction]: https://developer.mozilla.org/en-US/docs/Web/API/Storage_API/Storage_quotas_and_eviction_criteria#does_browser-stored_data_persist
[mdn-local]: https://developer.mozilla.org/en-US/docs/Web/API/Window/localStorage#description
[mdn-local-exceptions]: https://developer.mozilla.org/en-US/docs/Web/API/Window/localStorage#exceptions
[mdn-quota]: https://developer.mozilla.org/en-US/docs/Web/API/Storage_API/Storage_quotas_and_eviction_criteria#web_storage
[mdn-session]: https://developer.mozilla.org/en-US/docs/Web/API/Window/sessionStorage#description
[mdn-web-storage]: https://developer.mozilla.org/en-US/docs/Web/API/Web_Storage_API#concepts_and_usage
[whatwg-setitem]: https://html.spec.whatwg.org/multipage/webstorage.html#dom-storage-setitem
[whatwg-web-storage]: https://html.spec.whatwg.org/multipage/webstorage.html#introduction-16
