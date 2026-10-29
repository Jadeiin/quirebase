---
title: 连接 HTTP API 客户端
description: 创建令牌，列出工作区，选对 UUID，再完成第一次文献库请求。
---

使用你所登录应用的 Origin，不是文档站地址。运行中的应用提供 `/api/v1/` JSON API、`/docs` 交互文档和 `/openapi.json` Schema。
本站的[自动生成 API 参考](/reference/api/)来自开发检出，保留 Schema 的英文描述。
部署版本不同时，以该实例自身的 Schema 为准。

## 创建凭据

1. 登录应用，打开“账号设置 → API 令牌”。
2. 创建带名称和有效期的令牌，立即复制一次性显示的明文值。
3. 展开“客户端连接指南”，核对应用地址。
4. 将令牌保存到客户端凭据机制中，通过 `Authorization: Bearer …` 请求头发送。

令牌继承用户的当前权限，没有额外的逐工具授权，也不能绕过缺失的工作区成员关系。
运维人员也可以在源码安装中执行：

```sh
uv run quirebase create-api-token USERNAME --name "Research client" --days 30
```

把 `USERNAME` 换成现有用户名。明文只显示一次，不要放到 URL 中。

## 第一次请求：列出并选择工作区

使用 curl 时，把 `QUIREBASE_URL` 设置为应用 Origin，通过本地凭据或环境机制提供 `QUIREBASE_API_TOKEN`，再运行：

```sh
curl --fail-with-body \
  -H "Authorization: Bearer $QUIREBASE_API_TOKEN" \
  "$QUIREBASE_URL/api/v1/workspaces?limit=10"
```

**核对结果：** 返回包含 `items`、`total`、`limit`、`offset` 的 JSON 分页对象。
从有权访问的工作区中选择 `items[].id`；这里需要的是工作区 UUID，不是用户名、条目 ID 或项目 ID。

把 `WORKSPACE_ID` 设为这个 UUID，再读取十条文献：

```sh
curl --fail-with-body \
  -H "Authorization: Bearer $QUIREBASE_API_TOKEN" \
  "$QUIREBASE_URL/api/v1/workspaces/$WORKSPACE_ID/items?limit=10"
```

空工作区可以正常返回空列表。即使用户只有一个工作区，研究请求路径仍然要明确包含工作区上下文。

## 可以直接运行的 Python 示例

下面只使用标准库，通过交互输入令牌，不把明文写入源码。保存为 `list_library.py`，按需修改应用地址，再用 Python 运行：

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
没有可访问工作区时，不要用空 ID 继续请求，应先取得成员资格。

## 处理错误和写入操作

| 结果 | 先检查什么 |
| --- | --- |
| 401 | 令牌是否缺失、无效、过期或撤销；显式错误的 Authorization 不会回退到浏览器 Cookie |
| 403 | 用户或成员权限、资源生命周期，或 Cookie 请求的 Origin |
| 409 | 版本或状态冲突；加载最新资源并检查后，再决定是否重试 |
| 输入校验失败 | 查看 `fields`，并按运行实例的 Schema 检查必需输入 |

错误包含 `code`、`message`，可能还带 `fields` 和 `meta`。客户端应按机器可读错误码处理，不依赖英文消息文案匹配。
部分修改请求要求提交预期版本，必须保留这些值。导入需要准备、检查预览、显式确认，查找成功不代表已经创建条目。

Bearer 请求与浏览器登录 Cookie 是两种认证方式。Cookie 认证的修改请求要求正确 Origin；
MCP 的 CORS 白名单不会开放 `/api/v1/` 的跨站浏览器访问。
