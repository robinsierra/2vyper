from py2viper_contracts.contracts import *


@Predicate  #:: ExpectedOutput(type.error:Encountered Any type. Type annotation missing?)
def test1(x: int):
    return x == 5