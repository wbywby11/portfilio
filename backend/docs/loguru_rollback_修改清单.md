# loguru 接入修改清单（回退参考）

本次修改为接入 loguru 实现启动时日志打印与按天切分存储。如需回退，可按下列项逐项还原。

---

## 修改日期

（执行本次修改的日期，由执行人填写）

---

## 涉及文件与回退方式

### 1. 新增文件（回退：删除即可）

- **`app/config/logging_config.py`**  
  新建的 loguru 配置模块。回退：删除该文件。

### 2. 修改文件（回退：用 git 或按下面说明还原）

- **`main.py`**
  - 删除最顶部两行：`from app.config.logging_config import setup_logging` 与 `setup_logging()`。
  - `on_startup`：恢复为使用 `print(...)` 的原始逻辑（见 git 历史或下方备份说明）。
  - `on_shutdown`：删除 `from loguru import logger` 与 `logger.info("应用已关闭")`，仅保留 `Database.close()`。

- **`app/config/database.py`**
  - 删除顶部：`from loguru import logger`。
  - `connect()` 内：`logger.info("数据库连接成功: {}", settings.DATABASE_NAME)` 改回 `print(f"✓ 数据库连接成功: {settings.DATABASE_NAME}")`。
  - `close()` 内：`logger.info("数据库连接已关闭")` 改回 `print("✓ 数据库连接已关闭")`。

- **`requirements.txt`**
  - 删除新增的 `loguru>=0.7.0` 及其上方的 `# 日志` 注释行。

- **`.gitignore`**
  - 删除新增的 `# 日志目录（loguru 切分存储）` 与 `logs/` 两行。

---

## 回退命令示例（在项目根目录）

```bash
# 查看本次修改
git status
git diff

# 回退所有上述修改（未提交时）
git checkout -- main.py app/config/database.py requirements.txt .gitignore
git clean -f app/config/logging_config.py

# 若已提交，则回退到上一提交
git revert HEAD --no-edit
```

---

## 备份说明（原始逻辑摘要）

- **main.py on_startup 原 print 逻辑**：  
  `print("\n========== 初始化内置策略模板 ==========")`；  
  成功后 `print(f"\n初始化完成:")` 及 4 行 `print(f"  - ...")`、`print("========================================\n")`；  
  异常时 `print(f"\n初始化内置模板失败: {e}")` 与 `print("========================================\n")`。
- **database.py**：`connect()` 中 `print(f"✓ 数据库连接成功: {settings.DATABASE_NAME}")`；`close()` 中 `print("✓ 数据库连接已关闭")`。

以上内容便于人工回退或编写脚本还原。
