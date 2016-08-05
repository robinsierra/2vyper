"""``MustRelease`` obligation implementation."""


import ast

from typing import Any, Dict, List, Optional

from py2viper_translation.lib import expressions as expr
from py2viper_translation.lib.program_nodes import (
    PythonMethod,
)
from py2viper_translation.translators.obligation.inexhale import (
    InexhaleObligationInstanceMixin,
    ObligationInhaleExhale,
)
from py2viper_translation.translators.obligation.types.base import (
    ObligationInstance,
    Obligation,
)


_OBLIGATION_NAME = 'MustRelease'
_BOUNDED_FIELD_NAME = _OBLIGATION_NAME + 'Bounded'
_UNBOUNDED_FIELD_NAME = _OBLIGATION_NAME + 'Unbounded'


class MustReleaseObligationInstance(
        InexhaleObligationInstanceMixin, ObligationInstance):
    """Class representing instance of ``MustRelease`` obligation."""

    def __init__(
            self, obligation: 'MustReleaseObligation', node: ast.expr,
            measure: Optional[ast.expr], target: ast.expr) -> None:
        super().__init__(obligation, node)
        self._measure = measure
        self._target = target

    def _get_inexhale(self) -> ObligationInhaleExhale:
        return ObligationInhaleExhale(
            expr.FieldAccess(
                self.get_target(), _BOUNDED_FIELD_NAME, expr.INT),
            expr.FieldAccess(
                self.get_target(), _UNBOUNDED_FIELD_NAME, expr.INT))

    def is_fresh(self) -> bool:
        return self._measure is None

    def get_measure(self) -> expr.IntExpression:
        assert not self.is_fresh()
        return expr.PythonIntExpression(self._measure)

    def get_target(self) -> expr.RefExpression:
        return expr.PythonRefExpression(self._target)


class MustReleaseObligation(Obligation):
    """Class representing ``MustRelease`` obligation."""

    def __init__(self) -> None:
        super().__init__([], [
            _BOUNDED_FIELD_NAME,
            _UNBOUNDED_FIELD_NAME])

    def identifier(self) -> str:
        return _OBLIGATION_NAME

    def check_node(
            self, node: ast.Call,
            obligation_info: 'PythonMethodObligationInfo',
            method: PythonMethod) -> Optional[MustReleaseObligationInstance]:
        if (isinstance(node.func, ast.Name) and
                node.func.id == _OBLIGATION_NAME):
            target = node.args[0]
            measure = node.args[1] if len(node.args) > 1 else None
            instance = MustReleaseObligationInstance(
                self, node, measure, target)
            return instance
        else:
            return None

    def generate_axiomatized_preconditions(
            self, obligation_info: 'PythonMethodObligationInfo',
            interface_dict: Dict[str, Any]) -> List[expr.BoolExpression]:
        return []

    def create_leak_check(self, var_name: str) -> List[expr.BoolExpression]:
        return [
            self._create_field_for_perm(_BOUNDED_FIELD_NAME, var_name),
            self._create_field_for_perm(_UNBOUNDED_FIELD_NAME, var_name),
        ]
