import ast
import mypy

from abc import ABCMeta
from collections import OrderedDict
from py2viper_contracts.io import BUILTIN_IO_OPERATIONS
from py2viper_translation.lib.constants import (
    END_LABEL,
    ERROR_NAME,
    INT_TYPE,
    INTERNAL_NAMES,
    PRIMITIVES,
    RESULT_NAME,
    VIPER_KEYWORDS,
)
from py2viper_translation.lib.io_checkers import IOOperationBodyChecker
from py2viper_translation.lib.typedefs import Expr
from py2viper_translation.lib.typeinfo import TypeInfo
from py2viper_translation.lib.util import InvalidProgramException
from typing import List, Optional, Set


class PythonScope:
    """
    Represents a namespace/scope in Python
    """
    def __init__(self, sil_names: List[str], superscope: 'PythonScope'):
        self.sil_names = sil_names
        self.superscope = superscope

    def contains_name(self, name: str) -> bool:
        result = name in self.sil_names
        if self.superscope is not None:
            result = result or self.superscope.contains_name(name)
        return result

    def get_fresh_name(self, name: str) -> str:
        if self.contains_name(name):
            counter = 0
            new_name = name + '_' + str(counter)
            while self.contains_name(new_name):
                counter += 1
                new_name = name + '_' + str(counter)
            self.sil_names.append(new_name)
            return new_name
        else:
            self.sil_names.append(name)
            return name

    def get_scope_prefix(self) -> List[str]:
        if self.superscope is None:
            return [self.name]
        else:
            return self.superscope.get_scope_prefix() + [self.name]

    def get_program(self) -> 'PythonProgram':
        if self.superscope is not None:
            return self.superscope.get_program()
        else:
            return self


class PythonProgram(PythonScope):
    def __init__(self, types: TypeInfo,
                 node_factory: 'ProgramNodeFactory') -> None:
        super().__init__(VIPER_KEYWORDS + INTERNAL_NAMES, None)
        self.classes = OrderedDict()
        self.functions = OrderedDict()
        self.methods = OrderedDict()
        self.predicates = OrderedDict()
        self.io_operations = OrderedDict()
        self.global_vars = OrderedDict()
        self.types = types
        for primitive in PRIMITIVES:
            self.classes[primitive] = node_factory.create_python_class(
                primitive, self, node_factory)

    def process(self, translator: 'Translator') -> None:
        for name, cls in self.classes.items():
            cls.process(self.get_fresh_name(name), translator)
        for name, function in self.functions.items():
            function.process(self.get_fresh_name(name), translator)
        for name, method in self.methods.items():
            method.process(self.get_fresh_name(name), translator)
        for name, predicate in self.predicates.items():
            predicate.process(self.get_fresh_name(name), translator)
        for name, var in self.global_vars.items():
            var.process(self.get_fresh_name(name), translator)
        for name, operation in self.io_operations.items():
            operation.process(self.get_fresh_name(name), translator, self)

    def get_scope_prefix(self) -> List[str]:
        return []

    def get_func_or_method(self, name: str) -> 'PythonMethod':
        if name in self.functions:
            return self.functions[name]
        else:
            return self.methods[name]


class PythonNode:
    def __init__(self, name: str, node=None):
        self.node = node
        self.name = name
        self.sil_name = None


class PythonType(metaclass=ABCMeta):
    """
    Abstract superclass of all kinds python types.
    """
    pass


