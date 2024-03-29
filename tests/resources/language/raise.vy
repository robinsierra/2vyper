#
# Copyright (c) 2019 ETH Zurich
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#

#@ ensures: revert()
@public
def test_raise():
    raise "Error"


#@ ensures: implies(a, revert())
@public
def test_raise_conditional(a: bool):
    if a:
        raise "Error"


@public
def test_raise_unreachable(a: int128):
    if a > 0 and a < 0:
        raise UNREACHABLE


@public
def test_raise_unreachable_fail(a: int128):
    if a > 0:
        #:: ExpectedOutput(assert.failed:assertion.false)
        raise UNREACHABLE
