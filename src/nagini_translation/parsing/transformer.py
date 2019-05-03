"""
Copyright (c) 2019 ETH Zurich
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""

import ast

from typing import List, Dict, Any

from nagini_translation.ast import names
from nagini_translation.errors.translation_exceptions import InvalidProgramException


def transform(ast: ast.Module) -> ast.Module:
    constants_decls, new_ast = ConstantCollector().collect_constants(ast)
    constants = _interpret_constants(constants_decls)
    transformed_ast = ConstantTransformer(constants).visit(new_ast)
    return transformed_ast


def _builtin_constants():
    # The zero address
    name = 'ZERO_ADDRESS'
    value = 0
    node = ast.Num(value)
    return {name: value}, {name: node}


def _interpret_constants(nodes: List[ast.AnnAssign]) -> Dict[str, ast.AST]:
    env, constants = _builtin_constants()
    interpreter = ConstantInterpreter(env)
    for node in nodes:
        name = node.target.id
        value = interpreter.visit(node.value)
        env[name] = value
        constants[name] = ast.parse(f'{value}', mode='eval').body
    
    return constants


class ConstantInterpreter(ast.NodeVisitor):
    """
    Determines the value of all constants in the AST.
    """

    def __init__(self, constants: Dict[str, Any]):
        self.constants = constants

    def visit_BoolOp(self, node: ast.BoolOp):
        operands = [self.visit(v) for v in node.values]
        if isinstance(node.op, ast.And):
            return all(operands)
        elif isinstance(node.op, ast.Or):
            return any(operands)
        
    def visit_BinOp(self, node: ast.BinOp):
        lhs = self.visit(node.left)
        rhs = self.visit(node.right)
        op = node.op
        if isinstance(op, ast.Add):
            return lhs + rhs
        elif isinstance(op, ast.Sub):
            return lhs - rhs
        elif isinstance(op, ast.Mult):
            return lhs * rhs
        elif isinstance(op, ast.Div):
            # Note that contrary to Python Vyper does a floor division
            return lhs // rhs
        elif isinstance(op, ast.Mod):
            return lhs % rhs
        elif isinstance(op, ast.Pow):
            return lhs ** rhs
        else:
            raise InvalidProgramException(node)

    def visit_UnaryOp(self, node: ast.UnaryOp):
        operand = self.visit(node.operand)
        if isinstance(node.op, ast.USub):
            return -operand
        elif isinstance(node.op, ast.Not):
            return not operand
        else:
            raise InvalidProgramException(node)

    def visit_Compare(self, node: ast.Compare):
        lhs = self.visit(node.left)
        rhs = self.visit(node.comparators[0])
        op = self.ops[0]
        if isinstance(op, ast.Eq):
            return lhs == rhs
        elif isinstance(op, ast.NotEq):
            return lhs != rhs
        elif isinstance(op, ast.Lt):
            return lhs < rhs
        elif isinstance(op, ast.LtE):
            return lhs <= rhs
        elif isinstance(op, ast.Gt):
            return lhs > rhs
        elif isinstance(op, ast.GtE):
            return lhs >= rhs
        else:
            raise InvalidProgramException(node)

    def visit_Call(self, node: ast.Call):
        args = [self.visit(arg) for arg in node.args]
        if isinstance(node.func, ast.Name):
            if node.func.id == names.MIN:
                return min(args)
            elif node.func.id == names.MAX:
                return max(args)

        raise InvalidProgramException(node)

    def visit_Num(self, node: ast.Num):
        return node.n
    
    def visit_NameConstant(self, node: ast.NameConstant):
        return node.value

    def visit_Name(self, node: ast.Name):
        return self.constants[node.id]


class ConstantCollector(ast.NodeTransformer):
    """
    Collects constants and deletes their declarations from the AST.
    """

    def __init__(self):
        self.constants = []

    def _is_constant(self, node):
        return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'constant'

    def collect_constants(self, node):
        new_node = self.visit(node)
        return self.constants, new_node

    def visit_AnnAssign(self, node: ast.AnnAssign):
        if self._is_constant(node.annotation):
            self.constants.append(node)
            return None
        else:
            return node

    def visit_FunctionDef(self, node: ast.FunctionDef):
        return node


class ConstantTransformer(ast.NodeTransformer):
    """
    Replaces all constants in the AST by their value.
    """
    
    def __init__(self, constants: Dict[str, ast.AST]):
        self.constants = constants

    def visit_Name(self, node: ast.Name):
        return ast.copy_location(self.constants.get(node.id) or node, node)

    