class PythonClass(PythonType, PythonNode, PythonScope):
    """
    Represents a class in the Python program.
    """

    def __init__(self, name: str, superscope: PythonScope,
                 node_factory: 'ProgramNodeFactory', node: ast.AST = None,
                 superclass: 'PythonClass' = None, interface=False):
        """
        :param superscope: The scope, usually program, this belongs to.
        :param interface: True iff the class implementation is provided in
        native Silver.
        """
        PythonNode.__init__(self, name, node)
        PythonScope.__init__(self, VIPER_KEYWORDS + INTERNAL_NAMES, superscope)
        self.node_factory = node_factory
        self.superclass = superclass
        self.functions = OrderedDict()
        self.methods = OrderedDict()
        self.predicates = OrderedDict()
        self.fields = OrderedDict()
        self.type = None  # infer, domain type
        self.interface = interface
        self.defined = False

    def get_all_methods(self) -> Set['PythonMethod']:
        result = set()
        if self.superclass:
            result |= self.superclass.get_all_methods()
        result |= set(self.methods.keys())
        return result

    def add_field(self, name: str, node: ast.AST,
                  type: 'PythonClass') -> 'PythonField':
        """
        Adds a field with the given name and type if it doesn't exist yet in
        this class.
        """
        if name in self.fields:
            field = self.fields[name]
            assert field.type == type
        else:
            field = self.node_factory.create_python_field(name, node,
                                                          type, self)
            self.fields[name] = field
        return field

    def get_field(self, name: str) -> Optional['PythonField']:
        """
        Returns the field with the given name in this class or a superclass.
        """
        if name in self.fields:
            return self.fields[name]
        elif self.superclass is not None:
            return self.superclass.get_field(name)
        else:
            return None

    def get_method(self, name: str) -> Optional['PythonMethod']:
        """
        Returns the method with the given name in this class or a superclass.
        """
        if name in self.methods:
            return self.methods[name]
        elif self.superclass is not None:
            return self.superclass.get_method(name)
        else:
            return None

    def get_function(self, name: str) -> Optional['PythonMethod']:
        """
        Returns the function with the given name in this class or a superclass.
        """
        if name in self.functions:
            return self.functions[name]
        elif self.superclass is not None:
            return self.superclass.get_function(name)
        else:
            return None

    def get_func_or_method(self, name: str) -> Optional['PythonMethod']:
        """
        Returns the function or method with the given name in this class or a
        superclass.
        """
        if self.get_function(name) is not None:
            return self.get_function(name)
        else:
            return self.get_method(name)

    def get_predicate(self, name: str) -> Optional['PythonMethod']:
        """
        Returns the predicate with the given name in this class or a superclass.
        """
        if name in self.predicates:
            return self.predicates[name]
        elif self.superclass is not None:
            return self.superclass.get_predicate(name)
        else:
            return None

    def get_all_fields(self) -> List['PythonField']:
        fields = []
        cls = self
        while cls is not None:
            for field in cls.fields.values():
                if field.inherited is None:
                    fields.append(field)
            cls = cls.superclass

        return fields

    def get_all_sil_fields(self) -> List['silver.ast.Field']:
        """
        Returns a list of fields defined in the given class or its superclasses.
        """
        fields = []
        cls = self
        while cls is not None:
            for field in cls.fields.values():
                if field.inherited is None:
                    fields.append(field.sil_field)
            cls = cls.superclass

        return fields

    def process(self, sil_name: str, translator: 'Translator') -> None:
        """
        Creates fresh Silver names for all class members and initializes all
        of them.
        """
        self.sil_name = sil_name
        for name, function in self.functions.items():
            func_name = self.name + '_' + name
            function.process(self.get_fresh_name(func_name), translator)
        for name, method in self.methods.items():
            method_name = self.name + '_' + name
            method.process(self.get_fresh_name(method_name), translator)
        for name, predicate in self.predicates.items():
            pred_name = self.name + '_' + name
            predicate.process(self.get_fresh_name(pred_name), translator)
        for name, field in self.fields.items():
            field_name = self.name + '_' + name
            field.process(self.get_fresh_name(field_name))

    def issubtype(self, cls: 'PythonClass') -> bool:
        if cls is self:
            return True
        if self.superclass is None:
            return False
        return self.superclass.issubtype(cls)


