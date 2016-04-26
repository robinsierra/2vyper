import ast

from py2viper_contracts.contracts import CONTRACT_FUNCS
from py2viper_translation.lib.jvmaccess import JVM
from py2viper_translation.lib.program_nodes import PythonClass
from py2viper_translation.lib.typeinfo import TypeInfo
from py2viper_translation.lib.util import (
    get_func_name,
    InvalidProgramException,
    UnsupportedException,
)
from py2viper_translation.lib.viper_ast import ViperAST
from py2viper_translation.sif.lib.context import SIFContext
from py2viper_translation.sif.lib.program_nodes import SIFPythonMethod
from py2viper_translation.translators.abstract import (
    Expr,
    Stmt,
    StmtsAndExpr,
    TranslatorConfig,
    )
from py2viper_translation.translators.call import CallTranslator
from typing import List, Optional, Tuple


class CallResults:
    """
    Container for the results of an already translated call node.
    """
    def __init__(self):
        self._results = []
        self._idx = 0

    def next(self) -> Optional[Expr]:
        """
        Returns the next result expr or None if there are no more available.
        """
        res = None
        if self._idx < len(self._results):
            res = self._results[self._idx]
            self._idx += 1

        return res

    def add_result(self, result: Expr):
        self._results.append(result)

    def __len__(self) -> int:
        return len(self._results)


