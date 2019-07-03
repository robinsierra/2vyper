#
# Copyright (c) 2019 ETH Zurich
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#

c1: constant(int128) = 12
c2: constant(int128) = 12 + 12 * 2 * 4 - 3
c3: constant(int128) = 12 / 5
c4: constant(bool) = True and False and not True
c5: constant(bool) = not True or False or True
c6: constant(bool) = True and False
c7: constant(int128) = min(c1, c2)
c8: constant(int128) = max(c7, 1 + 3)


@public
def foo() -> int128:
    return c1 + c2

@public
def bar() -> int128:
    return c3

@public
def some() -> bool:
    b: bool = c6
    b = c5
    b = c4
    return b

@public
def zero_add() -> address:
    return ZERO_ADDRESS

@public
def empty_bytes() -> bytes32:
    return EMPTY_BYTES32