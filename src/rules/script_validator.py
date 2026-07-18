"""AST and evidence validation for one fixed current-door calculation."""

from __future__ import annotations

import ast
import hashlib

from src.schemas.rule import (
    GeneratedFieldScript,
    RuleTargetField,
    ValidatedFieldScript,
)


class FieldScriptValidationError(ValueError):
    """Raised when generated code exceeds the calculation-only contract."""


FORBIDDEN_NODES = (
    ast.Import,
    ast.ImportFrom,
    ast.ClassDef,
    ast.AsyncFunctionDef,
    ast.Lambda,
    ast.While,
    ast.For,
    ast.AsyncFor,
    ast.With,
    ast.AsyncWith,
    ast.Try,
    ast.Raise,
    ast.Global,
    ast.Nonlocal,
    ast.Delete,
    ast.Yield,
    ast.YieldFrom,
    ast.Await,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
    ast.NamedExpr,
)
ALLOWED_CALLS = {"abs", "ceil", "floor", "int", "max", "min", "round"}


def validate_field_script(
    script: GeneratedFieldScript,
    *,
    target_field: RuleTargetField,
    allowed_evidence: set[str],
) -> ValidatedFieldScript:
    if script.target_field != target_field:
        raise FieldScriptValidationError("script target_field does not match group")
    evidence_ids = tuple(dict.fromkeys(script.evidence_ids))
    if not evidence_ids:
        raise FieldScriptValidationError("script must cite assigned evidence")
    unknown_evidence = set(evidence_ids) - allowed_evidence
    if unknown_evidence:
        raise FieldScriptValidationError(
            "script cites evidence outside its T3 group: "
            + ", ".join(sorted(unknown_evidence))
        )

    source = script.source.strip()
    if source.startswith("```"):
        raise FieldScriptValidationError("Python source must not contain Markdown")
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError as exc:
        raise FieldScriptValidationError(
            f"invalid generated Python: {exc.msg}"
        ) from exc
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise FieldScriptValidationError(
            "source must contain exactly one function definition"
        )
    function = tree.body[0]
    _validate_signature(function)
    for node in ast.walk(function):
        if node is not function and isinstance(node, ast.FunctionDef):
            raise FieldScriptValidationError("nested functions are not allowed")
        if isinstance(node, FORBIDDEN_NODES):
            raise FieldScriptValidationError(
                f"generated code contains forbidden syntax: {type(node).__name__}"
            )
        if isinstance(node, ast.Attribute):
            raise FieldScriptValidationError("attribute access is not allowed")
    _FixedCalculationVisitor().visit(function)
    if not any(isinstance(node, ast.Return) for node in ast.walk(function)):
        raise FieldScriptValidationError("calculate_value must return a result")
    return ValidatedFieldScript(
        target_field=target_field,
        source=source,
        source_hash=hashlib.sha256(source.encode("utf-8")).hexdigest(),
        evidence_ids=evidence_ids,
    )


def _validate_signature(function: ast.FunctionDef) -> None:
    args = function.args
    if (
        function.name != "calculate_value"
        or args.args
        or args.posonlyargs
        or args.kwonlyargs
        or args.vararg is not None
        or args.kwarg is not None
        or args.defaults
        or args.kw_defaults
        or function.decorator_list
    ):
        raise FieldScriptValidationError(
            "calculate_value must be a no-argument function"
        )


class _FixedCalculationVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.local_names: set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.local_names.update(
            item.id
            for item in ast.walk(node)
            if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store)
        )
        for statement in node.body:
            self.visit(statement)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id.startswith("__"):
            raise FieldScriptValidationError("dunder names are not allowed")
        if isinstance(node.ctx, ast.Load) and node.id not in (
            self.local_names | ALLOWED_CALLS
        ):
            raise FieldScriptValidationError(
                f"generated code uses an unapproved name: {node.id}"
            )

    def visit_Call(self, node: ast.Call) -> None:
        if not isinstance(node.func, ast.Name) or node.func.id not in ALLOWED_CALLS:
            raise FieldScriptValidationError("function call is not allowed")
        self.generic_visit(node)
