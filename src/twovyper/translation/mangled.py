"""
Copyright (c) 2019 ETH Zurich
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""

from twovyper.ast import names


# Constants for names in translated AST

INIT = names.INIT
SELF = names.SELF
OLD_SELF = f'$old_{names.SELF}'
PRE_SELF = f'$pre_{names.SELF}'
ISSUED_SELF = f'$issued_{names.SELF}'

CONTRACTS = '$contracts'
OLD_CONTRACTS = '$old_contracts'
PRE_CONTRACTS = '$pre_contracts'
ISSUED_CONTRACTS = '$issued_contracts'

MSG = names.MSG
BLOCK = names.BLOCK
TX = names.TX

SENT_FIELD = '$sent'
RECEIVED_FIELD = '$received'
SELFDESTRUCT_FIELD = '$selfdestruct'

RESULT_VAR = '$res'
SUCCESS_VAR = '$succ'

OVERFLOW = '$overflow'
OUT_OF_GAS = '$out_of_gas'
MSG_SENDER_CALL_FAIL = '$msg_sender_call_fail'

FIRST_PUBLIC_STATE = '$first_public_state'

END_LABEL = 'end'
RETURN_LABEL = 'return'
REVERT_LABEL = 'revert'

CONTRACT_DOMAIN = '$Contract'
SELF_ADDRESS = '$self_address'
IMPLEMENTS = '$implements'

MATH_DOMAIN = '$Math'
MATH_SIGN = '$sign'
MATH_DIV = '$div'
MATH_MOD = '$mod'
MATH_POW = '$pow'
MATH_SQRT = '$sqrt'
MATH_FLOOR = '$floor'
MATH_CEIL = '$ceil'

ARRAY_DOMAIN = '$Array'
ARRAY_INT_DOMAIN = '$ArrayInt'
ARRAY_ELEMENT_VAR = '$E'

ARRAY_INIT = '$array_init'
ARRAY_KECCAK256 = '$array_keccak256'
ARRAY_SHA256 = '$array_sha256'

MAP_DOMAIN = '$Map'
MAP_INT_DOMAIN = '$MapInt'
MAP_KEY_VAR = '$K'
MAP_VALUE_VAR = '$V'

MAP_INIT = '$map_init'
MAP_EQ = '$map_eq'
MAP_GET = '$map_get'
MAP_SET = '$map_set'
MAP_SUM = '$map_sum'

STRUCT_DOMAIN = '$Struct'
STRUCT_OPS_DOMAIN = '$StructOps'
STRUCT_OPS_VALUE_VAR = '$T'

STRUCT_LOC = '$struct_loc'
STRUCT_GET = '$struct_get'
STRUCT_SET = '$struct_set'

STRUCT_INIT_DOMAIN = '$StructInit'

RANGE_DOMAIN = '$Range'
RANGE_RANGE = '$range'

IMPLEMENTS_DOMAIN = '$Implements'

TRANSITIVITY_CHECK = '$transitivity_check'
FORCED_ETHER_CHECK = '$forced_ether_check'


def method_name(vyper_name: str) -> str:
    return f'f${vyper_name}'


def struct_name(vyper_struct_name: str) -> str:
    return f's${vyper_struct_name}'


def struct_init_name(vyper_struct_name: str) -> str:
    return f'{struct_name(vyper_struct_name)}$init'


def struct_eq_name(vyper_struct_name: str) -> str:
    return f'{struct_name(vyper_struct_name)}$eq'


def interface_name(vyper_interface_name: str) -> str:
    return f'i${vyper_interface_name}'


def interface_function_name(vyper_iname: str, vyper_fname: str) -> str:
    return f'{interface_name(vyper_iname)}${vyper_fname}'


def ghost_function_name(vyper_name: str) -> str:
    return f'g${vyper_name}'


def axiom_name(viper_name: str) -> str:
    return f'{viper_name}$ax'


def ghost_axiom_name(vyper_name: str, idx: int):
    return axiom_name(f'{ghost_function_name(vyper_name)}${idx}')


def event_name(vyper_name: str) -> str:
    return f'e${vyper_name}'


def accessible_name(vyper_name: str) -> str:
    return f'$accessible${vyper_name}'


def local_var_name(inline_prefix: str, vyper_name: str) -> str:
    if vyper_name in {names.SELF, names.MSG, names.BLOCK}:
        prefix = ''
    else:
        prefix = 'l$'
    return f'{prefix}{inline_prefix}{vyper_name}'


def quantifier_var_name(vyper_name: str) -> str:
    return f'q${vyper_name}'


def model_var_name(*components: str) -> str:
    return f'm${"$".join(components)}'
