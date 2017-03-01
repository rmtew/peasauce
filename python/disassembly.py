"""
    Peasauce - interactive disassembler
    Copyright (C) 2012-2017 Richard Tew
    Licensed using the MIT license.
"""

DEBUG_ANNOTATE_DISASSEMBLY = True

# COPIED FROM archm68k.py
MAF_CODE = 1
MAF_ABSOLUTE_ADDRESS = 2
MAF_CONSTANT_VALUE = 4
MAF_UNCERTAIN = 8
MAF_CERTAIN = 16

import binascii
import bisect
import copy
import logging
import operator
import os
import threading
import types
# mypy-lang support
from typing import Tuple, List, Set, Union, Any, Callable

import loaderlib
import disassemblylib
import disassemblylib.util
import disassembly_data
import disassembly_persistence
import persistence
import util
# mypy-lang support
from disassembly_util import WorkState

logger = logging.getLogger("disassembly")

#
# TODO(rmtew):  The locking conundrum.  Currently we have enough locking to avoid problems.  But it's correct, and likely does not solve real problems.
#
# There are two actors that can be involved in race conditions.
# 1) The main thread which receives events and reacts by asking for display data from the state manager (this file) on the main thread.
# 2) The active logic thread in progress, which is changing data types and may be in the act of modifying data.
# 
# The active logic thread cannot lock everything for the duration of it's action, or the main thread will not be able to do it's job of continually updating the display.
# The main thread will already be doing an abstract isolated action (get line count, get detail for some line in the display) so can lock for the duration of it's action.
#
# The implication seems to be that the active logic should be inverted and prolonged actions where possible divided into individually locked sub-steps.
# 

line_count_rlock = threading.RLock()

LI_OFFSET = 0
LI_BYTES = 1
LI_LABEL = 2
LI_INSTRUCTION = 3
LI_OPERANDS = 4
if DEBUG_ANNOTATE_DISASSEMBLY:
    LI_ANNOTATIONS = 5


## TODO: Move elsewhere and make per-arch.

class DisplayConfiguration(object):
    trailing_line_exit = True
    trailing_line_branch = True
    trailing_line_trap = True

display_configuration = DisplayConfiguration()

## Typing aliases
Instruction = disassemblylib.util.Match
InstructionEntryLite = Tuple[int, Union[int, Instruction]]
InstructionEntry = Tuple[int, Instruction]
Address = int
LineNumber = int
UncertainReference = Tuple[int, int, str]

## disassembly_data.SegmentBlock flag helpers

def create_instruction_entry(program_data, block, block_offset):
    # type: (disassembly_data.ProgramData, disassembly_data.SegmentBlock, int) -> Instruction
    """
    Disassemble the data at the given block offset to get the instruction located there.
    """
    data = loaderlib.get_segment_data(program_data.loader_segments, block.segment_id)
    data_offset_start = block.segment_offset + block_offset
    match, data_offset_end = program_data.dis_disassemble_one_line_func(data, data_offset_start, block.address + block_offset)
    if match is None:
        raise RuntimeError("Catastrophic failure. data_ofs=%d block/seg_ofs=%d mem_addr=%x data_len=%d" % (data_offset_start, block.segment_offset, block.address + block_offset, len(data)))
    return match

def get_instruction_entry(program_data, block, line_data, idx, cache=True):
    # type: (disassembly_data.ProgramData, disassembly_data.SegmentBlock, List[InstructionEntryLite], int, bool) -> Instruction
    """
    An instruction entry is runtime data.  There's nothing in there that cannot be recreated by redisassembling
    the data at the given address.  So, if the entry is the segment data offset, then that can in turn be
    used to recreate the instruction at that address.

    Calling this function will check for the lite entry, and replace it with the real one.
    """
    entry = line_data[idx][1]
    if isinstance(entry, int):
        entry = create_instruction_entry(program_data, block, entry)
        if cache:
            line_data[idx] = (disassembly_data.SLD_INSTRUCTION, entry)
    return entry

def find_previous_instruction(program_data, block, line_data, idx):
    # type: (disassembly_data.ProgramData, disassembly_data.SegmentBlock, List[InstructionEntryLite], int) -> Tuple[int, Union[None, Instruction]]
    """
    Get the preceding instruction of the given type and it's line index within the block.
    This will generate the instruction entry if it does not exist.
    """
    while idx > 0:
        idx -= 1
        if line_data[idx][0] == disassembly_data.SLD_INSTRUCTION:
            return idx, get_instruction_entry(program_data, block, line_data, idx)
    return idx, None

SEGMENT_HEADER_LINE_COUNT = 2

def get_block_header_line_count(program_data, block):
    # type: (disassembly_data.ProgramData, disassembly_data.SegmentBlock) -> int
    if block.segment_offset == 0 and loaderlib.has_segment_headers(program_data.loader_system_name):
        return SEGMENT_HEADER_LINE_COUNT
    return 0


def get_instruction_line_count(program_data, match):
    # type: (disassembly_data.ProgramData, Instruction) -> int
    line_count = 1
    # TODO(rmtew): Make non-architecture specific.  m68k = should be a per-instruction configuration?
    if display_configuration.trailing_line_trap and match.specification.key == "TRAP":
        line_count += 1
    elif display_configuration.trailing_line_branch and match.specification.key in ("Bcc", "DBcc",):
        line_count += 1
    return line_count


def get_block_line_count(program_data, block):
    """ line_count_rlock: irrelevant """
    # type: (disassembly_data.ProgramData, disassembly_data.SegmentBlock) -> int
    # Overwrite the old line count, it's OK, we've notified any removal if necessary.
    line_count = get_block_header_line_count(program_data, block)

    data_type = disassembly_data.get_block_data_type(block)
    if data_type == disassembly_data.DATA_TYPE_CODE:
        for line_idx, (type_id, entry) in enumerate(block.line_data):
            if type_id == disassembly_data.SLD_INSTRUCTION:
                entry = get_instruction_entry(program_data, block, block.line_data, line_idx)
                line_count += get_instruction_line_count(program_data, entry)
            elif type_id in (disassembly_data.SLD_COMMENT_FULL_LINE, disassembly_data.SLD_EQU_LOCATION_RELATIVE):
                line_count += 1
    elif data_type in disassembly_data.NUMERIC_DATA_TYPES:
        sizes = get_data_type_sizes(block)
        for data_size, num_bytes, size_count, size_lines in sizes:
            line_count += size_lines
    elif data_type == disassembly_data.DATA_TYPE_ASCII:
        line_count = len(block.line_data)
    else:
        # This will cause an error, but if it is happening, there are larger problems.
        raise Exception("unexpected code path")

    segments = program_data.loader_segments
    if block.segment_offset + block.length == loaderlib.get_segment_length(segments, block.segment_id):
        # Any addresses not within a segment, get potentially displayed as extra lines after that segment.
        addresses = program_data.post_segment_addresses.get(block.segment_id)
        if addresses is not None:
            line_count += len(addresses)

    discard, block_idx = lookup_block_by_address(program_data, block.address)
    line_count += get_block_footer_line_count(program_data, block, block_idx)

    return line_count

def api_get_code_block_info_for_address(program_data, address):
    # type: (disassembly_data.ProgramData, int) -> Union[None, InstructionEntry]
    with line_count_rlock:
        return get_code_block_info_for_address(program_data, address)

# NOTE(rmtew): Called from two locations, guarded by line count lock.
def get_code_block_info_for_address(program_data, address):
    # type: (disassembly_data.ProgramData, int) -> Union[None, InstructionEntry]
    block, block_idx = lookup_block_by_address(program_data, address)
    base_address = program_data.block_addresses[block_idx]

    bytes_used = 0
    line_number = get_block_line_number(program_data, block_idx) + get_block_header_line_count(program_data, block)
    previous_result = None
    for line_idx, (type_id, entry) in enumerate(block.line_data):
        if type_id == disassembly_data.SLD_INSTRUCTION:
            # Within but not at the start of the previous instruction.
            if address < base_address + bytes_used:
                return previous_result

            entry = get_instruction_entry(program_data, block, block.line_data, line_idx)
            current_result = line_number, entry

            # Exactly this instruction.
            if address == base_address + bytes_used:
                return current_result

            previous_result = current_result
            bytes_used += entry.num_bytes
            line_number += get_instruction_line_count(program_data, entry)
        elif type_id in (disassembly_data.SLD_COMMENT_FULL_LINE, disassembly_data.SLD_EQU_LOCATION_RELATIVE):
            line_number += 1

    # Within but not at the start of the previous instruction.
    if address < base_address + bytes_used:
        return previous_result

# NOTE(rmtew): All users at this time use line count locking.
def get_code_block_info_for_line_number(program_data, line_number):
    # type: (disassembly_data.ProgramData, int) -> Union[None, InstructionEntry]
    block, block_idx = lookup_block_by_line_count(program_data, line_number)
    if disassembly_data.get_block_data_type(block) != disassembly_data.DATA_TYPE_CODE:
        return None
    base_address = program_data.block_addresses[block_idx]

    bytes_used = 0
    line_count = get_block_line_number(program_data, block_idx) + get_block_header_line_count(program_data, block)
    previous_result = None # type: Union[None, InstructionEntry]
    for line_idx, (type_id, entry) in enumerate(block.line_data):
        if type_id == disassembly_data.SLD_INSTRUCTION:
            # Within but not at the start of the previous instruction.
            if line_number < line_count:
                line_type = None
                if previous_result is not None:
                    line_type = hex(previous_result[0])
                #logger.debug("get_code_block_info_for_line_number.1: %d, %d = %s", line_number, line_count, line_type)
                return previous_result

            entry = get_instruction_entry(program_data, block, block.line_data, line_idx)
            current_result = base_address + bytes_used, entry

            # Exactly this instruction.
            if line_number == line_count:
                #logger.debug("get_code_block_info_for_line_number.1: %d, %d = %s (code)", line_number, line_count, hex(current_result[0]))
                return current_result

            previous_result = current_result
            bytes_used += entry.num_bytes
            line_count += get_instruction_line_count(program_data, entry)
        elif type_id in (disassembly_data.SLD_COMMENT_FULL_LINE, disassembly_data.SLD_EQU_LOCATION_RELATIVE):
            if line_number == line_count:
                #logger.debug("get_code_block_info_for_line_number.1: %d, %d = %s (comment/location-relative)", line_number, line_count, hex(base_address + entry))
                return base_address + entry, previous_result[1]
            line_count += 1
    # Within but not at the start of the previous instruction.
    if line_number < line_count:
        logger.debug("get_code_block_info_for_line_number.2: %d, %d = %s", line_number, line_count, hex(previous_result[0]))
        return previous_result

    #logger.debug("get_code_block_info_for_line_number.3: %d, %d", line_number, line_count)
    # return None, previous_result

# NOTE(rmtew): Called from three places, all guarded by line count lock.
def get_line_number_for_address(program_data, address):
    """ line_count_rlock """
    # type: (disassembly_data.ProgramData, int) -> Union[None, int]
    block, block_idx = lookup_block_by_address(program_data, address)
    data_type = disassembly_data.get_block_data_type(block)
    if data_type == disassembly_data.DATA_TYPE_CODE:
        result = get_code_block_info_for_address(program_data, address)
        return result[0]

    block_offsetN = 0
    block_lineN = None
    if data_type in disassembly_data.NUMERIC_DATA_TYPES:
        block_lineN = get_block_line_number(program_data, block_idx) + get_block_header_line_count(program_data, block)
        address_block_offset = address - block.address
        for data_size, num_bytes, size_count, size_lines in get_data_type_sizes(block):
            block_offset0 = block_offsetN
            block_offsetN += num_bytes * size_count
            block_line0 = block_lineN
            block_lineN += size_lines
            if address_block_offset >= block_offset0 and address_block_offset < block_offsetN:
                return block_line0 + (address_block_offset - block_offset0) / num_bytes
    elif data_type == disassembly_data.DATA_TYPE_ASCII:
        block_lineN = get_block_line_number(program_data, block_idx) + get_block_header_line_count(program_data, block)
        address_block_offset = address - block.address
        for byte_offset, byte_length in block.line_data:
            block_offset0 = block_offsetN
            block_offsetN += byte_length
            block_line0 = block_lineN
            block_lineN += 1
            if address_block_offset >= block_offset0 and address_block_offset < block_offsetN:
                return block_line0

    if block_offsetN > 0 and block_lineN is not None and block_idx == len(program_data.blocks)-1:
        addresses = program_data.post_segment_addresses.get(block.segment_id, [])
        line0 = block_lineN
        for i, post_segment_address in enumerate(addresses):
            if address + i == post_segment_address:
                return line0 + i

    return None

def api_get_address_for_line_number(program_data, line_number):
    # type: (disassembly_data.ProgramData, int) -> Union[int, None]
    with line_count_rlock:
        return get_address_for_line_number(program_data, line_number)

# NOTE(rmtew): Called from two functions which are guarded by line count lock.
def get_address_for_line_number(program_data, line_number):
    # type: (disassembly_data.ProgramData, int) -> Union[int, None]
    block, block_idx = lookup_block_by_line_count(program_data, line_number)

    data_type = disassembly_data.get_block_data_type(block)
    #logger.debug("get_address_for_line_number: data type = %d", data_type)

    if data_type == disassembly_data.DATA_TYPE_CODE:
        result = get_code_block_info_for_line_number(program_data, line_number)
        if result is not None:
            address, match = result
            return address
    elif data_type in disassembly_data.NUMERIC_DATA_TYPES:
        base_line_count = get_block_line_number(program_data, block_idx) + get_block_header_line_count(program_data, block)
        block_lineN = base_line_count
        block_offsetN = 0
        for data_size, num_bytes, size_count, size_lines in get_data_type_sizes(block):
            block_offset0 = block_offsetN
            block_offsetN += num_bytes * size_count
            block_line0 = block_lineN
            block_lineN += size_lines
            if line_number >= block_line0 and line_number < block_lineN:
                return block.address + block_offset0 + (line_number - block_line0) * num_bytes
    elif data_type == disassembly_data.DATA_TYPE_ASCII:
        base_line_count = get_block_line_number(program_data, block_idx) + get_block_header_line_count(program_data, block)
        block_lineN = base_line_count
        block_offsetN = 0
        for byte_offset, byte_length in block.line_data:
            block_offset0 = block_offsetN
            block_offsetN += byte_length
            block_line0 = block_lineN
            block_lineN += 1
            if line_number >= block_line0 and line_number < block_lineN:
                return block.address + block_offset0

    return None