class GenericType(PythonType):
    """
    Represents a specific instantiation of a generic type, e.g. list[int].
    Provides access to the type arguments (in this case int) and otherwise
    behaves like the underlying PythonClass (in this case list).
    """

    def __init__(self, name: str, program: PythonProgram,
                 args: List[PythonType]) -> None:
        self.name = name
        self.program = program
        self.cls = self.program.classes[self.name]
        self.type_args = args
        self.exact_length = True

    def get_class(self) -> PythonClass:
        return self.cls

    def get_program(self) -> 'PythonProgram':
        return self.program

    @property
    def sil_name(self) -> str:
        return self.get_class().sil_name

    @property
    def superclass(self) -> PythonClass:
        return self.get_class().superclass

    def get_field(self, name: str) -> Optional['PythonField']:
        """
        Returns the field with the given name in this class or a superclass.
        """
        return self.get_class().get_field(name)

    def get_method(self, name: str) -> Optional['PythonMethod']:
        """
        Returns the method with the given name in this class or a superclass.
        """
        return self.get_class().get_method(name)

    def get_function(self, name: str) -> Optional['PythonMethod']:
        """
        Returns the function with the given name in this class or a superclass.
        """
        return self.get_class().get_function(name)

    def get_func_or_method(self, name: str) -> Optional['PythonMethod']:
        """
        Returns the function or method with the given name in this class or a
        superclass.
        """
        return self.get_class().get_func_or_method(name)

    def get_predicate(self, name: str) -> Optional['PythonMethod']:
        """
        Returns the predicate with the given name in this class or a superclass.
        """
        return self.get_class().get_predicate(name)


