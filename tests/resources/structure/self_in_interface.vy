#
# Copyright (c) 2019 ETH Zurich
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#


#@ interface


val: int128

#:: ExpectedOutput(invalid.program:invalid.storage.var)
#@ ensures: self.val == 0
@public
def get_val_fail() -> int128:
    raise "Not implemented"
