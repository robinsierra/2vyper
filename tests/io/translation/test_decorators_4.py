from nagini_contracts.contracts import Ghost, Result
from nagini_contracts.io_contracts import *


#:: ExpectedOutput(invalid.program:decorators.incompatible)
@Ghost
@IOOperation
def read_int_io(
        t_pre1: Place,
        res: int = Result(),
        t_post: Place = Result(),
        ) -> bool:
    Terminates(False)