class PythonMethod(PythonNode, PythonScope):
    """
    Represents a Python function which may be pure or impure, belong
    to a class or not
    """

    def __init__(self, name: str, node: ast.AST, cls: PythonClass,
                 superscope: PythonScope,
                 pure: bool, contract_only: bool,
                 node_factory: 'ProgramNodeFactory',
                 interface: bool = False):
        """
        :param cls: Class this method belongs to, if any.
        :param superscope: The scope (class or program) this method belongs to
        :param pure: True iff ir's a pure function, not an impure method
        :param contract_only: True iff we're not generating the method's
        implementation, just its contract
        :param interface: True iff the method implementation is provided in
        native Silver.
        """
        PythonNode.__init__(self, name, node)
        PythonScope.__init__(self, VIPER_KEYWORDS + INTERNAL_NAMES +
                             [RESULT_NAME, ERROR_NAME, END_LABEL],
                             superscope)
        if cls is not None:
            if not isinstance(cls, PythonClass):
                raise Exception(cls)
        self.cls = cls
        self.overrides = None  # infer
        self._locals = OrderedDict()  # direct
        self._args = OrderedDict()  # direct
        self._special_vars = OrderedDict()  # direct
        self._io_existential_vars = OrderedDict()
        self._nargs = -1  # direct
        self.var_arg = None   # direct
        self.kw_arg = None  # direct
        self.type = None  # infer
        self.generic_type = -1
        self.result = None  # infer
        self.error_var = None  # infer
        self.declared_exceptions = OrderedDict()  # direct
        self.precondition = []
        self.postcondition = []
        self.try_blocks = []  # direct
        self.pure = pure
        self.predicate = False
        self.contract_only = contract_only
        self.interface = interface
        self.node_factory = node_factory
        self.labels = [END_LABEL]

    def process(self, sil_name: str, translator: 'Translator') -> None:
        """
        Creates fresh Silver names for all parameters and initializes them,
        same for local variables. Also sets the method type and
        checks if this method overrides one from a superclass,
        """
        self.sil_name = sil_name
        for name, arg in self.args.items():
            arg.process(self.get_fresh_name(name), translator)
        if self.var_arg:
            self.var_arg.process(self.get_fresh_name(self.var_arg.name),
                                 translator)
        if self.kw_arg:
            self.kw_arg.process(self.get_fresh_name(self.kw_arg.name),
                                translator)
        if self.interface:
            return
        func_type = self.get_program().types.get_func_type(
            self.get_scope_prefix())
        if self.type is not None:
            self.result = self.node_factory.create_python_var(RESULT_NAME, None,
                                                              self.type)
            self.result.process(RESULT_NAME, translator)
        if self.cls is not None and self.cls.superclass is not None:
            if self.predicate:
                self.overrides = self.cls.superclass.get_predicate(self.name)
            else:
                self.overrides = self.cls.superclass.get_func_or_method(
                    self.name)
        for local in self.locals:
            self.locals[local].process(self.get_fresh_name(local), translator)
        for name in self.special_vars:
            self.special_vars[name].process(self.get_fresh_name(name), translator)
        for try_block in self.try_blocks:
            try_block.process(translator)

    @property
    def nargs(self) -> int:
        if self._nargs == -1:
            return len(self.args)
        else:
            return self._nargs

    @nargs.setter
    def nargs(self, nargs: int) -> None:
        self._nargs = nargs

    @property
    def args(self) -> OrderedDict:
        # TODO(shitz): Should make this return an immutable copy.
        return self._args

    def add_arg(self, name: str, arg: 'PythonVar'):
        self._args[name] = arg

    @property
    def locals(self) -> OrderedDict:
        # TODO(shitz): Should make this return an immutable copy.
        return self._locals

    def add_local(self, name: str, local: 'PythonVar'):
        self._locals[name] = local

    @property
    def special_vars(self) -> OrderedDict:
        return self._special_vars

    @property
    def io_existential_vars(self) -> OrderedDict:
        """
        IO existential variables are variables defined by using
        ``IOExists`` construct.
        """
        return self._io_existential_vars

    def get_variable(self, name: str) -> Optional['PythonVar']:
        """
        Returns the variable (local variable or method parameter) with the
        given name.
        """
        if name in self.locals:
            return self.locals[name]
        elif name in self.args:
            return self.args[name]
        elif name in self.special_vars:
            return self.special_vars[name]
        elif name in self.io_existential_vars:
            return self.io_existential_vars[name]
        elif self.var_arg and self.var_arg.name == name:
            return self.var_arg
        elif self.kw_arg and self.kw_arg.name == name:
            return self.kw_arg
        else:
            return self.get_program().global_vars.get(name)

    def create_variable(self, name: str, cls: PythonClass,
                        translator: 'Translator',
                        local: bool=True) -> 'PythonVar':
        """
        Creates a new local variable with the given name and type and performs
        all necessary processing/initialization
        """
        sil_name = self.get_fresh_name(name)
        result = self.node_factory.create_python_var(sil_name, None, cls)
        result.process(sil_name, translator)
        if local:
            self.add_local(sil_name, result)
        return result

    def get_locals(self) -> List['PythonVar']:
        """
        Returns all method locals as a list of PythonVars.
        """
        return list(self.locals.values())

    def get_args(self) -> List['PythonVar']:
        """
        Returns all method args as a list of PythonVars.
        """
        return list(self.args.values())

    def get_results(self) -> List['PythonVar']:
        """
        Returns all results as a list of PythonVars.
        """
        if self.result:
            return [self.result]
        else:
            return []