def api_get_referenced_symbol_addresses_for_line_number(program_data, line_number):
    # type: (disassembly_data.ProgramData, int) -> List[int]
    with line_count_rlock:
        return get_referenced_symbol_addresses_for_line_number(program_data, line_number)

# NOTE(rmtew): Only used by API, and really needs line locking.
def get_referenced_symbol_addresses_for_line_number(program_data, line_number):
    # type: (disassembly_data.ProgramData, int) -> List[int]
    result = get_code_block_info_for_line_number(program_data, line_number)
    if result is not None:
        address, match = result
        return [
			k
			for (k, v) in program_data.dis_get_match_addresses_func(match).iteritems()
			if k in program_data.symbols_by_address
		]

    block, block_idx = lookup_block_by_line_count(program_data, line_number)
    data_type = disassembly_data.get_block_data_type(block)
    if data_type == disassembly_data.DATA_TYPE_DATA32:
        address = get_address_for_line_number(program_data, line_number)
        data = loaderlib.get_segment_data(program_data.loader_segments, block.segment_id)
        value = program_data.loader_data_types.uint32_value(data, block.segment_offset + (address - block.address))
        if value in program_data.symbols_by_address:
            return [ value ]

    return []


"""
This may be of future use, but what it should return remains to be decided.

def get_all_references(program_data):
    for target_address, referring_addresses in program_data.reference_addresses.iteritems():
        target_block, target_block_idx = lookup_block_by_address(program_data, target_address)
        if target_block.address != target_address:
            logger.error("get_all_references: analysing reference referrers, target address mismatch: %X != %X", target_block.address, target_address)
            continue
        if disassembly_data.get_block_data_type(target_block) == disassembly_data.DATA_TYPE_DATA32:
            for source_address in referring_addresses:
                source_block, source_block_idx = lookup_block_by_address(program_data, source_address)
                if disassembly_data.get_block_data_type(source_block) == disassembly_data.DATA_TYPE_CODE:
                    line_number, match = get_code_block_info_for_address(program_data, source_address)
"""

def get_data_type_sizes(block):
    # type: (disassembly_data.SegmentBlock) -> List[Tuple[int, int, int, int]]
    block_data_size = disassembly_data.get_block_data_type(block)
    size_types = disassembly_data.DESCENDING_DATA_TYPE_SIZES[block_data_size]

    sizes = []
    unconsumed_byte_count = block.length
    for data_size, num_bytes in size_types:
        size_count = unconsumed_byte_count / num_bytes
        if size_count == 0:
            continue
        if block.flags & disassembly_data.BLOCK_FLAG_ALLOC:
            size_lines = 1
        else:
            size_lines = size_count
        sizes.append((data_size, num_bytes, size_count, size_lines))
        unconsumed_byte_count -= size_count * num_bytes
    return sizes

def get_block_footer_line_count(program_data, block, block_idx):
    # type: (disassembly_data.ProgramData, disassembly_data.SegmentBlock, int) -> int
    """ We may be working with a temporary block copy, so the block index
        should only be used for the purpose of comparing neighbouring
        blocks. """
    line_count = 0
    segments = program_data.loader_segments
    if block.segment_offset + block.length == loaderlib.get_segment_length(segments, block.segment_id):
        if block.segment_id < len(segments)-1:
            line_count += 1 # SEGMENT FOOTER (blank line)
    elif disassembly_data.get_block_data_type(block) == disassembly_data.DATA_TYPE_CODE:
        entry_type_id, entry = block.line_data[-1]
        if entry_type_id == disassembly_data.SLD_INSTRUCTION:
            line_idx = len(block.line_data) - 1
            entry = get_instruction_entry(program_data, block, block.line_data, line_idx)
            if display_configuration.trailing_line_exit:
                discard, preceding_entry = find_previous_instruction(program_data, block, block.line_data, line_idx)
                if program_data.dis_is_final_instruction_func(entry, preceding_entry):
                    line_count += 1

        if False:
            # Separating line between code block and following non-code block (only if not final instruction).
            if line_count == 0 and block_idx+1 < len(program_data.blocks):
                next_block = program_data.blocks[block_idx+1]
                if next_block.segment_id == block.segment_id:
                    if disassembly_data.get_block_data_type(next_block) != disassembly_data.DATA_TYPE_CODE:
                        line_count += 1
    else:
        if False:
            # Separating line between non-code block and following code block.
            if block_idx+1 < len(program_data.blocks):
                next_block = program_data.blocks[block_idx+1]
                if next_block.segment_id == block.segment_id:
                    if disassembly_data.get_block_data_type(next_block) == disassembly_data.DATA_TYPE_CODE:
                        line_count += 1
    return line_count

def get_file_footer_line_count(program_data):
    # type: (disassembly_data.ProgramData) -> int
    last_block_idx = len(program_data.blocks)-1
    last_block = program_data.blocks[last_block_idx]
    if get_block_footer_line_count(program_data, last_block, last_block_idx) > 0:
        return 1
    return 2

def api_get_file_line_count(program_data):
    # type: (disassembly_data.ProgramData) -> int
    with line_count_rlock:
        return get_file_line_count(program_data)

def get_file_line_count(program_data):
    # type: (disassembly_data.ProgramData) -> int
    """ Get the total number of lines (with 0 being the first) in the 'file'. """
    if program_data.block_line0s is None:
        return 0
    last_block_idx = len(program_data.blocks)-1
    last_block = program_data.blocks[last_block_idx]
    return get_block_line_number(program_data, last_block_idx) + get_block_line_count_cached(program_data, last_block) + get_file_footer_line_count(program_data)

def DEBUG_check_file_line_count(program_data):
    # type: (disassembly_data.ProgramData) -> None
    return
    result = get_file_line_count(program_data)
    line_count0 = line_count1 = get_file_footer_line_count(program_data)
    for block in program_data.blocks:
        line_count0 += get_block_line_count(program_data, block)
        line_count1 += get_block_line_count_cached(program_data, block)
    #if line_count0 != result or line_count1 != result:
    #print "LINE COUNTS", result, line_count0, line_count1

def api_get_file_line(program_data, line_idx, column_idx):
    """ line_count_rlock """
    # type: (disassembly_data.ProgramData, int, int) -> str
    return get_file_line(program_data, line_idx, column_idx)

def get_file_line(program_data, line_idx, column_idx): # Zero-based
    """ line_count_rlock """
    # type: (disassembly_data.ProgramData, int, int) -> str
    if line_idx is None:
        return "BAD ROW"
    if column_idx is None:
        return "BAD COLUMN"
    with line_count_rlock:
        block, block_idx = lookup_block_by_line_count(program_data, line_idx)
        block_line_count0 = get_block_line_number(program_data, block_idx)
        block_line_countN = block_line_count0 + get_block_line_count_cached(program_data, block)
    segments = program_data.loader_segments

    # If the line is at the start of the first segment, check if it is a segment header.
    leading_line_count = 0
    if block.segment_offset == 0 and loaderlib.has_segment_headers(program_data.loader_system_name):
        # First line is the segment header.
        if line_idx == block_line_count0:
            segment_address = loaderlib.get_segment_address(segments, block.segment_id)
            segment_header = loaderlib.get_segment_header(program_data.loader_system_name, block.segment_id, program_data.loader_internal_data)
            i = segment_header.find(" ")
            if column_idx == LI_INSTRUCTION:
                return segment_header[0:i]
            elif column_idx == LI_OPERANDS:
                return segment_header[i+1:].format(address=segment_address)
            else:
                return ""
        # Second line is a blank one separating the header from what follows.
        if line_idx == block_line_count0+1:
            return ""
        leading_line_count += SEGMENT_HEADER_LINE_COUNT

    if block.segment_offset + block.length == loaderlib.get_segment_length(segments, block.segment_id):
        # Account for the inter-segment blank line.
        trailing_line_count = block.segment_id < len(segments)-1
        addresses = program_data.post_segment_addresses.get(block.segment_id, [])
        trailing_line_count += len(addresses)
        address_idx = line_idx - (block_line_countN-trailing_line_count)
        if address_idx > -1:
            # Whether there are trailing post-segment labels.
            if address_idx < len(addresses):
                if column_idx == LI_OFFSET:
                    return "%08X" % addresses[address_idx]
                elif column_idx == LI_LABEL:
                    return get_symbol_for_address(program_data, addresses[address_idx])
                elif column_idx == LI_INSTRUCTION:
                    return "EQU"
                elif column_idx == LI_OPERANDS:
                    last_address = loaderlib.get_segment_address(segments, block.segment_id)
                    last_address += block.segment_offset + block.length
                    address_offset = addresses[address_idx] - last_address
                    if address_offset == 0:
                        return "*"
                    return "*+$%X" % address_offset
                return ""
            # Whether there is am inter-segment blank line.
            if address_idx == len(addresses) and address_idx+1 == trailing_line_count:
                return ""

    ## End of list "special" line generation.
    with line_count_rlock:
        final_block_idx = len(program_data.blocks)-1
        final_block = program_data.blocks[final_block_idx]
        file_footer_line_idx = get_block_line_number(program_data, final_block_idx) + get_block_line_count_cached(program_data, final_block)
        file_footer_line_count = get_file_footer_line_count(program_data)

    # Potential trailing footer separating blank line between last block and END directive.
    if file_footer_line_count == 2 and line_idx == file_footer_line_idx:
        return ""
    # Potential trailing footer END directive.
    if line_idx == file_footer_line_idx+file_footer_line_count-1:
        if column_idx == LI_INSTRUCTION:
            return "END"
        return ""

    data_type = disassembly_data.get_block_data_type(block)

    ## Block content line generation.
    if data_type == disassembly_data.DATA_TYPE_CODE:
        block_offset0 = 0
        block_offsetN = 0
        line_count = block_line_count0 + leading_line_count
        line_type_id = None
        line_match = None
        line_num_bytes = None
        for idx_e, (type_id, entry) in enumerate(block.line_data):
            if type_id == disassembly_data.SLD_INSTRUCTION:
                entry = get_instruction_entry(program_data, block, block.line_data, idx_e)
                block_offsetN += entry.num_bytes
            if line_count == line_idx:
                line_type_id = type_id
                line_match = entry
                break
            if type_id == disassembly_data.SLD_INSTRUCTION:
                block_offset0 = block_offsetN
                line_count += get_instruction_line_count(program_data, entry)
            elif type_id in (disassembly_data.SLD_COMMENT_FULL_LINE, disassembly_data.SLD_EQU_LOCATION_RELATIVE):
                line_count += 1
        else:
            # Trailing blank lines.
            return ""

        address0 = block.address + block_offset0
        addressN = block.address + block_offsetN
        if line_type_id == disassembly_data.SLD_EQU_LOCATION_RELATIVE:
            segment_address = loaderlib.get_segment_address(segments, block.segment_id)
            block_offset0 = line_match
            address0 = segment_address + block.segment_offset + block_offset0
        line_num_bytes = addressN - address0

        if column_idx == LI_OFFSET:
            return "%08X" % address0
        elif column_idx == LI_BYTES:
            if line_type_id in (disassembly_data.SLD_INSTRUCTION, disassembly_data.SLD_EQU_LOCATION_RELATIVE):
                data = loaderlib.get_segment_data(segments, block.segment_id)
                data_offset = block.segment_offset + block_offset0
                return binascii.hexlify(data[data_offset:data_offset+line_num_bytes])
            return ""
        elif column_idx == LI_LABEL:
            label = get_symbol_for_address(program_data, address0)
            if label is None:
                return ""
            return label
        elif column_idx == LI_INSTRUCTION:
            if line_type_id == disassembly_data.SLD_INSTRUCTION:
                return program_data.dis_get_instruction_string_func(line_match, line_match.vars)
            elif line_type_id == disassembly_data.SLD_EQU_LOCATION_RELATIVE:
                return "EQU"
            return ""
        elif column_idx == LI_OPERANDS:
            if line_type_id == disassembly_data.SLD_INSTRUCTION:
                lookup_symbol = lambda address, absolute_info=None: get_symbol_for_address(program_data, address, absolute_info)
                operand_string = ""
                # TODO(rmtew): Make non-architecture specific.  m68k = operand seperator, configurable spacing, assembler-specific setting?
                for i, operand in enumerate(line_match.opcodes):
                    if i > 0:
                        operand_string += ", "
                    operand_string += program_data.dis_get_operand_string_func(line_match, operand, lookup_symbol=lookup_symbol)
                return operand_string
            elif line_type_id == disassembly_data.SLD_EQU_LOCATION_RELATIVE:
                return "*-%d" % line_num_bytes
            return ""
        elif DEBUG_ANNOTATE_DISASSEMBLY and column_idx == LI_ANNOTATIONS:
            if line_type_id == disassembly_data.SLD_INSTRUCTION:
                l = []
                for o in line_match.opcodes:
                    key = o.specification.key
                    if o.key is not None and key != o.key:
                        l.append(o.key)
                    else:
                        l.append(key)
                return line_match.specification.key +" "+ ",".join(l)
            return ""
    elif data_type in disassembly_data.NUMERIC_DATA_TYPES:
        block_lineN = block_line_count0 + leading_line_count
        block_offsetN = block.segment_offset
        sizes = get_data_type_sizes(block)
        for i, (data_size, num_bytes, size_count, size_lines) in enumerate(sizes):
            block_offset0 = block_offsetN
            block_offsetN += num_bytes * size_count
            block_line0 = block_lineN
            block_lineN += size_lines

            if line_idx >= block_line0 and line_idx < block_lineN:
                data_idx = block_offset0 + (line_idx - block_line0) * num_bytes
                if column_idx == LI_OFFSET:
                    return "%08X" % (loaderlib.get_segment_address(segments, block.segment_id) + data_idx)
                elif column_idx == LI_BYTES:
                    if block.flags & disassembly_data.BLOCK_FLAG_ALLOC:
                        return ""
                    data = loaderlib.get_segment_data(segments, block.segment_id)
                    return binascii.hexlify(data[data_idx:data_idx+num_bytes])
                elif column_idx == LI_LABEL:
                    symbol_address = loaderlib.get_segment_address(segments, block.segment_id) + data_idx
                    label = get_symbol_for_address(program_data, symbol_address)
                    if label is None:
                        return ""
                    return label
                elif column_idx == LI_INSTRUCTION:
                    with_file_data = (block.flags & disassembly_data.BLOCK_FLAG_ALLOC) != disassembly_data.BLOCK_FLAG_ALLOC
                    return loaderlib.get_data_instruction_string(program_data.loader_system_name, segments, block.segment_id, data_size, with_file_data)
                elif column_idx == LI_OPERANDS:
                    if block.flags & disassembly_data.BLOCK_FLAG_ALLOC:
                        return str(size_count)
                    data = loaderlib.get_segment_data(segments, block.segment_id)
                    value = program_data.loader_data_types.sized_value(data_size, data, data_idx)
                    label = None

                    # TODO(rmtew): Should this be per-architecture pointer sized, not just 32 bit?
                    if data_size == disassembly_data.DATA_TYPE_DATA32:
                        referring_address = loaderlib.get_segment_address(segments, block.segment_id) + data_idx
                        label = get_potential_symbol_for_address(program_data, value, referring_address)
                        
                    if label is None:
                        label = ("$%0"+ str(num_bytes<<1) +"X") % value
                    return label
                elif DEBUG_ANNOTATE_DISASSEMBLY and column_idx == LI_ANNOTATIONS:
                    return "-"
    elif data_type == disassembly_data.DATA_TYPE_ASCII:
        block_lineN = block_line_count0 + leading_line_count
        block_offsetN = block.segment_offset
        for i, (byte_offset, byte_length) in enumerate(block.line_data):
            block_offset0 = block_offsetN
            block_offsetN += byte_length
            block_line0 = block_lineN
            block_lineN += 1

            if line_idx >= block_line0 and line_idx < block_lineN:
                data_idx = block_offset0
                if column_idx == LI_OFFSET:
                    return "%08X" % (loaderlib.get_segment_address(segments, block.segment_id) + data_idx)
                elif column_idx == LI_BYTES:
                    data = loaderlib.get_segment_data(segments, block.segment_id)
                    return binascii.hexlify(data[data_idx:data_idx+byte_length])
                elif column_idx == LI_LABEL:
                    label = get_symbol_for_address(program_data, loaderlib.get_segment_address(segments, block.segment_id) + data_idx)
                    if label is None:
                        return ""
                    return label
                elif column_idx == LI_INSTRUCTION:
                    return loaderlib.get_data_instruction_string(program_data.loader_system_name, segments, block.segment_id, disassembly_data.DATA_TYPE_DATA08, True)
                elif column_idx == LI_OPERANDS:
                    string = ""
                    last_value = None
                    data = loaderlib.get_segment_data(segments, block.segment_id)
                    # TODO(rmtew): Make non-architecture specific.  m68k = comma separation?
                    for char in data[data_idx:data_idx+byte_length]:
                        byte = ord(char)
                        if byte >= 32 and byte < 127:
                            # Sequential displayable characters get collected into a contiguous string.
                            value = chr(byte)
                            if type(last_value) is not str:
                                if last_value is not None:
                                    string += ","
                                string += "'"
                            string += value
                        else:
                            # Non-displayable characters are appended as separate pieces of data.
                            value = byte
                            if last_value is not None:
                                if type(last_value) is str:
                                    string += "'"
                                string += ","
                            string += _get_byte_representation(chr(byte))
                        last_value = value
                    if last_value is not None:
                        if type(last_value) is str:
                            string += "'"
                    return string
                elif DEBUG_ANNOTATE_DISASSEMBLY and column_idx == LI_ANNOTATIONS:
                    return "-"
    raise Exception("unhandled case")

