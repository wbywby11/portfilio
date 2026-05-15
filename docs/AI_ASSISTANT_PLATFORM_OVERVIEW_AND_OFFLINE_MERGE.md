# 数智平台 AI 助手 — 子界面、前后端功能、依赖与离线合并清单

本文梳理 **「数智平台 AI 助手」** 菜单下各子界面的前后端职责、接口与数据依赖，并整理 **增量文件/包**，便于在无外网环境合并到另一套前后端工程。

---

## 一、子界面与路由（前端 `portfilio`）

| 菜单/功能 | 路由 path | 组件 | 说明 |
|-----------|-----------|------|------|
| 智能对话 | `/agent/chat` | `views/agent/AgentWorkspace.vue` | 主工作台：场景选择 + `AgentChatPanel`，支持 SSE 流式 |
| 场景对话（隐藏） | `/agent/chat/:scene` | 同上 `props: true` | 按场景 key 打开，与 `config/agentScenes.js` 对齐 |
| 对话历史 | `/agent/history` | `views/agent/ConversationHistory.vue` | 列表、跳转回对话、删会话 |
| 知识记忆 | `/agent/memories` | `views/agent/MemoryManager.vue` | 记忆 CRUD/搜索 |
| 报告中心 | `/agent/reports` | `views/agent/ReportCenter.vue` | 报告列表、详情、导出 |
| 分析模板 | `/agent/templates` | `views/agent/AnalysisTemplates.vue` | 模板 CRUD、执行 |
| 场景管理 | `/agent/scenes` | `views/agent/SceneManager.vue` | 仅管理员 `roles: ['admin']`，展示 `AGENT_SCENES` |

**兼容跳转（数据分析模块下）：**

- `analysis/agent` → `/agent/chat`
- `analysis/memories` → `/agent/memories`

**主导航：** `layout/MainLayout.vue` 中 `el-submenu index="agent"` 与上述路径一致。

---

## 二、前端功能 ↔ 后端 API 映射

统一前缀：`{API_PREFIX}/agent`，默认即 **`/api/v1/agent`**（与 `main.py` 中 `settings.API_PREFIX` 一致）。

| 功能 | 方法 | 路径 | 前端调用 |
|------|------|------|----------|
| 非流式对话 | POST | `/chat` | `api/agent.js` → `sendMessage` |
| 流式对话（SSE） | POST | `/chat/stream` | `sendMessageStream`（**原生 fetch**，需带 `VUE_APP_BASE_URL` 与 Bearer token） |
| 对话列表 | GET | `/conversations` | `getConversations` |
| 对话详情 | GET | `/conversations/{id}` | `getConversation` |
| 删除对话 | DELETE | `/conversations/{id}` | `deleteConversation` |
| 更新标题 | PUT | `/conversations/{id}/title` | `updateConversationTitle` |
| 记忆列表 | GET | `/memories` | `getMemories` |
| 删除记忆 | DELETE | `/memories/{id}` | `deleteMemory` |
| 搜索记忆 | POST | `/memories/search` | `searchMemories` |
| 报告列表 | GET | `/reports` | `getReports` |
| 报告详情 | GET | `/reports/{id}` | `getReport` |
| 删除报告 | DELETE | `/reports/{id}` | `deleteReport` |
| 导出报告 | GET | `/reports/{id}/export` | `exportReport` |
| 模板列表 | GET | `/analysis-templates` | `getAnalysisTemplates` |
| 创建模板 | POST | `/analysis-templates` | `createAnalysisTemplate` |
| 模板详情 | GET | `/analysis-templates/{id}` | `getAnalysisTemplate` |
| 更新模板 | PUT | `/analysis-templates/{id}` | `updateAnalysisTemplate` |
| 删除模板 | DELETE | `/analysis-templates/{id}` | `deleteAnalysisTemplate` |
| 执行模板 | POST | `/analysis-templates/{id}/execute` | `executeAnalysisTemplate` |