class PythonIOOperation(PythonNode, PythonScope):
    """
    Represents an IO operation which may be basic or not.

    +   ``preset`` – a set of input places.
    +   ``postset`` – a set of output places.
    +   ``inputs`` – inputs of IO operation (excluding preset).
    +   ``outputs`` – outputs of IO operation (excluding postset).
    """
    def __init__(
            self,
            name: str,
            node: ast.AST,
            superscope: PythonScope,
            node_factory: 'ProgramNodeFactory',
            ):
        PythonNode.__init__(self, name, node)
        PythonScope.__init__(self, [], superscope)
        self._preset = []
        self._postset = []
        self._inputs = []
        self._outputs = []
        self._terminates = None
        self._termination_measure = None
        self._body = None
        self._io_existentials = None

    @property
    def is_builtin(self) -> bool:
        return self.name in BUILTIN_IO_OPERATIONS

    def _process_var_list(self, var_list: List['PythonVar'],
                          translator: 'Translator') -> None:
        """
        Creates fresh Silver names for all variables in ``var_list``.
        """
        for var in var_list:
            var.process(self.get_fresh_name(var.name), translator)

    def process(self, sil_name: str, translator: 'Translator',
                program: PythonProgram) -> None:
        """
        Creates fresh Silver names for preset, postset, inputs and
        outputs. Also, sets the ``sil_name``.
        """
        if self._body is not None:
            body_checker = IOOperationBodyChecker(
                self._body,
                self.get_results(),
                self._io_existentials,
                program)
            body_checker.check()
        self.sil_name = sil_name
        self._process_var_list(self._preset, translator)
        self._process_var_list(self._postset, translator)
        self._process_var_list(self._inputs, translator)
        self._process_var_list(self._outputs, translator)

    def set_preset(self, preset: List['PythonVar']) -> None:
        assert len(preset) == 1 or self.is_builtin
        self._preset = preset

    def set_postset(self, postset: List['PythonVar']) -> None:
        assert len(postset) == 1 or self.is_builtin
        self._postset = postset

    def set_inputs(self, inputs: List['PythonVar']) -> None:
        assert isinstance(inputs, list)
        self._inputs = inputs

    def is_input(self, name) -> bool:
        for input in self._inputs:
            if input.name == name:
                return True
        else:
            return False

    def set_outputs(self, outputs: List['PythonVar']) -> None:
        assert isinstance(outputs, list)
        self._outputs = outputs

    def set_terminates(self, expression: ast.AST) -> bool:
        """
        Set the property if it is not already set and return ``True``.
        """
        if self._terminates is None:
            self._terminates = expression
            return True
        else:
            return False

    def set_termination_measure(self, expression: ast.AST) -> bool:
        """
        Set the property if it is not already set and return ``True``.
        """
        if self._termination_measure is None:
            self._termination_measure = expression
            return True
        else:
            return False

    def is_basic(self) -> bool:
        """
        Is this IO operation basic?
        """
        return self._body is None

    def set_body(self, expression: ast.AST) -> bool:
        """
        Set the body if it is not already set and return ``True``.
        """
        if self._body is None:
            self._body = expression
            return True
        else:
            return False

    def get_body(self) -> ast.AST:
        """
        Return IO operation body.
        """
        assert self._body is not None
        return self._body

    def set_io_existentials(
            self,
            io_existentials: List['PythonVarCreator']) -> bool:
        """
        Set io existentials list if not already set and return
        ``True``.
        """
        if self._io_existentials is None:
            self._io_existentials = io_existentials
            return True
        else:
            return False

    def get_io_existentials(self) -> List['PythonVarCreator']:
        """
        Get IO existentials.
        """
        assert self._io_existentials is not None
        return self._io_existentials

    def get_parameters(self) -> List['PythonVar']:
        """
        Return a list of parameters that uniquely identify IO operation
        instance.
        """
        return self._preset + self._inputs

    def get_results(self) -> List['PythonVar']:
        """
        Return a list of results for this IO operation.
        """
        return self._outputs + self._postset


class PythonExceptionHandler(PythonNode):
    """
    Represents an except-block belonging to a try-block.
    """

    def __init__(self, node: ast.AST, exception_type: PythonClass,
                 try_block: 'PythonTryBlock', handler_name: str, body: ast.AST,
                 exception_name: str):
        """
        :param exception_type: The type of exception this handler catches
        :param try_block: The try-block this handler belongs to
        :param handler_name: Label that this handler will get in Silver
        :param exception_name: Variable name for the exception in the block
        """
        super().__init__(handler_name, node=node)
        self.try_block = try_block
        self.body = body
        self.exception = exception_type
        self.exception_name = exception_name


