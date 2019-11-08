"""
Copyright (c) 2019 ETH Zurich
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""

import ast

from typing import Callable, Dict, List, Optional, Tuple

from twovyper.utils import seq_to_list

from twovyper.viper.typedefs import Node, AbstractSourcePosition
from twovyper.viper.typedefs import AbstractVerificationError, AbstractErrorReason

from twovyper.verification.messages import ERRORS, REASONS, VAGUE_REASONS
from twovyper.verification.rules import Rules


"""Wrappers for Scala error objects."""


class Position:
    """Wrapper around ``AbstractSourcePosition``."""

    def __init__(self, position: AbstractSourcePosition):
        self._position = position
        if hasattr(position, 'id'):
            self.node_id = position.id()
        else:
            self.node_id = None

    @property
    def file_name(self) -> str:
        """Return ``file``."""
        return self._position.file().toString()

    @property
    def line(self) -> int:
        """Return ``start.line``."""
        return self._position.line()

    @property
    def column(self) -> int:
        """Return ``start.column``."""
        return self._position.column()

    def __str__(self) -> str:
        return str(self._position)


class Via:

    def __init__(self, origin: str, position: AbstractSourcePosition):
        self.origin = origin
        self.position = position


ModelTransformation = Callable[[str, str], Tuple[str, str]]


class Model:

    def __init__(self, error: AbstractVerificationError, transform: Optional[ModelTransformation]):
        self._model = error.parsedModel().get()
        print(self._model)
        self._transform = transform
        self.values()

    def values(self) -> Dict[str, str]:
        res = {}
        if self._model and self._transform:
            entries = self._model.entries()
            for name_entry in seq_to_list(entries):
                name = str(name_entry._1())
                value = str(name_entry._2())
                transformation = self._transform(name, value)
                if transformation:
                    name, value = transformation
                    res[name] = value

        return res

    def __str__(self):
        return "\n".join(f"   {name} = {value}" for name, value in self.values().items())


class ErrorInfo:

    def __init__(self,
                 function: str,
                 node: ast.AST,
                 vias: List[Via],
                 model_transformation: Optional[ModelTransformation],
                 reason_string: str):
        self.function = function
        self.node = node
        self.vias = vias
        self.model_transformation = model_transformation
        self.reason_string = reason_string


class Reason:
    """Wrapper around ``AbstractErrorReason``."""

    def __init__(self, reason_id: str, reason: AbstractErrorReason, reason_info: ErrorInfo):
        self._reason = reason
        self.identifier = reason_id
        self._reason_info = reason_info
        self.offending_node = reason.offendingNode()
        self.position = Position(self.offending_node.pos())

    def __str__(self) -> str:
        return self.string(False)

    def string(self, show_viper_reason: bool) -> str:
        """
        Creates a string representation of this reason including a reference to the Python
        AST node that caused it.
        If no such node is available, either returns a partial message that describes the
        kind of error in general, or outputs the concrete Viper-level description of the
        error, depending on the parameter ``show_viper_reason``.
        """
        reason = self._reason_info.reason_string or self._reason_info.node
        if reason is None and self.identifier in VAGUE_REASONS:
            if not show_viper_reason:
                return VAGUE_REASONS[self.identifier]
            else:
                return self._reason.readableMessage()
        return REASONS[self.identifier](self._reason_info)


class Error:
    """Wrapper around ``AbstractVerificationError``."""

    def __init__(self, error: AbstractVerificationError, rules: Rules,
                 reason_item: ErrorInfo, error_item: ErrorInfo) -> None:

        # Translate error id.
        viper_reason = error.reason()
        error_id = error.id()
        reason_id = viper_reason.id()
        key = error_id, reason_id
        if key in rules:
            error_id, reason_id = rules[key]

        # Construct object.
        self._error = error
        self.identifier = error_id
        self._error_info = error_item
        self.reason = Reason(reason_id, viper_reason, reason_item)
        if error.parsedModel().isDefined():
            self.model = Model(error, error_item.model_transformation)
        else:
            self._model = None
        self.position = Position(error.pos())

    def pos(self) -> AbstractSourcePosition:
        """
        Get position.
        """
        return self._error.pos()

    @property
    def full_id(self) -> str:
        """
        Full error identifier.
        """
        return f"{self.identifier}:{self.reason.identifier}"

    @property
    def offending_node(self) -> Node:
        """
        AST node where the error occurred.
        """
        return self._error.offendingNode()

    @property
    def readable_message(self) -> str:
        """
        Readable error message.
        """
        return self._error.readableMessage()

    @property
    def position_string(self) -> str:
        """
        Full error position as a string.
        """
        vias = self._error_info.vias or self.reason._reason_info.vias or []
        vias_string = "".join(f", via {via.origin} at {via.position}" for via in vias)
        return f"{self.position}{vias_string}"

    @property
    def message(self) -> str:
        """
        Human readable error message.
        """
        return ERRORS[self.identifier](self._error_info)

    def __str__(self) -> str:
        return self.string(False, False)

    def string(self, ide_mode: bool, show_viper_errors: bool, include_model: bool = False) -> str:
        """
        Format error.

        Creates an appropriate error message (referring to the
        responsible Python code) for the given Viper error.

        The error format is either optimized for human readability or uses the same format
        as IDE-mode Viper error messages, depending on the first parameter.
        The second parameter determines if the message may show Viper-level error
        explanations if no Python-level explanation is available.
        """
        assert not (ide_mode and include_model)

        if ide_mode:
            file_name = self.position.file_name
            line = self.position.line
            col = self.position.column
            msg = self.message
            reason = self.reason
            return f"{file_name}:{line}:{col}: error: {msg} {reason}"
        else:
            msg = self.message
            reason = self.reason.string(show_viper_errors)
            pos = self.position_string
            error_msg = f"{msg} {reason} ({pos})"
            if include_model and self.model:
                return f"{error_msg}\nCounterexample:\n{self.model}"
            else:
                return error_msg
