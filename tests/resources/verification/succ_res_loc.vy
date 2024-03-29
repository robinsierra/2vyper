#
# Copyright (c) 2019 ETH Zurich
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#

#:: ExpectedOutput(postcondition.violated:assertion.false)
#@ ensures: result()
@public
def func0() -> bool:
    return False

#:: ExpectedOutput(postcondition.violated:assertion.false)
#@ ensures: implies(success(), result())
@public
def func1() -> bool:
    return False

#:: ExpectedOutput(postcondition.violated:assertion.false)
#@ ensures: success()
@public
def func2():
    assert False