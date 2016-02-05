"""
    Peasauce - interactive disassembler
    Copyright (C) 2012-2016 Richard Tew
    Licensed using the MIT license.
"""

"""
GEMDOS PRG executable files.

The text and data segments seem to be loaded contiguously, given that
relocation seems to happen within both based on the base address of
where the text segment is loaded in memory.
"""

import cPickle
import os
import struct
import sys
import logging

from .. import constants

logger = logging.getLogger("loader-atarist")


SIZEOF_HEADER = 0x1E - 2 # ??? Documentation differs from reality :-(

MAGIC_WORD = 0x601A

SEGMENT_TEXT    = 1
SEGMENT_DATA    = 2
SEGMENT_BSS     = 3

SIZEOF_SYMBOL_ENTRY = 8 + 2 + 4

SYMBOL_DEFINED                  = 0x8000
SYMBOL_EQUATED                  = 0x4000
SYMBOL_GLOBAL                   = 0x2000
SYMBOL_EQUATED_REGISTER         = 0x1000
SYMBOL_EXTERNAL_REFERENCE       =  0x800
SYMBOL_DATA_BASED_RELOCATABLE   =  0x400
SYMBOL_TEXT_BASED_RELOCATABLE   =  0x200
SYMBOL_BSS_BASED_RELOCATABLE    =  0x100

SYMBOL_SEGMENT_MASK             = SYMBOL_DATA_BASED_RELOCATABLE | SYMBOL_TEXT_BASED_RELOCATABLE | SYMBOL_BSS_BASED_RELOCATABLE

class PRGFile(object):
    # Executable file header field values.
    _text_segment_size = 0
    _data_segment_size = 0
    _bss_segment_size = 0
    _symbol_table_size = 0
    _reserved1 = None
    _reserved2 = None
    _reserved3 = None

    # Processed file metadata.
    _hunk_sizes = None
    _symbol_table_entries = None
    _fixup_offsets = None

EXPECTED_SUFFIX = "prg"

def identify_input_file(input_file, file_info, data_types, f_offset=0, f_length=None):
    result = constants.MatchResult()

    if file_info.has_file_name_suffix(EXPECTED_SUFFIX):
        result.confidence = constants.MATCH_POSSIBLE

    if load_prg_file(file_info, data_types, input_file, f_offset, f_length):
        result.platform_id = constants.PLATFORM_ATARIST
        result.file_format_id = constants.FILE_FORMAT_ATARIST_GEMDOS_EXECUTABLE
        result.confidence = constants.MATCH_CERTAIN

    return result

def load_input_file(input_file, file_info, data_types, f_offset=0, f_length=None):
    return load_prg_file(file_info, data_types, input_file, f_offset, f_length)

def load_prg_file(file_info, data_types, f, f_offset, f_length):
    f.seek(f_offset, os.SEEK_SET)
    magic_word = data_types.uint16(f.read(2))
    if magic_word != MAGIC_WORD:
        logger.debug("atarist/prgfile.py: _process_file: Unrecognised file.")
        return False

    prg_file = PRGFile()
    prg_file._hunk_sizes = []

    # Read the PRG executable file header.
    prg_file._text_segment_size = data_types.uint32(f.read(4))
    prg_file._data_segment_size = data_types.uint32(f.read(4))
    prg_file._bss_segment_size = data_types.uint32(f.read(4))
    prg_file._symbol_table_size = data_types.uint32(f.read(4))
    prg_file._reserved1 = data_types.uint32(f.read(4))
    prg_file._reserved2 = data_types.uint32(f.read(4))
    prg_file._reserved3 = data_types.uint16(f.read(2)) # GEMDOS reference manual says this should be a longword, but that does not work.

    if f.tell() != SIZEOF_HEADER:
        logger.debug("Header size mismatch")
        return False

    # Process the file meta-data.
    if not _read_symbol_table(file_info, data_types, prg_file, f):
        return False

    if not _read_fixup_information(file_info, data_types, prg_file, f):
        return False

    symbols = []
    for symbol_name, symbol_type, symbol_value in prg_file._symbol_table_entries:
        if symbol_type & SYMBOL_SEGMENT_MASK:
            symbols.append((symbol_value, symbol_name, True))

    # Disassembler segment partitioning.
    merged_segment_offset = SIZEOF_HEADER
    merged_segment_size = prg_file._text_segment_size + prg_file._data_segment_size
    prg_file._hunk_sizes.append((SEGMENT_TEXT, merged_segment_offset, merged_segment_size, merged_segment_size))
    file_info.add_code_segment(merged_segment_offset, merged_segment_size, merged_segment_size, prg_file._fixup_offsets, symbols)

    if prg_file._bss_segment_size:
        # Does not contain file data, so no file offset, or file data length.
        prg_file._hunk_sizes.append((SEGMENT_BSS, 0, 0, prg_file._bss_segment_size))
        file_info.add_bss_segment(-1, 0, prg_file._bss_segment_size, [], {})

    file_info.set_internal_data(prg_file)
    file_info.set_savefile_data(None)

    return True