**后端路由实现：** `app/agent/api/agent_router.py`  
**对话编排：** `app/agent/services/chat_service.py`（`InvestmentAgent` + `ContextEngine` + Mongo `ConversationStore`）  
**记忆：** `app/agent/memory/memory_store.py`（集合 `agent_memories`）  
**报告：** `app/services/report_service.py`（集合 `reports` 等）  
**分析模板：** `app/services/template_service.py`（集合 `analysis_templates`，执行时调用 `tool_registry` 内工具并写报告）

---

## 三、前端模块依赖（文件级）

### 3.1 核心文件（建议整目录同步）

```
src/views/agent/           # 全部子界面
src/api/agent.js
src/store/modules/agent.js
src/store/index.js         # 注册 agent 模块（增量：import + modules）
src/router/index.js        # /agent 路由组 + analysis 重定向
src/layout/MainLayout.vue  # AI 助手子菜单、activeMenu 逻辑
src/config/agentScenes.js
src/components/AgentChatPanel.vue
src/components/AgentResultCard.vue
src/components/PlanProgress.vue
src/components/SceneSelector.vue
```

### 3.2 全局依赖

- `src/main.js`：`echarts` 挂到 `Vue.prototype.$echarts`（对话内图表渲染依赖）。
- `utils/request.js`：除 SSE 外均走 axios；SSE 使用 `VUE_APP_BASE_URL`（见 `agent.js`）。

### 3.3 UI/工具库（与 AI 助手强相关）

| npm 包 | 用途 |
|--------|------|
| `marked` | Markdown 渲染助手回复 |
| `dompurify` | 对 Markdown HTML 消毒 |
| `echarts` | 工具返回中的 `echarts_option` 绘图 |
| `element-ui` | 布局与表单（工程全局） |
| `axios` | 非 SSE 请求 |
| `vue` / `vue-router` / `vuex` | 框架与状态 |

**工程级补丁（非 npm 包）：**

- `scripts/apply-vxe-table-scroll-fix.js` — 与 vxe-table 相关，**非 AI 菜单必需**；若目标项目无 vxe 可不带。
- `scripts/ensure-nested-tslib.js` + `vue.config.js` 中 `tslib` 配置 — 解决 `echarts` 链上 `tslib` 解析；**若已合并 echarts，建议保留**。

---

## 四、后端模块依赖（Python 包 + 目录）

### 4.1 入口与路由

- `main.py`：`from app.agent.api.agent_router import router as agent_router`，`include_router(..., prefix=f"{settings.API_PREFIX}/agent")`

### 4.2 Agent 包（建议整体拷贝）

```
app/agent/
  __init__.py
  api/agent_router.py
  core/          # agent, llm_client, model_router, context_engine, config, error_handler, plan_manager
  services/      # chat_service, conversation_store
  memory/        # MemoryManager, MemoryStore
  prompts/
  schemas/
  tools/         # 全量工具 + pipeline_executor + chart_builder 等
  skills/        # skill_loader, skill_selector, docs/*.md
  workflows/     # 可选工作流 YAML 引擎
  templates/reports/*.md
```

### 4.3 与 Agent 强耦合的业务层（增量）

| 路径 | 作用 |
|------|------|
| `app/services/report_service.py` | 报告 CRUD/导出；引用 `app/agent/templates/reports` |
| `app/services/template_service.py` | 分析模板；依赖 `tool_registry`、Jinja2、集合 `analysis_templates` |
| `app/models/report_model.py` | 报告模型（若路由或服务引用） |

### 4.4 MongoDB 集合（AI 相关）

| 集合 | 用途 |
|------|------|
| `agent_conversations` | 会话元数据 |
| `agent_messages` | 消息（含 tool_calls / tool_calls_raw） |
| `agent_memories` | 用户记忆 |
| `analysis_templates` | 分析模板定义 |
| `reports` | 报告实例 |
| `research_knowledge` | 报告服务内检索（如配置使用） |

索引由 `ConversationStore.ensure_indexes()` 等在运行时创建。

### 4.5 环境变量（`.env`，与 Agent 相关）

