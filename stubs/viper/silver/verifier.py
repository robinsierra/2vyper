from typing import Any

from viper.silver.ast import (
    IdentifierPosition,
    Node,
)


class AbstractError:
    def pos(self) -> IdentifierPosition:
        pass
    def fullId(self) -> str:
        pass
    def readableMessage(self) -> str:
        pass

class AbstractErrorReason:
    def id(self) -> str:
        pass
    def offendingNode(self) -> Node:
        pass
    def pos(self) -> IdentifierPosition:
        pass
    def readableMessage(self) -> str:
        pass

class ErrorMessage:
    def id(self) -> str:
        pass
    def offendingNode(self) -> Node:
        pass
    def pos(self) -> IdentifierPosition:
        pass
    def readableMessage(self) -> str:
        pass

class VerificationError(AbstractError, ErrorMessage):
    def reason(self) -> Any:
        pass
    def readableMessage(self, withId: bool = False,
                        withPosition: bool = True) -> str:
        pass

class AbstractVerificationError(VerificationError):
    def pos(self) -> IdentifierPosition:
        pass
