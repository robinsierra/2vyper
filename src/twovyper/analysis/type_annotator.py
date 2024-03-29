"""
Copyright (c) 2019 ETH Zurich
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""

from contextlib import contextmanager
from typing import List, Optional, Union

from twovyper.utils import first_index, switch

from twovyper.ast import ast_nodes as ast, names, types
from twovyper.ast.arithmetic import Decimal
from twovyper.ast.types import (
    TypeBuilder, VyperType, MapType, ArrayType, StringType, StructType, AnyStructType, SelfType, ContractType, InterfaceType
)
from twovyper.ast.nodes import VyperProgram, VyperFunction, GhostFunction
from twovyper.ast.visitors import NodeVisitor

from twovyper.exceptions import InvalidProgramException, UnsupportedException


def _check(condition: bool, node: ast.Node, reason_code: str, msg: Optional[str] = None):
    if not condition:
        raise InvalidProgramException(node, reason_code, msg)


def _check_number_of_arguments(node: ast.FunctionCall, *expected: int,
                               allowed_keywords: List[str] = [], required_keywords: List[str] = [],
                               resources: int = 0):
    _check(len(node.args) in expected, node, 'invalid.no.args')
    for kw in node.keywords:
        _check(kw.name in allowed_keywords, node, 'invalid.no.args')

    for kw in required_keywords:
        _check(any(k.name == kw for k in node.keywords), node, 'invalid.no.args')

    if node.resource:
        if resources == 1:
            cond = not isinstance(node.resource, ast.Exchange)
        elif resources == 2:
            cond = isinstance(node.resource, ast.Exchange)
        else:
            cond = False

        _check(cond, node, 'invalid.no.resources')


class TypeAnnotator(NodeVisitor):

    # The type annotator annotates all expression nodes with type information.
    # It works by using the visitor pattern as follows:
    # - Each expression that is visited returns a list of possible types for it (ordered by
    #   priority) and a list of nodes which will have that type, e.g., the literal 5 will return
    #   the types [int128, uint256, address] when visited, and itself as the only node.
    # - Statements simply return None, as they don't have types.
    # - Some operations, e.g., binary operations, have as their result type the same type
    #   as the input type. The 'combine' method combines the input type sets for that.
    # - If the required type is known at some point, 'annotate_expected' can be called with
    #   the expected type as the argument. It then checks that the nodes of the expected type
    #   and annotates all nodes.
    # - If any type can be used, 'annotate' can be called to annotate all nodes with the first
    #   type in the list, i.e., the type with the highest priority.

    def __init__(self, program: VyperProgram):
        type_map = {}
        for name, struct in program.structs.items():
            type_map[name] = struct.type
        for name, contract in program.contracts.items():
            type_map[name] = contract.type

        self.type_builder = TypeBuilder(type_map)

        self.program = program
        self.current_func = None

        self_type = self.program.fields.type
        # Contains the possible types a variable can have
        self.variables = {
            names.BLOCK: [types.BLOCK_TYPE],
            names.CHAIN: [types.CHAIN_TYPE],
            names.TX: [types.TX_TYPE],
            names.MSG: [types.MSG_TYPE],
            names.SELF: [types.VYPER_ADDRESS, self_type],
            names.LOG: [None]
        }

    @contextmanager
    def _function_scope(self, func: Union[VyperFunction, GhostFunction]):
        old_func = self.current_func
        self.current_func = func
        old_variables = self.variables.copy()
        self.variables.update({k: [v.type] for k, v in func.args.items()})

        yield

        self.current_func = old_func
        self.variables = old_variables

    @contextmanager
    def _quantified_vars_scope(self):
        old_variables = self.variables.copy()

        yield

        self.variables = old_variables

    @property
    def method_name(self):
        return 'visit'

    def annotate_program(self):
        for function in self.program.functions.values():
            with self._function_scope(function):
                self.visit(function.node)

                for name, default in function.defaults.items():
                    if default:
                        self.annotate_expected(default, function.args[name].type)

                for post in function.postconditions:
                    self.annotate_expected(post, types.VYPER_BOOL)

                for check in function.checks:
                    self.annotate_expected(check, types.VYPER_BOOL)

                for performs in function.performs:
                    self.annotate(performs)

        for ghost_function in self.program.ghost_function_implementations.values():
            with self._function_scope(ghost_function):
                self.annotate_expected(ghost_function.node.body[0].value, ghost_function.type.return_type)

        for inv in self.program.invariants:
            self.annotate_expected(inv, types.VYPER_BOOL)

        for post in self.program.general_postconditions:
            self.annotate_expected(post, types.VYPER_BOOL)

        for post in self.program.transitive_postconditions:
            self.annotate_expected(post, types.VYPER_BOOL)

        for check in self.program.general_checks:
            self.annotate_expected(check, types.VYPER_BOOL)

    def generic_visit(self, node: ast.Node):
        assert False

    def pass_through(self, node1, node=None):
        types, nodes = self.visit(node1)
        if node is not None:
            nodes.append(node)
        return types, nodes

    def combine(self, node1, node2, node=None, allowed=lambda t: True):
        types1, nodes1 = self.visit(node1)
        types2, nodes2 = self.visit(node2)

        def is_array(t):
            return isinstance(t, ArrayType) and not t.is_strict

        def longest_array(matching, lst):
            try:
                arrays = [t for t in lst if is_array(t) and t.element_type == matching.element_type]
                return max(arrays, key=lambda t: t.size)
            except ValueError:
                raise InvalidProgramException(node if node is not None else node2, 'wrong.type')

        def intersect(l1, l2):
            for e in l1:
                if is_array(e):
                    yield longest_array(e, l2)
                else:
                    for t in l2:
                        if types.matches(e, t):
                            yield e
                        elif types.matches(t, e):
                            yield t

        intersection = list(filter(allowed, intersect(types1, types2)))
        if not intersection:
            raise InvalidProgramException(node if node is not None else node2, 'wrong.type')
        else:
            if node:
                return intersection, [*nodes1, *nodes2, node]
            else:
                return intersection, [*nodes1, *nodes2]

    def annotate(self, node1, node2=None, allowed=lambda t: True):
        if node2 is None:
            combined, nodes = self.visit(node1)
        else:
            combined, nodes = self.combine(node1, node2, allowed=allowed)
        for node in nodes:
            node.type = combined[0]

    def annotate_expected(self, node, expected, orelse=None):
        """
        Checks that node has type `expected` (or matches the predicate `expected`) or, if that isn't the case,
        that is has type `orelse` (or matches the predicate `orelse`).
        """
        tps, nodes = self.visit(node)

        def annotate_nodes(t):
            node.type = t
            for n in nodes:
                n.type = t

        if isinstance(expected, VyperType):
            if any(types.matches(t, expected) for t in tps):
                annotate_nodes(expected)
                return
        else:
            for t in tps:
                if expected(t):
                    annotate_nodes(t)
                    return

        if orelse:
            self.annotate_expected(node, orelse)
        else:
            raise InvalidProgramException(node, 'wrong.type')

    def visit_FunctionDef(self, node: ast.FunctionDef):
        for stmt in node.body:
            self.visit(stmt)

    def visit_Return(self, node: ast.Return):
        if node.value:
            # Interfaces are allowed to just have `pass` as a body instead of a correct return,
            # therefore we don't check for the correct return type.
            if self.program.is_interface():
                self.annotate(node.value)
            else:
                self.annotate_expected(node.value, self.current_func.type.return_type)

    def visit_Assign(self, node: ast.Assign):
        self.annotate(node.target, node.value)

    def visit_AugAssign(self, node: ast.AugAssign):
        self.annotate(node.target, node.value, types.is_numeric)

    def visit_AnnAssign(self, node: ast.AnnAssign):
        # This is a variable declaration so we add it to the type map. Since Vyper
        # doesn't allow shadowing, we can just override the previous value.
        variable_name = node.target.id
        variable_type = self.type_builder.build(node.annotation)
        self.variables[variable_name] = [variable_type]

        if node.value:
            self.annotate(node.target, node.value)
        else:
            self.annotate(node.target)

    def visit_For(self, node: ast.For):
        self.annotate_expected(node.iter, lambda t: isinstance(t, ArrayType))

        # Add the loop variable to the type map
        var_name = node.target.id
        var_type = node.iter.type.element_type
        self.variables[var_name] = [var_type]

        self.annotate_expected(node.target, var_type)
        for stmt in node.body:
            self.visit(stmt)

    def visit_If(self, node: ast.If):
        self.annotate_expected(node.test, types.VYPER_BOOL)
        for stmt in node.body + node.orelse:
            self.visit(stmt)

    def visit_Raise(self, node: ast.Raise):
        if not (isinstance(node.msg, ast.Name) and node.msg.id == names.UNREACHABLE):
            self.annotate(node.msg)

    def visit_Assert(self, node: ast.Assert):
        self.annotate_expected(node.test, types.VYPER_BOOL)

    def visit_ExprStmt(self, node: ast.ExprStmt):
        self.annotate(node.value)

    def visit_Pass(self, node: ast.Pass):
        pass

    def visit_Continue(self, node: ast.Continue):
        pass

    def visit_Break(self, node: ast.Break):
        pass

    def visit_BoolOp(self, node: ast.BoolOp):
        self.annotate_expected(node.left, types.VYPER_BOOL)
        self.annotate_expected(node.right, types.VYPER_BOOL)
        return [types.VYPER_BOOL], [node]

    def visit_Not(self, node: ast.Not):
        self.annotate_expected(node.operand, types.VYPER_BOOL)
        return [types.VYPER_BOOL], [node]

    def visit_ArithmeticOp(self, node: ast.ArithmeticOp):
        return self.combine(node.left, node.right, node, types.is_numeric)

    def visit_UnaryArithmeticOp(self, node: ast.UnaryArithmeticOp):
        return self.pass_through(node.operand, node)

    def visit_IfExpr(self, node: ast.IfExpr):
        self.annotate_expected(node.test, types.VYPER_BOOL)
        return self.combine(node.body, node.orelse, node)

    def visit_Comparison(self, node: ast.Comparison):
        self.annotate(node.left, node.right)
        return [types.VYPER_BOOL], [node]

    def visit_Containment(self, node: ast.Containment):
        self.annotate_expected(node.list, lambda t: isinstance(t, ArrayType))
        self.annotate_expected(node.value, node.list.type.element_type)
        return [types.VYPER_BOOL], [node]

    def visit_Equality(self, node: ast.Equality):
        self.annotate(node.left, node.right)
        return [types.VYPER_BOOL], [node]

    def visit_FunctionCall(self, node: ast.FunctionCall):
        name = node.name

        if node.resource:
            self._visit_resource(node.resource)

        with switch(name) as case:
            if case(names.CONVERT):
                _check_number_of_arguments(node, 2)
                self.annotate(node.args[0])
                ntype = self.type_builder.build(node.args[1])
                return [ntype], [node]
            elif case(names.SUCCESS):
                _check_number_of_arguments(node, 0, 1, allowed_keywords=[names.SUCCESS_IF_NOT])
                return [types.VYPER_BOOL], [node]
            elif case(names.REVERT):
                return [types.VYPER_BOOL], [node]
            elif case(names.FORALL):
                return self._visit_forall(node)
            elif case(names.ACCESSIBLE):
                return self._visit_accessible(node)
            elif case(names.EVENT):
                _check_number_of_arguments(node, 1, 2)
                return self._visit_event(node)
            elif case(names.RANGE):
                _check_number_of_arguments(node, 1, 2)
                return self._visit_range(node)
            elif case(names.MIN) or case(names.MAX):
                _check_number_of_arguments(node, 2)
                return self.combine(node.args[0], node.args[1], node, types.is_numeric)
            elif case(names.ADDMOD) or case(names.MULMOD):
                _check_number_of_arguments(node, 3)
                for arg in node.args:
                    self.annotate_expected(arg, types.VYPER_UINT256)
                return [types.VYPER_UINT256], [node]
            elif case(names.SQRT):
                _check_number_of_arguments(node, 1)
                self.annotate_expected(node.args[0], types.VYPER_DECIMAL)
                return [types.VYPER_DECIMAL], [node]
            elif case(names.SHIFT):
                _check_number_of_arguments(node, 2)
                self.annotate_expected(node.args[0], types.VYPER_UINT256)
                self.annotate_expected(node.args[1], types.VYPER_INT128)
            elif case(names.BITWISE_NOT):
                _check_number_of_arguments(node, 1)
                self.annotate_expected(node.args[0], types.VYPER_UINT256)
                return [types.VYPER_UINT256], [node]
            elif case(names.BITWISE_AND) or case(names.BITWISE_OR) or case(names.BITWISE_XOR):
                _check_number_of_arguments(node, 2)
                self.annotate_expected(node.args[0], types.VYPER_UINT256)
                self.annotate_expected(node.args[1], types.VYPER_UINT256)
                return [types.VYPER_UINT256], [node]
            elif case(names.OLD) or case(names.ISSUED):
                _check_number_of_arguments(node, 1)
                return self.pass_through(node.args[0], node)
            elif case(names.INDEPENDENT):
                _check_number_of_arguments(node, 2)
                self.annotate(node.args[0])
                self.annotate(node.args[1])
                return [types.VYPER_BOOL], [node]
            elif case(names.REORDER_INDEPENDENT):
                _check_number_of_arguments(node, 1)
                self.annotate(node.args[0])
                return [types.VYPER_BOOL], [node]
            elif case(names.FLOOR) or case(names.CEIL):
                _check_number_of_arguments(node, 1)
                self.annotate_expected(node.args[0], types.VYPER_DECIMAL)
                return [types.VYPER_INT128], [node]
            elif case(names.LEN):
                _check_number_of_arguments(node, 1)
                self.annotate_expected(node.args[0], lambda t: isinstance(t, types.ArrayType))
                return [types.VYPER_INT128], [node]
            elif case(names.STORAGE):
                _check_number_of_arguments(node, 1)
                self.annotate_expected(node.args[0], types.VYPER_ADDRESS)
                # We know that storage(self) has the self-type
                if isinstance(node.args[0], ast.Name) and node.args[0].id == names.SELF:
                    return [self.program.type, AnyStructType()], [node]
                # Otherwise it is just some struct, which we don't know anything about
                else:
                    return [AnyStructType()], [node]
            elif case(names.ASSERT_MODIFIABLE):
                _check_number_of_arguments(node, 1)
                self.annotate_expected(node.args[0], types.VYPER_BOOL)
                return [None], [node]
            elif case(names.SEND):
                _check_number_of_arguments(node, 2)
                self.annotate_expected(node.args[0], types.VYPER_ADDRESS)
                self.annotate_expected(node.args[1], types.VYPER_WEI_VALUE)
                return [None], [node]
            elif case(names.SELFDESTRUCT):
                _check_number_of_arguments(node, 0, 1)
                if node.args:
                    # The selfdestruct Vyper function
                    self.annotate_expected(node.args[0], types.VYPER_ADDRESS)
                    return [None], [node]
                else:
                    # The selfdestruct verification function
                    return [types.VYPER_BOOL], [node]
            elif case(names.CLEAR):
                # Not type checking is needed here as clear may only occur in actual Vyper code
                self.annotate(node.args[0])
                return [None], [node]
            elif case(names.RAW_CALL):
                # No type checking is needed here as raw_call may only occur in actual Vyper code
                for arg in node.args:
                    self.annotate(arg)
                for kwarg in node.keywords:
                    self.annotate(kwarg.value)

                idx = first_index(lambda n: n.name == names.RAW_CALL_OUTSIZE, node.keywords)
                size = node.keywords[idx].value.n
                return [ArrayType(types.VYPER_BYTE, size, False)], [node]
            elif case(names.RAW_LOG):
                _check_number_of_arguments(node, 2)
                self.annotate_expected(node.args[0], ArrayType(types.VYPER_BYTES32, 4, False))
                self.annotate_expected(node.args[1], types.is_bytes_array)
                return [None], [node]
            elif case(names.CREATE_FORWARDER_TO):
                _check_number_of_arguments(node, 1, allowed_keywords=[names.CREATE_FORWARDER_TO_VALUE])
                self.annotate_expected(node.args[0], types.VYPER_ADDRESS)
                if node.keywords:
                    self.annotate_expected(node.keywords[0].value, types.VYPER_WEI_VALUE)
                return [types.VYPER_ADDRESS], [node]
            elif case(names.AS_WEI_VALUE):
                _check_number_of_arguments(node, 2)
                self.annotate_expected(node.args[0], types.is_integer)
                unit = node.args[1]
                unit_exists = lambda u: next((v for k, v in names.ETHER_UNITS.items() if u in k), False)
                _check(isinstance(unit, ast.Str) and unit_exists(unit.s), node, 'invalid.unit')
                return [types.VYPER_WEI_VALUE], [node]
            elif case(names.AS_UNITLESS_NUMBER):
                _check_number_of_arguments(node, 1)
                # We ignore units completely, therefore the type stays the same
                return self.pass_through(node.args[0], node)
            elif case(names.CONCAT):
                _check(node.args, node, 'invalid.no.args')

                for arg in node.args:
                    self.annotate_expected(arg, types.is_bytes_array)

                size = sum(arg.type.size for arg in node.args)
                return [ArrayType(node.args[0].type.element_type, size, False)], [node]
            elif case(names.KECCAK256) or case(names.SHA256):
                _check_number_of_arguments(node, 1)
                self.annotate_expected(node.args[0], types.is_bytes_array)
                return [types.VYPER_BYTES32], [node]
            elif case(names.BLOCKHASH):
                _check_number_of_arguments(node, 1)

                self.annotate_expected(node.args[0], types.VYPER_UINT256)
                return [types.VYPER_BYTES32], [node]
            elif case(names.METHOD_ID):
                _check_number_of_arguments(node, 2)

                self.annotate_expected(node.args[0], lambda t: isinstance(t, StringType))
                ntype = self.type_builder.build(node.args[1])
                is_bytes32 = lambda t: t == types.VYPER_BYTES32
                is_bytes4 = lambda t: isinstance(ntype, ArrayType) and ntype.element_type == types.VYPER_BYTE and ntype.size == 4
                _check(is_bytes32(ntype) or is_bytes4(ntype), node.args[1], 'invalid.method_id')
                return [ntype], [node]
            elif case(names.ECRECOVER):
                _check_number_of_arguments(node, 4)
                self.annotate_expected(node.args[0], types.VYPER_BYTES32)
                self.annotate_expected(node.args[1], types.VYPER_UINT256)
                self.annotate_expected(node.args[2], types.VYPER_UINT256)
                self.annotate_expected(node.args[3], types.VYPER_UINT256)
                return [types.VYPER_ADDRESS], [node]
            elif case(names.ECADD) or case(names.ECMUL):
                _check_number_of_arguments(node, 2)
                int_pair = ArrayType(types.VYPER_UINT256, 2)
                self.annotate_expected(node.args[0], int_pair)
                arg_type = int_pair if case(names.ECADD) else types.VYPER_UINT256
                self.annotate_expected(node.args[1], arg_type)
                return [int_pair], [node]
            elif case(names.IMPLIES):
                _check_number_of_arguments(node, 2)

                self.annotate_expected(node.args[0], types.VYPER_BOOL)
                self.annotate_expected(node.args[1], types.VYPER_BOOL)
                return [types.VYPER_BOOL], [node]
            elif case(names.RESULT):
                _check_number_of_arguments(node, 0)
                return [self.current_func.type.return_type], [node]
            elif case(names.SUM):
                _check_number_of_arguments(node, 1)

                def is_numeric_map(t):
                    return isinstance(t, types.MapType) and types.is_integer(t.value_type)

                self.annotate_expected(node.args[0], is_numeric_map)
                return [node.args[0].type.value_type], [node]
            elif case(names.SENT) or case(names.RECEIVED) or case(names.ALLOCATED):
                _check_number_of_arguments(node, 0, 1, resources=1 if case(names.ALLOCATED) else 0)

                if not node.args:
                    type = types.MapType(types.VYPER_ADDRESS, types.VYPER_WEI_VALUE)
                    return [type], [node]
                else:
                    self.annotate_expected(node.args[0], types.VYPER_ADDRESS)
                    return [types.VYPER_WEI_VALUE], [node]
            elif case(names.LOCKED):
                _check_number_of_arguments(node, 1)
                lock = node.args[0]
                _check(isinstance(lock, ast.Str) and lock.s in self.program.nonreentrant_keys(), node, 'invalid.lock')
                return [types.VYPER_BOOL], [node]
            elif case(names.OVERFLOW) or case(names.OUT_OF_GAS):
                _check_number_of_arguments(node, 0)
                return [types.VYPER_BOOL], [node]
            elif case(names.FAILED):
                _check_number_of_arguments(node, 1)
                self.annotate_expected(node.args[0], types.VYPER_ADDRESS)
                return [types.VYPER_BOOL], [node]
            elif case(names.IMPLEMENTS):
                _check_number_of_arguments(node, 2)
                address = node.args[0]
                interface = node.args[1]
                is_interface = isinstance(interface, ast.Name) and interface.id in self.program.interfaces
                _check(is_interface, node, 'invalid.interface')
                self.annotate_expected(address, types.VYPER_ADDRESS)
                return [types.VYPER_BOOL], [node]
            elif case(names.REALLOCATE):
                keywords = [names.REALLOCATE_TO, names.REALLOCATE_ACTING_FOR]
                required = [names.REALLOCATE_TO]
                _check_number_of_arguments(node, 1, allowed_keywords=keywords, required_keywords=required, resources=1)
                self.annotate_expected(node.args[0], types.VYPER_WEI_VALUE)
                self.annotate_expected(node.keywords[0].value, types.VYPER_ADDRESS)
                for kw in node.keywords:
                    self.annotate_expected(kw.value, types.VYPER_ADDRESS)
                return [None], [node]
            elif case(names.FOREACH):
                return self._visit_foreach(node)
            elif case(names.OFFER):
                keywords = {
                    names.OFFER_TO: types.VYPER_ADDRESS,
                    names.OFFER_ACTING_FOR: types.VYPER_ADDRESS,
                    names.OFFER_TIMES: types.VYPER_UINT256
                }
                required = [names.OFFER_TO, names.OFFER_TIMES]
                _check_number_of_arguments(node, 2, allowed_keywords=keywords.keys(), required_keywords=required, resources=2)
                self.annotate_expected(node.args[0], types.VYPER_WEI_VALUE)
                self.annotate_expected(node.args[1], types.VYPER_WEI_VALUE)
                for kw in node.keywords:
                    self.annotate_expected(kw.value, keywords[kw.name])
                return [None], [node]
            elif case(names.REVOKE):
                keywords = {
                    names.REVOKE_TO: types.VYPER_ADDRESS,
                    names.REVOKE_ACTING_FOR: types.VYPER_ADDRESS
                }
                required = [names.REVOKE_TO]
                _check_number_of_arguments(node, 2, allowed_keywords=keywords.keys(), required_keywords=required, resources=2)
                self.annotate_expected(node.args[0], types.VYPER_WEI_VALUE)
                self.annotate_expected(node.args[1], types.VYPER_WEI_VALUE)
                for kw in node.keywords:
                    self.annotate_expected(kw.value, keywords[kw.name])
                return [None], [node]
            elif case(names.EXCHANGE):
                keywords = [names.EXCHANGE_TIMES]
                _check_number_of_arguments(node, 4, allowed_keywords=keywords, required_keywords=keywords, resources=2)
                self.annotate_expected(node.args[0], types.VYPER_WEI_VALUE)
                self.annotate_expected(node.args[1], types.VYPER_WEI_VALUE)
                self.annotate_expected(node.args[2], types.VYPER_ADDRESS)
                self.annotate_expected(node.args[3], types.VYPER_ADDRESS)
                self.annotate_expected(node.keywords[0].value, types.VYPER_UINT256)
                return [None], [node]
            elif case(names.CREATE):
                msg = "Ether cannot be created."
                is_wei = not node.resource or (isinstance(node.resource, ast.Name) and node.resource.id == names.WEI)
                _check(not is_wei, node, 'ether.change', msg)
                keywords = {
                    names.CREATE_TO: types.VYPER_ADDRESS,
                    names.CREATE_ACTING_FOR: types.VYPER_ADDRESS
                }
                _check_number_of_arguments(node, 1, allowed_keywords=keywords.keys(), resources=1)
                self.annotate_expected(node.args[0], types.VYPER_UINT256)
                for kw in node.keywords:
                    self.annotate_expected(kw.value, keywords[kw.name])
                return [None], [node]
            elif case(names.DESTROY):
                msg = "Ether cannot be destroyed."
                is_wei = not node.resource or (isinstance(node.resource, ast.Name) and node.resource.id == names.WEI)
                _check(not is_wei, node, 'ether.change', msg)
                keywords = [names.DESTROY_ACTING_FOR]
                _check_number_of_arguments(node, 1, resources=1, allowed_keywords=keywords)
                self.annotate_expected(node.args[0], types.VYPER_UINT256)
                for kw in node.keywords:
                    self.annotate_expected(kw.value, types.VYPER_ADDRESS)
                return [None], [node]
            elif case(names.TRUST):
                keywords = [names.TRUST_ACTING_FOR]
                _check_number_of_arguments(node, 2, allowed_keywords=keywords)
                self.annotate_expected(node.args[0], types.VYPER_ADDRESS)
                self.annotate_expected(node.args[1], types.VYPER_BOOL)
                for kw in node.keywords:
                    self.annotate_expected(kw.value, types.VYPER_ADDRESS)
                return [None], [node]
            elif case(names.OFFERED):
                _check_number_of_arguments(node, 4, resources=2)
                self.annotate_expected(node.args[0], types.VYPER_WEI_VALUE)
                self.annotate_expected(node.args[1], types.VYPER_WEI_VALUE)
                self.annotate_expected(node.args[2], types.VYPER_ADDRESS)
                self.annotate_expected(node.args[3], types.VYPER_ADDRESS)
                return [types.VYPER_INT128], [node]
            elif case(names.TRUSTED):
                keywords = [names.TRUSTED_BY]
                _check_number_of_arguments(node, 1, allowed_keywords=keywords, required_keywords=keywords)
                self.annotate_expected(node.args[0], types.VYPER_ADDRESS)
                self.annotate_expected(node.keywords[0].value, types.VYPER_ADDRESS)
                return [types.VYPER_BOOL], [node]
            elif len(node.args) == 1 and isinstance(node.args[0], ast.Dict):
                # This is a struct inizializer
                _check_number_of_arguments(node, 1)

                return self._visit_struct_init(node)
            elif name in self.program.contracts:
                # This is a contract initializer
                _check_number_of_arguments(node, 1)

                self.annotate_expected(node.args[0], types.VYPER_ADDRESS)
                return [self.program.contracts[name].type], [node]
            elif name in self.program.interfaces:
                # This is an interface initializer
                _check_number_of_arguments(node, 1)

                self.annotate_expected(node.args[0], types.VYPER_ADDRESS)
                return [self.program.interfaces[name].type], [node]
            elif name in self.program.ghost_functions:
                function = self.program.ghost_functions[name]
                _check_number_of_arguments(node, len(function.args) + 1)

                arg_types = [types.VYPER_ADDRESS, *[arg.type for arg in function.args.values()]]
                for type, arg in zip(arg_types, node.args):
                    self.annotate_expected(arg, type)

                return [function.type.return_type], [node]
            else:
                raise UnsupportedException(node, "Unsupported function call")

    def visit_ReceiverCall(self, node: ast.ReceiverCall):
        def expected(t):
            is_self_call = isinstance(t, SelfType)
            is_external_call = isinstance(t, (ContractType, InterfaceType))
            is_log = t is None
            return is_self_call or is_external_call or is_log

        self.annotate_expected(node.receiver, expected)
        receiver_type = node.receiver.type

        # We don't have to type check calls as they are not allowed in specifications
        for arg in node.args:
            self.annotate(arg)

        for kw in node.keywords:
            self.annotate(kw.value)

        # A logging call
        if not receiver_type:
            return [None], [node]

        # A self call
        if isinstance(receiver_type, SelfType):
            function = self.program.functions[node.name]
            return [function.type.return_type], [node]
        # A contract call
        elif isinstance(receiver_type, ContractType):
            return [receiver_type.function_types[node.name].return_type], [node]
        elif isinstance(receiver_type, InterfaceType):
            interface = self.program.interfaces[receiver_type.name]
            function = interface.functions[node.name]
            return [function.type.return_type], [node]

    def _visit_resource(self, node: ast.Node):
        if isinstance(node, ast.Name):
            resource = self.program.resources.get(node.id)
            args = []
        elif isinstance(node, ast.FunctionCall) and node.name == names.CREATOR:
            self._visit_resource(node.args[0])
            return
        elif isinstance(node, ast.FunctionCall):
            resource = self.program.resources.get(node.name)
            args = node.args
        elif isinstance(node, ast.Exchange):
            self._visit_resource(node.left)
            self._visit_resource(node.right)
            return
        else:
            assert False

        if not resource or len(args) != len(resource.type.member_types):
            raise InvalidProgramException(node, 'invalid.resource')

        node.type = resource.type

        for type, arg in zip(resource.type.member_types.values(), args):
            self.annotate_expected(arg, type)

    def _add_quantified_vars(self, var_decls: ast.Dict):
        vars_types = zip(var_decls.keys, var_decls.values)
        for name, type_annotation in vars_types:
            type = self.type_builder.build(type_annotation)
            self.variables[name.id] = [type]
            name.type = type

    def _visit_forall(self, node: ast.FunctionCall):
        with self._quantified_vars_scope():
            # Add the quantified variables {<x1>: <t1>, <x2>: <t2>, ...} to the
            # variable map
            self._add_quantified_vars(node.args[0])

            # Triggers can have any type
            for arg in node.args[1:len(node.args) - 1]:
                self.annotate(arg)

            # The quantified expression is always a Boolean
            self.annotate_expected(node.args[len(node.args) - 1], types.VYPER_BOOL)

        return [types.VYPER_BOOL], [node]

    def _visit_foreach(self, node: ast.FunctionCall):
        with self._quantified_vars_scope():
            # Add the quantified variables {<x1>: <t1>, <x2>: <t2>, ...} to the
            # variable map
            self._add_quantified_vars(node.args[0])

            # Annotate the body
            self.annotate(node.args[1])

        return [None], [node]

    def _visit_accessible(self, node: ast.FunctionCall):
        self.annotate_expected(node.args[0], types.VYPER_ADDRESS)
        self.annotate_expected(node.args[1], types.VYPER_WEI_VALUE)

        if len(node.args) == 3:
            function = self.program.functions[node.args[2].name]
            for arg, type in zip(node.args[2].args, function.type.arg_types):
                self.annotate_expected(arg, type)

        return [types.VYPER_BOOL], [node]

    def _visit_event(self, node: ast.FunctionCall):
        event_name = node.args[0].name
        event_type = self.program.events[event_name].type

        for arg, type in zip(node.args[0].args, event_type.arg_types):
            self.annotate_expected(arg, type)

        if len(node.args) == 2:
            self.annotate_expected(node.args[1], types.VYPER_UINT256)

        return [types.VYPER_BOOL], [node]

    def _visit_struct_init(self, node: ast.FunctionCall):
        ntype = self.program.structs[node.name].type

        for key, value in zip(node.args[0].keys, node.args[0].values):
            type = ntype.member_types[key.id]
            self.annotate_expected(value, type)

        return [ntype], [node]

    def _visit_range(self, node: ast.FunctionCall):
        self.annotate_expected(node.args[0], types.VYPER_INT128)

        if len(node.args) == 1:
            # A range expression of the form 'range(n)' where 'n' is a constant
            size = node.args[0].n
        elif len(node.args) == 2:
            # A range expression of the form 'range(x, x + n)' where 'n' is a constant
            self.annotate_expected(node.args[1], types.VYPER_INT128)
            size = node.args[1].right.n
        else:
            raise InvalidProgramException(node, 'invalid.range')

        return [ArrayType(types.VYPER_INT128, size, True)], [node]

    def visit_Bytes(self, node: ast.Bytes):
        # Bytes could either be non-strict or (if it has length 32) strict
        non_strict = types.ArrayType(types.VYPER_BYTE, len(node.s), False)
        if len(node.s) == 32:
            return [non_strict, types.VYPER_BYTES32], [node]
        else:
            return [non_strict], [node]

    def visit_Str(self, node: ast.Str):
        string_bytes = bytes(node.s, 'utf-8')
        ntype = StringType(len(string_bytes))
        return [ntype], [node]

    # Sets occur in trigger expressions
    def visit_Set(self, node: ast.Set):
        for elem in node.elements:
            # Triggers can have any type
            self.annotate(elem)
        return [None], [node]

    def visit_Num(self, node: ast.Num):
        if isinstance(node.n, int):
            if node.n >= 0:
                tps = [types.VYPER_INT128,
                       types.VYPER_UINT256,
                       types.VYPER_ADDRESS,
                       types.VYPER_BYTES32]
            else:
                tps = [types.VYPER_INT128]
            nodes = [node]
            return tps, nodes
        elif isinstance(node.n, Decimal):
            return [types.VYPER_DECIMAL], [node]
        else:
            assert False

    def visit_Bool(self, node: ast.Bool):
        return [types.VYPER_BOOL], [node]

    def visit_Attribute(self, node: ast.Attribute):
        self.annotate_expected(node.value, lambda t: isinstance(t, StructType), types.VYPER_ADDRESS)
        struct_type = node.value.type if isinstance(node.value.type, StructType) else types.AddressType()
        ntype = struct_type.member_types.get(node.attr)
        if not ntype:
            raise InvalidProgramException(node, 'invalid.storage.var')
        return [ntype], [node]

    def visit_Subscript(self, node: ast.Subscript):
        self.annotate_expected(node.value, lambda t: isinstance(t, (ArrayType, MapType)))
        if isinstance(node.value.type, MapType):
            key_type = node.value.type.key_type
            self.annotate_expected(node.index, key_type)
            ntype = node.value.type.value_type
        elif isinstance(node.value.type, ArrayType):
            self.annotate_expected(node.index, types.is_integer)
            ntype = node.value.type.element_type
        else:
            assert False

        return [ntype], [node]

    def visit_Name(self, node: ast.Name):
        _check(node.id in self.variables, node, 'invalid.local.var')
        return self.variables[node.id], [node]

    def visit_List(self, node: ast.List):
        # Vyper guarantees that size > 0
        size = len(node.elements)
        for e in node.elements:
            self.annotate(e)
        element_types = [e.type for e in node.elements]
        for element_type in element_types:
            if element_type != types.VYPER_INT128:
                return [types.ArrayType(element_type, size)], [node]
        else:
            return [types.ArrayType(types.VYPER_INT128, size)], [node]
