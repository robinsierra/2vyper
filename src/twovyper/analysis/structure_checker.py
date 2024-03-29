"""
Copyright (c) 2019 ETH Zurich
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""

from contextlib import contextmanager
from enum import Enum
from itertools import chain
from typing import Optional, Union

from twovyper.ast import ast_nodes as ast, names
from twovyper.ast.nodes import VyperProgram, VyperFunction
from twovyper.ast.visitors import NodeVisitor

from twovyper.exceptions import InvalidProgramException, UnsupportedException


def _assert(cond: bool, node: ast.Node, error_code: str, msg: Optional[str] = None):
    if not cond:
        raise InvalidProgramException(node, error_code, msg)


def check_structure(program: VyperProgram):
    StructureChecker().check(program)


class _Context(Enum):

    CODE = 'code'
    INVARIANT = 'invariant'
    CHECK = 'check'
    POSTCONDITION = 'postcondition'
    TRANSITIVE_POSTCONDITION = 'transitive.postcondition'
    GHOST_CODE = 'ghost.code'
    GHOST_FUNCTION = 'ghost.function'
    GHOST_STATEMENT = 'ghost.statement'

    @property
    def is_specification(self):
        return self not in [_Context.CODE, _Context.GHOST_FUNCTION]

    @property
    def is_postcondition(self):
        return self in [_Context.POSTCONDITION, _Context.TRANSITIVE_POSTCONDITION]


class StructureChecker(NodeVisitor):

    def __init__(self):
        self.allowed = {
            _Context.CODE: [],
            _Context.INVARIANT: names.NOT_ALLOWED_IN_INVARIANT,
            _Context.CHECK: names.NOT_ALLOWED_IN_CHECK,
            _Context.POSTCONDITION: names.NOT_ALLOWED_IN_POSTCONDITION,
            _Context.TRANSITIVE_POSTCONDITION: names.NOT_ALLOWED_IN_TRANSITIVE_POSTCONDITION,
            _Context.GHOST_CODE: names.NOT_ALLOWED_IN_GHOST_CODE,
            _Context.GHOST_FUNCTION: names.NOT_ALLOWED_IN_GHOST_FUNCTION,
            _Context.GHOST_STATEMENT: names.NOT_ALLOWED_IN_GHOST_STATEMENT
        }

        self._inside_old = False

    @contextmanager
    def _inside_old_scope(self):
        current_inside_old = self._inside_old
        self._inside_old = True

        yield

        self._inside_old = current_inside_old

    def check(self, program: VyperProgram):
        if program.resources and not program.config.has_option(names.CONFIG_ALLOCATION):
            resource = next(iter(program.resources.values()))
            msg = "Resources require allocation config option."
            raise InvalidProgramException(resource.node, 'alloc.not.alloc', msg)

        for function in program.functions.values():
            self.visit(function.node, _Context.CODE, program, function)

            for postcondition in function.postconditions:
                self.visit(postcondition, _Context.POSTCONDITION, program, function)

            for check in function.checks:
                self.visit(check, _Context.CHECK, program, function)

            for performs in function.performs:
                self._visit_performs(performs, program, function)

        for invariant in program.invariants:
            self.visit(invariant, _Context.INVARIANT, program, None)

        for check in program.general_checks:
            self.visit(check, _Context.CHECK, program, None)

        for postcondition in program.general_postconditions:
            self.visit(postcondition, _Context.POSTCONDITION, program, None)

        for postcondition in program.transitive_postconditions:
            self.visit(postcondition, _Context.TRANSITIVE_POSTCONDITION, program, None)

        for ghost_function in program.ghost_function_implementations.values():
            self.visit(ghost_function.node, _Context.GHOST_FUNCTION, program, None)

    def visit(self, node: ast.Node, ctx: _Context, program: VyperProgram, function: Optional[VyperFunction]):
        _assert(ctx != _Context.GHOST_CODE or isinstance(node, ast.AllowedInGhostCode), node, 'invalid.ghost.code')
        super().visit(node, ctx, program, function)

    def _visit_performs(self, node: ast.Expr, program: VyperProgram, function: VyperFunction):
        _assert(isinstance(node, ast.FunctionCall) and node.name in names.GHOST_STATEMENTS, node, 'invalid.performs')
        self.visit(node, _Context.CODE, program, function)

    def visit_FunctionDef(self, node: ast.FunctionDef, ctx: _Context, program: VyperProgram, function: Optional[VyperFunction]):
        for stmt in node.body:
            if ctx == _Context.GHOST_FUNCTION:
                new_ctx = ctx
            elif ctx == _Context.CODE:
                new_ctx = _Context.GHOST_CODE if stmt.is_ghost_code else ctx
            else:
                assert False

            self.visit(stmt, new_ctx, program, function)

    def visit_Name(self, node: ast.Name, ctx: _Context, program: VyperProgram, function: Optional[VyperFunction]):
        if ctx == _Context.GHOST_FUNCTION and node.id in names.ENV_VARIABLES:
            _assert(node.id not in names.ENV_VARIABLES, node, 'invalid.ghost.function')
        elif ctx == _Context.INVARIANT:
            _assert(node.id != names.MSG, node, 'invariant.msg')
            _assert(node.id != names.BLOCK, node, 'invariant.block')
        elif ctx == _Context.TRANSITIVE_POSTCONDITION:
            _assert(node.id != names.MSG, node, 'postcondition.msg')

    def visit_FunctionCall(self, node: ast.FunctionCall, ctx: _Context, program: VyperProgram, function: Optional[VyperFunction]):
        _assert(node.name not in self.allowed[ctx], node, f'{ctx.value}.call')

        if ctx == _Context.POSTCONDITION and function and function.name == names.INIT:
            _assert(node.name != names.OLD, node, 'postcondition.init.old')

        # Success is of the form success() or success(if_not=cond1 or cond2 or ...)
        if node.name == names.SUCCESS:

            def check_success_args(node):
                if isinstance(node, ast.Name):
                    _assert(node.id in names.SUCCESS_CONDITIONS, node, 'spec.success')
                elif isinstance(node, ast.BoolOp) and node.op == ast.BoolOperator.OR:
                    check_success_args(node.left)
                    check_success_args(node.right)
                else:
                    raise InvalidProgramException(node, 'spec.success')

            _assert(len(node.keywords) <= 1, node, 'spec.success')
            if node.keywords:
                _assert(node.keywords[0].name == names.SUCCESS_IF_NOT, node, 'spec.success')
                check_success_args(node.keywords[0].value)

            return
        # Accessible is of the form accessible(to, amount, self.some_func(args...))
        elif node.name == names.ACCESSIBLE:
            _assert(not self._inside_old, node, 'spec.old.accessible')
            _assert(len(node.args) == 2 or len(node.args) == 3, node, 'spec.accessible')

            self.visit(node.args[0], ctx, program, function)
            self.visit(node.args[1], ctx, program, function)

            if len(node.args) == 3:
                call = node.args[2]
                _assert(isinstance(call, ast.ReceiverCall), node, 'spec.accessible')
                _assert(isinstance(call.receiver, ast.Name), node, 'spec.accessible')
                _assert(call.receiver.id == names.SELF, node, 'spec.accessible')
                _assert(call.name in program.functions, node, 'spec.accessible')
                _assert(call.name != names.INIT, node, 'spec.accessible')

                self.generic_visit(call, ctx, program, function)

            return
        elif node.name in [names.FORALL, names.FOREACH]:
            _assert(len(node.args) >= 2 and not node.keywords, node, 'invalid.no.args')
            _assert(isinstance(node.args[0], ast.Dict), node.args[0], f'invalid.{node.name}')

            for name in node.args[0].keys:
                _assert(isinstance(name, ast.Name), name, f'invalid.{node.name}')

            for trigger in node.args[1:len(node.args) - 1]:
                _assert(isinstance(trigger, ast.Set), trigger, f'invalid.{node.name}')
                self.visit(trigger, ctx, program, function)

            body = node.args[-1]

            if node.name == names.FOREACH:
                _assert(isinstance(body, ast.FunctionCall), body, 'invalid.foreach')
                _assert(body.name in names.QUANTIFIED_GHOST_STATEMENTS, body, 'invalid.foreach')

            self.visit(body, ctx, program, function)
            return
        elif node.name == names.OLD:
            with self._inside_old_scope():
                self.generic_visit(node, ctx, program, function)

            return
        elif node.name == names.INDEPENDENT:
            self.visit(node.args[0], ctx, program, function)

            def check_allowed(arg):
                if isinstance(arg, ast.FunctionCall):
                    is_old = len(arg.args) == 1 and arg.name == names.OLD
                    _assert(is_old, node, 'spec.independent')
                    return check_allowed(arg.args[0])
                if isinstance(arg, ast.Attribute):
                    return check_allowed(arg.value)
                elif isinstance(arg, ast.Name):
                    allowed = [names.SELF, names.BLOCK, names.CHAIN, names.TX, *function.args]
                    _assert(arg.id in allowed, node, 'spec.independent')
                else:
                    _assert(False, node, 'spec.independent')

            check_allowed(node.args[1])
        elif node.name == names.RAW_CALL:
            if names.RAW_CALL_DELEGATE_CALL in (kw.name for kw in node.keywords):
                raise UnsupportedException(node, "Delegate calls are not supported.")

        if node.name in names.ALLOCATION_FUNCTIONS:
            msg = "Allocation statements require allocation config option."
            _assert(program.config.has_option(names.CONFIG_ALLOCATION), node, 'alloc.not.alloc', msg)

        if node.name in names.GHOST_STATEMENTS:
            msg = "Allocation statements are not allowed in constant functions."
            _assert(not (function and function.is_constant()), node, 'alloc.in.constant', msg)

        arg_ctx = _Context.GHOST_STATEMENT if node.name in names.GHOST_STATEMENTS else ctx

        if node.resource:
            # Resources are only allowed in allocation functions. They can have the following structure:
            #   - a simple name: r
            #   - an exchange: r <-> s
            #   - a creator: creator(r)

            _assert(node.name in names.ALLOCATION_FUNCTIONS, node, 'invalid.no.resources')

            def check_resource(resource: ast.Node, top: bool):
                if isinstance(resource, ast.Name):
                    return
                elif isinstance(resource, ast.Exchange) and top:
                    check_resource(resource.left, False)
                    check_resource(resource.right, False)
                elif isinstance(resource, ast.FunctionCall):
                    if resource.name == names.CREATOR:
                        _assert(len(resource.args) == 1 and not resource.keywords, resource, 'invalid.resource')
                        check_resource(resource.args[0], False)
                    else:
                        self.generic_visit(resource, arg_ctx, program, function)
                else:
                    _assert(False, resource, 'invalid.resource')

            check_resource(node.resource, True)
        else:
            self.visit_nodes(chain(node.args, node.keywords), arg_ctx, program, function)

    def visit_ReceiverCall(self, node: ast.Name, ctx: _Context, program: VyperProgram, function: Optional[VyperFunction]):
        if ctx == _Context.GHOST_CODE:
            _assert(False, node, 'invalid.ghost.code')
        elif ctx.is_specification:
            _assert(False, node, 'spec.call')
        elif ctx == _Context.GHOST_FUNCTION:
            _assert(False, node, 'invalid.ghost')

        self.generic_visit(node, ctx, program, function)

    def visit_Exchange(self, node: ast.Exchange, ctx: _Context, program: VyperProgram, function: Optional[VyperFunction]):
        _assert(False, node, 'exchange.not.resource')

        self.generic_visit(node, ctx, program, function)

    def _visit_assertion(self, node: Union[ast.Assert, ast.Raise], ctx: _Context):
        if ctx == _Context.GHOST_CODE:
            _assert(node.msg and isinstance(node.msg, ast.Name), node, 'invalid.ghost.code')
            _assert(node.msg.id == names.UNREACHABLE, node, 'invalid.ghost.code')

    def visit_Assert(self, node: ast.Assert, ctx: _Context, program: VyperProgram, function: Optional[VyperFunction]):
        self._visit_assertion(node, ctx)
        self.generic_visit(node, ctx, program, function)

    def visit_Raise(self, node: ast.Raise, ctx: _Context, program: VyperProgram, function: Optional[VyperFunction]):
        self._visit_assertion(node, ctx)
        self.generic_visit(node, ctx, program, function)