def check_known_address(program_data, address):
    # type: (disassembly_data.ProgramData, int) -> bool
    """
    Returns True if the address is valid.  Valid addresses are of two kinds, addresses that
    fall within the known address ranges for segments, and specific addresses the lie outside
    of segments.

    NOTE(rmtew): I'm not sure how well this works, given we only accept post segment addresses
    at 1 byte higher than the end of the any segment that precedes it.
    """
    pre_ids = set() # type: Set[int]
    for address0, addressN, segment_ids in program_data.address_ranges:
        if address < address0:
            pass
        elif address > addressN:
            pre_ids.update(segment_ids)
            break
        else:
            return True

    if address == addressN + 1:
        # At this point we have an address that lies outside segment address spaces.
        pre_segment_id = -1
        if len(pre_ids):
            pre_segment_id = max(pre_ids)
            addresses = program_data.post_segment_addresses.get(pre_segment_id, None)
            if addresses is None:
                program_data.post_segment_addresses[pre_segment_id] = [ address ]
            elif address not in addresses:
                addresses.append(address)
                addresses.sort()
        return True
    else:
        pass # logger.debug("Found address not within segment address spaces: %X, excess: %d, pre segment_id: %s", address, address - addressN, pre_ids)
    return False

def insert_branch_address(program_data, address, src_abs_idx, pending_symbol_addresses):
    # type: (disassembly_data.ProgramData, int, int, Set[int]) -> bool
    if not check_known_address(program_data, address):
        return False
    # These get split as their turn to be disassembled comes up.
    program_data.branch_addresses.setdefault(address, set()).add(src_abs_idx)
    pending_symbol_addresses.add(address)
    return True

def remove_uncertain_reference(program_data, data_type, referring_address1, referred_address1):
    new_block, new_block_idx = lookup_block_by_address(program_data, referring_address1)
    for t in new_block.references:
        referring_address2, referred_address2, text = t
        if referring_address1 == referring_address2:
            if referred_address1 == referred_address2:
                new_block.references.remove(t)
                if program_data.uncertain_reference_modification_func is not None:
                    program_data.uncertain_reference_modification_func(data_type, data_type, referring_address1, 4)
                break

def insert_reference_address(program_data, address, src_abs_idx, pending_symbol_addresses):
    # type: (disassembly_data.ProgramData, int, int, Set[int]) -> bool
    if not check_known_address(program_data, address):
        return False
    _insert_reference_address(program_data, address, src_abs_idx)
    pending_symbol_addresses.add(address)
    return True

def _insert_reference_address(program_data, at_address, value):
    program_data.reference_addresses.setdefault(at_address, set()).add(value)

def api_get_referring_addresses(program_data, address):
    return get_referring_addresses(program_data, address)

def get_referring_addresses(program_data, address):
    # type: (disassembly_data.ProgramData, int) -> Set[int]
    referring_addresses = set() # type: Set[int]
    referring_addresses.update(program_data.branch_addresses.get(address, set()))
    referring_addresses.update(program_data.reference_addresses.get(address, set()))
    other_addresses = program_data.loader_relocated_addresses.get(address, None)
    if other_addresses is not None:
        referring_addresses.update(other_addresses)
    return referring_addresses

def api_set_symbol_insert_func(program_data, f):
    # type: (disassembly_data.ProgramData, Callable[[int, str], None]) -> None
    program_data.symbol_insert_func = f

def api_set_symbol_delete_func(program_data, f):
    # type: (disassembly_data.ProgramData, Callable[[int, str], None]) -> None
    program_data.symbol_delete_func = f

def set_symbol_for_address(program_data, address, symbol_label):
    # type: (disassembly_data.ProgramData, int, str) -> bool
    if not check_known_address(program_data, address):
        return False

    for existing_symbol_label in program_data.symbols_by_address.itervalues():
        if symbol_label == existing_symbol_label:
            return False

    program_data.symbols_by_address[address] = symbol_label
    if program_data.symbol_insert_func:
        program_data.symbol_insert_func(address, symbol_label)

    return True

def get_symbol_for_address(program_data, address, absolute_info=None):
    # type: (disassembly_data.ProgramData, int, Tuple[int, int]) -> str
    # If the address we want a symbol was relocated somewhere, verify the instruction got relocated.
    if absolute_info is not None:
        valid_address = False
        referring_instruction_address, num_instruction_bytes = absolute_info
        if program_data.flags & disassembly_data.PDF_BINARY_FILE == disassembly_data.PDF_BINARY_FILE:
            # This gets called for values.  All values of the given kind, not just the ones that
            # actually were picked up as references.  We need to verify they are known references.
            if referring_instruction_address in get_referring_addresses(program_data, address):
                valid_address = True
        elif address in program_data.loader_relocated_addresses:
            # For now, check all instruction bytes as addresses to see if they were relocated within.
            search_address = referring_instruction_address
            while search_address < referring_instruction_address + num_instruction_bytes:
                if search_address in program_data.loader_relocatable_addresses:
                    valid_address = True
                    break
                search_address += 1
    else:
        valid_address = True
    if valid_address:
        return program_data.symbols_by_address.get(address)

def get_potential_symbol_for_address(program_data, symbol_address, referring_address=None):
    if referring_address in program_data.reference_addresses:
        if symbol_address in program_data.reference_addresses[referring_address]:
            return program_data.symbols_by_address.get(symbol_address)

    #if program_data.flags & disassembly_data.PDF_BINARY_FILE == disassembly_data.PDF_BINARY_FILE:
    #    if check_known_address(program_data, symbol_address):
    #        return program_data.symbols_by_address.get(symbol_address, None)
    #    return None

    # This case only applies if the address of the data had that address relocated within it.
    if symbol_address in program_data.loader_relocated_addresses:
        if referring_address in program_data.loader_relocated_addresses[symbol_address]:
            return program_data.symbols_by_address.get(symbol_address)
        return None

    return None


def process_pending_symbol_address(program_data, address):
    if address not in program_data.symbols_by_address:
        block, block_idx = lookup_block_by_address(program_data, address)
        if block.address != address:
            result = split_block(program_data, address, own_midinstruction=True)
            # Add in labels for out of bounds addresses, they should be displayed.
            if IS_SPLIT_ERR(result[1]):
                # These are the only possible block splitting errors.
                if result[1] == ERR_SPLIT_BOUNDS:
                    label = program_data.dis_get_default_symbol_name_func(address, disassemblylib.constants.DIS_ID_BOUNDS)
                    set_symbol_for_address(program_data, address, label)
                elif result[1] == ERR_SPLIT_MIDINSTRUCTION:
                    label = program_data.dis_get_default_symbol_name_func(address, disassemblylib.constants.DIS_ID_MIDINSTRUCTION)
                    set_symbol_for_address(program_data, address, label)
                else:
                    logger.error("_process_address_as_code/labeling: At $%06X unexpected splitting error #%d", address, result[1])
                    return False
                return True
            block, block_idx = result
        return set_symbol_for_address(program_data, address, _get_auto_label_for_block(program_data, block, address))
    return False

def _recalculate_line_count_index(program_data, dirtyidx=None):
    # type: (disassembly_data.ProgramData, int) -> None
    with line_count_rlock:
        if dirtyidx is None:
            dirtyidx = program_data.block_line0s_dirtyidx
        elif program_data.block_line0s_dirtyidx is not None:
            dirtyidx = min(dirtyidx, program_data.block_line0s_dirtyidx)

        if dirtyidx is not None:
            # logger.debug("Recalculated line counts, from idx %d", dirtyidx)
            line_count_start = 0
            if dirtyidx > 0:
                line_count_start = program_data.block_line0s[dirtyidx-1] + get_block_line_count_cached(program_data, program_data.blocks[dirtyidx-1])
            for i in xrange(dirtyidx, len(program_data.block_line0s)):
                program_data.block_line0s[i] = line_count_start
                line_count_start += get_block_line_count_cached(program_data, program_data.blocks[i])
            program_data.block_line0s_dirtyidx = None

def get_block_line_number(program_data, block_idx):
    """ line_count_rlock """
    # type: (disassembly_data.ProgramData, int) -> int
    with line_count_rlock:
        _recalculate_line_count_index(program_data)
        return program_data.block_line0s[block_idx]

def clear_block_line_count(program_data, block, block_idx=None):
    """ line_count_rlock """
    # type: (disassembly_data.ProgramData, disassembly_data.SegmentBlock, int) -> None
    with line_count_rlock:
        if block_idx is None:
            discard, block_idx = lookup_block_by_address(program_data, block.address)
        block.line_count = 0
        if program_data.block_line0s_dirtyidx is None or block_idx < program_data.block_line0s_dirtyidx:
            program_data.block_line0s_dirtyidx = block_idx

def get_block_line_count_cached(program_data, block):
    # type: (disassembly_data.ProgramData, disassembly_data.SegmentBlock) -> int
    if block.line_count == 0:
        block.line_count = get_block_line_count(program_data, block)
    return block.line_count

def lookup_block_by_line_count(program_data, lookup_key):
    """ line_count_rlock """
    # type: (disassembly_data.ProgramData, int) -> Tuple[disassembly_data.SegmentBlock, int]
    with line_count_rlock:
        _recalculate_line_count_index(program_data)
        lookup_index = bisect.bisect_right(program_data.block_line0s, lookup_key)
    return program_data.blocks[lookup_index-1], lookup_index-1

def lookup_block_by_address(program_data, lookup_key):
    # type: (disassembly_data.ProgramData, int) -> Tuple[disassembly_data.SegmentBlock, int]
    lookup_index = bisect.bisect_right(program_data.block_addresses, lookup_key)
    return program_data.blocks[lookup_index-1], lookup_index-1

