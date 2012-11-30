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


## SegmentBlock flag field related.

def _count_bits(v):
    count = 0
    while v:
        count += 1
        v >>= 1
    return count

def _make_bitmask(bitcount):
    mask = 0
    while bitcount:
        bitcount -= 1
        mask |= 1<<bitcount
    return mask

DATA_TYPE_CODE          = 1
DATA_TYPE_ASCII         = 2
DATA_TYPE_BYTE          = 3
DATA_TYPE_WORD          = 4
DATA_TYPE_LONGWORD      = 5
DATA_TYPE_BIT0          = DATA_TYPE_CODE - 1
DATA_TYPE_BITCOUNT      = _count_bits(DATA_TYPE_LONGWORD)
DATA_TYPE_BITMASK       = _make_bitmask(DATA_TYPE_BITCOUNT)

""" Indicates that the block is not backed by file data. """
BLOCK_FLAG_ALLOC        = 1 << (DATA_TYPE_BITCOUNT+0)

""" Indicates that the block has been processed. """
BLOCK_FLAG_PROCESSED    = 1 << (DATA_TYPE_BITCOUNT+1)

""" The mask for the flags to preserve if the block is split. """
BLOCK_SPLIT_BITMASK     = BLOCK_FLAG_ALLOC | DATA_TYPE_BITMASK | BLOCK_FLAG_PROCESSED


NUMERIC_DATA_TYPES = (DATA_TYPE_LONGWORD, DATA_TYPE_WORD, DATA_TYPE_BYTE)

## SegmentBlock line data entry type ids.

SLD_INSTRUCTION = 1
SLD_COMMENT_TRAILING = 2
SLD_COMMENT_FULL_LINE = 3
SLD_EQU_LOCATION_RELATIVE = 4


PDF_CACHE_INPUT_DATA = 1

DEFAULT_PROGRAMDATA_FLAGS = PDF_CACHE_INPUT_DATA

class ProgramData(object):
    def __init__(self):
        ## Persisted state.
        # Local:
        self.branch_addresses = {}
        self.reference_addresses = {}
        self.symbols_by_address = {}
        "List of blocks ordered by ascending address."
        self.blocks = []
        "Extra lines for the last block in a segment, for trailing labels."
        self.post_segment_addresses = None # {}
        "Default flags"
        self.flags = 0

        # disassemblylib:
        "Identifies which architecture the file has been identified as belonging to."
        self.dis_name = None

        # loaderlib:
        "The file name of the original loaded file."
        self.file_name = None
        "The size of the original loaded file on disk."
        self.file_size = None
        "When file data is not stored within saved work, this allows verification of substitute files."
        self.file_checksum = None
        self.loader_system_name = None
        self.loader_segments = []
        self.loader_relocated_addresses = None # set()
        self.loader_relocatable_addresses = None # set()
        self.loader_entrypoint_segment_id = None
        self.loader_entrypoint_offset = None
        self.loader_internal_data = None # PERSISTED VIA LOADERLIB

        ## Non-persisted state.
        # Local:
        "List of ascending block addresses (used by bisect for address based lookups)."
        self.block_addresses = None # []
        "List of ascending block first line numbers (used by bisect for line number based lookups)."
        self.block_line0s = None # []
        "If list of first line numbers need recalculating, this is the entry to start at."
        self.block_line0s_dirtyidx = None # 0
        "Callback application can register to be notified."
        self.symbol_insert_func = None
        "List of segment address ranges, used to validate addresses."
        self.address_ranges = None # []
        "Where the file was saved to, or loaded from."
        self.savefile_path = None

        # disassemblylib:
        self.dis_is_final_instruction_func = None
        self.dis_get_match_addresses_func = None
        self.dis_get_instruction_string_func = None
        self.dis_get_operand_string_func = None
        self.dis_disassemble_one_line_func = None
        self.dis_disassemble_as_data_func = None

        # loaderlib:
        self.loader_file_path = None
        self.loader_data_types = None


class SegmentBlock(object):
    """ The number of this segment in the file. """
    segment_id = None
    """ The offset of this block in its segment. """
    segment_offset = None
    """ All segments appear as one contiguous address space.  This is the offset of this block in that space. """
    address = None
    """ The number of bytes data that this block contains. """
    length = None
    """ The data type of this block (DATA_TYPE_*) and more """
    flags = 0
    """ DATA_TYPE_CODE: [ line0_match, ... lineN_match ]. """
    line_data = None
    """ Calculated number of lines. """
    line_count = 0


class NewProjectOptions:
    cache_input_data = True

    # Binary file options.
    dis_name = None
    loader_load_address = None
    loader_entrypoint_offset = None

class LoadProjectOptions:
    valid_file_size = False
    valid_file_checksum = False

    cache_input_data = True
    loader_file_path = None

class SaveProjectOptions:
    cache_input_data = True