class PythonTryBlock(PythonNode):
    """
    Represents a try-block, which may include except-blocks, an else-block
    and/or a finally-block.
    """

    def __init__(self, node: ast.AST, try_name: str,
                 node_factory: 'ProgramNodeFactory',
                 method: PythonMethod,
                 protected_region: ast.AST):
        """
        :param node_factory: Factory to create PythonVar objects.
        :param method: Method this block is in
        :param protected_region: Statements protected by the try
        """
        super().__init__(try_name, node=node)
        self.handlers = []
        self.else_block = None
        self.finally_block = None
        self.protected_region = protected_region
        self.finally_var = None
        self.error_var = None
        self.method = method
        self.node_factory = node_factory
        self.finally_name = None
        self.post_name = None
        method.labels.append(try_name)

    def get_finally_var(self, translator: 'Translator') -> 'PythonVar':
        """
        Lazily creates and returns the variable in which we store the
        information how control flow should proceed after the execution
        of a finally block. We use a value of 0 to say normal flow, 1 to say
        we returned normally, i.e. jump to the end of the function asap, 2
        to say we returned exceptionally, i.e. jump to the end of the function
        moving through exception handlers.
        """
        if self.finally_var:
            return self.finally_var
        sil_name = self.method.get_fresh_name('try_finally')
        int_type = self.method.get_program().classes[INT_TYPE]
        result = self.node_factory.create_python_var(sil_name, None,
                                                     int_type)
        result.process(sil_name, translator)
        self.method.locals[sil_name] = result
        self.finally_var = result
        return result

    def get_error_var(self, translator: 'Translator') -> 'PythonVar':
        """
        Lazily creates and returns the variable in which any exceptions thrown
        within the block will be stored.
        """
        if self.error_var:
            return self.error_var
        sil_name = self.method.get_fresh_name('error')
        exc_type = self.method.get_program().classes['Exception']
        result = self.node_factory.create_python_var(sil_name, None,
                                                     exc_type)
        result.process(sil_name, translator)
        self.method.locals[sil_name] = result
        self.error_var = result
        return result

    def process(self, translator: 'Translator') -> None:
        self.get_error_var(translator)
        self.get_finally_var(translator)


class PythonVarBase(PythonNode):
    """
    Abstract class representing any variable in Python.
    """

    def __init__(self, name: str, node: ast.AST, type: PythonClass):
        super().__init__(name, node)
        self.type = type
        self.writes = []
        self.reads = []
        self.alt_types = {}
        self.default = None
        self.default_expr = None

    def process(self, sil_name: str, translator: 'Translator') -> None:
        """
        Sets ``sil_name``.
        """
        self.sil_name = sil_name


class PythonVar(PythonVarBase):
    """
    Represents a variable in Python. Can be a local variable or a
    function parameter.
    """

    def __init__(self, name: str, node: ast.AST, type: PythonClass):
        super().__init__(name, node, type)
        self.decl = None
        self._ref = None
        self._translator = None
        self.value = None

    def process(self, sil_name: str, translator: 'Translator') -> None:
        """
        Creates a Silver variable declaration and reference representing
        this Python variable.
        """
        super().process(sil_name, translator)
        self._translator = translator
        prog = self.type.get_program()
        self.decl = translator.translate_pythonvar_decl(self, prog)
        self._ref = translator.translate_pythonvar_ref(self, prog, None, None)

    def ref(self, node: ast.AST=None,
            ctx: 'Context'=None) -> 'silver.ast.LocalVarRef':
        """
        Creates a reference to this variable. If no arguments are supplied,
        the reference will have no position. Otherwise, it will have the
        position of the given node in the given context.
        """
        if not node:
            return self._ref
        prog = self.type.get_program()
        return self._translator.translate_pythonvar_ref(self, prog, node, ctx)


class PythonGlobalVar(PythonVarBase):
    """
    Represents a global variable in Python.
    """


class PythonIOExistentialVar(PythonVarBase):
    """
    Represents an existential variable in Python. Existential variable
    is a variable created by using ``IOExists`` construct and it can be
    used only in contracts. Unlike normal variables, it is translated to
    getter functions.
    """

    def __init__(self, name: str, node: ast.AST, type: PythonClass):
        super().__init__(name, node, type)
        self._ref = None

    def is_defined(self) -> bool:
        """
        Returns true if main getter was already defined.
        """
        return not self._ref is None

    def ref(self, node: ast.AST = None, ctx: 'Context' = None) -> Expr:
        """
        Returns a Silver expression node that can be used to refer to
        this variable.
        """
        # TODO (Vytautas): Update to new API.
        assert not self._ref is None, self.name
        return self._ref

    def set_ref(self, ref: Expr) -> None:
        """
        Sets a Silver expression node that can be used to refer to this
        variable.
        """
        # TODO (Vytautas): Update to new API.
        assert self._ref is None
        self._ref = ref