def insert_block(program_data, insert_idx, block):
    """ line_count_rlock """
    # type: (disassembly_data.ProgramData, int, disassembly_data.SegmentBlock) -> None
    with line_count_rlock:
        program_data.block_addresses.insert(insert_idx, block.address)
        program_data.blocks.insert(insert_idx, block)

        program_data.block_line0s.insert(insert_idx, None)
        # Update how much of the sorted line number index needs to be recalculated.
        if program_data.block_line0s_dirtyidx is None or insert_idx < program_data.block_line0s_dirtyidx:
            program_data.block_line0s_dirtyidx = insert_idx

ERR_SPLIT_EXISTING = -1
ERR_SPLIT_BOUNDS = -2
ERR_SPLIT_MIDINSTRUCTION = -3

def IS_SPLIT_ERR(value):
    # type: (int) -> bool
    return value < 0

def split_block(program_data, address, own_midinstruction=False):
    """ line_count_rlock """
    # type: (disassembly_data.ProgramData, int, bool) -> Tuple[disassembly_data.SegmentBlock, int]
    """
    Locate the block at `address` and split it if possible.
    own_midinstruction: Where something refers to an address mid-instruction in a code block, split it and add a relative EQU to deal with it.

    CONSTRAINT: This function should preserve line count.
    """
    block, block_idx = lookup_block_by_address(program_data, address)
    if block.address == address:
        return block, ERR_SPLIT_EXISTING

    segments = program_data.loader_segments
    segment_address = loaderlib.get_segment_address(segments, block.segment_id)
    segment_length = loaderlib.get_segment_length(segments, block.segment_id)
    if address < segment_address or address >= segment_address + segment_length:
        logger.error("Tried to split at out of bounds address: %06X not within %06X-%06X", address, segment_address, segment_address+segment_length-1)
        return block, ERR_SPLIT_BOUNDS

    block_data_type = disassembly_data.get_block_data_type(block)

    # How long the new block will be.
    split_offset = address - block.address
    excess_length = block.length - split_offset
    block_length_reduced = block.length - excess_length

    # Do some pre-split code block validation.
    if block_data_type == disassembly_data.DATA_TYPE_CODE:
        offsetN = 0
        for i, (type_id, entry) in enumerate(block.line_data):
            # Comments are assumed to be related to succeeding instruction lines, so are grouped for purposes of splitting.
            if type_id in (disassembly_data.SLD_INSTRUCTION, disassembly_data.SLD_COMMENT_FULL_LINE):
                if block_length_reduced == offsetN:
                    break

            if type_id == disassembly_data.SLD_INSTRUCTION:
                entry = get_instruction_entry(program_data, block, block.line_data, i)
                offsetN += entry.num_bytes
                if block_length_reduced < offsetN:
                    if own_midinstruction:
                        # Multiple consecutive entries of this type will be out of order.  Not worth bothering about.
                        block.line_data.insert(i+1, (disassembly_data.SLD_EQU_LOCATION_RELATIVE, split_offset))
                        clear_block_line_count(program_data, block, block_idx)
                    else:
                        logger.debug("Attempting to split block mid-instruction (not handled here): %06X", address)
                    return block, ERR_SPLIT_MIDINSTRUCTION

        # Line data: divide between blocks at the given point.
        block_line_data = block.line_data[:i]
        split_block_line_data = block.line_data[i:]

        # Line data: rebase block offsets within new block entries.
        for i, (type_id, entry) in enumerate(split_block_line_data):
            if type_id in (disassembly_data.SLD_EQU_LOCATION_RELATIVE, disassembly_data.SLD_INSTRUCTION) and type(entry) is int:
                split_block_line_data[i] = (type_id, entry-split_offset)

        if address & 1:
            logger.debug("Splitting code block at odd address: %06X", address)

    # References: divide between blocks at the given address.
    if block.references is not None and len(block.references):
        for i, entry in enumerate(block.references):
            if entry[0] >= address:
                break
        new_block_references = block.references[i:]
        block.references[i:] = []
    else:
        new_block_references = None

    # Truncate the preceding block the address is currently within.
    block.length = block_length_reduced

    # Create a new block for the address we are processing.
    new_block = disassembly_data.SegmentBlock()
    new_block.flags = block.flags & disassembly_data.BLOCK_SPLIT_BITMASK
    new_block.segment_id = block.segment_id
    new_block.segment_offset = block.segment_offset + block.length
    new_block.address = block.address + block.length
    new_block.length = excess_length
    new_block.references = new_block_references

    if block_data_type == disassembly_data.DATA_TYPE_CODE:
        block.line_data = block_line_data
        new_block.line_data = split_block_line_data
    elif block_data_type == disassembly_data.DATA_TYPE_ASCII:
        _process_block_as_ascii(program_data, block)
        _process_block_as_ascii(program_data, new_block)

    insert_block(program_data, block_idx + 1, new_block)
    clear_block_line_count(program_data, block, block_idx)
    on_block_created(program_data, new_block)

    return new_block, block_idx + 1

def _locate_uncertain_data_references(program_data, address, block=None):
    """ line_count_rlock """
    # type: (disassembly_data.ProgramData, int, disassembly_data.SegmentBlock) -> List[UncertainReference]
    """ Check for valid 32 bit addresses at all 16 bit aligned offsets within the data block from address onwards. """
    if block is None:
        block, block_idx = lookup_block_by_address(program_data, address)
    data = loaderlib.get_segment_data(program_data.loader_segments, block.segment_id)
    data_idx_start = block.segment_offset + (address - block.address)
    data_idx_end = block.segment_offset + block.length
    address_offset = 0
    matches = []
    f = program_data.loader_data_types.uint32_value
    while data_idx_start + address_offset + 4 <= data_idx_end:
        value = f(data, data_idx_start + address_offset)
        if check_known_address(program_data, value):
            with line_count_rlock:
                line_idx = get_line_number_for_address(program_data, address + address_offset)
                code_string = get_file_line(program_data, line_idx, LI_INSTRUCTION)
                operands_text = get_file_line(program_data, line_idx, LI_OPERANDS)
            if len(operands_text):
                code_string += " "+ operands_text
            matches.append((address + address_offset, value, code_string))
        address_offset += 2
    return matches

def _locate_uncertain_code_references(program_data, address, is_binary_file, block=None):
    """ line_count_rlock """
    # type: (disassembly_data.ProgramData, int, bool, disassembly_data.SegmentBlock) -> List[UncertainReference]
    """ Check for candidate operand values in instructions within the code block from address onwards. """
    if block is None:
        block, block_idx = lookup_block_by_address(program_data, address)
    matches = []
    addressN = block.address
    for i, (type_id, entry) in enumerate(block.line_data):
        if type_id == disassembly_data.SLD_INSTRUCTION:
            entry = get_instruction_entry(program_data, block, block.line_data, i)
            address0 = addressN
            addressN += entry.num_bytes
            if addressN >= address:
                for match_address, (opcode_idx, flags) in program_data.dis_get_match_addresses_func(entry).iteritems():
                    do_match = False
                    if is_binary_file:
                        do_match = flags & (MAF_ABSOLUTE_ADDRESS | MAF_CONSTANT_VALUE)
                    elif match_address not in program_data.loader_relocated_addresses:
                        do_match = flags & MAF_ABSOLUTE_ADDRESS
                    if do_match:
                        with line_count_rlock:
                            line_idx = get_line_number_for_address(program_data, address0)
                            code_string = get_file_line(program_data, line_idx, LI_INSTRUCTION)
                            operands_text = get_file_line(program_data, line_idx, LI_OPERANDS)
                        if len(operands_text):
                            code_string += " "+ operands_text
                        matches.append((address0, match_address, code_string))
    return matches

def set_data_type_at_address(program_data, address, data_type, work_state=None):
    """ line_count_rlock """
    # type: (disassembly_data.ProgramData, int, int, WorkState) -> None
    block, block_idx = lookup_block_by_address(program_data, address)
    set_block_data_type(program_data, data_type, block, block_idx=block_idx, work_state=work_state, address=address)

def set_block_data_type(program_data, data_type, block, block_idx=None, work_state=None, address=None):
    """ line_count_rlock """
    # type: (disassembly_data.ProgramData, int, disassembly_data.SegmentBlock, int, WorkState, int) -> None
    if address is None:
        address = block.address
    if block_idx is None:
        discard, block_idx = lookup_block_by_address(program_data, block.address)
    # If the block is already the given data type, no need to do anything.
    block_data_type = disassembly_data.get_block_data_type(block)
    if data_type == block_data_type:
        return
    # Preserve these as recalculated block information needs to be done for the whole range, not just after the split.
    original_block_address = block.address
    old_block_length = block.length
    original_block_idx = block_idx

    result = split_block(program_data, address)
    # If the address was within the address range of another block, split off a block at the given address and use that.
    if IS_SPLIT_ERR(result[1]):
        if result[1] != ERR_SPLIT_EXISTING:
            logger.error("set_block_data_type: At $%06X unexpected splitting error #%d", address, result[1])
            return
    else:
        block, block_idx = result

    # At this point we are attempting to change a block from one data type to another.
    program_data.new_block_events = []
    program_data.block_data_type_events = []
    if data_type == disassembly_data.DATA_TYPE_CODE:
        # Force this, so that the attempt can go ahead.
        block.flags &= ~disassembly_data.BLOCK_FLAG_PROCESSED
        # This can fail, so we do not explicitly change the block ourselves.
        _process_address_as_code(program_data, address, set([ ]), work_state)
    else:
        _internal_set_block_data(program_data, block, block_idx, data_type, old_block_length)

    event_blocks = {} # type: Dict[int, Tuple[disassembly_data.SegmentBlock, int, int, Union[int, None]]]
    for event_block in program_data.new_block_events:
        data_type = disassembly_data.get_block_data_type(event_block)
        data_type_old = None
        for t in program_data.block_data_type_events:
            if t[0].address < event_block.address and t[0].address + t[3] > event_block.address:
                data_type_old = t[1]
                break
        else:
            logger.warning("set_block_data_type: unable to identify old block data type for %x", event_block.address)
            # Assuming there was a simple split in this case.
            data_type_old = data_type
        event_blocks[event_block.address] = (event_block, data_type_old, data_type, None)
    for t in program_data.block_data_type_events:
        event_blocks[t[0].address] = t

    # The type of the block has been changed.  If the new type was code, then that may have cascaded changing the
    # type of other existing blocks, as well as splitting off parts of the original selected block.
    #
    # Blocks with changed types have to have new updated references,.
    # New blocks should already have up-to-date references.
    #
    # In both cases, events need to be broadcast as otherwise the only place events are broadcast is on file load.

    is_binary_file = (program_data.flags & disassembly_data.PDF_BINARY_FILE) == disassembly_data.PDF_BINARY_FILE
    for k, (affected_block, data_type_old, data_type_new, length_old) in event_blocks.iteritems():
        do_broadcast = False
        old_references = affected_block.references
        if data_type_new == disassembly_data.DATA_TYPE_CODE:
            affected_block.references = _locate_uncertain_code_references(program_data, affected_block.address, is_binary_file, affected_block)
        else:
            affected_block.references = _locate_uncertain_data_references(program_data, affected_block.address)
        if old_references != affected_block.references:
            do_broadcast = True
        if do_broadcast and program_data.uncertain_reference_modification_func is not None:
            #if program_data.state == disassembly_data.STATE_LOADED:
            #    print "BROADCAST", affected_block.sequence_id, hex(affected_block.address), "dt:", data_type_old, "->", data_type_new
            program_data.uncertain_reference_modification_func(data_type_old, data_type_new, affected_block.address, affected_block.length)
        #else:
        #    if program_data.state == disassembly_data.STATE_LOADED:
        #        print "NON-BROADCAST", affected_block.sequence_id, hex(affected_block.address), "dt:", data_type_old, "->", data_type_new

    logger.debug("Changed data type at %X to %d", address, data_type)


def _process_block_as_ascii(program_data, block):
    """ line_count_rlock: irrelevant """
    # type: (disassembly_data.ProgramData, disassembly_data.SegmentBlock) -> None
    """
    Ensure that the block line data contans metadata suitable for rendering the lines,
    and counting how many there are for the given data.
    """
    data = loaderlib.get_segment_data(program_data.loader_segments, block.segment_id)
    data_offset_start = block.segment_offset
    bytes_consumed = 0
    bytes_consumed0 = bytes_consumed
    block_line_data = []
    line_width = 0
    line_width_max = 40
    last_value = None
    while bytes_consumed < block.length:
        byte = data[data_offset_start+bytes_consumed]
        comma_separated = False
        char_line_width = 0
        if ord(byte) >= 32 and ord(byte) < 127:
            # Sequential displayable characters get collected into a contiguous string.
            value = byte
            if type(last_value) is not str:
                comma_separated = True
                char_line_width += 2 # start and end quoting characters for this character and all appended to it.
            char_line_width += 1 # char
        else:
            # Non-displayable characters are appended as separate pieces of data.
            value = byte
            comma_separated = last_value is not None
            byte_string = _get_byte_representation(byte)
            char_line_width += len(byte_string)
        if comma_separated:
            char_line_width += 1
        bytes_consumed += 1

        # Append to current line or start a new one?
        force_new_line = False
        # Trailing null bytes indicate the end of each string in the block.
        if last_value != 0 and value == 0:
            force_new_line = True
        if line_width + char_line_width > line_width_max or force_new_line:
            # Would make the current line too long, store the current one and make a new one.
            block_line_data.append((bytes_consumed0, bytes_consumed-bytes_consumed0))
            bytes_consumed0 = bytes_consumed
            line_width = char_line_width
            last_value = None
        else:
            # Still room in this line, add it on.
            line_width += char_line_width
            last_value = value
    if bytes_consumed != bytes_consumed0:
        block_line_data.append((bytes_consumed0, bytes_consumed-bytes_consumed0))
    block.line_data = block_line_data

def _get_byte_representation(byte):
    # type: (str) -> str
    v = ord(byte)
    if v < 16:
        return "%d" % v
    return "$%X" % v

