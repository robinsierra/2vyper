from nagini_contracts.contracts import Pure, Result
from nagini_contracts.io_contracts import *


#:: ExpectedOutput(invalid.program:decorators.incompatible)
@Pure
@IOOperation
def read_int_io(
        t_pre1: Place,
        res: int = Result(),
        t_post: Place = Result(),
        ) -> bool:
    Terminates(False)