class PythonVarCreator:
    """
    A factory for Python variable. It is used instead of a concrete
    variable when the same Python variable can be translated into
    multiple silver variables. For example, when opening a non-basic IO
    operation.
    """

    def __init__(self, name: str, node: ast.AST,
                 type: PythonClass) -> None:
        self._name = name
        self._node = node
        self._type = type

    @property
    def name(self) -> str:
        return self._name

    def create_variable_instance(self) -> PythonVar:
        return PythonVar(self._name, self._node, self._type)


class PythonField(PythonNode):
    """
    Represents a field of a Python class.
    """
    def __init__(self, name: str, node: ast.AST, type: PythonClass,
                 cls: PythonClass):
        """
        :param type: The type of the field.
        :param cls: The class this field belongs to
        """
        super().__init__(name, node)
        self.cls = cls
        self.inherited = None  # infer
        self.type = type
        self._sil_field = None
        self.reads = []  # direct
        self.writes = []  # direct

    @property
    def sil_field(self) -> 'silver.ast.Field':
        return self._sil_field

    @sil_field.setter
    def sil_field(self, field: 'silver.ast.Field'):
        self._set_sil_field(field)

    def _set_sil_field(self, field: 'silver.ast.Field'):
        self._sil_field = field

    def process(self, sil_name: str) -> None:
        """
        Checks if this field is inherited from a superclass.
        """
        self.sil_name = sil_name
        if not self.is_mangled():
            if self.cls.superclass is not None:
                self.inherited = self.cls.superclass.get_field(self.name)

    def is_mangled(self) -> bool:
        return self.name.startswith('__') and not self.name.endswith('__')


class ProgramNodeFactory:
    """
    Factory to create Python ProgramNodes.
    
    TODO: Add more interfaces for other types of containers if needed.
    """

    def create_python_var(
            self, name: str, node: ast.AST,
            type_: PythonClass) -> PythonVar:
        return PythonVar(name, node, type_)

    def create_python_global_var(
            self, name: str, node: ast.AST,
            type_: PythonClass) -> PythonGlobalVar:
        return PythonGlobalVar(name, node, type_)

    def create_python_io_existential_var(
            self, name: str, node: ast.AST,
            type_: PythonClass) -> PythonIOExistentialVar:
        return PythonIOExistentialVar(name, node, type_)

    def create_python_var_creator(
            self, name: str, node: ast.AST,
            type_: PythonClass) -> PythonIOExistentialVar:
        return PythonVarCreator(name, node, type_)

    def create_python_method(self, name: str, node: ast.AST, cls: PythonClass,
                             superscope: PythonScope,
                             pure: bool, contract_only: bool,
                             container_factory: 'ProgramNodeFactory',
                             interface: bool = False) -> PythonMethod:
        return PythonMethod(name, node, cls, superscope, pure, contract_only,
                            container_factory, interface)

    def create_python_io_operation(self, name: str, node: ast.AST,
                                   superscope: PythonScope,
                                   container_factory: 'ProgramNodeFactory',
                                   ) -> PythonIOOperation:
        return PythonIOOperation(name, node, superscope, container_factory)

    def create_python_field(self, name: str, node: ast.AST, type_: PythonClass,
                            cls: PythonClass) -> PythonField:
        return PythonField(name, node, type_, cls)

    def create_python_class(self, name: str, superscope: PythonScope,
                            node_factory: 'ProgramNodeFactory',
                            node: ast.AST = None,
                            superclass: PythonClass = None,
                            interface=False):
        return PythonClass(name, superscope, node_factory, node,
                           superclass, interface)
