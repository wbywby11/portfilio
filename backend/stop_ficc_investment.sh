#!/bin/bash
#
# 查找并终止 ficc_investment 相关进程（含主进程及其子进程）
# 用法: ./stop_ficc_investment.sh [--dry-run]
#   --dry-run: 仅打印将要终止的进程，不实际执行 kill
#

set -e

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=1
    echo "[dry-run] 仅预览，不执行 kill"
fi

PATTERN="ficc_investment"

# 1. 查找主进程（uvicorn 或 python 运行 ficc_investment，排除 grep 自身）
MAIN_PIDS=$(ps -ef | grep -E "ficc_investment.*(uvicorn|main:app)" | grep -v grep | awk '{print $2}' | sort -u)

if [[ -z "$MAIN_PIDS" ]]; then
    echo "未找到 ficc_investment 主进程，可能已停止"
    exit 0
fi

echo "找到主进程 PID: $MAIN_PIDS"

# 2. 收集所有需终止的 PID：主进程 + 其子进程（PPID 等于主进程 PID 的进程）
ALL_PIDS=""
for MAIN_PID in $MAIN_PIDS; do
    # 主进程自身
    ALL_PIDS="$ALL_PIDS $MAIN_PID"
    # 子进程（PPID = MAIN_PID）
    CHILD_PIDS=$(ps -ef | awk -v ppid="$MAIN_PID" '$3 == ppid {print $2}')
    if [[ -n "$CHILD_PIDS" ]]; then
        echo "  主进程 $MAIN_PID 的子进程: $CHILD_PIDS"
        ALL_PIDS="$ALL_PIDS $CHILD_PIDS"
    fi
done

# 去重并排序：子进程 PID 通常大于父进程，按 PID 降序以便先终止子进程
PIDS_TO_KILL=$(echo $ALL_PIDS | tr ' ' '\n' | sort -n | uniq | sort -n -r)

echo "将终止以下进程: $PIDS_TO_KILL"

if [[ $DRY_RUN -eq 1 ]]; then
    echo "[dry-run] 跳过实际 kill"
    exit 0
fi

# 3. 先 SIGTERM 优雅退出
for PID in $PIDS_TO_KILL; do
    if kill -0 "$PID" 2>/dev/null; then
        echo "发送 SIGTERM 到 PID $PID"
        kill -TERM "$PID" 2>/dev/null || true
    fi
done

# 4. 等待最多 10 秒
echo "等待进程退出（最多 10 秒）..."
for i in {1..10}; do
    REMAINING=""
    for PID in $PIDS_TO_KILL; do
        if kill -0 "$PID" 2>/dev/null; then
            REMAINING="$REMAINING $PID"
        fi
    done
    if [[ -z "$REMAINING" ]]; then
        echo "所有进程已退出"
        exit 0
    fi
    sleep 1
done

# 5. 若仍有残留，SIGKILL 强制终止
REMAINING=""
for PID in $PIDS_TO_KILL; do
    if kill -0 "$PID" 2>/dev/null; then
        REMAINING="$REMAINING $PID"
    fi
done

if [[ -n "$REMAINING" ]]; then
    echo "以下进程未响应 SIGTERM，发送 SIGKILL: $REMAINING"
    for PID in $REMAINING; do
        kill -9 "$PID" 2>/dev/null || true
    done
fi

echo "ficc_investment 进程已终止"
