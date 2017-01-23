import ast

from py2viper_translation.lib.constants import (
    BOOL_TYPE,
    BOXED_PRIMITIVES,
    DICT_TYPE,
    END_LABEL,
    INT_TYPE,
    LIST_TYPE,
    PRIMITIVE_INT_TYPE,
    SET_TYPE,
    STRING_TYPE,
    TUPLE_TYPE,
)
from py2viper_translation.lib.program_nodes import (
    PythonClass,
    PythonField,
    PythonGlobalVar,
    PythonIOExistentialVar,
    PythonModule,
    PythonTryBlock,
    PythonType,
    PythonVar,
)
from py2viper_translation.lib.typedefs import (
    Expr,
    Stmt,
    StmtsAndExpr,
)
from py2viper_translation.lib.util import (
    get_func_name,
    get_surrounding_try_blocks,
    InvalidProgramException,
    join_expressions,
    UnsupportedException,
)
from py2viper_translation.translators.abstract import Context
from py2viper_translation.translators.common import CommonTranslator
from typing import List, Optional


class ExpressionTranslator(CommonTranslator):

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        # TODO: Update all code to use this flag.
        self._is_expression = False
        self._target_type = None
        self.primitive_compare = {
            ast.Is: self.viper.EqCmp,
            ast.Eq: self.viper.EqCmp,
            ast.NotEq: self.viper.NeCmp,
            ast.IsNot: self.viper.NeCmp,
            ast.Lt: self.viper.LtCmp,
            ast.LtE: self.viper.LeCmp,
            ast.Gt: self.viper.GtCmp,
            ast.GtE: self.viper.GeCmp,
        }

    def translate_expr(self, node: ast.AST, ctx: Context,
                       target_type = None,
                       expression: bool = False) -> StmtsAndExpr:
        """
        Generic visitor function for translating an expression.

        :param target_type:
            The Silver type this expression should be translated to, defaults
            to Ref if no arguments is provided.
        :param expression:
            Indicates if ``node`` must be translated into Silver
            expression.

            +   If ``True``, then sets a flag that ``node`` must be
                translated into Silver expression.
            +   If ``False``, leaves the flag unaltered.
        """

        old_is_expression = self._is_expression

        if expression:
            self._is_expression = True

        method = 'translate_' + node.__class__.__name__
        visitor = getattr(self, method, self.translate_generic)
        if not target_type:
            target_type = self.viper.Ref
        old_target = self._target_type
        self._target_type = target_type
        stmt, result = visitor(node, ctx)

        if target_type != result.typ():
            result = self.convert_to_type(result, target_type, ctx, node)

        self._is_expression = old_is_expression
        self._target_type = old_target
        return stmt, result

    def translate_Return(self, node: ast.Return, ctx: Context) -> StmtsAndExpr:
        return self.translate_expr(node.value, ctx)

    def translate_Num(self, node: ast.Num, ctx: Context) -> StmtsAndExpr:
        lit = self.viper.IntLit(node.n, self.to_position(node, ctx),
                                self.no_info(ctx))
        int_class = ctx.module.global_module.classes[PRIMITIVE_INT_TYPE]
        boxed_lit = self.get_function_call(int_class, '__box__', [lit],
                                           [None], node, ctx)
        return ([], boxed_lit)

    def translate_Dict(self, node: ast.Dict, ctx: Context) -> StmtsAndExpr:
        args = []
        res_var = ctx.current_function.create_variable('dict',
            ctx.module.global_module.classes[DICT_TYPE], self.translator)
        dict_class = ctx.module.global_module.classes[DICT_TYPE]
        arg_types = []
        constr_call = self.get_method_call(dict_class, '__init__', [],
                                           [], [res_var.ref()], node, ctx)
        stmt = constr_call
        # Inhale the type of the newly created dict (including type arguments)
        dict_type = self.get_type(node, ctx)
        position = self.to_position(node, ctx)
        stmt.append(self.viper.Inhale(self.type_check(res_var.ref(node, ctx),
                                                      dict_type, position, ctx),
                                      position, self.no_info(ctx)))
        for key, val in zip(node.keys, node.values):
            key_stmt, key_val = self.translate_expr(key, ctx)
            key_type = self.get_type(key, ctx)
            val_stmt, val_val = self.translate_expr(val, ctx)
            val_type = self.get_type(val, ctx)
            args = [res_var.ref(), key_val, val_val]
            arg_types = [None, key_type, val_type]
            append_call = self.get_method_call(dict_class, '__setitem__', args,
                                               arg_types, [], node, ctx)
            stmt += key_stmt + val_stmt + append_call
        return stmt, res_var.ref(node, ctx)

    def translate_Set(self, node: ast.Set, ctx: Context) -> StmtsAndExpr:
        set_class = ctx.module.global_module.classes[SET_TYPE]
        res_var = ctx.current_function.create_variable(SET_TYPE,
            set_class, self.translator)
        constr_call = self.get_method_call(set_class, '__init__', [], [],
                                           [res_var.ref()], node, ctx)
        stmt = constr_call
        # Inhale the type of the newly created set (including type arguments)
        set_type = self.get_type(node, ctx)
        position = self.to_position(node, ctx)
        stmt.append(self.viper.Inhale(self.type_check(res_var.ref(node, ctx),
                                                      set_type, position, ctx),
                                      position, self.no_info(ctx)))
        for el in node.elts:
            el_stmt, el_val = self.translate_expr(el, ctx)
            el_type = self.get_type(el, ctx)
            args = [res_var.ref(), el_val]
            arg_types = [None, el_type]
            append_call = self.get_method_call(set_class, 'add', args,
                                               arg_types, [], node, ctx)
            stmt += el_stmt + append_call
        return stmt, res_var.ref(node, ctx)

    def translate_List(self, node: ast.List, ctx: Context) -> StmtsAndExpr:
        list_class = ctx.module.global_module.classes[LIST_TYPE]
        res_var = ctx.current_function.create_variable(LIST_TYPE,
            list_class, self.translator)
        targets = [res_var.ref()]

        constr_call = self.get_method_call(list_class, '__init__', [], [],
                                           [res_var.ref()], node, ctx)
        stmt = constr_call
        # Inhale the type of the newly created list (including type arguments)
        list_type = self.get_type(node, ctx)
        position = self.to_position(node, ctx)
        stmt.append(self.viper.Inhale(self.type_check(res_var.ref(node, ctx),
                                                      list_type, position, ctx),
                                      position, self.no_info(ctx)))
        for element in node.elts:
            el_stmt, el = self.translate_expr(element, ctx)
            el_type = self.get_type(element, ctx)
            args = [res_var.ref(), el]
            arg_types = [None, el_type]
            append_call = self.get_method_call(list_class, 'append', args,
                                               arg_types, [], node, ctx)
            stmt += el_stmt + append_call
        return stmt, res_var.ref(node, ctx)

    def translate_Str(self, node: ast.Str, ctx: Context) -> StmtsAndExpr:
        length = len(node.s)
        length_arg = self.viper.IntLit(length, self.no_position(ctx),
                                       self.no_info(ctx))
        val_arg = self.viper.IntLit(self._get_string_value(node.s),
                                    self.no_position(ctx), self.no_info(ctx))
        args = [length_arg, val_arg]
        arg_types = [None, None]
        str_type = ctx.module.global_module.classes[STRING_TYPE]
        func_name = '__create__'
        call = self.get_function_call(str_type, func_name, args, arg_types,
                                      node, ctx)
        return [], call

    def translate_Tuple(self, node: ast.Tuple, ctx: Context) -> StmtsAndExpr:
        stmts = []
        vals = []
        val_types = []
        for el in node.elts:
            el_stmt, el_val = self.translate_expr(el, ctx)
            stmts += el_stmt
            vals.append(el_val)
            val_types.append(self.get_type(el, ctx))
        tuple_class = ctx.module.global_module.classes[TUPLE_TYPE]
        type_class = ctx.module.global_module.classes['type']
        func_name = '__create' + str(len(node.elts)) + '__'
        vals = vals + [self.get_tuple_type_arg(v, t, node, ctx)
                       for (t, v) in zip(val_types, vals)]
        val_types += [type_class] * len(val_types)
        call = self.get_function_call(tuple_class, func_name, vals, val_types,
                                      node, ctx)
        return stmts, call

    def translate_Subscript(self, node: ast.Subscript,
                            ctx: Context) -> StmtsAndExpr:
        if not isinstance(node.slice, ast.Index):
            raise UnsupportedException(node)
        target_stmt, target = self.translate_expr(node.value, ctx,
                                                  target_type=self.viper.Ref)
        target_type = self.get_type(node.value, ctx)
        index_stmt, index = self.translate_expr(node.slice.value, ctx,
                                                target_type=self.viper.Ref)
        index_type = self.get_type(node.slice.value, ctx)
        args = [target, index]
        arg_types = [target_type, index_type]
        call = self.get_function_call(target_type, '__getitem__', args,
                                      arg_types, node, ctx)
        result = call
        result_type = self.get_type(node, ctx)
        return target_stmt + index_stmt, result

    def create_exception_catchers(self, var: PythonVar,
                                  try_blocks: List[PythonTryBlock],
                                  call: ast.Call, ctx: Context) -> List[Stmt]:
        """
        Creates the code for catching an exception, i.e. redirecting control
        flow to the handlers, to a finally block, or giving the exception to
        the caller function.
        """
        if isinstance(var, PythonVar):
            var = var.ref()
        cases = []
        position = self.to_position(call, ctx)
        err_var = ctx.error_var.ref()
        relevant_try_blocks = get_surrounding_try_blocks(try_blocks, call)
        goto_finally = self._create_goto_finally(relevant_try_blocks, ctx)
        if goto_finally:
            uncaught_option = goto_finally
        else:
            if ctx.actual_function.declared_exceptions:
                assignerror = self.viper.LocalVarAssign(err_var, var, position,
                                                        self.no_info(ctx))
                end_label = ctx.get_label_name(END_LABEL)
                gotoend = self.viper.Goto(end_label, position,
                                          self.no_info(ctx))
                uncaught_option = self.translate_block([assignerror, gotoend],
                                                       position,
                                                       self.no_info(ctx))
            else:
                error_string = '"method raises no exceptions"'
                error_pos = self.to_position(call, ctx, error_string)
                uncaught_option = self.viper.Exhale(
                    self.viper.FalseLit(error_pos, self.no_info(ctx)),
                    error_pos,
                    self.no_info(ctx))

        for block in relevant_try_blocks:
            for handler in block.handlers:
                condition = self.type_check(var, handler.exception,
                                            self.to_position(handler.node, ctx),
                                            ctx, inhale_exhale=False)
                label_name = ctx.get_label_name(handler.name)
                goto = self.viper.Goto(label_name,
                                       self.to_position(handler.node, ctx),
                                       self.no_info(ctx))
                cases.insert(0, (condition, goto))
            if block.finally_block:
                break

        result = None
        for cond, goto in cases:
            if result is None:
                result = self.viper.If(cond, goto,
                                       uncaught_option,
                                       self.to_position(handler.node, ctx),
                                       self.no_info(ctx))
            else:
                result = self.viper.If(cond, goto, result,
                                       self.to_position(handler.node, ctx),
                                       self.no_info(ctx))
        if result is None:
            error_case = uncaught_option
        else:
            error_case = result
        errnotnull = self.viper.NeCmp(var,
                                      self.viper.NullLit(self.no_position(ctx),
                                                         self.no_info(ctx)),
                                      position, self.no_info(ctx))
        emptyblock = self.translate_block([], self.no_position(ctx),
                                          self.no_info(ctx))
        errcheck = self.viper.If(errnotnull, error_case, emptyblock,
                                 position,
                                 self.no_info(ctx))
        return [errcheck]

    def _create_goto_finally(self, tries: List[PythonTryBlock],
                             ctx: Context) -> Optional[Stmt]:
        """
        If any of the blocks in tries has a finally-block, creates and
        returns the statements to jump there.
        """
        for try_ in tries:
            if try_.finally_block:
                # Propagate return value
                var_next = try_.get_finally_var(self.translator)
                if var_next.sil_name in ctx.var_aliases:
                    var_next = ctx.var_aliases[var_next.sil_name]
                number_two = self.viper.IntLit(2, self.no_position(ctx),
                                               self.no_info(ctx))
                next_assign = self.viper.LocalVarAssign(var_next.ref(),
                                                        number_two,
                                                        self.no_position(ctx),
                                                        self.no_info(ctx))
                # Goto finally block
                label_name = ctx.get_label_name(try_.finally_name)
                goto_next = self.viper.Goto(label_name,
                                            self.no_position(ctx),
                                            self.no_info(ctx))
                return_block = [next_assign, goto_next]
                result = self.translate_block(return_block,
                                              self.no_position(ctx),
                                              self.no_info(ctx))
                return result
        return None

    def translate_to_bool(self, node: ast.AST, ctx: Context,
                          expression: bool = False) -> StmtsAndExpr:
        """
        Translates node as a normal expression, then applies Python's auto-
        conversion to a boolean value (using the __bool__ function)
        """
        stmt, res = self.translate_expr(node, ctx, expression)
        type = self.get_type(node, ctx)
        bool_class = ctx.module.global_module.classes[BOOL_TYPE]
        if type is not bool_class:
            args = [res]
            arg_type = self.get_type(node, ctx)
            arg_types = [arg_type]
            res = self.get_function_call(arg_type, '__bool__', args, arg_types,
                                         node, ctx)
        if res.typ() != self.viper.Bool:
            res = self.get_function_call(bool_class, '__unbox__', [res], [None],
                                         node, ctx)
        return stmt, res

    def translate_Expr(self, node: ast.Expr, ctx: Context) -> StmtsAndExpr:
        return self.translate_expr(node.value, ctx)

    def translate_Name(self, node: ast.Name, ctx: Context) -> StmtsAndExpr:
        target = self.get_target(node, ctx)
        if isinstance(target, PythonGlobalVar):
            var = target
            type = self.translate_type(var.type, ctx)
            func_app = self.viper.FuncApp(var.sil_name, [],
                                          self.to_position(node, ctx),
                                          self.no_info(ctx), type, [])
            return [], func_app
        else:
            if isinstance(target, PythonClass):
                return [], self.type_factory.translate_type_literal(target,
                    node, ctx)
            if node.id in ctx.var_aliases:
                var = ctx.var_aliases[node.id]
            else:
                var = ctx.actual_function.get_variable(node.id)
            if (isinstance(var, PythonIOExistentialVar) and
                    not var.is_defined()):
                raise InvalidProgramException(
                    node, 'io_existential_var.use_of_undefined')
            return [], var.ref(node, ctx)

    def _lookup_field(self, node: ast.Attribute, ctx: Context) -> PythonField:
        """
        Returns the PythonField for a given ast.Attribute node.
        """
        recv = self.get_type(node.value, ctx)
        if recv.name == 'type':
            recv = recv.type_args[0]
        field = recv.get_field(node.attr)
        if not field:
            if (isinstance(recv, PythonClass) and
                    recv.get_static_field(node.attr)):
                var = recv.static_fields[node.attr]
                return var
            recv = self.get_type(node.value, ctx)
            raise InvalidProgramException(node, 'field.nonexistent')
        while field.inherited is not None:
            field = field.inherited
        if field.is_mangled() and (field.cls is not ctx.current_class and
                                   field.cls is not ctx.actual_function.cls):
            raise InvalidProgramException(node, 'private.field.access')

        return field

    def translate_Attribute(self, node: ast.Attribute,
                            ctx: Context) -> StmtsAndExpr:
        target = self.get_target(node.value, ctx)
        func_name = get_func_name(node.value)
        if isinstance(target, PythonModule):
            target = self.get_target(node, ctx)
            if isinstance(target, PythonGlobalVar):
                # Global var?
                pos = self.to_position(node, ctx)
                info = self.no_info(ctx)
                var_type = self.translate_type(target.type, ctx)
                return [], self.viper.FuncApp(target.sil_name, [], pos, info,
                                              var_type, [])
            else:
                raise UnsupportedException(node)
        elif isinstance(target, PythonClass) and func_name != 'Result':
            field = target.static_fields[node.attr]
            type = self.translate_type(field.type, ctx)
            func_app = self.viper.FuncApp(field.sil_name, [],
                                          self.to_position(node, ctx),
                                          self.no_info(ctx), type, [])
            return [], func_app
        else:
            stmt, receiver = self.translate_expr(node.value, ctx,
                                                 target_type=self.viper.Ref)
            field = self._lookup_field(node, ctx)
            if isinstance(field, PythonVar):
                type = self.translate_type(field.type, ctx)
                func_app = self.viper.FuncApp(field.sil_name, [],
                                              self.to_position(node, ctx),
                                              self.no_info(ctx), type, [])
                return [], func_app
            return (stmt, self.viper.FieldAccess(receiver, field.sil_field,
                                                 self.to_position(node, ctx),
                                                 self.no_info(ctx)))

    def translate_UnaryOp(self, node: ast.UnaryOp,
                          ctx: Context) -> StmtsAndExpr:
        if isinstance(node.op, ast.Not):
            stmt, expr = self.translate_expr(node.operand, ctx,
                                             target_type=self.viper.Bool)
            return (stmt, self.viper.Not(expr, self.to_position(node, ctx),
                                         self.no_info(ctx)))
        stmt, expr = self.translate_expr(node.operand, ctx,
                                         target_type=self.viper.Int)
        if isinstance(node.op, ast.USub):
            return (stmt, self.viper.Minus(expr, self.to_position(node, ctx),
                                           self.no_info(ctx)))
        else:
            raise UnsupportedException(node)

    def translate_IfExp(self, node: ast.IfExp, ctx: Context) -> StmtsAndExpr:
        position = self.to_position(node, ctx)
        cond_stmt, cond = self.translate_expr(node.test, ctx,
                                              target_type=self.viper.Bool)
        then_stmt, then = self.translate_expr(node.body, ctx,
                                              target_type=self._target_type)
        else_stmt, else_ = self.translate_expr(node.orelse, ctx,
                                               target_type=self._target_type)
        if then_stmt or else_stmt:
            then_block = self.translate_block(then_stmt, position,
                                              self.no_info(ctx))
            else_block = self.translate_block(else_stmt, position,
                                              self.no_info(ctx))
            if_stmt = self.viper.If(cond, then_block, else_block, position,
                                    self.no_info(ctx))
            bodystmt = [if_stmt]
        else:
            bodystmt = []
        cond_exp = self.viper.CondExp(cond, then, else_,
                                      self.to_position(node, ctx),
                                      self.no_info(ctx))
        return cond_stmt + bodystmt, cond_exp

    def translate_BinOp(self, node: ast.BinOp, ctx: Context) -> StmtsAndExpr:
        left_stmt, left = self.translate_expr(node.left, ctx)
        right_stmt, right = self.translate_expr(node.right, ctx)
        stmt = left_stmt + right_stmt
        left_type = self.get_type(node.left, ctx)
        right_type = self.get_type(node.right, ctx)
        op_stmt, result = self.translate_operator(left, right, left_type,
                                                  right_type, node, ctx)
        return stmt + op_stmt, result

    def _get_primitive_compare(self, node: ast.BinOp):
        return self.primitive_compare[type(node.ops[0])]

    def translate_Compare(self, node: ast.Compare,
                          ctx: Context) -> StmtsAndExpr:
        if self.is_io_existential_defining_equality(node, ctx):
            self.define_io_existential(node, ctx)
            return ([], self.viper.TrueLit(self.to_position(node, ctx),
                                           self.no_info(ctx)))
        if self.is_wait_level_comparison(node, ctx):
            return self.translate_wait_level_comparison(node, ctx)
        if len(node.ops) != 1 or len(node.comparators) != 1:
            raise UnsupportedException(node)
        left_stmt, left = self.translate_expr(node.left, ctx)
        left_type = self.get_type(node.left, ctx)
        right_stmt, right = self.translate_expr(node.comparators[0], ctx)
        right_type = self.get_type(node.comparators[0], ctx)
        stmts = left_stmt + right_stmt
        position = self.to_position(node, ctx)
        info = self.no_info(ctx)

        left_type_boxed = left_type.try_box()
        right_type_boxed = right_type.try_box()
        # If both sides are of the same, primitive type, use the builtin Viper
        # operator instead of the function
        if (right_type_boxed.name in BOXED_PRIMITIVES and
                right_type_boxed.name == left_type_boxed.name):
            op = self._get_primitive_compare(node)
            if left_type_boxed.name == INT_TYPE:
                wrap = self.to_int
            else:
                wrap = self.to_bool
            result = op(wrap(left, ctx), wrap(right, ctx), position, info)
            return stmts, result

        if isinstance(node.ops[0], ast.Is):
            return (stmts, self.viper.EqCmp(left, right, position, info))
        elif isinstance(node.ops[0], ast.IsNot):
            return (stmts, self.viper.NeCmp(left, right, position, info))
        elif isinstance(node.ops[0], (ast.In, ast.NotIn)):
            args = [right, left]
            arg_types = [right_type, left_type]
            app = self.get_function_call(right_type, '__contains__',
                                         args, arg_types, node, ctx)
            if isinstance(node.ops[0], ast.NotIn):
                app = self.viper.Not(app, position, info)
            return stmts, app
        if isinstance(node.ops[0], ast.Eq):
            int_compare = self.viper.EqCmp
            compare_func = '__eq__'
        elif isinstance(node.ops[0], ast.NotEq):
            int_compare = self.viper.NeCmp
            compare_func = '__ne__'
        elif isinstance(node.ops[0], ast.Gt):
            int_compare = self.viper.GtCmp
            compare_func = '__gt__'
        elif isinstance(node.ops[0], ast.GtE):
            int_compare = self.viper.GeCmp
            compare_func = '__ge__'
        elif isinstance(node.ops[0], ast.Lt):
            int_compare = self.viper.LtCmp
            compare_func = '__lt__'
        elif isinstance(node.ops[0], ast.LtE):
            int_compare = self.viper.LeCmp
            compare_func = '__le__'
        else:
            raise UnsupportedException(node.ops[0])
        if left_type.get_function(compare_func):
            comparison = self.get_function_call(left_type, compare_func,
                                                [left, right],
                                                [left_type, right_type],
                                                node, ctx)
        elif compare_func == '__ne__' and left_type.get_function('__eq__'):
            # The default behavior if __ne__ is not explicitly defined
            # is to invert the result of __eq__.
            call = self.get_function_call(left_type, '__eq__',
                                          [left, right],
                                          [left_type, right_type],
                                          node, ctx)
            comparison = self.viper.Not(self.to_bool(call, ctx, node.left),
                                        position, info)
        else:
            raise InvalidProgramException(node, 'undefined.comparison')
        return stmts, comparison

    def translate_NameConstant(self, node: ast.NameConstant,
                               ctx: Context) -> StmtsAndExpr:
        if node.value is True:
            return ([], self.viper.TrueLit(self.to_position(node, ctx),
                                           self.no_info(ctx)))
        elif node.value is False:
            return ([], self.viper.FalseLit(self.to_position(node, ctx),
                                            self.no_info(ctx)))
        elif node.value is None:
            return ([],
                    self.viper.NullLit(self.to_position(node, ctx),
                                       self.no_info(ctx)))
        else:
            raise UnsupportedException(node)

    def translate_BoolOp(self, node: ast.BoolOp, ctx: Context) -> StmtsAndExpr:
        assert isinstance(node.op, ast.Or) or isinstance(node.op, ast.And)

        position = self.to_position(node, ctx)
        info = self.no_info(ctx)

        statements_parts = []
        expression_parts = []
        for value in node.values:
            statements_part, expression_part = self.translate_expr(
                value, ctx, target_type=self.viper.Bool)
            if self._is_expression and statements_part:
                raise InvalidProgramException(node, 'not_expression')
            statements_parts.append(statements_part)
            expression_parts.append(expression_part)

        if isinstance(node.op, ast.And):
            operator = (
                lambda left, right:
                self.viper.And(left, right, position, info))
        else:
            operator = (
                lambda left, right:
                self.viper.Or(left, right, position, info))

        joined_expression_parts = [
            join_expressions(operator, expression_parts[:i+1])
            for i in range(len(expression_parts))
            ]

        statements = statements_parts[0]
        for i, part in enumerate(statements_parts[1:]):

            cond = joined_expression_parts[i]
            if isinstance(node.op, ast.Or):
                cond = self.viper.Not(cond, position, info)

            if part:
                then_block = self.translate_block(part, position, info)
                else_block = self.translate_block([], position, info)
                if_stmt = self.viper.If(cond, then_block, else_block,
                                        position, info)
                statements.append(if_stmt)

        return statements, joined_expression_parts[-1]

    def translate_pythonvar_decl(self, var: PythonVar,
                                 ctx: Context) -> 'silver.ast.LocalVarDecl':
        """
        Creates a variable declaration for the given PythonVar.
        To be called during the processing phase by the Analyzer.
        """
        return self.viper.LocalVarDecl(var.sil_name,
                                       self.translate_type(var.type, ctx),
                                       self.no_position(ctx), self.no_info(ctx))

    def translate_pythonvar_ref(self, var: PythonVar, node: ast.AST,
                                ctx: Context) -> Expr:
        """
        Creates a variable reference for the given PythonVar.
        To be called during the processing phase by the Analyzer.
        """
        return self.viper.LocalVar(var.sil_name,
                                   self.translate_type(var.type, ctx),
                                   self.to_position(node, ctx),
                                   self.no_info(ctx))
