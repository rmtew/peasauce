"""
    Peasauce - interactive disassembler
    Copyright (C) 2012-2016 Richard Tew
    Licensed using the MIT license.
"""

## ProgramData related.

STATE_LOADING = 1
STATE_LOADED = 2

def program_data_set_state(program_data, state):
    program_data.state = state

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

def get_block_flags_data_type(flags):
    return (flags >> DATA_TYPE_BIT0) & DATA_TYPE_BITMASK

def get_data_type_block_flags(data_type):
    return ((data_type & DATA_TYPE_BITMASK) << DATA_TYPE_BIT0)

def get_block_data_type(block):
    return get_block_flags_data_type(block.flags)

def set_block_data_type(block, data_type):
    """
    NOTE: If this function is called after loading of an input file is complete, then it is 
          the responsibility of the caller to update the uncertain reference lists.
    """
    block.flags &= ~(DATA_TYPE_BITMASK << DATA_TYPE_BIT0)
    block.flags |= get_data_type_block_flags(data_type)

_block_event_func = None

def set_block_event_func(f):
    global _block_event_func
    _block_event_func = f

## SegmentBlock line data entry type ids.

SLD_INSTRUCTION = 1
SLD_COMMENT_TRAILING = 2
SLD_COMMENT_FULL_LINE = 3
SLD_EQU_LOCATION_RELATIVE = 4


PDF_BINARY_FILE = 1


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
        self.loader_relocatable_addresses = None # dict()
        self.loader_entrypoint_segment_id = None
        self.loader_entrypoint_offset = None
        self.loader_internal_data = None # PERSISTED VIA LOADERLIB

        # persistence exposed information:
        self.save_count = 0

        ## Non-persisted state.
        # Local:
        "State the program data is in."
        self.state = STATE_LOADING
        "List of ascending block addresses (used by bisect for address based lookups)."
        self.block_addresses = None # []
        "List of ascending block first line numbers (used by bisect for line number based lookups)."
        self.block_line0s = None # []
        "If list of first line numbers need recalculating, this is the entry to start at."
        self.block_line0s_dirtyidx = None # 0
        "Callback application can register to be notified."
        self.symbol_insert_func = None
        "Callback application can register to be notified."
        self.symbol_delete_func = None
        "Callback application can register to be notified."
        self.uncertain_reference_modification_func = None
        "Callback application can register to be notified."
        self.pre_line_change_func = None
        "Callback application can register to be notified."
        self.post_line_change_func = None
        "List of segment address ranges, used to validate addresses."
        self.address_ranges = None # []
        "Where the file was saved to, or loaded from."
        self.savefile_path = None
        "Newly created blocks, since this was set to non-None"
        self.new_block_events = None
        "Blocks that have had data type changes, since this was set to non-None"
        self.block_data_type_events = None

        # disassemblylib:
        self.dis_is_final_instruction_func = None
        self.dis_get_match_addresses_func = None
        self.dis_get_instruction_string_func = None
        self.dis_get_operand_string_func = None
        self.dis_disassemble_one_line_func = None
        self.dis_disassemble_as_data_func = None

        # loaderlib:
        self.loader_data_types = None

        # persistence exposed information:
        """ Whether the saved project embeds the input file in it's entirety. """
        self.input_file_cached = False


class SegmentBlock(object):
    """ Sequential numbering in order of creation. """
    sequence_id = None
    last_sequence_id = 0
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
    """ DATA_TYPE_CODE: [ line0_match, ... lineN_match ]. 
        DATA_TYPE_ASCII: [ (offset, length), ... ]. """
    line_data = None
    """ Calculated number of lines. """
    line_count = 0
    """ Cached potential address references. """
    references = None

    def __init__(self, copy_block=None):        
        if copy_block is not None:
            copy_block.copy_to(self)

        # Override the copied sequence_id so that copied references are distinct.
        self.sequence_id = SegmentBlock.last_sequence_id + 1
        SegmentBlock.last_sequence_id = self.sequence_id

    def __repr__(self):
        return "<SegmentBlock sid=%d address=%x>" % (self.sequence_id, self.address)

    def copy_to(self, new_block):
        new_block.sequence_id = self.sequence_id
        new_block.segment_id = self.segment_id
        new_block.segment_offset = self.segment_offset
        new_block.address = self.address
        new_block.length = self.length
        new_block.flags = self.flags
        new_block.line_data = self.line_data
        new_block.line_count = self.line_count
        new_block.references = self.references


class NewProjectOptions:
    # Binary file options.
    dis_name = None
    loader_load_address = None
    loader_entrypoint_offset = None

class LoadProjectOptions:
    valid_file_size = False
    valid_file_checksum = False

class SaveProjectOptions:
    input_file = None
    save_file_path = None
