from py2viper_contracts.contracts import Ensures, Implies, Result
from py2viper_contracts.io import *
from typing import Tuple, Callable


def test(x: bool) -> Place:
    IOExists1(Place)(
        lambda t2: (
        Ensures(
            #:: ExpectedOutput(invalid.program:io_existential_var.use_of_undefined)
            Implies(x, t2 == Result())
        ),
        )
    )