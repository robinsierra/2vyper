"""
Copyright (c) 2019 ETH Zurich
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""

from typing import List

from twovyper.ast import ast_nodes as ast, names, types
from twovyper.ast.types import PrimitiveType, BoundedType

from twovyper.translation import helpers
from twovyper.translation.abstract import CommonTranslator
from twovyper.translation.context import Context

from twovyper.utils import switch

from twovyper.viper.ast import ViperAST
from twovyper.viper.typedefs import Expr, Stmt


class ArithmeticTranslator(CommonTranslator):

    def __init__(self, viper_ast: ViperAST, no_reverts: bool = False):
        self.viper_ast = viper_ast
        self.no_reverts = no_reverts

        self._unary_arithmetic_operations = {
            ast.UnaryArithmeticOperator.ADD: lambda o, pos, info: o,
            ast.UnaryArithmeticOperator.SUB: self.viper_ast.Minus
        }

        self._arithmetic_ops = {
            ast.ArithmeticOperator.ADD: self.viper_ast.Add,
            ast.ArithmeticOperator.SUB: self.viper_ast.Sub,
            ast.ArithmeticOperator.MUL: self.viper_ast.Mul,
            # Note that / and % in Vyper means truncating division
            ast.ArithmeticOperator.DIV: lambda l, r, pos: helpers.div(viper_ast, l, r, pos),
            ast.ArithmeticOperator.MOD: lambda l, r, pos: helpers.mod(viper_ast, l, r, pos),
            ast.ArithmeticOperator.POW: lambda l, r, pos: helpers.pow(viper_ast, l, r, pos),
        }

    def unary_arithmetic_op(self, op: ast.UnaryArithmeticOperator, arg, otype: PrimitiveType, res: List[Stmt], ctx: Context, pos=None) -> Expr:
        result = self._unary_arithmetic_operations[op](arg, pos)
        # Unary negation can only overflow if one negates MIN_INT128
        if types.is_bounded(otype):
            self.check_overflow(result, otype, res, ctx, pos)

        return result

    # Decimals are scaled integers, i.e. the decimal 2.3 is represented as the integer
    # 2.3 * 10^10 = 23000000000. For addition, subtraction, and modulo the same operations
    # as with integers can be used. For multiplication we need to divide out one of the
    # scaling factors while in division we need to multiply one in.

    def decimal_mul(self, lhs, rhs, ctx: Context, pos=None, info=None) -> Expr:
        scaling_factor = self.viper_ast.IntLit(types.VYPER_DECIMAL.scaling_factor, pos)
        mult = self.viper_ast.Mul(lhs, rhs, pos)
        # In decimal multiplication we divide the end result by the scaling factor
        return helpers.div(self.viper_ast, mult, scaling_factor, pos, info)

    def decimal_div(self, lhs, rhs, ctx: Context, pos=None, info=None) -> Expr:
        scaling_factor = self.viper_ast.IntLit(types.VYPER_DECIMAL.scaling_factor, pos)
        # In decimal division we first multiply the lhs by the scaling factor
        mult = self.viper_ast.Mul(lhs, scaling_factor, pos)
        return helpers.div(self.viper_ast, mult, rhs, pos, info)

    def arithmetic_op(self, lhs, op: ast.ArithmeticOperator, rhs, otype: PrimitiveType, res: List[Stmt], ctx: Context, pos=None) -> Expr:
        ast_op = ast.ArithmeticOperator

        with switch(op, otype) as case:
            from twovyper.utils import _

            if (case(ast_op.DIV, _) or case(ast_op.MOD, _)) and not self.no_reverts:
                cond = self.viper_ast.EqCmp(rhs, self.viper_ast.IntLit(0, pos), pos)
                self.fail_if(cond, [], res, ctx, pos)

            if case(ast_op.MUL, types.VYPER_DECIMAL):
                expr = self.decimal_mul(lhs, rhs, ctx, pos)
            elif case(ast_op.DIV, types.VYPER_DECIMAL):
                expr = self.decimal_div(lhs, rhs, ctx, pos)
            else:
                expr = self._arithmetic_ops[op](lhs, rhs, pos)

        if types.is_bounded(otype):
            self.check_under_overflow(expr, otype, res, ctx, pos)

        return expr

    # Overflows and underflow checks can be disabled with the config flag 'no_overflows'.
    # If it is not enabled, we revert if an overflow happens. Additionally, we set the overflows
    # variable to true, which is used for success(if_not=overflow).
    #
    # Note that we only treat 'arbitary' bounds due to limited bit size as overflows,
    # getting negative unsigned values results in a normal revert.

    def _set_overflow_flag(self, res: List[Stmt], ctx: Context, pos=None):
        overflow = helpers.overflow_var(self.viper_ast, pos).localVar()
        true_lit = self.viper_ast.TrueLit(pos)
        res.append(self.viper_ast.LocalVarAssign(overflow, true_lit, pos))

    def check_underflow(self, arg, type: BoundedType, res: List[Stmt], ctx: Context, pos=None):
        lower = self.viper_ast.IntLit(type.lower, pos)
        lt = self.viper_ast.LtCmp(arg, lower, pos)

        if types.is_unsigned(type) and not self.no_reverts:
            self.fail_if(lt, [], res, ctx, pos)
        elif not self.no_reverts and not ctx.program.config.has_option(names.CONFIG_NO_OVERFLOWS):
            stmts = []
            self._set_overflow_flag(stmts, ctx, pos)
            self.fail_if(lt, stmts, res, ctx, pos)

    def check_overflow(self, arg, type: BoundedType, res: List[Stmt], ctx: Context, pos=None):
        upper = self.viper_ast.IntLit(type.upper, pos)
        gt = self.viper_ast.GtCmp(arg, upper, pos)

        if not self.no_reverts and not ctx.program.config.has_option(names.CONFIG_NO_OVERFLOWS):
            stmts = []
            self._set_overflow_flag(stmts, ctx, pos)
            self.fail_if(gt, stmts, res, ctx, pos)

    def check_under_overflow(self, arg, type: BoundedType, res: List[Stmt], ctx: Context, pos=None):
        # For unsigned types we need to check over and underflow separately as we treat underflows
        # as normal reverts
        if types.is_unsigned(type) and not self.no_reverts:
            self.check_underflow(arg, type, res, ctx, pos)
            self.check_overflow(arg, type, res, ctx, pos)
        elif not self.no_reverts and not ctx.program.config.has_option(names.CONFIG_NO_OVERFLOWS):
            # Checking for overflow and undeflow in the same if-condition is more efficient than
            # introducing two branches
            lower = self.viper_ast.IntLit(type.lower, pos)
            upper = self.viper_ast.IntLit(type.upper, pos)

            lt = self.viper_ast.LtCmp(arg, lower, pos)
            gt = self.viper_ast.GtCmp(arg, upper, pos)

            cond = self.viper_ast.Or(lt, gt, pos)
            stmts = []
            self._set_overflow_flag(stmts, ctx, pos)
            self.fail_if(cond, stmts, res, ctx, pos)
