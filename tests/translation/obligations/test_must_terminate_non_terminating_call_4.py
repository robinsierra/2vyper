from py2viper_contracts.contracts import (
    Requires,
    Invariant,
)
from py2viper_contracts.obligations import *


def non_terminating() -> None:
    pass


def test_call_non_terminating_2() -> None:
    i = 0
    while i < 5:
        Invariant(MustTerminate(5 - i))
        i += 1
        #:: ExpectedOutput(invalid.program:non_terminating_call_in_terminating_context)
        non_terminating()
