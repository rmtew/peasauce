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

"""
Human68K executable files (.x suffix).

Future work for people more interested in the X68k platform:
o The debug information is something called SCD, and code can be found
  in the source code of a linker which outputs it (albeit with Japanese
  comments).  See: hlkev9.zip
o What are .r files?
o Does the load mode matter?
o Find a file with a base address and see what needs to be done for
  disassembling that to be as correct as possible.
o What is the bindlist?

"""

import os
import sys
import logging


logger = logging.getLogger("loader-human68k")


MAGIC_WORD = 0x4855 # HU
SIZEOF_HEADER = 0x40
SIZEOF_SYMBOL_ENTRY = 8 + 2 + 4


XDEF_COMMON	= 0x0003
XDEF_ABS = 0x0200           # label: .equ $value
XDEF_TEXT = 0x0201
XDEF_DATA = 0x0202
XDEF_BSS = 0x0203
XDEF_STACK = 0x0204



def is_accepted_file_type(word1):
    """ Whether the first word of a potentially loaded file is handled by us. """
    if word1 == MAGIC_WORD:
        return True
    return False

LOADMODE_NORMAL = 0
LOADMODE_MINIMAL_MEMORY = 1
LOADMODE_HIGH_ADDRESS = 2

class XFile(object):
    # Executable file header field values.
    _reserved1 = None
    _loadmode = None
    _base_address = None # Normally 0
    _entry_offset = None
    _text_segment_size = None
    _data_segment_size = None
    _bss_segment_size = None
    _relocation_table_size = None
    _symbol_table_size = None
    _debug_line_size = None
    _debug_symbol_size = None
    _debug_string_size = None
    _reserved2 = None
    _reserved3 = None
    _reserved4 = None
    _reserved5 = None
    _bindlist_offset = None

    _relocation_table_entries = None
    _symbol_table_entries = None


def load_file(file_info, data_types):
    with open(file_info.file_path, "rb") as f:
        return load_x_file(file_info, data_types, f)

def load_x_file(file_info, data_types, f):
    magic_word = data_types.uint16(f.read(2))
    if magic_word != MAGIC_WORD:
        logger.debug("human68k/xfile.py: _process_file: Unrecognised file.")
        return False

    data = XFile()
    data._reserved1 = data_types.uint8(f.read(1))
    data._loadmode = data_types.uint8(f.read(1))
    data._base_address = data_types.uint32(f.read(4))
    data._entry_offset = data_types.uint32(f.read(4))
    data._text_segment_size = data_types.uint32(f.read(4))
    data._data_segment_size = data_types.uint32(f.read(4))
    data._bss_segment_size = data_types.uint32(f.read(4))
    data._relocation_table_size = data_types.uint32(f.read(4))
    data._symbol_table_size = data_types.uint32(f.read(4))
    data._debug_line_size = data_types.uint32(f.read(4))
    data._debug_symbol_size = data_types.uint32(f.read(4))
    data._debug_string_size = data_types.uint32(f.read(4))
    data._reserved2 = data_types.uint32(f.read(4))
    data._reserved3 = data_types.uint32(f.read(4))
    data._reserved4 = data_types.uint32(f.read(4))
    data._reserved5 = data_types.uint32(f.read(4))
    data._bindlist_offset = data_types.uint32(f.read(4))

    if f.tell() != SIZEOF_HEADER:
        logger.debug("Header size mismatch, is %d, expected %d", f.tell(), SIZEOF_HEADER)
        return False

    if not _read_relocation_table(file_info, data_types, data, f):
        return False

    if not _read_symbol_table(file_info, data_types, data, f):
        return False

    symbols = []
    for symbol_name, symbol_type, symbol_value in data._symbol_table_entries:
        symbols.append((symbol_value, symbol_name, True))

    # Disassembler segment partitioning.
    file_info.set_entrypoint(0, data._entry_offset)

    merged_segment_offset = SIZEOF_HEADER
    merged_segment_size = data._text_segment_size + data._data_segment_size
    file_info.add_code_segment(merged_segment_offset, merged_segment_size, merged_segment_size, data._relocation_table_entries, symbols)

    if data._bss_segment_size:
        # Does not contain file data, so no file offset, or file data length.
        file_info.add_bss_segment(-1, 0, data._bss_segment_size, [], {})

    file_info.set_file_data(data)

    return True