- **LLM：** `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL` 或 `LLM_MODELS`（JSON 多模型）
- **行为：** `AGENT_MAX_TOOL_ROUNDS`、`AGENT_CONVERSATION_MAX_HISTORY`、`AGENT_MAX_RETRIES`、`AGENT_RETRY_BASE_BACKOFF`、`AGENT_COMPRESS_THRESHOLD`、`AGENT_TOOL_RESULT_MAX_CHARS`、`LLM_SOFT_TOOLS`、`LLM_MAX_CONTEXT_TOKENS`
- **HTTP：** `LLM_HTTP_CONNECT_TIMEOUT`、`LLM_HTTP_READ_TIMEOUT`、`LLM_HTTP_WRITE_TIMEOUT`（若在 `config.py` 中已定义）
- **Skills：** `SKILL_VERSION_CONFIG`（可选）
- **Mongo：** 与全局 `Database` 配置一致

---

## 五、增量 Python 依赖（相对「无 AI 的 FastAPI 骨架」）

在 `requirements.txt` 中与 **Agent / 模板 / 报告渲染** 直接相关的增量通常为：

```
openai>=1.0.0
httpx>=0.27.0          # OpenAI SDK 底层；建议与现有版本区间一致
tiktoken>=0.7.0        # 上下文 token 估算（可选：未安装时有回退）
jinja2>=3.1.0          # 模板服务渲染
pyyaml>=6.0            # workflows / 部分配置
```

> **说明：** `pandas` / `numpy` / `pymongo` / `motor` / `loguru` / `pydantic` 等多为全项目共用；合并时以目标项目 `requirements.txt` **取并集** 即可。

---

## 六、Agent 工具与平台其它模块的依赖（逻辑层）

`app/agent/tools/` 下工具会通过 **服务层/API** 调用资产、回测、监控、策略等能力，例如：

- `asset_tools`、`data_query_tools`、`analysis_tools`
- `backtest_tools`、`strategy_tools`、`portfolio_tools`、`monitor_tools`
- `compare_tools`、`strategy_advisor_tools`、`chart_builder`

**离线合并时：** 若目标环境缺少对应 `app/api/*`、`app/services/*`、Mongo 集合或业务数据，Agent **对话可能部分工具报错**，但路由与页面仍可启动。需按实际业务做 **工具清单裁剪** 或 **mock**。

---

## 七、离线合并操作建议（最小步骤）

### 7.1 前端

1. 拷贝 **第三节** 所列目录与文件。  
2. 合并 `router/index.js`、`store/index.js`、`MainLayout.vue`、`main.js`（echarts）。  
3. 安装 npm 依赖：`marked`、`dompurify`、`echarts`（及已存在的 `element-ui`、`axios` 等）。  
4. 配置 `.env` / `VUE_APP_BASE_URL` 指向后端。  
5. 若使用 echarts：保留 `tslib` 与 `vue.config.js` 别名、或 `postinstall` 中的 `ensure-nested-tslib.js`（见项目 `package.json`）。

### 7.2 后端

1. 拷贝 **第四节** `app/agent/` 及 `report_service` / `template_service` / `report_model` 等差异文件。  
2. 合并 `main.py` 中 `agent_router`。  
3. `pip install` **第五节** 与现有 `requirements.txt` 并集（离线可用 `pip download` + `pip install --no-index`）。  
4. 配置 **4.5** 环境变量并确保 Mongo 可连。  
5. 首次启动执行索引与数据初始化（依赖现有 `Database.connect()` 与业务 init 脚本）。

### 7.3 校验清单

- `GET /api/v1/agent/conversations` 200  
- `POST /api/v1/agent/chat/stream` SSE 有事件  
- 前端「智能对话」可收流、Markdown 与图表正常  
- 「知识记忆 / 报告 / 分析模板」与各自 CRUD 接口一致  

---

## 八、版本与维护说明

- 路由、集合名、接口前缀以当前仓库 **`portfilio` + `portfilio-end`** 为准；合并到其它分支后请以 `agent_router.py` 与 `router/index.js` 为最终源。  
- `ChatRequest.user_id` 后端默认为 `"default"`；若需多用户隔离，应在登录态下由前端传入并与会话列表 `user_id` 查询一致。  

---

*文档生成基于仓库目录扫描；合并前请用 `git diff` 再确认与目标分支的差异。*