class SIFCallTranslator(CallTranslator):
    """
    SIF version of the CallTranslator.
    """
    def __init__(self, config: TranslatorConfig, jvm: JVM, source_file: str,
                 type_info: TypeInfo, viper_ast: ViperAST) -> None:
        super().__init__(config, jvm, source_file, type_info, viper_ast)
        # Map of already translated call nodes.
        self.translated_calls = {}  # Map[ast.Call, CallResults]

    def _translate_constructor_call(self, target_class: PythonClass,
            node: ast.Call, args: List, arg_stmts: List,
            ctx: SIFContext) -> StmtsAndExpr:
        call_results = self.translated_calls[node]
        res_var = ctx.current_function.create_variable(target_class.name +
                                                       '_res',
                                                       target_class,
                                                       self.translator)
        call_results.add_result(res_var.ref)
        call_results.add_result(res_var.var_prime.ref)
        fields = []
        for field in target_class.get_all_fields():
            fields.append(field.sil_field)
            fields.append(field.field_prime.sil_field)
        new_stmt = self.viper.NewStmt(res_var.ref, fields,
                                      self.no_position(ctx),
                                      self.no_info(ctx))
        result_has_type = self.var_concrete_type_check(res_var.name,
                                                       target_class, ctx)
        # inhale the type information about the newly created object
        # so that it's already present when calling __init__.
        type_inhale = self.viper.Inhale(result_has_type, self.no_position(ctx),
                                        self.no_info(ctx))
        # Set the prime version to be equal to the newly created var.
        assign = self.viper.LocalVarAssign(res_var.var_prime.ref, res_var.ref,
                                           self.no_position(ctx),
                                           self.no_info(ctx))
        args = [res_var.ref, res_var.var_prime.ref] + args
        stmts = [new_stmt, type_inhale, assign]
        target = target_class.get_method('__init__')
        if target:
            targets = []
            if target.declared_exceptions:
                raise UnsupportedException(node, "Exceptions not supported.")
            # Add timeLevel to targets.
            targets.append(ctx.current_function.tl_var.ref)
            init = self.viper.MethodCall(target.sil_name, args, targets,
                                         self.to_position(node, ctx),
                                         self.no_info(ctx))
            stmts.append(init)

        return arg_stmts + stmts, call_results.next()

    def translate_builtin_func(self, node: ast.Call,
                               ctx: SIFContext) -> StmtsAndExpr:
        raise UnsupportedException(node, "Built-ins not supported.")

    def translate_method_call(self, target: SIFPythonMethod, args: List[Expr],
                              arg_stmts: List[Stmt],
                              position: 'silver.ast.Position', node: ast.AST,
                              ctx: SIFContext) -> StmtsAndExpr:
        call_results = self.translated_calls[node]
        targets = []

        if ctx.current_function is None:
            if ctx.current_class is None:
                # global variable
                raise UnsupportedException(node, "Global function call "
                                           "not supported.")
            else:
                # static field
                raise UnsupportedException(node, "Static fields not supported.")

        if target.type is not None:
            result_var = ctx.current_function.create_variable(
                target.name + '_res', target.type, self.translator)
            targets.append(result_var.ref)
            call_results.add_result(result_var.ref)
            targets.append(result_var.var_prime.ref)
            call_results.add_result(result_var.var_prime.ref)
        if target.declared_exceptions:
            raise UnsupportedException(node)
        # Add timeLevel to targets.
        targets.append(ctx.current_function.tl_var.ref)

        call = self.viper.MethodCall(target.sil_name, args, targets,
                                     position, self.no_info(ctx))
        res_expr = call_results.next() if target.type else None

        return arg_stmts + [call], res_expr

    def _translate_args(self, node: ast.Call,
                        ctx: SIFContext) -> Tuple[List[Stmt], List[Expr]]:
        args = []
        arg_stms = []
        for arg in node.args:
            arg_stmt, arg_expr = self.translate_expr(arg, ctx)
            arg_stms += arg_stmt
            args.append(arg_expr)
            ctx.use_prime = True
            arg_stmt, arg_expr = self.translate_expr(arg, ctx)
            ctx.use_prime = False
            arg_stms += arg_stmt
            args.append(arg_expr)
        # Add timeLevel.
        assert ctx.current_function
        args.append(ctx.current_function.tl_var.ref)

        return arg_stms, args

    def _translate_receiver(self, node: ast.Call,
                            ctx: SIFContext) -> Tuple[List[Stmt], List[Expr]]:
        recv_stmts, recv = self.translate_expr(node.func.value, ctx)
        ctx.use_prime = True
        recv_stmts_p, recv_p = self.translate_expr(node.func.value, ctx)
        assert not recv_stmts_p
        ctx.use_prime = False

        # timeLevel := timeLevel || !(typeof(recv) == typeof(recv_p))
        type_expr = self.type_factory.type_comp(recv, recv_p, ctx)
        rhs = self.viper.Or(ctx.current_function.tl_var.ref,
                            type_expr,
                            self.no_position(ctx),
                            self.no_info(ctx))
        assign = self.viper.LocalVarAssign(ctx.current_function.tl_var.ref,
                                           rhs,
                                           self.no_position(ctx),
                                           self.no_info(ctx))
        return recv_stmts + [assign], [recv, recv_p]

    def translate_normal_call(self, node: ast.Call,
                              ctx: SIFContext) -> StmtsAndExpr:
        arg_stmts, args = self._translate_args(node, ctx)
        name = get_func_name(node)
        position = self.to_position(node, ctx)
        if name in ctx.program.classes:
            # This is a constructor call.
            target_class = ctx.program.classes[name]
            return self._translate_constructor_call(target_class, node, args,
                                                    arg_stmts, ctx)
        if isinstance(node.func, ast.Attribute):
            # Method called on an object.
            recv_cls = self.get_type(node.func.value, ctx)
            target = recv_cls.get_func_or_method(node.func.attr)
            recv_stmts, recvs = self._translate_receiver(node, ctx)
            arg_stmts += recv_stmts
            args = recvs + args
        else:
            # Global function/method called.
            recv_cls = None
            target = ctx.program.get_func_or_method(name)

        assert target, "Predicates not supported yet."
        if target.pure:
            raise UnsupportedException(node, "Pure functions not supported.")

        return self.translate_method_call(target, args, arg_stmts,
                                          position, node, ctx)

    def translate_Call(self, node: ast.Call, ctx: SIFContext) -> StmtsAndExpr:
        """
        First checks in self.translated_calls of the call was already
        translated (returning the next result). Calls super().translate_Call
        if that isn't the case.
        """
        func_name = get_func_name(node)
        if node in self.translated_calls:
            # Sanity check. This can only happen if ctx.use_prime == True.
            assert ctx.use_prime
            assert len(self.translated_calls[node])
            return [], self.translated_calls[node].next()
        elif func_name in CONTRACT_FUNCS:
            # Contract functions need no CallResult.
            return self.translate_contractfunc_call(node, ctx)
        else:
            self.translated_calls[node] = CallResults()
            return super().translate_Call(node, ctx)

