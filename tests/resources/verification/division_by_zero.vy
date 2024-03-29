#
# Copyright (c) 2019 ETH Zurich
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#


#@ config: no_gas, no_overflows


#@ ensures: (b != 0) == success()
@public
def _div(a: int128, b: int128) -> int128:
    return a / b


#:: ExpectedOutput(not.wellformed:division.by.zero)
#@ ensures: result() == 5 / n
@public
def div_in_spec(n: int128) -> int128:
    if n != 0:
        return 5 / n
    else:
        return 0
