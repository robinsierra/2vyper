"""
Copyright (c) 2019 ETH Zurich
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""

import ast

from typing import List

from twovyper.viper.ast import ViperAST
from twovyper.viper.typedefs import Stmt
from twovyper.viper.typedefs import Position, Info

from twovyper.translation.context import Context

from twovyper.verification import error_manager
from twovyper.verification.error import ErrorInfo, Via
from twovyper.verification.rules import Rules


class PositionTranslator:

    def __init__(self, viper_ast: ViperAST):
        self.viper_ast = viper_ast

    def _register_potential_error(self,
                                  node,
                                  ctx: Context,
                                  rules: Rules = None,
                                  vias: List[Via] = [],
                                  error_string: str = None) -> str:
        name = None if not ctx.function else ctx.function.name
        error_info = ErrorInfo(name, node, vias, error_string)
        id = error_manager.add_error_information(error_info, rules)
        return id

    def to_position(self,
                    node: ast.AST,
                    ctx: Context,
                    rules: Rules = None,
                    vias: List[Via] = [],
                    error_string: str = None) -> Position:
        """
        Extracts the position from a node, assigns an ID to the node and stores
        the node and the position in the context for it.
        """
        id = self._register_potential_error(node, ctx, rules, vias, error_string)
        return self.viper_ast.to_position(node, id, ctx.file)

    def no_position(self, error_string: str = None) -> Position:
        return self.viper_ast.NoPosition

    def to_info(self, comments: List[str]) -> Info:
        """
        Wraps the given comments into an Info object.
        """
        if comments:
            return self.viper_ast.SimpleInfo(comments)
        else:
            return self.viper_ast.NoInfo

    def no_info(self) -> Info:
        return self.to_info([])


class CommonTranslator:

    def fail_if(self, cond, stmts, ctx: Context, pos=None, info=None) -> Stmt:
        body = [*stmts, self.viper_ast.Goto(ctx.revert_label, pos)]
        return self.viper_ast.If(cond, body, [], pos, info)

    def _seqn_with_info(self, stmts: [Stmt], comment: str) -> [Stmt]:
        if not stmts:
            return stmts
        info = self.to_info([comment])
        return [self.viper_ast.Seqn(stmts, info=info)]


class NodeTranslator(PositionTranslator, CommonTranslator):

    def __init__(self, viper_ast: ViperAST):
        super().__init__(viper_ast)

    def translate(self, node, ctx):
        """Translate a node."""
        method = 'translate_' + node.__class__.__name__
        visitor = getattr(self, method, self.generic_translate)
        return visitor(node, ctx)

    def generic_translate(self, node, ctx):
        raise AssertionError(f"Node of type {type(node)} not supported.")