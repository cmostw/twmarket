"""Generate localized MDX API references from Python source docstrings.

Run python3 scripts/generate-api.py from apps/docs. Read src/twmarket and
write content/docs/reference/api without importing the package or using the network.
"""

import ast
import copy
import json
import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
SOURCE = APP.parents[1] / "src/twmarket"
OUTPUT = APP / "content/docs/reference/api"
SECTIONS = {
    "clients": (
        "Client / AsyncClient",
        ["client.py", "async_client.py"],
        {"Client", "AsyncClient"},
    ),
    "twse-tpex": (
        "TWSE / TPEx",
        ["providers/_equities.py"],
        {"StockMarket", "AsyncStockMarket"},
    ),
    "esb": ("興櫃 / ESB", ["providers/esb/market.py"], {"ESB", "AsyncESB"}),
    "taifex": ("TAIFEX", ["providers/taifex/market.py"], {"Taifex", "AsyncTaifex"}),
    "mops": ("MOPS", ["providers/mops/market.py"], {"MOPS", "AsyncMOPS"}),
    "tdcc": ("TDCC", ["providers/tdcc/market.py"], {"TDCC", "AsyncTDCC"}),
    "ndc": ("NDC", ["providers/ndc/market.py"], {"NDC", "AsyncNDC"}),
    "cbc": ("CBC", ["providers/cbc/market.py"], {"CBC", "AsyncCBC"}),
    "models": (
        "資料模型 / Models",
        [str(p.relative_to(SOURCE)) for p in sorted((SOURCE / "models").glob("*.py"))],
        None,
    ),
    "errors": ("例外 / Exceptions", ["errors.py"], None),
    "integrations": ("DataFrame", ["integrations/frames.py"], set()),
}
FUNCTIONS = {"to_pandas", "to_polars", "to_pandas_book", "to_polars_book"}
INTERNAL = {"register_stream", "unregister_stream", "close_streams"}


def doc(node: ast.AST, locale: str) -> str:
    """Return the requested docstring language and validate PEP 257 structure."""
    text = ast.get_docstring(node)
    if not text:
        raise ValueError(f"Missing docstring: {node.name}")
    for part in text.split("\n\nEnglish:\n\n"):
        lines = part.splitlines()
        if not lines[0].endswith(".") or (len(lines) > 1 and lines[1]):
            raise ValueError(f"Invalid PEP 257 summary: {node.name}")
    parts = text.split("\n\nEnglish:\n\n", 1)
    localized = parts[1] if locale == "en" and len(parts) == 2 else parts[0]
    localized = localized.replace("；", "。\n\n")
    localized = re.sub(r";\s+", ".\n\n", localized)
    if locale == "zh-TW":
        localized = re.sub(r"(?<=[\u4e00-\u9fff])\.", "。", localized)
    return localized


def signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Return the annotated signature without the implicit receiver."""
    node = copy.deepcopy(node)
    node.decorator_list = []
    if node.args.args and node.args.args[0].arg in {"self", "cls"}:
        node.args.args.pop(0)
    return ast.unparse(node).splitlines()[0].removesuffix(":") + ": ..."


def describe(node: ast.AST, locale: str, depth: int = 2) -> str:
    """Render a documented class, method or function as an MDX section."""
    body = [f"{'#' * depth} `{node.name}`", doc(node, locale)]
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        body.insert(1, f"```python\n{signature(node)}\n```")
    if isinstance(node, ast.ClassDef):
        fields = [n for n in node.body if isinstance(n, ast.AnnAssign)]
        if fields:
            heading = "欄位" if locale == "zh-TW" else "Fields"
            body.append(
                f"### {heading}\n\n```python\n"
                + "\n".join(ast.unparse(n) for n in fields)
                + "\n```"
            )
        for member in node.body:
            if (
                isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
                and (not member.name.startswith("_") or member.name == "__init__")
                and member.name not in INTERNAL
                and (
                    member.name != "__init__" or node.name in {"Client", "AsyncClient"}
                )
            ):
                body.append(describe(member, locale, depth + 1))
    return "\n\n".join(body)


def main() -> None:
    """Write the complete public reference in both languages."""
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for section, (title, files, classes) in SECTIONS.items():
        for locale, suffix in [("zh-TW", ""), ("en", ".en")]:
            localized_title = (
                title.split(" / ")[1 if locale == "en" and " / " in title else 0]
                if section not in {"clients", "twse-tpex"}
                else title
            )
            parts = [
                "---\ntitle: "
                + json.dumps(localized_title, ensure_ascii=False)
                + "\n---"
            ]
            if section == "models":
                parts.append(
                    "## 數值與日期\n\n"
                    "價格與金額使用 `Decimal`，缺值為 `None`。"
                    "依模型的 `volume_unit`、`amount_unit` 或 `unit` 判讀單位。\n\n"
                    "百分數欄位保留百分數，例如 `20.25` 表示 20.25%。\n\n"
                    "`SourceInfo` 記錄來源、URL 與 UTC 取得時間。"
                    "交易日與報導期間由各模型的日期欄位表示。"
                    if locale == "zh-TW"
                    else "## Values and dates\n\n"
                    "Prices and monetary values use `Decimal`. "
                    "Missing values use `None`. "
                    "Read each model's `volume_unit`, `amount_unit` "
                    "or `unit` for units.\n\n"
                    "Percentage fields retain percent units. "
                    "For example, `20.25` means 20.25%.\n\n"
                    "`SourceInfo` records the source, URL and UTC retrieval time. "
                    "Model date fields identify trading dates and reporting periods."
                )
            for file in files:
                tree = ast.parse((SOURCE / file).read_text())
                for node in tree.body:
                    if (
                        isinstance(node, ast.ClassDef)
                        and not node.name.startswith("_")
                        and (classes is None or node.name in classes)
                    ):
                        parts.append(describe(node, locale))
                    elif (
                        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and node.name in FUNCTIONS
                    ):
                        parts.append(describe(node, locale))
            (OUTPUT / (section + suffix + ".mdx")).write_text("\n\n".join(parts) + "\n")
    for suffix, title in [("", "API"), (".en", "API")]:
        (OUTPUT / ("meta" + suffix + ".json")).write_text(
            json.dumps({"title": title, "pages": list(SECTIONS)}, indent=2) + "\n"
        )


if __name__ == "__main__":
    main()
