"""Whitelisted expression evaluator. Allowed: names, numbers, bool, comparisons,
and/or/not, + - * / and unary minus, min/max-free. No calls, attributes,
subscripts, comprehensions, lambdas, strings."""
import ast
import operator as op

_BIN = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv}
_CMP = {ast.Lt: op.lt, ast.LtE: op.le, ast.Gt: op.gt, ast.GtE: op.ge, ast.Eq: op.eq, ast.NotEq: op.ne}


class UnsafeExpression(ValueError):
    pass


def compile_expr(src: str):
    if len(src) > 300:
        raise UnsafeExpression("too long")
    try:
        tree = ast.parse(src, mode="eval")
    except SyntaxError as e:
        raise UnsafeExpression(f"syntax: {e}")
    _check(tree.body)
    return tree.body


def _check(n):
    ok = (ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.USub, ast.BinOp, ast.Compare,
          ast.Name, ast.Load, ast.Constant) + tuple(_BIN) + tuple(_CMP)
    for c in ast.walk(n):
        if not isinstance(c, ok):
            raise UnsafeExpression(f"forbidden: {type(c).__name__}")
        if isinstance(c, ast.Constant) and not isinstance(c.value, (int, float, bool)):
            raise UnsafeExpression("only numbers/bools")
        if isinstance(c, ast.Name) and c.id.startswith("_"):
            raise UnsafeExpression("forbidden name")


def _ev(n, env):
    if isinstance(n, ast.Constant): return n.value
    if isinstance(n, ast.Name):
        if n.id not in env: raise UnsafeExpression(f"unknown name {n.id}")
        return env[n.id]
    if isinstance(n, ast.UnaryOp):
        v = _ev(n.operand, env)
        return (not v) if isinstance(n.op, ast.Not) else -v
    if isinstance(n, ast.BinOp):
        r = _ev(n.right, env)
        if isinstance(n.op, ast.Div) and r == 0: return 0.0
        return _BIN[type(n.op)](_ev(n.left, env), r)
    if isinstance(n, ast.BoolOp):
        vals = (_ev(v, env) for v in n.values)
        return all(vals) if isinstance(n.op, ast.And) else any(vals)
    if isinstance(n, ast.Compare):
        l = _ev(n.left, env)
        for o, c in zip(n.ops, n.comparators):
            r = _ev(c, env)
            if not _CMP[type(o)](l, r): return False
            l = r
        return True
    raise UnsafeExpression("bad node")


def safe_eval(src_or_tree, env: dict):
    tree = compile_expr(src_or_tree) if isinstance(src_or_tree, str) else src_or_tree
    return _ev(tree, env)
