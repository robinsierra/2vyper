"""
Copyright (c) 2019 ETH Zurich
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""

from functools import reduce
from typing import List

from lark import Lark
from lark.exceptions import ParseError, UnexpectedInput, VisitError
from lark.indenter import Indenter
from lark.tree import Meta
from lark.visitors import Transformer, v_args

from twovyper.ast import ast_nodes as ast
from twovyper.ast.arithmetic import Decimal

from twovyper.exceptions import ParseException, InvalidProgramException


class PythonIndenter(Indenter):
    NL_type = '_NEWLINE'
    OPEN_PAREN_types = ['LPAR', 'LSQB', 'LBRACE']
    CLOSE_PAREN_types = ['RPAR', 'RSQB', 'RBRACE']
    INDENT_type = '_INDENT'
    DEDENT_type = '_DEDENT'
    tab_len = 8


_kwargs = dict(postlex=PythonIndenter(), parser='lalr', maybe_placeholders=False)
_vyper_module_parser = Lark.open('vyper.lark', rel_to=__file__, start='file_input', **_kwargs)
_vyper_expr_parser = Lark.open('vyper.lark', rel_to=__file__, start='test', **_kwargs)


def copy_pos(function):

    def with_pos(self, children: List[ast.Node], meta: Meta):
        node = function(self, children, meta)
        node.file = self.file
        node.lineno = meta.line
        node.col_offset = meta.column
        node.end_lineno = meta.end_line
        node.end_col_offset = meta.end_column
        return node

    return with_pos


def copy_pos_from(node: ast.Node, to: ast.Node):
    to.file = node.file
    to.lineno = node.lineno
    to.col_offset = node.col_offset
    to.end_lineno = node.end_lineno
    to.end_col_offset = node.end_col_offset


def copy_pos_between(node: ast.Node, left: ast.Node, right: ast.Node) -> ast.Node:
    assert left.file == right.file
    assert left.lineno <= right.lineno
    assert left.lineno != right.lineno or left.col_offset < right.col_offset

    node.file = left.file
    node.lineno = left.lineno
    node.col_offset = left.col_offset
    node.end_lineno = right.end_lineno
    node.end_col_offset = right.end_col_offset

    return node


@v_args(meta=True)
class _PythonTransformer(Transformer):

    def transform_tree(self, tree, file):
        self.file = file
        transformed = self.transform(tree)
        self.file = None
        return transformed

    def file_input(self, children, meta):
        return ast.Module(children)

    @copy_pos
    def contractdef(self, children, meta):
        name = str(children[0])
        body = children[1]
        return ast.ContractDef(name, body)

    @copy_pos
    def structdef(self, children, meta):
        name = str(children[0])
        body = children[1]
        return ast.StructDef(name, body)

    @copy_pos
    def funcdef(self, children, meta):
        decorators = children[0]
        name = str(children[1])
        args = children[2]
        has_ret = isinstance(children[3], list)
        ret = None if has_ret else children[3]
        body = children[3 if has_ret else 4]
        return ast.FunctionDef(name, args, body, decorators, ret)

    def decorators(self, children, meta):
        return children

    @copy_pos
    def decorator(self, children, meta):
        name = str(children[0])

        if len(children) == 1:
            args = []
        else:
            args, kwargs = children[1]

            if kwargs:
                raise InvalidProgramException(kwargs[0], 'invalid.decorator')

        return ast.Decorator(name, args)

    def parameter_list(self, children, meta):
        return children

    @copy_pos
    def parameter(self, children, meta):
        name = str(children[0])
        annotation = children[1]
        default = children[2] if len(children) == 3 else None
        return ast.Arg(name, annotation, default)

    @copy_pos
    def expr_stmt(self, children, meta):
        target = children[0]
        if len(children) == 2:
            assign_builder = children[1]
            return assign_builder(target)
        else:
            return ast.ExprStmt(target)

    def assign(self, children, meta):
        if len(children[0]) > 1:
            # Used for config
            value = self._tuple(children[0], meta)
        else:
            value = children[0][0]

        return lambda target: ast.Assign(target, value)

    @copy_pos
    def _tuple(self, children, meta):
        return ast.Tuple(children)

    def annassign(self, children, meta):
        annotation = children[0]
        value = children[1] if len(children) == 2 else None
        return lambda target: ast.AnnAssign(target, annotation, value)

    def augassign(self, children, meta):
        op = children[0]
        value = children[1]
        return lambda target: ast.AugAssign(target, op, value)

    def aug_op(self, children, meta):
        # The actual operation is the first character of augment operator
        op = children[0][0]
        return ast.ArithmeticOperator(op)

    @copy_pos
    def pass_stmt(self, children, meta):
        return ast.Pass()

    @copy_pos
    def break_stmt(self, children, meta):
        return ast.Break()

    @copy_pos
    def continue_stmt(self, children, meta):
        return ast.Continue()

    @copy_pos
    def return_stmt(self, children, meta):
        value = children[0] if children else None
        return ast.Return(value)

    @copy_pos
    def raise_stmt(self, children, meta):
        exc = children[0] if children else None
        return ast.Raise(exc)

    @copy_pos
    def import_name(self, children, meta):
        names = children[0]
        return ast.Import(names)

    @copy_pos
    def import_from(self, children, meta):
        level, module = children[0]
        names = children[1]
        return ast.ImportFrom(module, names, level)

    def relative_name(self, children, meta):
        if len(children) == 2:
            level = children[0]
            name = children[1]
        elif isinstance(children[0], str):
            level = 0
            name = children[0]
        else:
            level = children[0]
            name = None
        return level, name

    def dots(self, children, meta):
        return len(children[0])

    def alias_list(self, children, meta):
        return children

    @copy_pos
    def alias(self, children, meta):
        name = children[0]
        asname = children[1] if len(children) == 2 else None
        return ast.Alias(name, asname)

    def dotted_name_list(self, children, meta):
        return children

    def dotted_name(self, children, meta):
        return '.'.join(children)

    @copy_pos
    def assert_stmt(self, children, meta):
        test = children[0]
        msg = children[1] if len(children) == 2 else None
        return ast.Assert(test, msg)

    @copy_pos
    def if_stmt(self, children, meta):
        if len(children) % 2 == 0:
            # We have no else branch
            orelse = []
        else:
            orelse = children.pop()

        while children:
            body = children.pop()
            test = children.pop()
            orelse = [self._if_stmt([test, body, orelse], meta)]

        return orelse[0]

    @copy_pos
    def _if_stmt(self, children, meta):
        test = children[0]
        body = children[1]
        orelse = children[2]
        return ast.If(test, body, orelse)

    @copy_pos
    def for_stmt(self, children, meta):
        target = children[0]
        iter = children[1]
        body = children[2]
        return ast.For(target, iter, body)

    @copy_pos
    def with_stmt(self, children, meta):
        body = children[1]
        # We ignore the items, as we don't need them
        return ast.Ghost(body)

    def suite(self, children, meta):
        return children

    @copy_pos
    def test(self, children, meta):
        body = children[0]
        cond = children[1]
        orelse = children[2]
        return ast.IfExpr(cond, body, orelse)

    def _left_associative_bool_op(self, children, op):
        return reduce(lambda l, r: copy_pos_between(ast.BoolOp(l, op, r), l, r), children)

    def _right_associative_bool_op(self, children, op):
        return reduce(lambda r, l: copy_pos_between(ast.BoolOp(l, op, r), l, r), reversed(children))

    @copy_pos
    def impl_test(self, children, meta):
        return self._right_associative_bool_op(children, ast.BoolOperator.IMPLIES)

    @copy_pos
    def or_test(self, children, meta):
        return self._left_associative_bool_op(children, ast.BoolOperator.OR)

    @copy_pos
    def and_test(self, children, meta):
        return self._left_associative_bool_op(children, ast.BoolOperator.AND)

    @copy_pos
    def unot(self, children, meta):
        operand = children[0]
        return ast.Not(operand)

    @copy_pos
    def comparison(self, children, meta):
        left = children[0]
        op = children[1]
        right = children[2]

        if isinstance(op, ast.ComparisonOperator):
            return ast.Comparison(left, op, right)
        elif isinstance(op, ast.ContainmentOperator):
            return ast.Containment(left, op, right)
        elif isinstance(op, ast.EqualityOperator):
            return ast.Equality(left, op, right)
        else:
            assert False

    @copy_pos
    def arith_expr(self, children, meta):
        return self._bin_op(children)

    @copy_pos
    def term(self, children, meta):
        return self._bin_op(children)

    @copy_pos
    def factor(self, children, meta):
        op = children[0]
        operand = children[1]
        return ast.UnaryArithmeticOp(op, operand)

    def _bin_op(self, children):
        operand = children.pop()

        def bop(right):
            if children:
                op = children.pop()
                left = bop(children.pop())
                ret = ast.ArithmeticOp(left, op, right)
                copy_pos_between(ret, left, right)
                return ret
            else:
                return right

        return bop(operand)

    def factor_op(self, children, meta):
        return ast.UnaryArithmeticOperator(children[0])

    def add_op(self, children, meta):
        return ast.ArithmeticOperator(children[0])

    def mul_op(self, children, meta):
        return ast.ArithmeticOperator(children[0])

    def comp_op(self, children, meta):
        return ast.ComparisonOperator(children[0])

    def cont_op(self, children, meta):
        if len(children) == 1:
            return ast.ContainmentOperator.IN
        else:
            return ast.ContainmentOperator.NOT_IN

    def eq_op(self, children, meta):
        return ast.EqualityOperator(children[0])

    @copy_pos
    def power(self, children, meta):
        left = children[0]
        right = children[1]
        return ast.ArithmeticOp(left, ast.ArithmeticOperator.POW, right)

    @copy_pos
    def funccall(self, children, meta):
        func = children[0]
        args, kwargs = children[1]
        return ast.Call(func, args, kwargs)

    @copy_pos
    def getitem(self, children, meta):
        value = children[0]
        index = children[1]
        return ast.Subscript(value, index)

    @copy_pos
    def getattr(self, children, meta):
        value = children[0]
        attr = str(children[1])
        return ast.Attribute(value, attr)

    @copy_pos
    def list(self, children, meta):
        return ast.List(children[0])

    @copy_pos
    def dictset(self, children, meta):
        if not children:
            return ast.Dict([], [])
        elif isinstance(children[0], tuple):
            keys, values = children[0]
            return ast.Dict(keys, values)
        else:
            return ast.Set(children[0])

    @copy_pos
    def var(self, children, meta):
        return ast.Name(str(children[0]))

    @copy_pos
    def strings(self, children, meta):
        if isinstance(children[0], ast.Str):
            conc = ''.join(c.s for c in children)
            return ast.Str(conc)
        else:
            conc = b''.join(c.s for c in children)
            return ast.Bytes(conc)

    @copy_pos
    def ellipsis(self, children, meta):
        return ast.Ellipsis()

    @copy_pos
    def const_true(self, children, meta):
        return ast.NameConstant(True)

    @copy_pos
    def const_false(self, children, meta):
        return ast.NameConstant(False)

    def testlist(self, children, meta):
        return children

    def dictlist(self, children, meta):
        keys = []
        values = []
        it = iter(children)
        for c in it:
            keys.append(c)
            values.append(next(it))
        return keys, values

    def arguments(self, children, meta):
        args = []
        kwargs = []
        for c in children:
            if isinstance(c, ast.Keyword):
                kwargs.append(c)
            else:
                # kwargs cannot come before normal args
                if kwargs:
                    raise InvalidProgramException(kwargs[0], 'invalid.kwargs')
                args.append(c)

        return args, kwargs

    @copy_pos
    def argvalue(self, children, meta):
        identifier = str(children[0])
        value = children[1]
        return ast.Keyword(identifier, value)

    @copy_pos
    def number(self, children, meta):
        n = eval(children[0])
        return ast.Num(n)

    @copy_pos
    def float(self, children, meta):
        assert 'e' not in children[0]

        numd = 10
        first, second = children[0].split('.')
        if len(second) > numd:
            node = self.number(children, meta)
            raise InvalidProgramException(node, 'invalid.decimal.literal')
        int_value = int(first) * 10 ** numd + int(second.ljust(numd, '0'))
        return ast.Num(Decimal[numd](scaled_value=int_value))

    @copy_pos
    def string(self, children, meta):
        s = eval(children[0])
        if isinstance(s, str):
            return ast.Str(s)
        elif isinstance(s, bytes):
            return ast.Bytes(s)
        else:
            assert False


def parse(parser, text, file):
    try:
        tree = parser.parse(text)
    except (ParseError, UnexpectedInput) as e:
        raise ParseException(str(e))
    try:
        return _PythonTransformer().transform_tree(tree, file)
    except VisitError as e:
        raise e.orig_exc


def parse_module(text, file) -> ast.Module:
    return parse(_vyper_module_parser, text + '\n', file)


def parse_expr(text, file) -> ast.Expr:
    return parse(_vyper_expr_parser, text, file)
