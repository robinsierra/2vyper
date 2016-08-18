"""Boolean typed Silver expressions."""


import ast

from typing import List

from py2viper_translation.lib.program_nodes import (
    PythonVar,
)
from py2viper_translation.lib.silver_nodes.expression import Expression
from py2viper_translation.lib.typedefs import (
    Expr,
    Info,
    Position,
)
from py2viper_translation.lib.util import (
    join_expressions,
)


class BoolExpression(Expression):   # pylint: disable=abstract-method
    """A base class for all boolean expressions."""

    def is_always_true(self) -> bool:
        """Return if this expression translation would always yield True."""
        return False

    def is_always_false(self) -> bool:
        """Return if this expression translation would always yield False."""
        return False


class TrueLit(BoolExpression):
    """``True`` literal."""

    def is_always_true(self) -> bool:
        """Return if this expression translation would always yield True."""
        return True

    def translate(self, translator: 'AbstractTranslator', ctx: 'Context',
                  position: Position, info: Info) -> Expr:
        return translator.viper.TrueLit(position, info)


class FalseLit(BoolExpression):
    """``False`` literal."""

    def is_always_false(self) -> bool:
        """Return if this expression translation would always yield False."""
        return True

    def translate(self, translator: 'AbstractTranslator', ctx: 'Context',
                  position: Position, info: Info) -> Expr:
        return translator.viper.FalseLit(position, info)


class Not(BoolExpression):
    """Negation of other expression."""

    def __init__(self, value: BoolExpression) -> None:
        self._value = value

    def translate(self, translator: 'AbstractTranslator', ctx: 'Context',
                  position: Position, info: Info) -> Expr:
        value = self._value.translate(translator, ctx, position, info)
        return translator.viper.Not(value, position, info)


class ForPerm(BoolExpression):
    """ForPerm expression."""

    def __init__(
            self, var_name: str, targets: List['Predicate'],
            body: BoolExpression) -> None:
        self._var_name = var_name
        self._targets = targets
        self._body = body

    def translate(self, translator: 'AbstractTranslator', ctx: 'Context',
                  position: Position, info: Info) -> Expr:
        var = translator.viper.LocalVarDecl(
            self._var_name, translator.viper.Ref, position, info)
        targets = [
            target.translate(translator, ctx, position, info)
            for target in self._targets]
        body = self._body.translate(translator, ctx, position, info)
        return translator.viper.ForPerm(
            var, targets, body, position, info)


class PythonBoolExpression(BoolExpression):
    """An boolean expression represented by Python bool expression."""

    def __init__(self, node: ast.expr) -> None:
        self._node = node

    def translate(self, translator: 'AbstractTranslator', ctx: 'Context',
                  position: Position, info: Info) -> Expr:
        stmt, expr = translator.translate_to_bool(
            self._node, ctx, expression=True)
        assert not stmt
        return expr


class BoolVar(BoolExpression):
    """A boolean variable reference."""

    def __init__(self, var: PythonVar) -> None:
        self._var = var

    def translate(self, translator: 'AbstractTranslator', ctx: 'Context',
                  position: Position, info: Info) -> Expr:
        bool_class = ctx.program.classes['bool']
        assert self._var.type is bool_class
        return self._var.ref()


class InhaleExhale(BoolExpression):
    """Inhale exhale expression."""

    def __init__(self, inhale: BoolExpression, exhale: BoolExpression) -> None:
        self._inhale = inhale
        self._exhale = exhale

    def translate(self, translator: 'AbstractTranslator', ctx: 'Context',
                  position: Position, info: Info) -> Expr:
        inhale = self._inhale.translate(translator, ctx, position, info)
        exhale = self._exhale.translate(translator, ctx, position, info)
        return translator.viper.InhaleExhaleExp(
            inhale, exhale, position, info)


class CallArg:
    """A call argument."""

    def __init__(
            self, parameter_name: str, parameter_type: 'Type',
            argument: Expression) -> None:
        self._parameter_name = parameter_name
        self._parameter_type = parameter_type
        self._argument = argument

    def construct_definition(
            self, translator: 'Translator', position: Position,
            info: Info) -> Expr:
        """Construct formal argument definition."""
        typ = self._parameter_type.translate(translator)
        return translator.viper.LocalVarDecl(
            self._parameter_name, typ, position, info)

    def translate_argument(
            self, translator: 'AbstractTranslator', ctx: 'Context',
            position: Position, info: Info) -> Expr:
        """Translate the argument passed to the function."""
        return self._argument.translate(translator, ctx, position, info)


