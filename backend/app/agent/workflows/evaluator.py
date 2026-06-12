"""
安全条件表达式求值器

基于 ast.parse + 白名单节点遍历，不使用 eval/exec。
支持：比较(==, !=, >, <, >=, <=)、逻辑(and, or, not)、
成员测试(in)、空值检查(is None)、字段访问(a.b)、字面量。
"""
import ast
import operator
from typing import Any

from loguru import logger


# 允许的 AST 节点类型白名单
_ALLOWED_NODES = frozenset({
    # 表达式容器
    ast.Expression, ast.Module,
    # 比较 & 逻辑
    ast.Compare, ast.BoolOp, ast.UnaryOp,
    # 操作符
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.In, ast.NotIn, ast.Is, ast.IsNot,
    ast.And, ast.Or, ast.Not,
    # 值
    ast.Constant, ast.Name, ast.Attribute,
    ast.Load,
    # 容器
    ast.List, ast.Tuple, ast.Dict,
    # 下标访问
    ast.Subscript, ast.Index,
})

# 比较操作映射
_CMP_OPS: dict[type, Any] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}


class ConditionEvaluator:
    """安全条件表达式求值器

    示例用法:
        evaluator = ConditionEvaluator()
        result = evaluator.evaluate(
            "input.asset_codes is not None and len(input.asset_codes) > 0",
            {"input": {"asset_codes": ["SH000300"]}}
        )
    """

    def evaluate(self, expression: str, context: dict[str, Any]) -> bool:
        """安全求值条件表达式

        Args:
            expression: 条件表达式字符串
            context: 上下文变量字典

        Returns:
            bool: 求值结果

        Raises:
            ValueError: 表达式包含不允许的操作
            SyntaxError: 表达式语法错误
        """
        if not expression or not expression.strip():
            return True  # 空条件视为满足

        try:
            tree = ast.parse(expression.strip(), mode="eval")
        except SyntaxError as e:
            raise ValueError(f"条件表达式语法错误: {e}") from e

        # 白名单校验
        self._validate_tree(tree)

        # 求值
        try:
            result = self._eval_node(tree.body, context)
            return bool(result)
        except Exception as e:
            logger.warning("[ConditionEvaluator] 求值异常: {} | 表达式: {}", e, expression)
            raise ValueError(f"条件表达式求值失败: {e}") from e

    def _validate_tree(self, tree: ast.AST) -> None:
        """遍历 AST 树，确保所有节点在白名单中"""
        for node in ast.walk(tree):
            if type(node) not in _ALLOWED_NODES:
                raise ValueError(
                    f"不允许的操作: {type(node).__name__}。"
                    f"仅支持比较、逻辑、成员测试、字段访问和字面量。"
                )

    def _eval_node(self, node: ast.AST, context: dict[str, Any]) -> Any:
        """递归求值 AST 节点"""

        # 常量
        if isinstance(node, ast.Constant):
            return node.value

        # 变量名
        if isinstance(node, ast.Name):
            if node.id == "None":
                return None
            if node.id == "True":
                return True
            if node.id == "False":
                return False
            if node.id in context:
                return context[node.id]
            raise ValueError(f"未知变量: {node.id}")

        # 属性访问 a.b
        if isinstance(node, ast.Attribute):
            obj = self._eval_node(node.value, context)
            if isinstance(obj, dict):
                return obj.get(node.attr)
            return getattr(obj, node.attr, None)

        # 下标访问 a[b]
        if isinstance(node, ast.Subscript):
            obj = self._eval_node(node.value, context)
            # Python 3.9+ slice is directly the node
            idx = self._eval_node(node.slice, context)
            return obj[idx]

        # 比较
        if isinstance(node, ast.Compare):
            left = self._eval_node(node.left, context)
            for op, comparator in zip(node.ops, node.comparators):
                right = self._eval_node(comparator, context)

                if isinstance(op, ast.In):
                    if right is None:
                        return False
                    result = left in right
                elif isinstance(op, ast.NotIn):
                    if right is None:
                        return True
                    result = left not in right
                elif isinstance(op, ast.Is):
                    result = left is right
                elif isinstance(op, ast.IsNot):
                    result = left is not right
                elif type(op) in _CMP_OPS:
                    result = _CMP_OPS[type(op)](left, right)
                else:
                    raise ValueError(f"不支持的比较操作: {type(op).__name__}")

                if not result:
                    return False
                left = right
            return True

        # 布尔逻辑
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                return all(self._eval_node(v, context) for v in node.values)
            if isinstance(node.op, ast.Or):
                return any(self._eval_node(v, context) for v in node.values)

        # 一元操作 (not)
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.Not):
                return not self._eval_node(node.operand, context)

        # 列表
        if isinstance(node, ast.List):
            return [self._eval_node(el, context) for el in node.elts]

        # 元组
        if isinstance(node, ast.Tuple):
            return tuple(self._eval_node(el, context) for el in node.elts)

        # 字典
        if isinstance(node, ast.Dict):
            return {
                self._eval_node(k, context): self._eval_node(v, context)
                for k, v in zip(node.keys, node.values)
            }

        raise ValueError(f"不支持的节点类型: {type(node).__name__}")
