"""
    Peasauce - interactive disassembler
    Copyright (C) 2012  Richard Tew

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

HUNK_UNIT           = 999
HUNK_NAME           = 1000
HUNK_CODE           = 1001
HUNK_DATA           = 1002
HUNK_BSS            = 1003
HUNK_RELOC32        = 1004
HUNK_RELOC16        = 1005
HUNK_RELOC8         = 1006
HUNK_EXT            = 1007
HUNK_SYMBOL         = 1008
HUNK_DEBUG          = 1009
HUNK_END            = 1010
HUNK_HEADER         = 1011

HUNK_BREAK          = 1014
HUNK_OVERLAY        = 1013

HUNK_DREL32         = 1015
HUNK_DREL16         = 1016
HUNK_DREL8          = 1017

HUNK_LIB            = 1018
HUNK_INDEX          = 1019

HUNK_RELOC32SHORT   = 1020
HUNK_ABSRELOC16     = 1021

EXT_SYMB        = 0   # symbol table
EXT_DEF         = 1   # relocatable definition
EXT_ABS         = 2   # Absolute definition
EXT_RES         = 3   # no longer supported
EXT_REF32       = 129 # 32 bit reference to symbol
EXT_COMMON      = 130 # 32 bit reference to COMMON block
EXT_REF16       = 131 # 16 bit reference to symbol
EXT_REF8        = 132 #  8 bit reference to symbol
EXT_DEXT32      = 133 # 32 bit data relative reference
EXT_DEXT16      = 134 # 16 bit data relative reference
EXT_DEXT8       = 135 #  8 bit data relative reference


def get_matching_constants(prefix):
    d = {}
    for k, v in globals().iteritems():
        if k.startswith(prefix):
            d[v] = k
    return d

HUNK_NAMES = get_matching_constants("HUNK_")
EXT_NAMES = get_matching_constants("EXT_")

if __name__ == "__main__":
    for k, v in HUNK_NAMES.iteritems():
        print v, hex(k)
