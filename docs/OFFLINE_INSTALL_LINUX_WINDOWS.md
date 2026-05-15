# 前后端离线依赖安装说明（Linux / Windows）

本文档适用于 **Agent 等功能融合后** 在内网或无外网环境下，手动准备依赖包并完成安装。请在与 **目标运行机相同架构、相同 Python 主版本** 的联网机器上下载 Python wheel；Node/npm 包可在任意联网机下载（建议与内网 **Node 主版本** 一致，如 Node 18/20）。

> 后端仓库中同路径文档：`portfilio-end/docs/OFFLINE_INSTALL_LINUX_WINDOWS.md`（内容一致）。

---

## 一、融合相关依赖清单（便于核对）

### 1. 后端（`portfilio-end`，`requirements.txt`）

| 用途 | 包名 | 备注 |
|------|------|------|
| Agent / Skills YAML | `pyyaml` | 解析技能与配置 |
| 报告 / 分析模板渲染 | `jinja2` | 依赖 `MarkupSafe` |
| OpenAI 兼容 API | `openai` | 会拉取 `httpx`、`pydantic` 等 |
| 上下文 token 估算 | `tiktoken` | 可选；未装时 `context_engine` 会降级为字符估算 |
| HTTP 客户端 | `httpx` | 与 `openai` 配合 |

其余条目为项目原有依赖；**完整列表以仓库内 `requirements.txt` 为准**。

### 2. 前端（`portfilio`，`package.json`）

| 用途 | 包名 | 备注 |
|------|------|------|
| Agent 对话 Markdown | `marked` | `AgentChatPanel.vue`、`AnalysisTemplates.vue` |
| HTML 消毒 | `dompurify` | 与 `marked` 配合 |

完整构建仍需安装 **全部** `dependencies` 与 `devDependencies`（见下文「整包离线」）。

---

## 二、后端 Python：联网机下载离线包

### 2.1 准备目录

在联网机上（**与内网生产机相同的 OS + CPU 架构 + Python 版本**，例如均为 Linux x86_64 + Python 3.11，或均为 Windows 64 位 + Python 3.11）：

```bash
mkdir -p offline-pip-wheels
cd portfilio-end   # 含 requirements.txt 的目录
```

### 2.2 仅下载融合新增或增量包（示例）

若内网已有旧环境，只需补装增量，可只下载指定包及其依赖：

**Linux / macOS（bash）：**

```bash
python3 -m pip download -d ./offline-pip-wheels \
  "pyyaml>=6.0" "jinja2>=3.1.0" "openai>=1.0.0" "tiktoken>=0.7.0" "httpx>=0.27.0"
```

**Windows（PowerShell，在 `portfilio-end` 目录）：**

```powershell
python -m pip download -d .\offline-pip-wheels `
  "pyyaml>=6.0" "jinja2>=3.1.0" "openai>=1.0.0" "tiktoken>=0.7.0" "httpx>=0.27.0"
```

### 2.3 下载完整 `requirements.txt`（推荐首次内网部署）

**Linux / macOS：**

```bash
python3 -m pip download -r requirements.txt -d ./offline-pip-wheels
```

**Windows：**

```powershell
python -m pip download -r requirements.txt -d .\offline-pip-wheels
```

将 **`offline-pip-wheels` 文件夹** 与 **`requirements.txt`** 一并拷贝到内网机。

> **注意：** Windows 下下载的 `.whl` 仅适用于 Windows；Linux 下下载的仅适用于 Linux。**不要混用**。

---

## 三、后端 Python：内网机手动安装

进入内网机上的项目目录（含 `requirements.txt` 与 `offline-pip-wheels`）。

**Linux / macOS：**

```bash
cd /path/to/portfilio-end
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install --no-index --find-links=./offline-pip-wheels -r requirements.txt
```

**Windows（PowerShell）：**

```powershell
cd D:\path\to\portfilio-end
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install --no-index --find-links=.\offline-pip-wheels -r requirements.txt
```

**Windows（CMD）：**

```bat
cd /d D:\path\to\portfilio-end
python -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install --no-index --find-links=.\offline-pip-wheels -r requirements.txt
```

### 验证（可选）

```bash
python -c "import yaml, jinja2, openai, tiktoken, httpx; print('ok')"
python -c "from main import app; print('app import ok')"
```

---

## 四、前端 npm：联网机准备离线包

### 方式 A：整项目依赖打包（推荐）

在联网机、**干净目录** 克隆或拷贝 `portfilio` 后：

```bash
cd portfilio
npm ci
# 或: npm install
```

将整个 **`node_modules`** 目录与 **`package.json`、`package-lock.json`** 打成压缩包，拷到内网后解压到项目根目录（路径保持一致）。

**Linux 打包示例：**

```bash
tar czvf portfilio-node_modules.tar.gz node_modules package-lock.json package.json
```

**Windows（PowerShell）：**

```powershell
Compress-Archive -Path node_modules,package-lock.json,package.json -DestinationPath portfilio-node_modules.zip
```

内网解压后执行 `npm run build` 或 `npm run dev` 验证。

> 若内网 OS 与联网机不同，一般 **纯 JS 包** 可跨平台；含 **原生模块** 时需在目标 OS 上重新 `npm install` 或使用对应平台的 `node_modules`。

### 方式 B：仅融合新增的两个 tgz（最小集）

仓库中若已有 `offline-npm-bundles/marked-4.3.0.tgz`、`dompurify-3.0.6.tgz`，内网在项目根目录执行：

**Linux / macOS：**

```bash
npm install ./offline-npm-bundles/marked-4.3.0.tgz ./offline-npm-bundles/dompurify-3.0.6.tgz --save
```

**Windows（PowerShell）：**

```powershell
npm install .\offline-npm-bundles\marked-4.3.0.tgz .\offline-npm-bundles\dompurify-3.0.6.tgz --save
```

若遇依赖解析问题可加：`--legacy-peer-deps`。

> 方式 B 仅覆盖 **marked / dompurify**；首次部署请仍用 **方式 A** 或在内网私服同步全量依赖。

### 联网机重新生成 tgz（可选）

```bash
npm pack marked@4.3.0
npm pack dompurify@3.0.6
```

将生成的 `.tgz` 拷入内网，用 `npm install ./xxx.tgz` 安装。

---

## 五、常见问题

1. **`pip install --no-index` 报找不到包**  
   - 确认 `--find-links` 指向的目录包含该包及其**所有传递依赖**的 wheel。  
   - 缺什么就在联网机对 `requirements.txt` 再执行一次 `pip download` 补齐。

2. **tiktoken 在部分环境无 wheel**  
   - 需在内网具备 **C 编译工具链** 才能从源码构建；更稳妥是在联网机下载 **对应平台** 的 `tiktoken` whl 一并带入。

3. **Python 版本不一致**  
   - 下载 wheel 的 Python 小版本尽量与内网一致（如均为 3.11.x）。

4. **npm 栈溢出或安装失败**  
   - 删除 `node_modules` 与 `package-lock.json` 后重试；或升级 npm；详见仓库 `offline-npm-bundles/OFFLINE_INSTALL.txt`。

---

## 六、文件对照

| 仓库 | 依赖声明 |
|------|-----------|
| 后端 | `portfilio-end/requirements.txt` |
| 前端 | `portfilio/package.json`、`package-lock.json` |

后端环境变量示例见 `portfilio-end/.env.example`。
