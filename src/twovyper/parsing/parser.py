"""
Copyright (c) 2019 ETH Zurich
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""

import ast

from typing import List

from twovyper.parsing.preprocessor import preprocess
from twovyper.parsing.transformer import transform

from twovyper.ast import names
from twovyper.ast import types

from twovyper.ast.nodes import (
    VyperProgram, VyperFunction, VyperStruct, VyperContract, VyperEvent, VyperVar,
    VyperConfig
)

from twovyper.ast.types import (
    TypeBuilder, FunctionType, EventType, StructType, ContractType
)

from twovyper.exceptions import InvalidProgramException


def parse(contract: str, filename: str) -> VyperProgram:
    try:
        preprocessed_contract = preprocess(contract)
        contract_ast = ast.parse(preprocessed_contract, filename)
        contract_ast = transform(contract_ast)
        program_builder = ProgramBuilder()
        return program_builder.build(contract_ast)
    except SyntaxError as err:
        err.text = contract.splitlines()[err.lineno - 1]
        raise err


class ProgramBuilder(ast.NodeVisitor):
    """
    The program builder creates a Vyper program out of the AST. It collects contract
    state variables and functions. It should only be used by calling the build method once.
    """

    # Pre and postconditions are only allowed before a function. As we walk through all
    # top-level statements we gather pre and postconditions until we reach a function
    # definition.

    def __init__(self):
        self.config = None

        self.field_types = {}
        self.functions = {}
        self.structs = {}
        self.contracts = {}
        self.events = {}
        self.invariants = []
        self.general_postconditions = []
        self.transitive_postconditions = []
        self.general_checks = []

        self.postconditions = []
        self.checks = []

        self.is_preserves = False

    @property
    def type_builder(self):
        type_map = {}
        for name, struct in self.structs.items():
            type_map[name] = struct.type
        for name, contract in self.contracts.items():
            type_map[name] = contract.type

        return TypeBuilder(type_map)

    def build(self, node) -> VyperProgram:
        self.visit(node)
        # No trailing local specs allowed
        self._check_no_local_spec()

        # Add self.balance
        assert not self.field_types.get(names.SELF_BALANCE)
        self.field_types[names.SELF_BALANCE] = types.VYPER_WEI_VALUE

        # Create the self-type
        self_type = StructType(names.SELF, self.field_types)
        self_struct = VyperStruct(names.SELF, self_type, None)

        self.config = self.config or VyperConfig([])

        return VyperProgram(self.config,
                            self_struct,
                            self.functions,
                            self.structs,
                            self.contracts,
                            self.events,
                            self.invariants,
                            self.general_postconditions,
                            self.transitive_postconditions,
                            self.general_checks)

    def _check_no_local_spec(self):
        """
        Checks that there are no specifications for functions pending, i.e. there
        are no local specifications followed by either global specifications or eof.
        """
        if self.postconditions:
            cond = "Postcondition"
            node = self.postconditions[0]
        elif self.checks:
            cond = "Check"
            node = self.checks[0]
        else:
            return
        raise InvalidProgramException(node, 'local.spec', f"{cond} only allowed before function")

    def visit_ClassDef(self, node: ast.ClassDef):
        type = self.type_builder.build(node)
        if isinstance(type, StructType):
            struct = VyperStruct(node.name, type, node)
            self.structs[struct.name] = struct
        elif isinstance(type, ContractType):
            contract = VyperContract(node.name, type, node)
            self.contracts[contract.name] = contract
        else:
            assert False

    def visit_AnnAssign(self, node):
        # No local specs are allowed before contract state variables
        self._check_no_local_spec()

        variable_name = node.target.id
        # We ignore the units and implements declarations
        if variable_name != names.UNITS and variable_name != names.IMPLEMENTS:
            variable_type = self.type_builder.build(node.annotation)
            if isinstance(variable_type, EventType):
                event = VyperEvent(variable_name, variable_type)
                self.events[variable_name] = event
            else:
                self.field_types[variable_name] = variable_type

    def visit_Assign(self, node):
        # This is for invariants and postconditions which get translated to
        # assignments during preprocessing.
        assert len(node.targets) == 1
        name = node.targets[0].id

        if name == names.CONFIG:
            if isinstance(node.value, ast.Name):
                options = [node.value.id]
            elif isinstance(node.value, ast.Tuple):
                options = [n.id for n in node.value.elts]
            self.config = VyperConfig(options)
            return
        elif name == names.INVARIANT:
            # No local specifications allowed before invariants
            self._check_no_local_spec()

            self.invariants.append(node.value)
        elif name == names.GENERAL_POSTCONDITION:
            # No local specifications allowed before general postconditions
            self._check_no_local_spec()

            if self.is_preserves:
                self.transitive_postconditions.append(node.value)
            else:
                self.general_postconditions.append(node.value)
        elif name == names.GENERAL_CHECK:
            # No local specifications allowed before general check
            self._check_no_local_spec()

            self.general_checks.append(node.value)
        elif name == names.POSTCONDITION:
            self.postconditions.append(node.value)
        elif name == names.CHECK:
            self.checks.append(node.value)
        else:
            assert False

    def visit_If(self, node: ast.If):
        # This is a preserves clause, since we replace all preserves clauses with if statements
        # when preprocessing
        if self.is_preserves:
            raise InvalidProgramException(node, 'preserves.in.preserves')

        self.is_preserves = True
        for stmt in node.body:
            self.visit(stmt)
        self.is_preserves = False

    def _decorators(self, node: ast.FunctionDef) -> List[str]:
        return [dec.id for dec in node.decorator_list if isinstance(dec, ast.Name)]

    def visit_FunctionDef(self, node):
        local = LocalProgramBuilder(self.type_builder)
        args, local_vars = local.build(node)
        arg_types = [arg.type for arg in args.values()]
        return_type = None if node.returns is None else self.type_builder.build(node.returns)
        type = FunctionType(arg_types, return_type)
        decs = self._decorators(node)
        function = VyperFunction(node.name, args, local_vars, type,
                                 self.postconditions, self.checks, decs, node)
        self.functions[node.name] = function
        # Reset local specs
        self.postconditions = []
        self.checks = []


class LocalProgramBuilder(ast.NodeVisitor):

    def __init__(self, type_builder: TypeBuilder):
        self.args = {}
        self.local_vars = {}

        self.type_builder = type_builder

    def build(self, node):
        self.visit(node)
        return self.args, self.local_vars

    def visit_arg(self, node):
        arg_name = node.arg
        arg_type = self.type_builder.build(node.annotation)
        var = VyperVar(arg_name, arg_type, node)
        self.args[arg_name] = var

    def visit_AnnAssign(self, node):
        variable_name = node.target.id
        variable_type = self.type_builder.build(node.annotation)
        var = VyperVar(variable_name, variable_type, node)
        self.local_vars[variable_name] = var

    def visit_For(self, node):
        # We ignore these variables as they are added in the type annotator
        self.generic_visit(node)