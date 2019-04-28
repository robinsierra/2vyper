"""
Copyright (c) 2019 ETH Zurich
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""

import ast

from nagini_translation.parsing.ast import VyperProgram, VyperFunction, VyperVar
from nagini_translation.lib.typedefs import Program
from nagini_translation.lib.viper_ast import ViperAST

from nagini_translation.translation.abstract import NodeTranslator
from nagini_translation.translation.function import FunctionTranslator
from nagini_translation.translation.type import TypeTranslator
from nagini_translation.translation.specification import SpecificationTranslator

from nagini_translation.translation.context import Context
from nagini_translation.translation.builtins import INIT, SELF
from nagini_translation.translation.builtins import init_function, self_var


class ProgramTranslator(NodeTranslator):

    def __init__(self, viper_ast: ViperAST, builtins: Program):
        self.viper_ast = viper_ast
        self.builtins = builtins
        self.function_translator = FunctionTranslator(viper_ast)
        self.type_translator = TypeTranslator(viper_ast)
        self.specification_translator = SpecificationTranslator(viper_ast, True)

    def _translate_field(self, var: VyperVar, ctx: Context):
        pos = self.to_position(var.node, ctx)
        info = self.no_info()

        name = var.name
        type = self.type_translator.translate(var.type, ctx)
        field = self.viper_ast.Field(name, type, pos, info)

        return field

    def _create_field_access_predicate(self, receiver, field, ctx: Context):
        pos = self.no_position()
        info = self.no_info()

        field_acc = self.viper_ast.FieldAccess(receiver, field, pos, info)
        perm = self.viper_ast.FullPerm(pos, info)
        return self.viper_ast.FieldAccessPredicate(field_acc, perm, pos, info)

    def translate(self, vyper_program: VyperProgram, file: str) -> Program:
        if INIT not in vyper_program.functions:
            vyper_program.functions[INIT] = init_function()
        pos = self.no_position()
        info = self.no_info()

        # Add built-in fields (for maps, etc.)
        builtin_fields = {}
        it = self.builtins.fields().iterator()
        while it.hasNext():
            field = it.next()
            builtin_fields[field.name()] = field

        # Add built-in methods
        methods = []
        it = self.builtins.methods().iterator()
        while it.hasNext():
            method = it.next()
            methods.append(method)

        # Add built-in functions
        viper_functions = []
        it = self.builtins.functions().iterator()
        while it.hasNext():
            func = it.next()
            viper_functions.append(func)

        ctx = Context(file)
        ctx.program = vyper_program
        ctx.self_var = self_var(self.viper_ast, pos, info)

        ctx.fields = {}
        ctx.ghost_general_invariants = []
        ctx.ghost_invariants = []
        for var in vyper_program.state.values():
            # Create field
            field = self._translate_field(var, ctx)
            ctx.fields[var.name] = field

            perm = self.type_translator.permissions(var.type, field, ctx)
            if perm:
                ctx.ghost_invariants.append(perm)

            # Pass around the permissions for all fields
            acc = self._create_field_access_predicate(ctx.self_var.localVar(), field, ctx)
            ctx.ghost_general_invariants.append(acc)

        fields_list = list(builtin_fields.values()) + list(ctx.fields.values())

        # Add the actual invariants
        ctx.invariants = [self.specification_translator.translate_spec(iv, ctx) for iv in vyper_program.invariants]
        functions = vyper_program.functions.values()
        methods += [self.function_translator.translate(function, ctx) for function in functions]
        viper_program = self.viper_ast.Program([], fields_list, viper_functions, [], methods, pos, info)
        return viper_program