def _read_relocation_table(file_info, data_types, data, f):
    file_offset = SIZEOF_HEADER + data._text_segment_size + data._data_segment_size
    f.seek(file_offset, os.SEEK_SET)

    offset = data_types.uint16(f.read(2))
    bytes_read = 2

    l = []
    offsets = [ offset ]

    maximum_offset = data._text_segment_size + data._data_segment_size
    while bytes_read < data._relocation_table_size:
        value = data_types.uint16(f.read(2))
        bytes_read += 2
        if value == 1:
            offset += data_types.uint32(f.read(4))
            bytes_read += 2
        else:
            offset += value
        if offset >= maximum_offset:
            logger.debug("Fixup table data unexpected")
            return False
        offsets.append(offset)
    l.append((0, offsets))

    data._relocation_table_entries = l
    return True


SIZEOF_SYMBOL_ENTRY = 1 + 1 + 4

def _read_symbol_table(file_info, data_types, data, f):
    file_offset = SIZEOF_HEADER + data._text_segment_size + data._data_segment_size + data._relocation_table_size
    f.seek(file_offset, os.SEEK_SET)
    
    entry_count = data._symbol_table_size
    if entry_count == 0:
        logger.debug("xfile.py: _read_symbol_table: no symbol table data to read")
        return False

    l = []
    bytes_read = 0
    while bytes_read < data._symbol_table_size:
        xdef_type = data_types.uint16(f.read(2))
        offset = data_types.uint32(f.read(4))
        bytes_read += SIZEOF_SYMBOL_ENTRY

        name = ""
        c = f.read(1)
        bytes_read += 1
        while c != "\0":
            name += c
            c = f.read(1)
            bytes_read += 1
        l.append((name, xdef_type, offset))

        if bytes_read & 1:
            f.read(1)
            bytes_read += 1
        # logger.debug("_read_symbol_table %d %d %d \"%s\"", byte1, byte2, offset, name) 
    
    data._symbol_table_entries = l
    return True


def print_summary(file_info):
    data = file_info.file_data

    print "_reserved1", data._reserved1
    print "_loadmode", data._loadmode
    print "_base_address", data._base_address
    print "_entry_offset", data._entry_offset
    print "_text_segment_size", data._text_segment_size
    print "_data_segment_size", data._data_segment_size
    print "_bss_segment_size", data._bss_segment_size
    print "_relocation_table_size", data._relocation_table_size
    print "_symbol_table_size", data._symbol_table_size
    print "_debug_line_size", data._debug_line_size
    print "_debug_symbol_size", data._debug_symbol_size
    print "_debug_string_size", data._debug_string_size
    print "_reserved2", data._reserved2
    print "_reserved3", data._reserved3
    print "_reserved4", data._reserved4
    print "_reserved5", data._reserved5
    print "_bindlist_offset", data._bindlist_offset

    xdef_types = {}
    min_stack, max_stack = 1<<31, 0
    min_stack_name = max_stack_name = "?"
    for x, xdef_type, y in data._symbol_table_entries:
        if xdef_type not in xdef_types:
            xdef_types[xdef_type] = 1
        else:
            xdef_types[xdef_type] += 1
        if xdef_type == XDEF_STACK:
            if y < min_stack: min_stack, min_stack_name = y, x
            if y > max_stack: max_stack, max_stack_name = y, x

    print "length of text + data + bss space", hex(data._text_segment_size + data._data_segment_size +data._bss_segment_size)
    print "lowest stack symbol offset", hex(min_stack), min_stack_name
    print "highest stack symbol offset", hex(max_stack), max_stack_name

def get_matching_constants(prefix):
    d = {}
    for k, v in globals().iteritems():
        if k.startswith(prefix):
            d[v] = k
    return d

XDEF_NAMES = get_matching_constants("XDEF_")