__label_metadata = {
    disassembly_data.DATA_TYPE_CODE: disassemblylib.constants.DIS_ID_CODE,
    disassembly_data.DATA_TYPE_ASCII: disassemblylib.constants.DIS_ID_ASCII,
    disassembly_data.DATA_TYPE_DATA08: disassemblylib.constants.DIS_ID_DATA08,
    disassembly_data.DATA_TYPE_DATA16: disassemblylib.constants.DIS_ID_DATA16,
    disassembly_data.DATA_TYPE_DATA32: disassemblylib.constants.DIS_ID_DATA32,
}

def get_auto_label(program_data, address, data_type):
    # type: (disassembly_data.ProgramData, int, int) -> str
    label = program_data.dis_get_default_symbol_name_func(address, __label_metadata[data_type])
    # For now indicate whether address was relocated, to give a hint why there is a symbol, but no referrers.
    if address in program_data.loader_relocated_addresses:
        # TODO(rmtew): Make this configurable.
        label += "r"
    return label

def _get_auto_label_for_block(program_data, block=None, address=None, data_type=None):
    # type: (disassembly_data.ProgramData, disassembly_data.SegmentBlock, int, int) -> str
    if data_type is None:
        data_type = disassembly_data.get_block_data_type(block)
    if address is None:
        address = block.address
    return get_auto_label(program_data, address, data_type)

def DEBUG_get_instruction_repr(program_data, instruction):
    # type: (disassembly_data.ProgramData, Instruction) -> str
    result = program_data.dis_get_instruction_string_func(instruction, instruction.vars)
    lookup_symbol = lambda address, absolute_info=None: get_symbol_for_address(program_data, address, absolute_info)
    # TODO(rmtew): Make non-architecture specific.  m68k = operand seperator, configurable spacing, assembler-specific setting?
    for operand_index, operand in enumerate(instruction.opcodes):
        if operand_index > 0:
            result += ","
        result += " "+ program_data.dis_get_operand_string_func(instruction, operand, lookup_symbol=lookup_symbol)
    return result

def _internal_set_block_data(program_data, block, block_idx, new_data_type, old_block_length, line_data=None):
    with line_count_rlock:
        line0 = get_block_line_number(program_data, block_idx)
        old_line_count = get_block_line_count_cached(program_data, block)
        old_data_type = disassembly_data.get_block_data_type(block)

        # 2. Apply the change to a temporary block.
        temp_block = disassembly_data.SegmentBlock(block)
        disassembly_data.set_block_data_type(temp_block, new_data_type)

        if new_data_type == disassembly_data.DATA_TYPE_CODE:
            temp_block.line_data = line_data
        else:
            if new_data_type == disassembly_data.DATA_TYPE_ASCII:
                _process_block_as_ascii(program_data, temp_block)
            else:
                temp_block.line_data = None
            temp_block.flags &= ~disassembly_data.BLOCK_FLAG_PROCESSED

        temp_block.line_count = get_block_line_count(program_data, temp_block)

        # 3. Notify listeners the change is about to happen (with metadata).
        line_count_delta = temp_block.line_count - old_line_count
        if line_count_delta != 0:
            if program_data.pre_line_change_func:
                if line_count_delta > 0:
                    program_data.pre_line_change_func(line0 + old_line_count, line_count_delta)
                else:
                    program_data.pre_line_change_func(line0 + old_line_count + line_count_delta, line_count_delta)

        # 4. Make the change.
        temp_block.copy_to(block)

        if line_count_delta != 0:
            # We changed the line count, we need to flag a block line numbering recalculation.
            if program_data.block_line0s_dirtyidx is None or program_data.block_line0s_dirtyidx > block_idx+1:
                program_data.block_line0s_dirtyidx = block_idx+1

            if program_data.post_line_change_func:
                program_data.post_line_change_func(None, line_count_delta)

        on_block_data_type_change(program_data, block, old_data_type, new_data_type, old_block_length)

# NOTE(rmtew): Applied lock to the portion where the block is put in place and affects line counts.
def _process_address_as_code(program_data, address, pending_symbol_addresses, work_state=None):
    # type: (disassembly_data.ProgramData, int, Set[int], WorkState) -> None
    debug_offsets = set()
    disassembly_offsets = set([ address ])
    while len(disassembly_offsets):
        if work_state is not None:
            extra_fraction = sum(block.length for block in program_data.blocks if disassembly_data.get_block_data_type(block) == disassembly_data.DATA_TYPE_CODE) / float(program_data.file_size) * 0.6
            if work_state.check_exit_update(0.2 + extra_fraction, "TEXT_LOAD_DISASSEMBLY_PASS"):
                return

        address = disassembly_offsets.pop()
        block, block_idx = lookup_block_by_address(program_data, address)
        block_data_type = disassembly_data.get_block_data_type(block)
        old_block_length = block.length
        # When the address is mid-block, split the associated portion of the block off.
        if address - block.address > 0:
            result = split_block(program_data, address)
            if IS_SPLIT_ERR(result[1]):
                logger.debug("_process_address_as_code/focus: At $%06X unexpected splitting error #%d", address, result[1])
                continue
            block, block_idx = result
            # address = block.address Superfluous due to it being the split address.

        if block_data_type == disassembly_data.DATA_TYPE_CODE or (block.flags & disassembly_data.BLOCK_FLAG_PROCESSED) == disassembly_data.BLOCK_FLAG_PROCESSED:
            # logger.debug("_process_address_as_code[%X]: skipping because it is code (%s) or already processed (%s), data type (%d)", block.address, block_data_type == disassembly_data.DATA_TYPE_CODE, (block.flags & disassembly_data.BLOCK_FLAG_PROCESSED) == disassembly_data.BLOCK_FLAG_PROCESSED, disassembly_data.get_block_data_type(block))
            continue

        # Disassemble as much of the block's data as possible.
        bytes_consumed = 0
        data_bytes_to_skip = 0
        line_data = []
        found_terminating_instruction = False
        while bytes_consumed < block.length:
            data = loaderlib.get_segment_data(program_data.loader_segments, block.segment_id)
            data_offset_start = block.segment_offset + bytes_consumed
            match_address = address + bytes_consumed
            match, data_offset_end = program_data.dis_disassemble_one_line_func(data, data_offset_start, match_address)
            if match is None:
                # Likely bad disassembly.
                if data_offset_start >= len(data):
                    logger.error("unable to disassemble out of bound data address at %X (started at %X)", match_address, address)
                    break
                # Likely a known instruction we can't disassemble, but know the length of and want to leave as interleaved data.
                data_bytes_to_skip = program_data.dis_disassemble_as_data_func(data, data_offset_start)
                if data_bytes_to_skip == 0:
                    logger.error("unable to disassemble data at %X (started at %X)", match_address, address)
                break
            bytes_matched = data_offset_end - data_offset_start
            if bytes_consumed + bytes_matched > block.length:
                logger.error("unable to disassemble due to a block length overrun at %X (started at %X)", match_address, address)
                break
            line_data.append((disassembly_data.SLD_INSTRUCTION, match))
            current_idx = len(line_data)-1
            for label_offset in range(1, bytes_matched):
                label_address = match_address + label_offset
                label = program_data.symbols_by_address.get(label_address)
                if label is not None:
                    line_data.append((disassembly_data.SLD_EQU_LOCATION_RELATIVE, label_address - address))
                    #logger.debug("%06X: mid-instruction label = '%s' %d", match_address, label, label_address-match_address)
            bytes_consumed += bytes_matched
            discard, preceding_match = find_previous_instruction(program_data, block, line_data, current_idx)
            found_terminating_instruction = program_data.dis_is_final_instruction_func(match, preceding_match)
            if found_terminating_instruction:
                break

        # Discard any unprocessed block / jump over isolatible unprocessed instructions.
        if bytes_consumed < block.length:
            # [ (address, new_data_type, attempt_to_disassemble), ... ]
            split_addresses = []
            last_match_end_address = address + bytes_consumed
            longword_flags = disassembly_data.get_data_type_block_flags(disassembly_data.DATA_TYPE_DATA32)
            # Reasons we are here:
            if found_terminating_instruction:
                # 1. We reached a terminating instruction before the end of the block (found_terminating_instruction is True).
                #    ACTION: Split and mark trailing as of unprocessed longword type.
                split_addresses.append((last_match_end_address, longword_flags, False))
            elif data_bytes_to_skip:
                # 2. We encountered a known quantifiable instruction 'A' we could not disassemble (data_bytes_to_skip > 0).
                #    ACTION: Split before 'A' and mark it's block as processed longword type.
                split_addresses.append((last_match_end_address, longword_flags | disassembly_data.BLOCK_FLAG_PROCESSED, False))
                #    ACTION: Split after 'A' and mark trailing as of unprocessed longword type to be disassembled.
                split_addresses.append((last_match_end_address + data_bytes_to_skip, longword_flags, True))
            else:
                if bytes_consumed == 0:
                    # 3. Unexpected disassembly failure/error immediately at start of block.
                    pass
                else:
                    # 4. Unexpected disassembly failure/error but not at start of block.
                    #    ACTION: Split after last instruction and mark trailing as processed longword type.
                    split_addresses.append((last_match_end_address, longword_flags | disassembly_data.BLOCK_FLAG_PROCESSED, False))

            error = False
            for split_address, split_flags, will_disassemble in split_addresses:
                new_block, new_block_idx = split_block(program_data, split_address)
                if IS_SPLIT_ERR(new_block_idx):
                    logger.error("_process_address_as_code/unrecognised-code: At $%06X unexpected splitting error %d, block address %X, bytes consumed %d, found terminating instruction %s", split_address, new_block_idx, block.address, bytes_consumed, found_terminating_instruction)
                    error = True
                    break

                split_data_type = disassembly_data.get_block_flags_data_type(split_flags)
                set_block_data_type(program_data, split_data_type, new_block, block_idx=new_block_idx, work_state=work_state)
                if split_flags & disassembly_data.BLOCK_FLAG_PROCESSED:
                    new_block.flags |= disassembly_data.BLOCK_FLAG_PROCESSED
                if will_disassemble:
                    disassembly_offsets.add(split_address)
            # TODO: Behaviour when a splitting error happens should likely differ depending on which split it happens to.
            if error:
                block.flags |= disassembly_data.BLOCK_FLAG_PROCESSED
                continue

        # If there were no code statements identified, this will just be processed data.
        block.flags |= disassembly_data.BLOCK_FLAG_PROCESSED
        if len(line_data) == 0:
            continue

        _internal_set_block_data(program_data, block, block_idx, disassembly_data.DATA_TYPE_CODE, old_block_length, line_data)

        # Extract any addresses which are referred to, for later use.
        is_binary_file = (program_data.flags & disassembly_data.PDF_BINARY_FILE) == disassembly_data.PDF_BINARY_FILE
        for type_id, entry in line_data:
            if type_id == disassembly_data.SLD_INSTRUCTION:
                entry_address = entry.pc - program_data.dis_constant_pc_offset
                xxx = entry.pc
                for match_address, (opcode_idx, flags) in program_data.dis_get_match_addresses_func(entry).iteritems():
                    if flags & MAF_CODE:
                        disassembly_offsets.add(match_address)
                        insert_branch_address(program_data, match_address, entry_address, pending_symbol_addresses)
                    elif flags & (MAF_ABSOLUTE_ADDRESS | MAF_CONSTANT_VALUE):
                        if match_address in program_data.loader_relocated_addresses:
                            search_address = match_address
                            while search_address < match_address + entry.num_bytes:
                                if search_address in program_data.loader_relocatable_addresses:
                                    insert_reference_address(program_data, match_address, entry_address, pending_symbol_addresses)
                                    break
                                search_address += 1
                        elif is_binary_file and check_known_address(program_data, match_address) and program_data.dis_is_operand_pointer_sized(entry, entry.opcodes[opcode_idx]):
                            insert_reference_address(program_data, match_address, entry_address, pending_symbol_addresses)
                    elif flags & MAF_UNCERTAIN != MAF_UNCERTAIN:
                        # This code is unverified.  For relocated programs, it was creating symbols for arbitrary Imm values.
                        do_insert = None
                        if flags & MAF_CERTAIN or is_binary_file:
                            do_insert = True
                        elif match_address in program_data.loader_relocated_addresses:
                            do_insert = True
                        if do_insert:
                            insert_reference_address(program_data, match_address, entry_address, pending_symbol_addresses)
                        else:
                            # TODO: These need to be handled.
                            print "SKIP REF ADDRESS INSERT SYM, instruction address: %x operand address %x" % (entry_address, match_address)

        # DEBUG BLOCK SPILLING BASED ON LOGICAL ASSUMPTION OF MORE CODE.
        if bytes_consumed == block.length and not found_terminating_instruction and not data_bytes_to_skip:
            debug_offsets.add(block.address+block.length)

    # Add in all the detected new addresses with default labeling, and split accordingly.
    for address in pending_symbol_addresses:
        process_pending_symbol_address(program_data, address)

    for address in debug_offsets:
        block, block_idx = lookup_block_by_address(program_data, address)
        if disassembly_data.get_block_data_type(block) == disassembly_data.DATA_TYPE_CODE and block.flags & disassembly_data.BLOCK_FLAG_PROCESSED:
            continue
        logger.debug("%06X (%06X): Found end of block boundary with processed code and no end instruction (data type: %d, processed: %d)", address, block.address, disassembly_data.get_block_data_type(block), block.flags & disassembly_data.BLOCK_FLAG_PROCESSED)

def api_get_save_project_options(program_data):
    return disassembly_data.SaveProjectOptions()

def api_is_project_inputfile_cached(program_data):
    # type: (disassembly_data.ProgramData) -> bool
    return program_data.input_file_cached

def api_get_project_save_count(program_data):
    # type: (disassembly_data.ProgramData) -> int
    return program_data.save_count

## Project loading and saving.

def api_save_project_file(save_file, program_data, save_options):
    # (file, disassembly_data.ProgramData, disassembly_data.SaveProjectOptions) -> None
    return disassembly_persistence.save_project(save_file, program_data, save_options)


