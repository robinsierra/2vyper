import ast

from py2viper_translation.abstract_translator import CommonTranslator, TranslatorConfig, Expr, StmtAndExpr, Stmt
from py2viper_translation.analyzer import PythonClass, PythonMethod, PythonVar, PythonTryBlock
from py2viper_translation.util import InvalidProgramException
from typing import List, Tuple, Optional, Union, Dict, Any

class ExpressionTranslator(CommonTranslator):

    def translate_expr(self, node: ast.AST, ctx) -> StmtAndExpr:
        """
        Generic visitor function for translating an expression
        """
        method = 'translate_' + node.__class__.__name__
        visitor = getattr(self, method, self.translate_generic)
        return visitor(node, ctx)

    def translate_Return(self, node: ast.Return, ctx) -> StmtAndExpr:
        return self.translate_expr(node.value, ctx)

    def translate_Num(self, node: ast.Num, ctx) -> StmtAndExpr:
        return ([], self.viper.IntLit(node.n, self.to_position(node, ctx),
                                      self.noinfo(ctx)))

    def translate_Dict(self, node: ast.Dict, ctx) -> StmtAndExpr:
        args = []
        res_var = ctx.current_function.create_variable('dict',
            ctx.program.classes['dict'], self.translator)
        targets = [res_var.ref]
        constr_call = self.viper.MethodCall('dict___init__', args, targets,
                                            self.to_position(node, ctx),
                                            self.noinfo(ctx))
        stmt = [constr_call]
        for key, val in zip(node.keys, node.values):
            key_stmt, key_val = self.translate_expr(key, ctx)
            val_stmt, val_val = self.translate_expr(val, ctx)
            append_call = self.viper.MethodCall('dict___setitem__',
                                                [res_var.ref, key_val, val_val],
                                                [], self.to_position(node, ctx),
                                                self.noinfo(ctx))
            stmt += key_stmt + val_stmt + [append_call]
        return stmt, res_var.ref

    def translate_Set(self, node: ast.Set, ctx) -> StmtAndExpr:
        args = []
        res_var = ctx.current_function.create_variable('set',
            ctx.program.classes['set'], self.translator)
        targets = [res_var.ref]
        constr_call = self.viper.MethodCall('set___init__', args, targets,
                                            self.to_position(node, ctx),
                                            self.noinfo(ctx))
        stmt = [constr_call]
        for el in node.elts:
            el_stmt, el_val = self.translate_expr(el, ctx)
            append_call = self.viper.MethodCall('set_add',
                                                [res_var.ref, el_val],
                                                [], self.to_position(node, ctx),
                                                self.noinfo(ctx))
            stmt += el_stmt + [append_call]
        return stmt, res_var.ref

    def translate_List(self, node: ast.List, ctx) -> StmtAndExpr:
        args = []
        res_var = ctx.current_function.create_variable('list',
            ctx.program.classes['list'], self.translator)
        targets = [res_var.ref]
        constr_call = self.viper.MethodCall('list___init__', args, targets,
                                            self.to_position(node, ctx),
                                            self.noinfo(ctx))
        stmt = [constr_call]
        for element in node.elts:
            el_stmt, el = self.translate_expr(element, ctx)
            append_call = self.viper.MethodCall('list_append',
                                                [res_var.ref, el], [],
                                                self.to_position(node, ctx),
                                                self.noinfo(ctx))
            stmt += el_stmt + [append_call]
        return stmt, res_var.ref

    def translate_Subscript(self, node: ast.Subscript, ctx) -> StmtAndExpr:
        if not isinstance(node.slice, ast.Index):
            raise UnsupportedException(node)
        target_stmt, target = self.translate_expr(node.value, ctx)
        index_stmt, index = self.translate_expr(node.slice.value, ctx)
        args = [target, index]
        call = self._get_function_call(node.value, '__getitem__', args, node, ctx)
        return target_stmt + index_stmt, call

    def create_exception_catchers(self, var: PythonVar,
                                  try_blocks: List[PythonTryBlock],
                                  call: ast.Call, ctx) -> List[Stmt]:
        """
        Creates the code for catching an exception, i.e. redirecting control
        flow to the handlers, to a finally block, or giving the exception to
        the caller function.
        """
        if isinstance(var, PythonVar):
            var = var.ref
        cases = []
        position = self.to_position(call, ctx)
        err_var = self.viper.LocalVar('_err', self.viper.Ref,
                                      self.noposition(ctx),
                                      self.noinfo(ctx))

        relevant_try_blocks = self._get_surrounding_try_blocks(try_blocks, call)
        goto_finally = self._create_goto_finally(relevant_try_blocks, var, ctx)
        if goto_finally:
            uncaught_option = goto_finally
        else:
            if ctx.current_function.declared_exceptions:
                assignerror = self.viper.LocalVarAssign(err_var, var, position,
                                                        self.noinfo(ctx))
                gotoend = self.viper.Goto('__end', position,
                                          self.noinfo(ctx))
                uncaught_option = self.translate_block([assignerror, gotoend],
                                                       position,
                                                       self.noinfo(ctx))
            else:
                uncaught_option = self.viper.Exhale(
                    self.viper.FalseLit(position, self.noinfo(ctx)), position,
                    self.noinfo(ctx))

        for block in relevant_try_blocks:
            for handler in block.handlers:
                condition = self.type_factory.has_type(var, handler.exception, ctx)
                goto = self.viper.Goto(handler.name,
                                       self.to_position(handler.node, ctx),
                                       self.noinfo(ctx))
                cases.insert(0, (condition, goto))
            if block.finally_block:
                break

        result = None
        for cond, goto in cases:
            if result is None:
                result = self.viper.If(cond, goto,
                                       uncaught_option,
                                       self.to_position(handler.node, ctx),
                                       self.noinfo(ctx))
            else:
                result = self.viper.If(cond, goto, result,
                                       self.to_position(handler.node, ctx),
                                       self.noinfo(ctx))
        if result is None:
            error_case = uncaught_option
        else:
            error_case = result
        errnotnull = self.viper.NeCmp(var,
                                      self.viper.NullLit(self.noposition(ctx),
                                                         self.noinfo(ctx)),
                                      position, self.noinfo(ctx))
        emptyblock = self.translate_block([], self.noposition(ctx),
                                          self.noinfo(ctx))
        errcheck = self.viper.If(errnotnull, error_case, emptyblock,
                                 position,
                                 self.noinfo(ctx))
        return [errcheck]

    def _create_goto_finally(self, tries: List[PythonTryBlock],
                             error_var: 'LocalVar', ctx) -> Optional[Stmt]:
        """
        If any of the blocks in tries has a finally-block, creates and
        returns the statements to jump there.
        """
        for try_ in tries:
            if try_.finally_block:
                # propagate return value
                var_next = try_.get_finally_var(self.translator)
                var_next_error = try_.get_error_var(self)
                next_error_assign = self.viper.LocalVarAssign(var_next_error.ref,
                                                              error_var,
                                                              self.noposition(ctx),
                                                              self.noinfo(ctx))
                number_two = self.viper.IntLit(2, self.noposition(ctx),
                                               self.noinfo(ctx))
                next_assign = self.viper.LocalVarAssign(var_next.ref,
                                                        number_two,
                                                        self.noposition(ctx),
                                                        self.noinfo(ctx))
                # goto finally block
                goto_next = self.viper.Goto(try_.finally_name,
                                            self.noposition(ctx),
                                            self.noinfo(ctx))
                return_block = [next_assign, goto_next]
                result = self.translate_block(return_block, self.noposition(ctx),
                                              self.noinfo(ctx))
                return result
        return None

    def translate_to_bool(self, node: ast.AST, ctx) -> StmtAndExpr:
        """
        Translates node as a normal expression, then applies Python's auto-
        conversion to a boolean value (using the __bool__ function)
        """
        stmt, res = self.translate_expr(node, ctx)
        type = self.get_type(node, ctx)
        if type is ctx.program.classes['bool']:
            return stmt, res
        args = [res]
        call = self._get_function_call(node, '__bool__', args, node, ctx)
        return stmt, call

    def translate_Expr(self, node: ast.Expr, ctx) -> StmtAndExpr:
        return self.translate_expr(node.value, ctx)

    def translate_Name(self, node: ast.Name, ctx) -> StmtAndExpr:
        if node.id in ctx.program.global_vars:
            var = ctx.program.global_vars[node.id]
            type = self.translate_type(var.type, ctx)
            func_app = self.viper.FuncApp(var.sil_name, [],
                                         self.to_position(node, ctx),
                                         self.noinfo(ctx), type, [])
            return [], func_app
        else:
            if ctx.var_aliases and node.id in ctx.var_aliases:
                return [], ctx.var_aliases[node.id].ref
            else:
                return [], ctx.current_function.get_variable(node.id).ref

    def translate_Attribute(self, node: ast.Attribute, ctx) -> StmtAndExpr:
        stmt, receiver = self.translate_expr(node.value, ctx)
        rec_type = self.get_type(node.value, ctx)
        result = rec_type.get_field(node.attr)
        while result.inherited is not None:
            result = result.inherited
        if result.is_mangled():
            if result.cls is not ctx.current_class:
                raise InvalidProgramException(node, 'private.field.access')
        return (stmt, self.viper.FieldAccess(receiver, result.field,
                                             self.to_position(node, ctx),
                                             self.noinfo(ctx)))

    def translate_UnaryOp(self, node: ast.UnaryOp, ctx) -> StmtAndExpr:
        if isinstance(node.op, ast.Not):
            stmt, expr = self.translate_to_bool(node.operand, ctx)
            return (stmt, self.viper.Not(expr, self.to_position(node, ctx),
                                         self.noinfo(ctx)))
        stmt, expr = self.translate_expr(node.operand, ctx)
        if isinstance(node.op, ast.USub):
            return (stmt, self.viper.Minus(expr, self.to_position(node, ctx),
                                           self.noinfo(ctx)))
        else:
            raise UnsupportedException(node)

    def translate_IfExp(self, node: ast.IfExp, ctx) -> StmtAndExpr:
        position = self.to_position(node, ctx)
        cond_stmt, cond = self.translate_to_bool(node.test, ctx)
        then_stmt, then = self.translate_expr(node.body, ctx)
        else_stmt, else_ = self.translate_expr(node.orelse, ctx)
        if then_stmt or else_stmt:
            then_block = self.translate_block(then_stmt, position,
                                              self.noinfo(ctx))
            else_block = self.translate_block(else_stmt, position,
                                              self.noinfo(ctx))
            if_stmt = self.viper.If(cond, then_block, else_block, position,
                                    self.noinfo(ctx))
            bodystmt = [if_stmt]
        else:
            bodystmt = []
        cond_exp = self.viper.CondExp(cond, then, else_,
                                      self.to_position(node, ctx),
                                      self.noinfo(ctx))
        return cond_stmt + bodystmt, cond_exp

    def translate_BinOp(self, node: ast.BinOp, ctx) -> StmtAndExpr:
        left_stmt, left = self.translate_expr(node.left, ctx)
        right_stmt, right = self.translate_expr(node.right, ctx)
        stmt = left_stmt + right_stmt
        if isinstance(node.op, ast.Add):
            return (stmt, self.viper.Add(left, right,
                                         self.to_position(node, ctx),
                                         self.noinfo(ctx)))
        elif isinstance(node.op, ast.Sub):
            return (stmt, self.viper.Sub(left, right,
                                         self.to_position(node, ctx),
                                         self.noinfo(ctx)))
        elif isinstance(node.op, ast.Mult):
            return (stmt, self.viper.Mul(left, right,
                                         self.to_position(node, ctx),
                                         self.noinfo(ctx)))
        elif isinstance(node.op, ast.FloorDiv):
            return (stmt, self.viper.Div(left, right,
                                         self.to_position(node, ctx),
                                         self.noinfo(ctx)))
        elif isinstance(node.op, ast.Mod):
            return (stmt, self.viper.Mod(left, right,
                                         self.to_position(node, ctx),
                                         self.noinfo(ctx)))
        else:
            raise UnsupportedException(node)

    def translate_Compare(self, node: ast.Compare, ctx) -> StmtAndExpr:
        if len(node.ops) != 1 or len(node.comparators) != 1:
            raise UnsupportedException(node)
        left_stmt, left = self.translate_expr(node.left, ctx)
        right_stmt, right = self.translate_expr(node.comparators[0], ctx)
        stmts = left_stmt + right_stmt
        if isinstance(node.ops[0], ast.Eq):
            return (stmts, self.viper.EqCmp(left, right,
                                            self.to_position(node, ctx),
                                            self.noinfo(ctx)))
        elif isinstance(node.ops[0], ast.Gt):
            return (stmts, self.viper.GtCmp(left, right,
                                            self.to_position(node, ctx),
                                            self.noinfo(ctx)))
        elif isinstance(node.ops[0], ast.GtE):
            return (stmts, self.viper.GeCmp(left, right,
                                            self.to_position(node, ctx),
                                            self.noinfo(ctx)))
        elif isinstance(node.ops[0], ast.Lt):
            return (stmts, self.viper.LtCmp(left, right,
                                            self.to_position(node, ctx),
                                            self.noinfo(ctx)))
        elif isinstance(node.ops[0], ast.LtE):
            return (stmts, self.viper.LeCmp(left, right,
                                            self.to_position(node, ctx),
                                            self.noinfo(ctx)))
        elif isinstance(node.ops[0], ast.NotEq):
            return (stmts, self.viper.NeCmp(left, right,
                                            self.to_position(node, ctx),
                                            self.noinfo(ctx)))
        elif isinstance(node.ops[0], ast.In):
            args = [right, left]
            app = self._get_function_call(node.comparators[0], '__contains__',
                                          args, node, ctx)
            return stmts, app
        else:
            raise UnsupportedException(node.ops[0])

    def translate_NameConstant(self,
                               node: ast.NameConstant, ctx) -> StmtAndExpr:
        if node.value is True:
            return ([], self.viper.TrueLit(self.to_position(node, ctx),
                                           self.noinfo(ctx)))
        elif node.value is False:
            return ([], self.viper.FalseLit(self.to_position(node, ctx),
                                            self.noinfo(ctx)))
        elif node.value is None:
            return ([],
                    self.viper.NullLit(self.to_position(node, ctx), self.noinfo(ctx)))
        else:
            raise UnsupportedException(node)

    def translate_BoolOp(self, node: ast.BoolOp, ctx) -> StmtAndExpr:
        if len(node.values) != 2:
            raise UnsupportedException(node)
        position = self.to_position(node, ctx)
        left_stmt, left = self.translate_expr(node.values[0], ctx)
        right_stmt, right = self.translate_expr(node.values[1], ctx)
        if left_stmt or right_stmt:
            # TODO: Something important breaks if we run this normally
            # with an acc() as left and a method call on the rhs. If this
            # happens in a test, all tests afterwards fail. Either catch all
            # such cases here, or fix it in Silver.
            if isinstance(left, self.jvm.viper.silver.ast.FieldAccessPredicate):
                return left_stmt + right_stmt, right
            cond = left
            if isinstance(node.op, ast.Or):
                cond = self.viper.Not(cond, position, self.noinfo(ctx))
            then_block = self.translate_block(right_stmt, position,
                                              self.noinfo(ctx))
            else_block = self.translate_block([], position, self.noinfo(ctx))
            if_stmt = self.viper.If(cond, then_block, else_block, position,
                                   self.noinfo(ctx))
            stmt = left_stmt + [if_stmt]
        else:
            stmt = []
        if isinstance(node.op, ast.And):
            return (stmt, self.viper.And(left,
                                         right,
                                         self.to_position(node, ctx),
                                         self.noinfo(ctx)))
        elif isinstance(node.op, ast.Or):
            return (stmt, self.viper.Or(left,
                                        right,
                                        self.to_position(node, ctx),
                                        self.noinfo(ctx)))
        else:
            raise UnsupportedException(node)

    def translate_pythonvar_decl(self,
                                 var: PythonVar, ctx) -> 'silver.ast.LocalVarDecl':
        """
        Creates a variable declaration for the given PythonVar.
        To be called during the processing phase by the Analyzer.
        """
        return self.viper.LocalVarDecl(var.sil_name,
                                       self.translate_type(var.type, ctx),
                                       self.noposition(ctx), self.noinfo(ctx))

    def translate_pythonvar_ref(self, var: PythonVar, ctx) -> Expr:
        """
        Creates a variable reference for the given PythonVar.
        To be called during the processing phase by the Analyzer.
        """
        return self.viper.LocalVar(var.sil_name,
                                   self.translate_type(var.type, ctx),
                                   self.noposition(ctx), self.noinfo(ctx))