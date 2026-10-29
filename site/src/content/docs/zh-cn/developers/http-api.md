---
title: 连接 HTTP API 客户端
description: 创建令牌，列出工作区，选对 UUID，再完成第一次文献库请求。
---

将客户端连接到 Quirebase 应用地址，例如 `http://127.0.0.1:9060`。
应用提供 `/api/v1/` JSON API、`/docs` 交互文档和 `/openapi.json` Schema。
本站的[自动生成 API 参考](/reference/api/)来自开发检出，保留 Schema 的英文描述。

## 创建凭据

1. 登录应用，打开“账号设置 → API 令牌”。
2. 创建带名称和有效期的令牌，立即复制一次性显示的明文值。
3. 展开“客户端连接指南”，核对应用地址。
4. 将令牌保存到客户端凭据机制中，通过 `Authorization: Bearer …` 请求头发送。

API 令牌以对应用户的身份执行请求。运维人员也可以在源码安装中执行：

```sh
uv run quirebase create-api-token USERNAME --name "Research client" --days 30
```

把 `USERNAME` 换成现有用户名，并将一次性显示的明文保存到客户端凭据存储中。

## 第一次请求：列出并选择工作区

使用 curl 时，把 `QUIREBASE_URL` 设置为应用根地址，通过本地凭据或环境机制提供 `QUIREBASE_API_TOKEN`，再运行：

```sh
curl --fail-with-body \
  -H "Authorization: Bearer $QUIREBASE_API_TOKEN" \
  "$QUIREBASE_URL/api/v1/workspaces?limit=10"
```

**核对结果：** 返回包含 `items`、`total`、`limit`、`offset` 的 JSON 分页对象。
从 `items` 中找到目标工作区，取它的 `id` 作为工作区 UUID。

把 `WORKSPACE_ID` 设为这个 UUID，再读取十条文献：

```sh
curl --fail-with-body \
  -H "Authorization: Bearer $QUIREBASE_API_TOKEN" \
  "$QUIREBASE_URL/api/v1/workspaces/$WORKSPACE_ID/items?limit=10"
```

请求路径中的工作区 UUID 决定本次读取哪个文献库。空工作区返回空列表。

## 可以直接运行的 Python 示例

下面的示例使用标准库，运行时交互输入令牌。保存为 `list_library.py`，按需修改应用地址，再用 Python 运行：

```python
import json
from getpass import getpass
from urllib.request import Request, urlopen

origin = "http://127.0.0.1:9060"
token = getpass("API Token: ")


def get(path):
    request = Request(origin + path, headers={"Authorization": f"Bearer {token}"})
    with urlopen(request) as response:
        return json.load(response)


workspaces = get("/api/v1/workspaces?limit=100")
for workspace in workspaces["items"]:
    print(workspace["id"], workspace["name"])
workspace_id = input("Workspace UUID from this list: ").strip()
items = get(f"/api/v1/workspaces/{workspace_id}/items?limit=10")
print(json.dumps(items, ensure_ascii=False, indent=2))
```

示例只列出第一页工作区；完整客户端应遵循每个操作的分页约定。
工作区列表为空时，先接受目标工作区的邀请，再运行示例。

## 处理错误和写入操作

| 结果 | 先检查什么 |
| --- | --- |
| 401 | 令牌是否缺失、无效、过期或撤销 |
| 403 | 用户或成员权限、资源生命周期，或 Cookie 请求的 Origin |
| 409 | 版本或状态冲突；加载最新资源并检查后，再决定是否重试 |
| 输入校验失败 | 查看 `fields`，并按运行实例的 Schema 检查必需输入 |

错误包含 `code`、`message`，可能还带 `fields` 和 `meta`。客户端可按 `code` 分别处理错误，并用 `fields` 定位输入问题。
写入操作按 Schema 提交所需的预期版本。导入流程为“准备 → 检查预览 → 确认创建条目”。

浏览器使用登录 Cookie 发起修改请求时，Origin 应与应用配置一致。相关设置见[配置指南](/zh-cn/administration/configuration/)。