def api_load_project_file(save_file, file_name, work_state=None):
    # type: (file, str, WorkState) -> Tuple[disassembly_data.ProgramData, int]
    program_data = disassembly_persistence.load_project(save_file, work_state=work_state)
    if program_data is None:
        return None, 0

    program_data.file_name = file_name

    for block in program_data.blocks:
        if disassembly_data.get_block_data_type(block) == disassembly_data.DATA_TYPE_ASCII:
            _process_block_as_ascii(program_data, block)

    onload_set_disassemblylib_functions(program_data)
    onload_make_address_ranges(program_data)
    disassembly_data.program_data_set_state(program_data, disassembly_data.STATE_LOADED)

    DEBUG_log_load_stats(program_data)

    return program_data, get_file_line_count(program_data)

def api_load_file(input_file, new_options, file_name, work_state=None):
    """ line_count_rlock """
    # type: (file, disassembly_data.NewProjectOptions, str, WorkState) -> Tuple[disassembly_data.ProgramData, int]
    loader_options = None
    if new_options.is_binary_file:
        loader_options = loaderlib.BinaryFileOptions()
        loader_options.processor_id = new_options.processor_id
        loader_options.load_address = new_options.loader_load_address
        loader_options.entrypoint_offset = new_options.loader_entrypoint_offset

    if work_state is not None and work_state.check_exit_update(0.1, "TEXT_LOAD_ANALYSING_FILE"):
        return None

    result = loaderlib.load_file(input_file, file_name, loader_options)
    if result is None:
        return None

    file_info, data_types = result

    program_data = disassembly_persistence.ProgramData()
    flags = 0
    if new_options.is_binary_file:
        flags |= disassembly_data.PDF_BINARY_FILE
    program_data.flags |= flags
    program_data.block_addresses = []
    program_data.block_line0s = []
    program_data.block_line0s_dirtyidx = 0
    program_data.post_segment_addresses = {}

    program_data.loader_system_name = file_info.system.system_name
    program_data.loader_relocatable_addresses = set()
    program_data.loader_relocated_addresses = dict()

    program_data.file_name = file_name
    input_file.seek(0, os.SEEK_END)
    program_data.file_size = input_file.tell()
    program_data.file_checksum = util.calculate_file_checksum(input_file)
    program_data.processor_id = file_info.system.get_processor_id()

    segments = program_data.loader_segments = file_info.segments

    # Extract useful information from file loading process.
    program_data.loader_data_types = data_types
    program_data.loader_internal_data = file_info.get_savefile_data()

    onload_set_disassemblylib_functions(program_data)
    onload_make_address_ranges(program_data)

    program_data.loader_entrypoint_segment_id = file_info.entrypoint_segment_id
    program_data.loader_entrypoint_offset = file_info.entrypoint_offset
    for i in range(len(segments)):
        loaderlib.cache_segment_data(input_file, segments, i)
    loaderlib.relocate_segment_data(segments, data_types, file_info.relocations_by_segment_id, program_data.loader_relocatable_addresses, program_data.loader_relocated_addresses)

    # Start disassembling.
    entrypoint_address = loaderlib.get_segment_address(segments, program_data.loader_entrypoint_segment_id) + program_data.loader_entrypoint_offset

    if work_state is not None and work_state.check_exit_update(0.2, "TEXT_LOAD_ANALYSING_FILE"):
        return None

    # Pass 1: Create a block for each of the segments.
    for segment_id in range(len(segments)):
        address = loaderlib.get_segment_address(segments, segment_id)
        data_length = loaderlib.get_segment_data_length(segments, segment_id)
        segment_length = loaderlib.get_segment_length(segments, segment_id)

        block = disassembly_data.SegmentBlock()
        if loaderlib.is_segment_type_bss(segments, segment_id):
            block.flags |= disassembly_data.BLOCK_FLAG_ALLOC
        disassembly_data.set_block_data_type(block, disassembly_data.DATA_TYPE_DATA32)
        block.segment_id = segment_id
        block.segment_offset = 0
        block.address = address
        block.length = data_length
        program_data.block_addresses.append(block.address)
        program_data.block_line0s.append(None)
        program_data.blocks.append(block)

        on_block_created(program_data, block)

        if segment_length > data_length:
            block = disassembly_data.SegmentBlock()
            block.flags |= disassembly_data.BLOCK_FLAG_ALLOC
            disassembly_data.set_block_data_type(block, disassembly_data.DATA_TYPE_DATA32)
            block.segment_id = segment_id
            block.segment_offset = data_length
            block.address = address + data_length
            block.length = segment_length - data_length
            program_data.block_addresses.append(block.address)
            program_data.block_line0s.append(None)
            program_data.blocks.append(block)

            on_block_created(program_data, block)

    # Pass 2: Stuff.
    # Incorporate known symbols.
    for segment_id in range(len(segments)):
        symbols = file_info.symbols_by_segment_id[segment_id]
        address = loaderlib.get_segment_address(segments, segment_id)
        for symbol_offset, symbol_name, code_flag in symbols:
            set_symbol_for_address(program_data, address + symbol_offset, symbol_name)

    # Pass 3: Do a disassembly pass.
    # Static pre-known addresses to make into symbols / labels.
    existing_symbol_addresses = program_data.symbols_by_address.keys()
    pending_symbol_addresses = set(program_data.loader_relocated_addresses)
    pending_symbol_addresses.add(entrypoint_address)

    # Follow the disassembly at the given address, as far as it takes us.
    _process_address_as_code(program_data, entrypoint_address, pending_symbol_addresses, work_state=work_state)

    if work_state is not None and work_state.check_exit_update(0.9, "TEXT_LOAD_POSTPROCESSING"):
        return None

    # Split the blocks for existing symbols (so their label appears).
    for address in existing_symbol_addresses:
        result = split_block(program_data, address)
        if IS_SPLIT_ERR(result[1]):
            if result[1] in (ERR_SPLIT_EXISTING, ERR_SPLIT_MIDINSTRUCTION):
                continue
            logger.error("load_file: At $%06X unexpected splitting error #%d", address, result[1])

    platform_specific_processing(program_data)

    ## Any analysis / post-processing that does not change line count should go below.
    onload_cache_uncertain_references(program_data)

    disassembly_data.program_data_set_state(program_data, disassembly_data.STATE_LOADED)

    DEBUG_log_load_stats(program_data)

    return program_data, get_file_line_count(program_data)

# NOTE(rmtew): The following platform specific logic will eventually be refactored out to platform-specific plugings, and abstracted to common parts where possible.

def platform_specific_processing(program_data, work_state=None):
    # type: (disassembly_data.ProgramData, WorkState) -> None
    if program_data.processor_id == loaderlib.constants.PROCESSOR_M680x0:
        if program_data.loader_system_name == loaderlib.amiga.__name__:
            platform_specific_processing_M680x0_amiga(program_data, work_state)

AMIGA_EXEC_BASE_ADDRESS = 4

def platform_specific_processing_M680x0_amiga(program_data, work_state=None):
    # type: (disassembly_data.ProgramData, WorkState) -> None

    # Where library handles are fetched for usage.  key: fetch address.  value: (address_register_number, library_handle).
    library_handle_fetches = {} # type: Dict[int, Tuple[int, Union[None, int]]]
    # When library handles are used.  key: usage address.  value: (address_register_number, library_handle). 
    library_handle_usage = {} # type: Dict[int, Tuple[int, Union[None, int]]]
    # When a library handle is stored in a pointer.  key: None means exec library, otherwise handle address.  value: pointer addresses handle is copied to.  
    library_handle_stores = {} # type: Dict[Union[None, int], Set[int]]
    # When a library is opened.  key: open call address.  value: name_address
    library_open_calls = {} # type: Dict[int, int]

    # Locate likely library calls and potential exec base aliasing.
    library_calls = []
    for block in program_data.blocks:
        block_data_type = disassembly_data.get_block_data_type(block)
        if block_data_type == disassembly_data.DATA_TYPE_CODE:
            for line_idx, (type_id, instruction) in enumerate(block.line_data):
                if type_id == disassembly_data.SLD_INSTRUCTION:
                    instruction = get_instruction_entry(program_data, block, block.line_data, line_idx)
                    # Detect aliasing of exec base address i.e. `move.l address.w, variable`
                    if len(instruction.opcodes) == 2:
                        instruction_operand0 = instruction.opcodes[0]
                        instruction_operand1 = instruction.opcodes[1]
                        # We can follow references for real store addresses, but exec base is a special case (at least for now).
                        if instruction.specification.key == "MOVE.L" and instruction_operand0.key == "AbsW" and instruction_operand1.key == "AbsL":
                            source_address = program_data.dis_get_operand_value_func(instruction, instruction_operand0.key, instruction_operand0.vars)                            
                            if source_address == AMIGA_EXEC_BASE_ADDRESS:
                                destination_address = program_data.dis_get_operand_value_func(instruction, instruction_operand1.key, instruction_operand1.vars)
                                if None not in library_handle_stores:
                                    library_handle_stores[None] = set()
                                library_handle_stores[None].add(destination_address)
                    # Detect potential library calls i.e. `jsr offset(address_register)`
                    elif len(instruction.opcodes) == 1:
                        instruction_operand0 = instruction.opcodes[0]
                        if instruction.specification.key == "JSR" and instruction_operand0.key == "ARid16":
                            offset = program_data.dis_get_operand_value_func(instruction, instruction_operand0.key, instruction_operand0.vars)
                            register_number = instruction_operand0.vars["Rn"]
                            library_calls.append((instruction.pc - program_data.dis_constant_pc_offset, block, line_idx, register_number, offset))
    # TODO(rmtew): Maybe track copies of the registers.

    # Analyse calls and resolve interesting input register values.
    for (initial_address, initial_block, initial_line_idx, call_register, call_offset) in library_calls:
        # Search backward for the call register address source.
        find_address_register_source = True
        found_address_register_source = False
        track_address_registers = {}
        if call_offset == -408 or call_offset == -552:
            # If this is an exec library call, then the library name will be in the A1 register.
            track_address_registers[1] = True
        address_register_values = {}

        # TODO(rmtew): In theory, we would go back through references until we resolved everything.
        # However, as it stands with this being reactive to instruction matching, we may be mid-disassembly.
        # So it is best to do all analysis as a post-disassembly step.
        # - Can do jump table detection.
        # - Can do library and device usage.

        # We go backwards to try and find an instruction that sets this address register.
        current_block = initial_block
        current_line_data = initial_block.line_data
        current_line_idx = initial_line_idx
        current_instruction = current_line_data[current_line_idx][1]
        while find_address_register_source or track_address_registers:
            current_line_idx, current_instruction = find_previous_instruction(program_data, current_block, current_line_data, current_line_idx)
            if current_instruction is not None:
                current_instruction_address = current_instruction.pc - program_data.dis_constant_pc_offset
                current_s = DEBUG_get_instruction_repr(program_data, current_instruction) # TODO(rmtew): Remove when no longer needed for debugging.

                # We handle the one operand case, in case there are instructions with one operand that modify a register we are interested in.
                if len(current_instruction.opcodes) >= 1:
                    current_dest_operand = current_instruction.opcodes[-1]
                    current_dest_operand_values = program_data.dis_get_operand_values_func(current_instruction, current_dest_operand)
                    # At this time we are monitoring changes in address register values.
                    if "An" in current_dest_operand_values:
                        current_dest_register_number = current_dest_operand_values["An"][0]
                        if current_dest_register_number in track_address_registers:
                            if current_instruction.specification.key == "LEA":
                                current_source_operand = current_instruction.opcodes[0]
                                if current_source_operand.key in ("PCid16", "PCid8", "AbsW", "AbsL"):
                                    address_register_values[current_dest_register_number] = program_data.dis_get_operand_value_func(current_instruction, current_source_operand.key, current_source_operand.vars) 
                                else:
                                    raise Exception("Unexpected operand type", current_source_operand.key)
                                del track_address_registers[current_dest_register_number]
                                continue
                            logger.debug("on_instruction_matched: At $%06X A%d unhandled source is %s", current_instruction_address, call_register, current_instruction.specification.key)
                            break
                        if find_address_register_source and current_dest_register_number == call_register:
                            # Have we reached an instruction which makes a known usage of this address register?
                            usage_entry = library_handle_usage.get(current_instruction_address, None)
                            if usage_entry is not None:
                                if usage_entry[0] == current_dest_register_number:
                                    # If so, copy the usage for the initial instruction and we're done.
                                    library_handle_usage[initial_address] = usage_entry
                                    find_address_register_source = False
                                    found_address_register_source = True
                                    continue
                                # This is actually an error.  The register should be the same.
                            elif current_instruction.specification.key == "MOVEA.L" and current_instruction.opcodes[0].key in ("AbsW", "AbsL") and current_instruction.opcodes[1].specification.key == "AR":
                                current_source_operand_values = program_data.dis_get_operand_values_func(current_instruction, current_instruction.opcodes[0])
                                handle_address = current_source_operand_values["xxx"][0]
                                # Amiga exec library base address.  Note that if the program has data at address 4, there may be a clash here..  Hmm.
                                if handle_address == 4:
                                    handle_address = None
                                usage_entry = (current_dest_register_number, handle_address)
                                library_handle_fetches[current_instruction_address] = usage_entry
                                library_handle_usage[initial_address] = usage_entry
                                current_s = DEBUG_get_instruction_repr(program_data, current_instruction) # TODO(rmtew): Remove when no longer needed for debugging.
                                find_address_register_source = False
                                found_address_register_source = True
                                continue
                        if current_dest_register_number != call_register and current_dest_register_number not in track_address_registers:
                            continue
                        logger.debug("on_instruction_matched: At $%06X unable to locate A%d source", initial_address, call_register)
                        break # We give up as we have not handled this case yet.  Or it's an error.
                continue # Look at next preceding instruction.

            # TODO(rmtew): we should follow back references from here to more blocks.
            break # No reason to look at any more preceding instructions as everything is resolved.

        # Post-processing of the results from this call analysis?
        if not find_address_register_source and not track_address_registers:
            usage = library_handle_usage.get(initial_address, None)
            # Exec library and either of OpenLibrary or OldOpenLibrary?
            if (call_register, None) == usage and (call_offset == -408 or call_offset == -552):
                # At this point we know it's an exec open library call.
                if 1 in address_register_values:
                    library_name_address = address_register_values[1]

                    # Change the library name data type to ASCII.
                    library_name_block, library_name_block_idx = lookup_block_by_address(program_data, library_name_address)
                    set_block_data_type(program_data, disassembly_data.DATA_TYPE_ASCII, library_name_block, block_idx=library_name_block_idx, address=library_name_address, work_state=work_state)
                    library_name_block, library_name_block_idx = lookup_block_by_address(program_data, library_name_address)

                    # Rename the symbol if it has a stock name.
                    library_name_symbol = get_symbol_for_address(program_data, library_name_address)
                    if library_name_symbol is not None and library_name_symbol.startswith("lbL") and library_name_symbol.endswith("r"):
                        library_name_prefix = get_string_at_address(program_data, library_name_block, library_name_address)
                        if library_name_prefix is None:
                            library_name_prefix = "Unknown"
                        else:
                            period_idx = library_name_prefix.find(".")
                            library_name_prefix = library_name_prefix[:period_idx].capitalize()
                        library_name_prefix += "LibName"

                        duplicate_count = 1
                        library_name = library_name_prefix
                        while 1:
                            if set_symbol_for_address(program_data, library_name_address, library_name):
                                break
                            duplicate_count += 1
                            library_name = "%s%02d" % (library_name_prefix, duplicate_count)

                    library_open_calls[initial_address] = library_name_address
                else:
                    logger.debug("on_instruction_matched: At $%06X unable to locate open library A1 source", initial_address, call_register)

        # TODO(rmtew): Maybe search forward for the result destination.
        # Should be able to use the same logic as above with find_previous_instruction
        # But with find_next_instruction, just with direction parameter
        # Same set of registers to look for.
        # Whether putting the register or setting the register.
        # Putting may happen multiple times.
        # .. Keep looking until register overwritten?
        # Getting only needs to happen once, but we may need to follow back.

    analyser = CodeAnalysis(program_data)
    analyser.run()


