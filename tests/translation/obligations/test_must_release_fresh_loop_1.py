from py2viper_contracts.contracts import (
    Invariant,
)
from py2viper_contracts.obligations import *
from threading import Lock


def test(lock: Lock) -> None:
    while True:
        #:: ExpectedOutput(invalid.program:obligation.fresh.in_loop)
        Invariant(MustRelease(lock))