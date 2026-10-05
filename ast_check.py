"""纯搬运校验：核对两份代码里所有函数/方法的名字、签名与函数体是否逐一对应。

重构应当只搬位置、不改内容。这个脚本把两边所有函数与方法（含类里的）按
「类名.方法名」为键抽出来，逐个比对签名与函数体（AST 层面，与位置和注释无关）。
两边完全对应才算通过——搬运式重构（尤其是 UI 代码）用它比跑界面更可靠。

用法：
    python ast_check.py --old <旧文件或旧目录> --new <新文件或新目录>
退出码：0 = 逐一对应，1 = 有差异，2 = 参数或路径有问题。
"""

import ast
import sys
from collections import Counter
from pathlib import Path


def _walk(node: ast.AST, prefix: str = ""):
    """只往类里递归，收集模块级与类级的函数/方法（不钻函数内部）。"""
    for child in getattr(node, "body", []):
        if isinstance(child, ast.ClassDef):
            yield from _walk(child, f"{prefix}{child.name}.")
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield child, prefix


def _fingerprint(node) -> str:
    """签名 + 装饰器 + 函数体：只认这些，跟在哪个文件、第几行无关。"""
    decorators = "|".join(ast.dump(item) for item in node.decorator_list)
    signature = ast.dump(node.args)
    body = ast.dump(ast.Module(body=node.body, type_ignores=[]))
    return f"{decorators}::{signature}::{body}"


def _collect(target: Path) -> dict[str, str]:
    """把一个文件或目录里所有函数/方法抽成 {限定名: 指纹}。"""
    paths = sorted(target.rglob("*.py")) if target.is_dir() else [target]
    found: dict[str, str] = {}
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node, prefix in _walk(tree):
            found[f"{prefix}{node.name}"] = _fingerprint(node)
    return found


def _short(text: str, limit: int = 72) -> str:
    """把一大段 AST 说明截短，报告里好看些。"""
    return text if len(text) <= limit else f"{text[:limit]}…"


def _module_statements(target: Path) -> list[str]:
    """模块级的赋值与调用语句（跳过 import 与文档字符串），按内容记账。

    这些不在函数里，但搬错地方照样出事——比如 Win32 那堆 ctypes 初始化。
    """
    paths = sorted(target.rglob("*.py")) if target.is_dir() else [target]
    found: list[str] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                found.append(ast.dump(node))
            elif isinstance(node, ast.Expr) and not isinstance(node.value, ast.Constant):
                found.append(ast.dump(node))
    return sorted(found)


def _compare_statements(old: Path, new: Path) -> list[str]:
    """模块级语句用多重集比对——同一条语句出现几次也算数，不能被去重蒙混过去。"""
    before = Counter(_module_statements(old))
    after = Counter(_module_statements(new))
    problems: list[str] = []
    for stmt, count in sorted((before - after).items()):
        problems.append(f"模块级语句少了 {count} 处：{_short(stmt)}")
    for stmt, count in sorted((after - before).items()):
        problems.append(f"模块级语句多了 {count} 处：{_short(stmt)}")
    return problems


def main() -> int:
    args = sys.argv[1:]
    if "--old" not in args or "--new" not in args:
        print("用法：python ast_check.py --old <旧文件或旧目录> --new <新文件或新目录>")
        return 2

    old = Path(args[args.index("--old") + 1])
    new = Path(args[args.index("--new") + 1])
    if not old.exists() or not new.exists():
        print(f"路径不存在：{old} / {new}")
        return 2

    before = _collect(old)
    after = _collect(new)
    if not before:
        print(f"{old} 里没找到任何函数，路径是不是给错了？")
        return 2

    problems = [f"丢了：{name}" for name in sorted(set(before) - set(after))]
    problems += [f"多了：{name}" for name in sorted(set(after) - set(before))]
    problems += [
        f"改了：{name}"
        for name in sorted(set(before) & set(after))
        if before[name] != after[name]
    ]
    problems += _compare_statements(old, new)

    if not problems:
        print(f"纯搬运校验通过：{len(before)} 个函数/方法的签名与函数体逐一相同")
        return 0

    for line in problems[:200]:
        print(line)
    if len(problems) > 200:
        print(f"...（还有 {len(problems) - 200} 处）")
    print(f"\n共 {len(problems)} 处不一致")
    return 1


if __name__ == "__main__":
    sys.exit(main())