DIRECTION_BACKWARD = -1
DIRECTION_FORWARD = 1

class RegisterAnalysisGoals(object):
    def __init__(self, direction):
        self.direction = direction # type: int
        # The list of register names to track down.
        self.register_values_pending = set([]) # type: Set[str]
        # Map the register name to the collection of address/value matches.
        self.register_values = {} # type: Dict[str, Dict[int,Instruction]]

    def clone(self):
        result =  RegisterAnalysisGoals(self.direction)
        result.register_values_pending = self.register_values_pending.copy()
        result.register_values = { k: copy.copy(v) for (k, v) in self.register_values.iteritems() }
        return result

    def track_register(self, register_name):
        # type: (str) -> None
        self.register_values_pending.add(register_name)
        self.register_values[register_name] = {}

    def stop_tracking_register(self, register_name):
        # type: (str) -> None
        self.register_values_pending.remove(register_name)

    def record_value(self, register_name, address, value):
        # type: (str, int, Instruction) -> None
        self.register_values[register_name][address] = value

    def is_incomplete(self):
        # type: () -> int
        return len(self.register_values_pending)

    def still_tracking_register(self, register_name):
        # type: (str) -> bool
        return register_name in self.register_values_pending

    def are_tracking_sources(self):
        # type: () -> bool
        return self.direction == DIRECTION_BACKWARD

    def are_tracking_destinations(self):
        # type: () -> bool
        return self.direction == DIRECTION_FORWARD

class M68KRuntimeContext(object):
    def __init__(self):
        self.registers = {}

class InstructionContext(object):
    def __init__(self, instruction, block, line_idx):
        self.instruction = instruction
        self.block = block
        self.line_idx = line_idx

class CodeAnalysis(object):
    def __init__(self, program_data):
        # type: (disassembly_data.ProgramData) -> None
        self.program_data = program_data
        self.library_calls = [] # type: List[Tuple[int, disassembly_data.SegmentBlock, int, str, int]]
        self.library_handle_stores = {} # type: Dict[Union[None, int], Set[int]]

        self._preprocess()

    def get_operand_register_name(self, instruction, operand_index):
        # type: (Instruction, int) -> str
        operand = instruction.opcodes[operand_index]
        operand_key = operand.key
        if operand_key is None:
            operand_key = operand.specification.key
        if operand_key == "AR":
            operand_values = self.program_data.dis_get_operand_values_func(instruction, operand)
            return operand_values["An"][1]
        elif operand_key == "DR":
            operand_values = self.program_data.dis_get_operand_values_func(instruction, operand)
            return operand_values["Dn"][1]

    def get_operand_value_address(self, instruction, operand_index):
        # type: (Instruction, int) -> int
        operand_values = self.program_data.dis_get_operand_values_func(instruction, instruction.opcodes[0])
        return operand_values["xxx"][0]

    def get_instruction_address(self, instruction):
        # type: (Instruction) -> int
        return instruction.pc - self.program_data.dis_constant_pc_offset

    def get_first_instruction(self, block):
        # type: (disassembly_data.SegmentBlock) -> Tuple[int, Union[None, Instruction]]
        block_data_type = disassembly_data.get_block_data_type(block)
        if block_data_type == disassembly_data.DATA_TYPE_CODE:
            for line_idx, (type_id, instruction) in enumerate(block.line_data):
                if type_id == disassembly_data.SLD_INSTRUCTION:
                    return line_idx, get_instruction_entry(self.program_data, block, block.line_data, line_idx)
        return 0, None

    def get_next_instruction(self, block, line_idx, direction):
        # type: (disassembly_data.SegmentBlock, int, int) -> Tuple[int, Union[None, Instruction]]
        """
        Get the next instruction of the given type and it's line index within the block.
        This will generate the instruction entry if it does not exist.
        """
        if direction not in (DIRECTION_FORWARD, DIRECTION_BACKWARD):
            raise Exception("bad direction", direction)
        while True:
            if direction == DIRECTION_FORWARD:
                if line_idx >= len(block.line_data)-1:
                    break
            elif direction == DIRECTION_BACKWARD:
                if line_idx <= 0:
                    break
            line_idx += direction
            if block.line_data[line_idx][0] == disassembly_data.SLD_INSTRUCTION:
                return line_idx, get_instruction_entry(self.program_data, block, block.line_data, line_idx)
        return line_idx, None

    def run(self):
        self._preprocess()

        # TODO(rmtew): This shouldn't be backwards.  It should just be back and forward as needed.

        if False:
            for (address, block, line_idx, register_name, call_offset) in self.library_calls:
                register_goals = RegisterAnalysisGoals(DIRECTION_BACKWARD)
                # Need register name.
                register_goals.track_register(register_name)
                self._resolve_register_values(block, line_idx, register_goals)

    def _preprocess(self):
        self.library_calls = []
        self.library_handle_stores = {} # 

        for block in self.program_data.blocks:
            line_idx, instruction = self.get_first_instruction(block)
            execbase_register_names = set()
            while instruction is not None:
                context = InstructionContext(instruction, block, line_idx)
                instruction_key = instruction.specification.key

                # TODO(rmtew):
                # 1. Detect if this instruction does a write to execbase_register_name.
                # 2. If so, clear execbase_register_name.
                # ... the last operand ... xxxx
                pass # ... xxx
                if len(execbase_register_names) and len(instruction.opcodes) > 0:
                    instr_s = DEBUG_get_instruction_repr(self.program_data, instruction)
                    handled = False
                    if instruction_key == "MOVEA.L":
                        src_register_name = self.get_operand_register_name(instruction, 0)
                        dst_register_name = self.get_operand_register_name(instruction, 1)
                        if src_register_name and dst_register_name:
                            if src_register_name in execbase_register_names:
                                execbase_register_names.add(dst_register_name)
                                handled = True
                    if not handled and instruction.opcodes[-1].specification.key == "AR":
                        register_name = self.get_operand_register_name(instruction, -1)
                        if register_name in execbase_register_names:
                            execbase_register_names.remove(register_name)

                if instruction_key == "JSR":
                    if instruction.opcodes[0].key == "ARid16":
                        operand_values = self.program_data.dis_get_operand_values_func(instruction, instruction.opcodes[0])
                        offset_value, register_name = operand_values["D16"][0], operand_values["An"][1]
                        # Found a call to Exec library.  We can identify it, and finish tracing it later.
                        if register_name in execbase_register_names:
                            pass
                        # self.library_calls.append((self.get_instruction_address(instruction), block, line_idx, register_name, offset_value))
                elif instruction_key == "MOVEA.L":
                    if instruction.opcodes[0].key == "AbsW":
                        source_address = self.get_operand_value_address(instruction, 0)
                        if source_address == 4:
                            # This is a light form of Exec library call tracking.
                            execbase_register_names.add(self.get_operand_register_name(instruction, 1))
                elif instruction_key == "MOVE.L":
                    if instruction.opcodes[0].key == "AbsW":
                        source_address = self.program_data.dis_get_operand_value_func(instruction, instruction.opcodes[0].key, instruction.opcodes[0].vars)
                        if source_address == 4:
                            # Catch storing the exec library base address in secondary locations.
                            # TODO(rmtew): This should be examined more closely, what if it shares the location with other handles?  Who knows why they did this?
                            if instruction.opcodes[1].key == "AbsL":
                                destination_address = self.program_data.dis_get_operand_value_func(instruction, instruction.opcodes[1].key, instruction.opcodes[1].vars)
                                if None not in self.library_handle_stores:
                                    self.library_handle_stores[None] = set()
                                self.library_handle_stores[None].add(destination_address)
                            else:
                                pass
                line_idx, instruction = self.get_next_instruction(block, line_idx, DIRECTION_FORWARD)
        pass

    def _trace_call(self, context):
        # ... xxx
        # Go up and get the source registers.
        ## Don't know what they are, besides the call base address register.
        ## Until the base call register is resolved.
        pass

    def _resolve_calls(self, initial_block, initial_idx, call_register_name):
        # type: (disassembly_data.SegmentBlock, int, str) -> None

        # NOTE(rmtew): Currently, this will start from the setting of execbase, then work it's way down to any trailing calls.
        # NOTE(rmtew): In theory, it should track other useful register values.
        current_block = initial_block
        current_idx = initial_idx
        visited_block_addresses = set([]) # type: Set[int]
        while True:
            # Exhaust all sources for a next instruction.
            direction = DIRECTION_FORWARD
            current_idx, instruction = self.get_next_instruction(current_block, current_idx, direction)
            if instruction is None:
                # TODO(rmtew): For initial implementation, give up when the initial block is exhausted.
                visited_block_addresses.add(current_block.address)
                # ... any reference that is followed from here, should proceed from this point ...
                # ... collect different results for each followed reference, detect clashes in input values ...
                if direction == DIRECTION_BACKWARD:
                    # ... is the preceding block a code block and is the last instruction a non-final instruction?
                    # ... does the first instruction have references by instructions in code blocks?
                    pass
                elif direction == DIRECTION_FORWARD:
                    # ... follow branches?  stop at final instructions?
                    # ... if final instruction in the block is not final, look to the next block and see if it is an instruction.
                    # ... if source return value is pointer, can ignore branches on eq condition
                    pass
                break

            instruction_key = instruction.specification.key
            if instruction_key == "JSR":
                if instruction.opcodes[0].key == "ARid16":
                    operand_values = self.program_data.dis_get_operand_values_func(instruction, instruction.opcodes[0])
                    offset_value, register_name = operand_values["D16"][0], operand_values["An"][1]
                    self.library_calls.append((self.get_instruction_address(instruction), current_block, initial_idx, register_name, offset_value))
            else:
                # TODO(rmtew): If the call register is clobbered, give up.
                # TODO(rmtew): Need to handle saves and restores?  pushes and pops?
                pass
        pass

    def _resolve_register_values(self, initial_block, initial_idx, register_goals):
        # type: (disassembly_data.SegmentBlock, int, RegisterAnalysisGoals) -> None
        """
        The direction implicitly determines if we are looking for register sources, or destinations.
        """
        # TODO(rmtew): Ideally this function will be architecture agnostic.  It will be necessary to improve the architecture infrastructure to support this.
        current_block = initial_block
        current_idx = initial_idx
        visited_block_addresses = set([]) # type: Set[int]
        while register_goals.is_incomplete():
            # Exhaust all sources for a next instruction.
            current_idx, instruction = self.get_next_instruction(current_block, current_idx, register_goals.direction)
            if instruction is None:
                # TODO(rmtew): For initial implementation, give up when the initial block is exhausted.
                visited_block_addresses.add(current_block.address)
                # ... any reference that is followed from here, should proceed from this point ...
                # ... collect different results for each followed reference, detect clashes in input values ...
                if register_goals.direction == DIRECTION_BACKWARD:
                    # ... is the preceding block a code block and is the last instruction a non-final instruction?
                    # ... does the first instruction have references by instructions in code blocks?
                    pass
                elif register_goals.direction == DIRECTION_FORWARD:
                    # ... follow branches?  stop at final instructions?
                    # ... if final instruction in the block is not final, look to the next block and see if it is an instruction.
                    # ... if source return value is pointer, can ignore branches on eq condition
                    pass
                break

            # ... if one operand, is not a source operand unless soemthing like a clear
            # ... otherwise, last operand is the destination operand.
            if register_goals.direction == DIRECTION_BACKWARD:
                if len(instruction.opcodes) == 2:
                    destination_register_name = self.get_operand_register_name(instruction, 1)
                    if destination_register_name is not None and register_goals.still_tracking_register(destination_register_name):
                        instruction_key = instruction.specification.key
                        if instruction_key in ("LEA", "MOVEA.L"):
                            register_goals.record_value(destination_register_name, self.get_instruction_address(instruction), instruction)
                            register_goals.stop_tracking_register(destination_register_name)
            elif register_goals.direction == DIRECTION_FORWARD:
                if len(instruction.opcodes) == 2:
                    source_register_name = self.get_operand_register_name(instruction, 0)
                    if source_register_name is not None and register_goals.still_tracking_register(source_register_name):
                        pass
            pass


