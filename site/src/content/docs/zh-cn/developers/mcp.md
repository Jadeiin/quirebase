---
title: 连接并验证 MCP 客户端
description: 配置带 API 令牌的 Streamable HTTP，发现工具，选择工作区，并验证读取权限。
---

通过 Streamable HTTP 连接 Quirebase，并在客户端配置 Bearer API 令牌。

## 1. 建立连接

1. 在应用“账号设置 → API 令牌”中，为这个客户端创建令牌。
2. 展开“客户端连接指南”，复制本实例的 MCP 地址或配置示例。
3. 在客户端的 MCP 设置中填写地址和 Bearer 请求头。使用 `mcpServers` JSON 结构的客户端可参考：

   ```json
   {
     "mcpServers": {
       "quirebase": {
         "url": "http://127.0.0.1:9060/mcp/",
         "headers": {"Authorization": "Bearer YOUR_API_TOKEN"}
       }
     }
   }
   ```

4. 替换为客户端可访问的应用地址和令牌。同机运行可使用示例地址，远程连接时填写服务器地址。
5. 保存并重新连接，检查工具列表。

各客户端配置格式不同，应使用等效的 Streamable HTTP 和请求头选项。

## 2. 查找工具并查看完整输入格式

**核对连接：** 初始工具列表应包含 `search_tools`、`get_schema`、`call_tool`。
查找时使用英文任务关键词。例如向 `search_tools` 传入：

```json
{"query": "list accessible workspaces"}
```

首次使用某个工具前，向 `get_schema` 请求完整输入、输出约定：

```json
{"tools": ["workspaces.get_workspaces"], "detail": "full"}
```

按完整 Schema 填写调用参数；客户端可缓存并复用已取得的 Schema。

## 3. 选择工作区，并验证一次读取

通过 `call_tool` 调用实际工具。列出可访问工作区的输入为：

```json
{"name": "workspaces.get_workspaces", "arguments": {}}
```

从返回结果中选择工作区 ID，再请求研究内容。之后按“查找任务工具 → 查看完整 Schema → 填写工作区与资源 ID → 调用”进行。
列出工作区成功说明连接和令牌有效；读取研究内容还会验证该工作区的当前权限。

标识符导入遵循“准备 → 检查预览和诊断 → 显式确认”。确认前应让用户审阅准备出的结果。

## 可用工具

可用工具包括文献元数据与整理、项目、文件元数据、批注和回复、标签、讨论、标识符导入、发现及引文。

## 连接失败时先检查什么

| 现象 | 检查 |
| --- | --- |
| 无法访问地址 | 应用 Origin、网络、TLS，以及客户端是否支持 Streamable HTTP |
| 401 | 令牌是否过期或撤销、Bearer 请求头、用户是否活跃 |
| 已连接，但研究操作被拒绝 | 是否传入工作区 ID、成员关系是否活跃、资源当前权限 |
| 浏览器客户端被 Origin/CORS 阻止 | 运维是否配置了明确的 `QUIREBASE_MCP_ALLOWED_ORIGINS` 白名单 |

浏览器客户端的 Origin 白名单见[配置指南](/zh-cn/administration/configuration/)。
实现决策见 [MCP ADR](https://github.com/Jadeiin/quirebase/blob/main/docs/adr/0004-research-intelligence-mcp-and-agent.md)。
