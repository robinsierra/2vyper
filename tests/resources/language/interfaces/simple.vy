#
# Copyright (c) 2019 ETH Zurich
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#


#@ interface

#@ ghost:
    #@ def _val() -> int128: ...
    #@ def _inc_val() -> int128: ...
    #@ def _pure(i: int128) -> int128: ...


#@ always ensures: _inc_val(self) >= old(_inc_val(self))


@public
def do_stuff():
    raise "Not implemented"


#@ ensures: implies(i <= 0, revert())
#@ ensures: implies(success(), result() == i)
@public
def positive(i: int128) -> int128:
    raise "Not implemented"


#@ ensures: implies(success(), result() == i / i * i)
@public
def positive_not_welldefined(i: int128) -> int128:
    raise "Not implemented"


#@ ensures: implies(success(), result() == msg.sender)
@public
def use_msg_sender() -> address:
    raise "Not imlpemented"


#@ ensures: implies(success(), result() == msg.value)
@public
@payable
def use_msg_value() -> wei_value:
    raise "Not implemented"


#@ ensures: implies(success(), result() == _pure(self, i))
@public
@constant
def pure(i: int128) -> int128:
    raise "Not implemented"


#@ ensures: implies(success(), result() == _val(self))
@public
@constant
def get_val() -> int128:
    raise "Not implemented"


#@ ensures: implies(success(), _val(self) == new_val)
#@ ensures: storage(msg.sender) == old(storage(msg.sender))
@public
def set_val(new_val: int128):
    raise "Not implemented"