def get_string_at_address(program_data, block, address):
    # type: (disassembly_data.ProgramData, disassembly_data.SegmentBlock, int) -> Union[str, None]
    data_idx = address - loaderlib.get_segment_address(program_data.loader_segments, block.segment_id)
    data = loaderlib.get_segment_data(program_data.loader_segments, block.segment_id)
    string_end_idx = data_idx
    while data[string_end_idx] != '\0' and string_end_idx < len(data):
        string_end_idx += 1
    if string_end_idx != data_idx:
        return data[data_idx:string_end_idx].tobytes()
    return None

def onload_set_disassemblylib_functions(program_data):
    # type: (disassembly_data.ProgramData) -> None
    arch = disassemblylib.get_processor(program_data.processor_id)
    program_data.dis_is_final_instruction_func = arch.function_is_final_instruction
    program_data.dis_get_match_addresses_func = arch.function_get_match_addresses
    program_data.dis_get_instruction_string_func = arch.function_get_instruction_string
    program_data.dis_is_operand_pointer_sized = arch.function_is_operand_pointer_sized
    program_data.dis_get_operand_string_func = arch.function_get_operand_string
    program_data.dis_get_operand_values_func = arch.function_get_operand_values
    program_data.dis_get_operand_value_func = arch.function_get_operand_value
    program_data.dis_disassemble_one_line_func = arch.function_disassemble_one_line
    program_data.dis_disassemble_as_data_func = arch.function_disassemble_as_data
    program_data.dis_get_default_symbol_name_func = arch.function_get_default_symbol_name
    program_data.dis_constant_pc_offset = arch.constant_pc_offset

def onload_make_address_ranges(program_data):
    # type: (disassembly_data.ProgramData) -> None
    program_data.address_ranges = []
    segments = program_data.loader_segments
    for segment_id in range(len(segments)):
        new_address0 = loaderlib.get_segment_address(segments, segment_id)
        new_addressN = new_address0 + loaderlib.get_segment_length(segments, segment_id)
        for i, (address0, addressN, segment_ids) in enumerate(program_data.address_ranges):
            if addressN+1 == new_address0:
                segment_ids.add(segment_id)
                program_data.address_ranges[i] = address0, new_addressN-1, segment_ids
                break
            elif address0 == new_addressN:
                segment_ids.add(segment_id)
                program_data.address_ranges[i] = new_address0, addressN, segment_ids
                break
        else:
            program_data.address_ranges.append((new_address0, new_addressN-1, set([segment_id])))

def onload_cache_uncertain_references(program_data):
    """ line_count_rlock """
    # type: (disassembly_data.ProgramData) -> None    
    is_binary_file = (program_data.flags & disassembly_data.PDF_BINARY_FILE) == disassembly_data.PDF_BINARY_FILE
    for block in program_data.blocks:
        data_type = disassembly_data.get_block_data_type(block)
        if data_type == disassembly_data.DATA_TYPE_CODE:
            block.references = _locate_uncertain_code_references(program_data, block.address, is_binary_file, block)
        elif is_binary_file:
            block.references = _locate_uncertain_data_references(program_data, block.address, block)


def api_is_segment_data_cached(program_data):
    # type: (disassembly_data.ProgramData) -> bool
    segments = program_data.loader_segments
    for i in range(len(segments)):
        if loaderlib.get_segment_data(segments, i) is not None:
            return True
    return False

def on_block_created(program_data, block):
    # type: (disassembly_data.ProgramData, disassembly_data.SegmentBlock) -> None
    if program_data.new_block_events is not None:
        program_data.new_block_events.append(block)

def on_block_data_type_change(program_data, block, old_data_type, new_data_type, old_length):
    # type: (disassembly_data.ProgramData, disassembly_data.SegmentBlock, int, int, int) -> None
    if program_data.block_data_type_events is not None:
        program_data.block_data_type_events.append((block, old_data_type, new_data_type, old_length))

def DEBUG_log_load_stats(program_data):
    # type: (disassembly_data.ProgramData) -> None

    # Log debug statistics
    num_code_blocks = 0
    num_code_bytes = 0
    for block in program_data.blocks:
        if disassembly_data.get_block_data_type(block) == disassembly_data.DATA_TYPE_CODE:
            num_code_bytes += block.length
            num_code_blocks += 1
    logger.debug("Initial result, code bytes: %d, code blocks: %d", num_code_bytes, num_code_blocks)

def DEBUG_locate_potential_code_blocks(program_data):
    # type: (disassembly_data.ProgramData) -> List[disassembly_data.SegmentBlock]
    blocks = []
    for block in program_data.blocks:
        if disassembly_data.get_block_data_type(block) != disassembly_data.DATA_TYPE_CODE and block.length >= 2:
            data = loaderlib.get_segment_data(program_data.loader_segments, block.segment_id)
            offset_start = block.length - 2
            data_offset_start = block.segment_offset + offset_start
            match, data_offset_end = program_data.dis_disassemble_one_line_func(data, data_offset_start, block.address + offset_start)
            if match is not None and data_offset_end < data_offset_start + block.length:
                if program_data.dis_is_final_instruction_func(match):
                    blocks.append(block)
    return blocks


class DisassemblyApi(object):
    """
    Plan:
    1) Proxy all existing api calls.
    2) Replace external calls to global functions with use of this object's api.
    3) Remove the global functions and integrate them into this object.
    """
    _program_data = None # type: disassembly_data.ProgramData

    def __init__(self, program_data):
        self._program_data = program_data

    def get_code_block_info_for_address(self, address):
        # type: (int) -> Union[None, InstructionEntry]
        with line_count_rlock:
            return api_get_code_block_info_for_address(self._program_data, address)

    def set_data_type_at_address(self, address, data_type, work_state=None):
        # type: (int, int, WorkState) -> None
        return set_data_type_at_address(self._program_data, address, data_type, work_state)

    def get_data_type_for_address(self, address):
        # type: (int) -> int
        block, block_idx = lookup_block_by_address(self._program_data, address)
        return disassembly_data.get_block_data_type(block)

    def get_line_number_for_address(self, address):
        # type: (int) -> Union[None, int]
        with line_count_rlock:
            return get_line_number_for_address(self._program_data, address)

    def get_address_for_line_number(self, line_number):
        # type: (int) -> Union[int, None]
        return api_get_address_for_line_number(self._program_data, line_number)

    def get_referenced_symbol_addresses_for_line_number(self, line_number):
        # type: (int) -> List[int]
        return api_get_referenced_symbol_addresses_for_line_number(self._program_data, line_number)

    def get_file_line_count(self):
        # type: () -> int
        return api_get_file_line_count(self._program_data)

    def get_file_line(self, line_idx, column_idx):
        # type: (int, int) -> str
        return api_get_file_line(self._program_data, line_idx, column_idx)

    def insert_reference_address(self, referring_address):
        # type: (int) -> None
        is_binary_file = (self._program_data.flags & disassembly_data.PDF_BINARY_FILE) == disassembly_data.PDF_BINARY_FILE
        # Is it a binary file?
        # Is the address ... this comment was never completed.
        if not is_binary_file or not check_known_address(self._program_data, referring_address):
            return

        # TODO(rmtew): This should be refactored into a general function when the best form becomes obvious.
        block, block_idx = lookup_block_by_address(self._program_data, referring_address)
        data_type = disassembly_data.get_block_data_type(block)
        if data_type == disassembly_data.DATA_TYPE_DATA32:
            block_addressN = block.address
            sizes = get_data_type_sizes(block)
            for i, (data_size, num_bytes, size_count, size_lines) in enumerate(sizes):
                block_address0 = block_addressN
                block_addressN += num_bytes * size_count
                if referring_address >= block_address0 and referring_address < block_addressN:
                    segments = self._program_data.loader_segments
                    data = loaderlib.get_segment_data(segments, block.segment_id)
                    data_idx = block.segment_offset + (referring_address - block.address)
                    referred_address = self._program_data.loader_data_types.sized_value(data_size, data, data_idx)

                    # TODO(rmtew): If the address is already present, then this is all not necessary?
                    _insert_reference_address(self._program_data, referring_address, referred_address)
                    was_new_symbol = process_pending_symbol_address(self._program_data, referred_address)

                    line0 = get_line_number_for_address(self._program_data, referring_address)
                    if self._program_data.post_line_change_func:
                        self._program_data.post_line_change_func(line0, 0)

                    if was_new_symbol:
                        line0 = get_line_number_for_address(self._program_data, referred_address)
                        if self._program_data.post_line_change_func:
                            self._program_data.post_line_change_func(line0, 0)

                    remove_uncertain_reference(self._program_data, data_type, referring_address, referred_address)
                    return

    def get_referring_addresses(self, address):
        # type: (int) -> Set[int]
        return api_get_referring_addresses(self._program_data, address)

    def get_entrypoint_address(self):
        # type: () -> int
        return loaderlib.get_segment_address(self._program_data.loader_segments, self._program_data.loader_entrypoint_segment_id) + self._program_data.loader_entrypoint_offset

    def get_operand_count_for_line_number(self, line_number):
        # type: (int) -> int
        ret = get_code_block_info_for_line_number(self._program_data, line_number)
        if ret is None:
            return 0
        address, instruction = ret
        return len(instruction.opcodes)

    def get_address_for_symbol(self, symbol_name):
        # type: (str) -> int
        symbol_name = symbol_name.lower()
        for k, v in self._program_data.symbols_by_address.iteritems():
            if v.lower() == symbol_name:
                return k

    def set_symbol_for_address(self, address, symbol_label):
        # type: (int, str) -> bool
        return set_symbol_for_address(self._program_data, address, symbol_label)

    def get_symbol_for_address(self, address, absolute_info=None):
        # type: (int, Tuple[int, int]) -> str
        with line_count_rlock:
            return get_symbol_for_address(self._program_data, address, absolute_info)

    def get_symbols(self):
        return self._program_data.symbols_by_address.items()

    def get_next_block_line_number(self, data_type, line_idx, direction_offset=1, op_func=operator.eq):
        """ line_count_rlock """
        # type: (int, int, int, Callable[[Any, Any], int]) -> int
        block, block_idx = lookup_block_by_line_count(self._program_data, line_idx)
        block_idx += direction_offset
        while block_idx < len(self._program_data.blocks) and block_idx >= 0:
            if op_func(disassembly_data.get_block_data_type(self._program_data.blocks[block_idx]), data_type):
                return get_block_line_number(self._program_data, block_idx)
            block_idx += direction_offset

    def get_uncertain_data_references(self):
        # type: () -> List[UncertainReference]
        results = [] # type: List[UncertainReference]
        for block in self._program_data.blocks:
            data_type = disassembly_data.get_block_data_type(block)
            if data_type != disassembly_data.DATA_TYPE_CODE and block.references:
                results.extend(block.references)
        return results

    def get_uncertain_code_references(self):
        # type: () -> List[UncertainReference]
        results = [] # type: List[UncertainReference]
        for block in self._program_data.blocks:
            data_type = disassembly_data.get_block_data_type(block)
            if data_type == disassembly_data.DATA_TYPE_CODE and block.references:
                results.extend(block.references)
        return results

    def get_uncertain_references_by_address(self, address):
        # type: (int) -> List[UncertainReference]
        block, block_idx = lookup_block_by_address(self._program_data, address)
        return block.references

    ## Events.

    def set_symbol_insert_func(self, f):
        # type: (Callable[[int, str], None]) -> None
        api_set_symbol_insert_func(self._program_data, f)

    def set_symbol_delete_func(self, f):
        # type: (Callable[[int, str], None]) -> None
        api_set_symbol_delete_func(self._program_data, f)

    def set_uncertain_reference_modification_func(self, f):
        # type: (Callable) -> None
        self._program_data.uncertain_reference_modification_func = f

    def set_pre_line_change_func(self, f):
        self._program_data.pre_line_change_func = f

    def set_post_line_change_func(self, f):
        self._program_data.post_line_change_func = f

    ## Project loading and saving support.

    def get_save_project_options(self):
        return api_get_save_project_options(self._program_data)

    def is_project_inputfile_cached(self):
        # type: () -> bool
        return api_is_project_inputfile_cached(self._program_data)

    def get_project_save_count(self):
        # type: () -> int
        return api_get_project_save_count(self._program_data)

    ## Project loading and saving.

    def load_project_file_finalise(self, f):
        # type: (file) -> None
        segments = self._program_data.loader_segments
        for i in range(len(segments)):
            loaderlib.cache_segment_data(f, segments, i)
        onload_cache_uncertain_references(self._program_data)

    def save_project_file(self, save_file, save_options):
        # type: (file, disassembly_data.SaveProjectOptions) -> None
        return api_save_project_file(save_file, self._program_data, save_options)

    def is_segment_data_cached(self):
        # type: () -> bool
        return api_is_segment_data_cached(self._program_data)

    def get_file_size(self):
        return self._program_data.file_size

    def get_file_name(self):
        return self._program_data.file_name

    def get_file_checksum(self):
        return self._program_data.file_checksum


def get_new_project_options():
    return disassembly_data.NewProjectOptions()

def load_file(input_file, new_options, file_name, work_state=None):
    # type: (file, disassembly_data.NewProjectOptions, str, WorkState) -> DisassemblyApi
    result = api_load_file(input_file, new_options, file_name, work_state)
    if result is not None:
        return DisassemblyApi(result[0])
        #self._program_data = result[0]

def load_project_file(save_file, file_name, work_state=None):
    # type: (file, str, WorkState) -> DisassemblyApi
    result = api_load_project_file(save_file, file_name, work_state)
    if result is not None:
        return DisassemblyApi(result[0])
        #self._program_data = result[0]


if __name__ == "__main__":
    logger.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    logger.addHandler(ch)