class BoolCall(BoolExpression):
    """A call to a boolean function."""

    def __init__(self, function: str, args: List[CallArg]) -> None:
        self._function = function
        self._args = args

    def translate(self, translator: 'AbstractTranslator', ctx: 'Context',
                  position: Position, info: Info) -> Expr:
        formal_args = [
            arg.construct_definition(translator, position, info)
            for arg in self._args]
        args = [
            arg.translate_argument(translator, ctx, position, info)
            for arg in self._args]
        return translator.viper.FuncApp(
            self._function, args, position, info, translator.viper.Bool,
            formal_args)


class BigAnd(BoolExpression):
    """A conjunction of 0 or more elements.

    If it has zero elements, then it is equivalent to ``True``.
    """

    def __init__(self, conjuncts: List[BoolExpression]) -> None:
        self._conjuncts = conjuncts

    def is_empty(self) -> None:
        """Check if have any conjuncts."""
        return not self._conjuncts

    def is_always_true(self) -> bool:
        return self.is_empty()

    def translate(self, translator: 'AbstractTranslator', ctx: 'Context',
                  position: Position, info: Info) -> Expr:
        if self.is_always_false():
            return translator.viper.FalseLit(position, info)
        conjuncts = [
            conjunct.translate(translator, ctx, position, info)
            for conjunct in self._conjuncts
            if not conjunct.is_always_true()]
        if not conjuncts:
            return translator.viper.TrueLit(position, info)
        else:
            and_operator = (
                lambda left, right:
                translator.viper.And(left, right, position, info))
            return join_expressions(and_operator, conjuncts)


class BigOr(BoolExpression):
    """A disjunction of 0 or more elements.

    If it has zero elements, then it is equivalent to ``False``.
    """

    def __init__(self, disjuncts: List[BoolExpression]) -> None:
        self._disjuncts = disjuncts

    def is_empty(self) -> None:
        """Check if have any elements."""
        return not self._disjuncts

    def is_always_false(self) -> bool:
        return self.is_empty()

    def translate(self, translator: 'AbstractTranslator', ctx: 'Context',
                  position: Position, info: Info) -> Expr:
        if self.is_always_true():
            return translator.viper.TrueLit(position, info)
        disjuncts = [
            disjunct.translate(translator, ctx, position, info)
            for disjunct in self._disjuncts
            if not disjunct.is_always_false()]
        if not disjuncts:
            return translator.viper.FalseLit(position, info)
        else:
            or_operator = (
                lambda left, right:
                translator.viper.Or(left, right, position, info))
            return join_expressions(or_operator, disjuncts)


class BoolCondExp(BoolExpression):
    """A ternary operator with boolean result."""

    def __init__(self, condition: BoolExpression, then: BoolExpression,
                 els: BoolExpression) -> None:
        self._condition = condition
        self._then = then
        self._els = els

    def translate(self, translator: 'AbstractTranslator', ctx: 'Context',
                  position: Position, info: Info) -> Expr:
        condition = self._condition.translate(translator, ctx, position, info)
        then = self._then.translate(translator, ctx, position, info)
        els = self._els.translate(translator, ctx, position, info)
        return translator.viper.CondExp(
            condition, then, els, position, info)


class Implies(BoolExpression):
    """Implication."""

    def __init__(self, condition: BoolExpression, value: Expression) -> None:
        self._condition = condition
        self._value = value

    def is_always_true(self) -> bool:
        return (self._condition.is_always_false() or
                self._value.is_always_true())

    def translate(self, translator: 'AbstractTranslator', ctx: 'Context',
                  position: Position, info: Info) -> Expr:
        value = self._value.translate(translator, ctx, position, info)
        if self._condition.is_always_true():
            return value
        else:
            condition = self._condition.translate(
                translator, ctx, position, info)
            return translator.viper.Implies(
                condition, value, position, info)


class EqCmp(BoolExpression):
    """Equality comparison."""

    def __init__(self, left: Expression, right: Expression) -> None:
        self._left = left
        self._right = right

    def translate(self, translator: 'AbstractTranslator', ctx: 'Context',
                  position: Position, info: Info) -> Expr:
        left = self._left.translate(translator, ctx, position, info)
        right = self._right.translate(translator, ctx, position, info)
        return translator.viper.EqCmp(
            left, right, position, info)


Expression.EqCmp = EqCmp


class NeCmp(BoolExpression):
    """Inequality comparison."""

    def __init__(self, left: Expression, right: Expression) -> None:
        self._left = left
        self._right = right

    def translate(self, translator: 'AbstractTranslator', ctx: 'Context',
                  position: Position, info: Info) -> Expr:
        left = self._left.translate(translator, ctx, position, info)
        right = self._right.translate(translator, ctx, position, info)
        return translator.viper.NeCmp(
            left, right, position, info)


Expression.NeCmp = NeCmp