def _read_symbol_table(file_info, data_types, prg_file, f):
    file_offset = SIZEOF_HEADER + prg_file._text_segment_size + prg_file._data_segment_size
    f.seek(file_offset, os.SEEK_SET)

    entry_count = prg_file._symbol_table_size / SIZEOF_SYMBOL_ENTRY
    if entry_count * SIZEOF_SYMBOL_ENTRY != prg_file._symbol_table_size:
        logger.debug("Symbol table size mismatch")
        return False

    l = []
    while len(l) != entry_count:
        symbol_name = f.read(8)
        # Strip unused space (null termination).
        idx = symbol_name.find("\0")
        if idx != -1:
            symbol_name = symbol_name[:idx]
        symbol_type = data_types.uint16(f.read(2))
        symbol_value = data_types.uint32(f.read(4))
        l.append((symbol_name, symbol_type, symbol_value))

    prg_file._symbol_table_entries = l
    return True


def _read_fixup_information(file_info, data_types, prg_file, f):
    file_offset = SIZEOF_HEADER + prg_file._text_segment_size + prg_file._data_segment_size + prg_file._symbol_table_size
    f.seek(file_offset, os.SEEK_SET)

    # First longword is an offset.  If it is NULL, there are no fixups to make.
    l = []
    offset = data_types.uint32(f.read(4))
    if offset != 0:
        offsets = [ offset ]

        maximum_offset = prg_file._text_segment_size + prg_file._data_segment_size
        while 1:
            byte = data_types.uint8(f.read(1))
            if byte == 0:
                break
            elif byte == 1:
                offset += 254
            else:
                offset += byte
                if offset < maximum_offset:
                    offsets.append(offset)
                else:
                    logger.debug("Fixup table data unexpected")
                    return False
        l.append((0, offsets))

    prg_file._fixup_offsets = l
    return True

SAVEFILE_VERSION = 1

def save_project_data(f, data):
    f.write(struct.pack("<H", SAVEFILE_VERSION))
    cPickle.dump(data, f, -1)
    return True

def load_project_data(f):
    savefile_version = struct.unpack("<H", f.read(2))[0]
    if savefile_version != SAVEFILE_VERSION:
        logger.error("Unable to load old savefile data, got: %d, wanted: %d", savefile_version, SAVEFILE_VERSION)
        return
    data = cPickle.load(f)
    return data


def print_summary(file_info):
    prg_file = file_info.file_data

    print "Text segment size:", prg_file._text_segment_size
    print "Data segment size:", prg_file._data_segment_size
    print "BSS segment size:", prg_file._bss_segment_size
    print "reserved1:", hex(prg_file._reserved1)
    print "reserved2:", hex(prg_file._reserved2)
    print "reserved3:", hex(prg_file._reserved3)

    print "# fixups:", sum(len(offsets) for (segment_id, offsets) in prg_file._fixup_offsets)

    print "# symbols:", len(prg_file._symbol_table_entries)
    if False:
        # Order the SYMBOL type masks from highest to lowest bits, for visual display.
        symbol_flags = [
            (k, v)
            for (k, v) in globals().items()
            if k.startswith("SYMBOL_") and k != "SYMBOL_SEGMENT_MASK"
        ]
        symbol_flags.sort(lambda a, b: cmp(a[1], b[1]))

        # List all the extracted symbols.
        for symbol_name, symbol_type, symbol_value in prg_file._symbol_table_entries:
            s = ""
            for i, (k, v) in enumerate(symbol_flags):
                if symbol_type & v:
                    if len(s) and i > 0:
                        s += " | "
                    s += k
            # if symbol_type & SYMBOL_SEGMENT_MASK == 0:
            print s, hex(symbol_value), symbol_name

