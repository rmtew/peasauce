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

DEBUG_ANNOTATE_DISASSEMBLY = True

import bisect
import logging
import os
import sys
import traceback


import loaderlib
import disassemblylib

logger = logging.getLogger("core")


END_INSTRUCTION_LINES = 2

LI_OFFSET = 0
LI_BYTES = 1
LI_LABEL = 2
LI_INSTRUCTION = 3
LI_OPERANDS = 4
if DEBUG_ANNOTATE_DISASSEMBLY:
    LI_ANNOTATIONS = 5

## BLOCK FLAG RELATED

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
BLOCK_SPLIT_BITMASK     = BLOCK_FLAG_ALLOC | DATA_TYPE_BITMASK

""" Used to map block data type to a character used in the label generation. """
char_by_data_type = { DATA_TYPE_CODE: "C", DATA_TYPE_ASCII: "A", DATA_TYPE_BYTE: "B", DATA_TYPE_WORD: "W", DATA_TYPE_LONGWORD: "L" }


## TODO: Move elsewhere and make per-arch.

class DisplayConfiguration(object):
    trailing_line_exit = True
    trailing_line_branch = True
    trailing_line_trap = True

display_configuration = DisplayConfiguration()


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


## SegmentBlock flag helpers

def get_data_type(flags):
    return (flags >> DATA_TYPE_BIT0) & DATA_TYPE_BITMASK

def set_data_type(block, data_type):
    block.flags &= ~(DATA_TYPE_BITMASK << DATA_TYPE_BIT0)
    block.flags |= ((data_type & DATA_TYPE_BITMASK) << DATA_TYPE_BIT0)


def calculate_block_leading_line_count(program_data, block):
    if block.segment_offset == 0 and program_data.file_info.has_section_headers():
        return 1
    return 0


def calculate_match_line_count(program_data, match):
    line_count = 1
    if display_configuration.trailing_line_exit and program_data.dis_is_final_instruction_func(match):
        line_count += 1
    elif display_configuration.trailing_line_trap and match.specification.key == "TRAP":
        line_count += 1
    elif display_configuration.trailing_line_branch and match.specification.key in ("Bcc", "DBcc",):
        line_count += 1
    return line_count


def calculate_line_count(program_data, block):
    old_line_count = block.line_count
    block.line_count = calculate_block_leading_line_count(program_data, block)
    if get_data_type(block.flags) == DATA_TYPE_CODE:
        for match in block.line_data:
            block.line_count += calculate_match_line_count(program_data, match)
    elif get_data_type(block.flags) in (DATA_TYPE_LONGWORD, DATA_TYPE_WORD, DATA_TYPE_BYTE):
        # If there are excess bytes that do not fit into the given data type, append them in the smaller data types.
        if get_data_type(block.flags) == DATA_TYPE_LONGWORD:
            size_types = [ ("L", 4), ("W", 2), ("B", 1) ]
        elif get_data_type(block.flags) == DATA_TYPE_WORD:
            size_types = [ ("W", 2), ("B", 1) ]
        elif get_data_type(block.flags) == DATA_TYPE_BYTE:
            size_types = [ ("B", 1) ]

        size_counts = []
        excess_length = block.length
        for size_char, num_bytes in size_types:
            size_count = excess_length / num_bytes
            if size_count == 0:
                continue
            size_counts.append(size_count)
            excess_length -= size_count * num_bytes

        # Memory that is not mapped to file contents is placed into aggregate space declarations.
        if block.flags & BLOCK_FLAG_ALLOC:
            block.line_count += len(size_counts)
        else:
            block.line_count += sum(size_counts)
    else:
        block.line_count = 0
        return block.line_count - old_line_count

    # Last block in a segment gets a trailing line, if it is not the last segment.
    segments = program_data.loader_segments
    if block.segment_offset + block.length == loaderlib.get_segment_length(segments, block.segment_id) and block.segment_id < len(segments)-1:
        block.line_count += 1 # SEGMENT FOOTER (blank line)
    return block.line_count - old_line_count


def get_code_block_info_for_address(program_data, address):
    block, block_idx = lookup_block_by_address(program_data, address)
    base_address = program_data.block_addresses[block_idx]

    bytes_used = 0
    line_number = program_data.block_line0s[block_idx] + calculate_block_leading_line_count(program_data, block)
    for match in block.line_data:
        if base_address + bytes_used == address:
            return line_number, match
        bytes_used += match.num_bytes
        line_number += calculate_match_line_count(program_data, match)


def get_code_block_info_for_line_number(program_data, line_number):
    block, block_idx = lookup_block_by_line_count(program_data, line_number)
    base_address = program_data.block_addresses[block_idx]

    bytes_used = 0
    line_count = program_data.block_line0s[block_idx] + calculate_block_leading_line_count(program_data, block)
    for match in block.line_data:
        if line_count == line_number:
            return base_address + bytes_used, match
        bytes_used += match.num_bytes
        line_count += calculate_match_line_count(program_data, match)


def get_line_number_for_address(program_data, address):
    block, block_idx = lookup_block_by_address(program_data, address)
    if get_data_type(block.flags) == DATA_TYPE_CODE:
        line_number, match = get_code_block_info_for_address(program_data, address)
        return line_number

    base_address = program_data.block_addresses[block_idx]
    line_number0 = program_data.block_line0s[block_idx]
    line_number1 = line_number0 + block.line_count

    # Account for leading lines.
    line_number0 += calculate_block_leading_line_count(program_data, block)

    if get_data_type(block.flags) in (DATA_TYPE_LONGWORD, DATA_TYPE_WORD, DATA_TYPE_BYTE):
        if get_data_type(block.flags) == DATA_TYPE_LONGWORD:
            size_types = [ ("L", 4), ("W", 2), ("B", 1) ]
        elif get_data_type(block.flags) == DATA_TYPE_WORD:
            size_types = [ ("W", 2), ("B", 1) ]
        elif get_data_type(block.flags) == DATA_TYPE_BYTE:
            size_types = [ ("B", 1) ]

        line_address0 = base_address
        line_count0 = line_number0
        excess_length = block.length
        for size_char, num_bytes in size_types:
            size_count = excess_length / num_bytes
            if size_count > 0:
                #print size_count, line_number, (line_count0, size_count), line_count0 + size_count
                num_size_bytes = size_count * num_bytes
                if num_size_bytes <= excess_length:
                    return line_count0 + (address - line_address0) / num_bytes
                excess_length -= size_count * num_bytes
                line_address0 += num_size_bytes
                line_count0 += size_count

    return None


def get_address_for_line_number(program_data, line_number):
    block, block_idx = lookup_block_by_line_count(program_data, line_number)
    base_line_count = program_data.block_line0s[block_idx] + calculate_block_leading_line_count(program_data, block)
    address0 = program_data.block_addresses[block_idx]
    address1 = address0 + block.length

    if get_data_type(block.flags) == DATA_TYPE_CODE:
        result = get_code_block_info_for_line_number(program_data, line_number)
        if result is not None:
            address, match = result
            return address
    elif get_data_type(block.flags) in (DATA_TYPE_LONGWORD, DATA_TYPE_WORD, DATA_TYPE_BYTE):
        if get_data_type(block.flags) == DATA_TYPE_LONGWORD:
            size_types = [ ("L", 4), ("W", 2), ("B", 1) ]
        elif get_data_type(block.flags) == DATA_TYPE_WORD:
            size_types = [ ("W", 2), ("B", 1) ]
        elif get_data_type(block.flags) == DATA_TYPE_BYTE:
            size_types = [ ("B", 1) ]

        # 
        line_address0 = address0
        line_count0 = base_line_count
        excess_length = block.length
        for size_char, num_bytes in size_types:
            size_count = excess_length / num_bytes
            if size_count > 0:
                #print size_count, line_number, (line_count0, size_count), line_count0 + size_count
                if line_number < line_count0 + size_count:
                    return line_address0 + (line_number - line_count0) * num_bytes
                num_size_bytes = size_count * num_bytes
                excess_length -= size_count * num_bytes
                line_address0 += num_size_bytes
                line_count0 += size_count

    return None


def get_referenced_symbol_addresses_for_line_number(program_data, line_number):
    address, match = get_code_block_info_for_line_number(program_data, line_number)
    return [ a[0] for a in program_data.dis_get_match_addresses_func(match, extra=True) if a[0] in program_data.symbols_by_address ]


def get_line_count(program_data):
    if program_data.block_line0s is None:
        return 0
    return program_data.block_line0s[-1] + program_data.blocks[-1].line_count + END_INSTRUCTION_LINES


def get_file_line(program_data, line_idx, column_idx): # Zero-based
    block, block_idx = lookup_block_by_line_count(program_data, line_idx)
    block_line_count0 = program_data.block_line0s[block_idx]
    block_line_countN = block_line_count0 + block.line_count
    
    # If the line is the first of the block, check if it is a segment header.
    leading_line_count = 0
    if block.segment_offset == 0 and program_data.file_info.has_section_headers():
        if line_idx == block_line_count0:
            section_header = program_data.file_info.get_section_header(block.segment_id)
            i = section_header.find(" ")
            if column_idx == LI_INSTRUCTION:
                return section_header[0:i]
            elif column_idx == LI_OPERANDS:
                return section_header[i+1:]
            else:
                return ""
        leading_line_count += 1

    segments = program_data.loader_segments

    # If the line is the last line in a block, check if it a "between segments" trailing blank line.
    if line_idx == block_line_countN-1:
        if block.segment_offset + block.length == loaderlib.get_segment_length(segments, block.segment_id) and block.segment_id < len(segments)-1:
            return ""

    if get_data_type(block.flags) == DATA_TYPE_CODE:
        bytes_used = 0
        line_count = block_line_count0 + leading_line_count
        line_match = None
        for match in block.line_data:
            if line_count == line_idx:
                line_match = match
                break
            bytes_used += match.num_bytes
            line_count += calculate_match_line_count(program_data, match)
        else:
            # Trailing blank lines.
            return ""
        address = block.address + bytes_used

        if column_idx == LI_OFFSET:
            return "%08X" % address
        elif column_idx == LI_BYTES:
            data = loaderlib.get_segment_data(segments, block.segment_id)
            data_offset = block.segment_offset+bytes_used
            return "".join([ "%02X" % c for c in data[data_offset:data_offset+line_match.num_bytes] ])
        elif column_idx == LI_LABEL:
            label = get_symbol_for_address(program_data, address)
            if label is None:
                return ""
            return label
        elif column_idx == LI_INSTRUCTION:
            return program_data.dis_get_instruction_string_func(line_match, line_match.vars)
        elif column_idx == LI_OPERANDS:
            def make_operand_string(match, operand, operand_idx):
                operand_string = None
                if match.specification.key[0:4] != "LINK" and operand.specification.key == "DISPLACEMENT":
                    operand_string = get_symbol_for_address(program_data, match.pc + operand.vars["xxx"])
                elif operand.specification.key == "AbsL" or operand.key == "AbsL":
                    operand_string = get_symbol_for_address(program_data, operand.vars["xxx"])
                elif operand_idx == 0 and (operand.specification.key == "Imm" or operand.key == "Imm"):
                    # e.g. MOVEA.L #vvv, A0 ?
                    if len(match.opcodes) > 1:
                        operand2 = match.opcodes[1]
                        if (operand2.specification.key == "AR" or operand.key == "AR"):
                            operand_string = get_symbol_for_address(program_data, operand.vars["xxx"])
                            if operand_string is not None:
                                operand_string = "#"+ operand_string
                if operand_string is None:
                    return program_data.dis_get_operand_string_func(match.pc, operand, operand.vars, lookup_symbol=lambda address, program_data=program_data: get_symbol_for_address(program_data, address))
                return operand_string
            opcode_string = ""
            if len(line_match.opcodes) >= 1:
                opcode_string += make_operand_string(line_match, line_match.opcodes[0], 0)
            if len(line_match.opcodes) == 2:
                opcode_string += ", "+ make_operand_string(line_match, line_match.opcodes[1], 1)
            return opcode_string
        elif DEBUG_ANNOTATE_DISASSEMBLY and column_idx == LI_ANNOTATIONS:
            l = []
            for o in line_match.opcodes:
                key = o.specification.key
                if o.key is not None and key != o.key:
                    l.append(o.key)
                else:
                    l.append(key)
            return line_match.specification.key +" "+ ",".join(l)
    elif get_data_type(block.flags) in (DATA_TYPE_LONGWORD, DATA_TYPE_WORD, DATA_TYPE_BYTE):
        # If there are excess bytes that do not fit into the given data type, append them in the smaller data types.
        size_types = []
        if get_data_type(block.flags) == DATA_TYPE_LONGWORD:
            size_types.append((4, "L", program_data.data_types.uint32_value))
        if get_data_type(block.flags) in (DATA_TYPE_LONGWORD, DATA_TYPE_WORD):
            size_types.append((2, "W", program_data.data_types.uint16_value))
        if get_data_type(block.flags) in (DATA_TYPE_LONGWORD, DATA_TYPE_WORD, DATA_TYPE_BYTE):
            size_types.append((1, "B", program_data.data_types.uint8_value))

        unconsumed_byte_count = block.length
        size_line_countN = block_line_count0 + leading_line_count
        for num_bytes, size_char, read_func in size_types:
            size_count = unconsumed_byte_count / num_bytes
            if size_count == 0:
                continue
            data_idx0 = block.segment_offset + (block.length - unconsumed_byte_count)
            unconsumed_byte_count -= size_count * num_bytes
            size_line_count0 = size_line_countN
            if block.flags & BLOCK_FLAG_ALLOC:
                size_line_countN += 1
            else:
                size_line_countN += size_count
            if line_idx < size_line_countN:
                data_idx = data_idx0 + (line_idx - size_line_count0) * num_bytes
                if column_idx == LI_OFFSET:
                    return "%08X" % (loaderlib.get_segment_address(segments, block.segment_id) + data_idx)
                elif column_idx == LI_BYTES:
                    if block.flags & BLOCK_FLAG_ALLOC:
                        return ""
                    data = loaderlib.get_segment_data(segments, block.segment_id)
                    return "".join([ "%02X" % c for c in data[data_idx:data_idx+num_bytes] ])
                elif column_idx == LI_LABEL:
                    label = get_symbol_for_address(program_data, loaderlib.get_segment_address(segments, block.segment_id) + data_idx)
                    if label is None:
                        return ""
                    return label
                elif column_idx == LI_INSTRUCTION:
                    name = program_data.file_info.get_data_instruction_string(block.segment_id, (block.flags & BLOCK_FLAG_ALLOC) != BLOCK_FLAG_ALLOC)
                    return name +"."+ size_char
                elif column_idx == LI_OPERANDS:
                    if block.flags & BLOCK_FLAG_ALLOC:
                        return str(size_count)
                    data = loaderlib.get_segment_data(segments, block.segment_id)
                    value = read_func(data, data_idx)
                    label = None
                    if size_char == "L" and value in program_data.loader_relocatable_addresses:
                        label = get_symbol_for_address(program_data, value)
                    if label is None:
                        label = ("$%0"+ str(num_bytes<<1) +"X") % value
                    return label
                elif DEBUG_ANNOTATE_DISASSEMBLY and column_idx == LI_ANNOTATIONS:
                    return "-"

    block_line_count0 = block_line_countN

    # Second to last line is a blank line.
    if line_idx == block_line_count0:
        return ""

    # Last line is an end instruction.
    if line_idx == block_line_count0+1:
        if column_idx == LI_INSTRUCTION:
            return "END"
        return ""


def insert_branch_address(program_data, address, src_abs_idx):
    if address not in program_data.loader_relocated_addresses:
        program_data.branch_addresses.add(address)
        # This errors because if the block is a code block, it has no match object.
        # split_block(address)

def set_symbol_insert_func(program_data, f):
    program_data.symbol_insert_func = f

def insert_symbol(program_data, address, name):
    program_data.symbols_by_address[address] = name
    if program_data.symbol_insert_func: program_data.symbol_insert_func(address, name)

def get_symbol_for_address(program_data, address):
    return program_data.symbols_by_address.get(address)

def set_symbol_for_address(program_data, address, symbol):
    program_data.symbols_by_address[address] = symbol

def recalculate_line_count_index(program_data):
    if program_data.block_line0s_dirtyidx is not None:
        line_count_start = 0
        if program_data.block_line0s_dirtyidx > 0:
            line_count_start = program_data.block_line0s[program_data.block_line0s_dirtyidx-1] + program_data.blocks[program_data.block_line0s_dirtyidx-1].line_count
        for i in range(program_data.block_line0s_dirtyidx, len(program_data.block_line0s)):
            program_data.block_line0s[i] = line_count_start
            line_count_start += program_data.blocks[i].line_count
        program_data.block_line0s_dirtyidx = None

def lookup_block_by_line_count(program_data, lookup_key):
    recalculate_line_count_index(program_data)
    lookup_index = bisect.bisect_right(program_data.block_line0s, lookup_key)
    return program_data.blocks[lookup_index-1], lookup_index-1

def lookup_block_by_address(program_data, lookup_key):
    lookup_index = bisect.bisect_right(program_data.block_addresses, lookup_key)
    return program_data.blocks[lookup_index-1], lookup_index-1

def insert_block(program_data, insert_idx, block):
    program_data.block_addresses.insert(insert_idx, block.address)
    program_data.block_line0s.insert(insert_idx, None)
    program_data.blocks.insert(insert_idx, block)
    # Update how much of the sorted line number index needs to be recalculated.
    if program_data.block_line0s_dirtyidx is not None and insert_idx < program_data.block_line0s_dirtyidx:
        program_data.block_line0s_dirtyidx = insert_idx

def split_block(program_data, address):
    block, block_idx = lookup_block_by_address(program_data, address)
    if block.address == address:
        return None

    new_block_idx = block_idx + 1

    # How long the new block will be.
    excess_length = block.length - (address - block.address)

    # Truncate the preceding block the address is currently within.
    block.length -= excess_length

    # Create a new block for the address we are processing.
    new_block = SegmentBlock()
    new_block.flags = block.flags & BLOCK_SPLIT_BITMASK
    new_block.segment_id = block.segment_id
    new_block.address = block.address + block.length
    new_block.segment_offset = block.segment_offset + block.length
    new_block.length = excess_length
    insert_block(program_data, new_block_idx, new_block)

    if get_data_type(block.flags) == DATA_TYPE_CODE:
        num_bytes = 0
        for i, match in enumerate(block.line_data):
            if num_bytes == block.length:
                break
            num_bytes += match.num_bytes
        new_block.line_data = block.line_data[i:]
        block.line_data[i:] = []

    calculate_line_count(program_data, block)
    calculate_line_count(program_data, new_block)

    return new_block, new_block_idx


class ProgramData(object):
    def __init__(self):
        ## Persisted state.
        # Local:
        self.branch_addresses = set()
        self.symbols_by_address = {}
        "List of blocks ordered by ascending address."
        self.blocks = []
        "List of ascending block addresses (used by bisect for address based lookups)."
        self.block_addresses = []
        "List of ascending block first line numbers (used by bisect for line number based lookups)."
        self.block_line0s = []
        "If list of first line numbers need recalculating, this is the entry to start at."
        self.block_line0s_dirtyidx = 0

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
        "When saved work is to be independently loadable without original file, we include the required data."
        self.loader_segments = []
        self.loader_relocated_addresses = set()
        self.loader_relocatable_addresses = set()
        self.loader_entrypoint_segment_id = None
        self.loader_entrypoint_offset = None

        ## Non-persisted state.
        # Local:
        self.symbol_insert_func = None

        # disassemblylib:
        self.dis_is_final_instruction_func = None
        self.dis_get_match_addresses_func = None
        self.dis_get_instruction_string_func = None
        self.dis_get_operand_string_func = None
        self.dis_disassemble_one_line_func = None
        self.dis_big_endian = None

        # loaderlib:
        self.file_path = None
        self.data_types = None


def load_file(file_path):
    result = loaderlib.load_file(file_path)
    if result is None:
        return None, 0

    file_info, data_types = result

    program_data = ProgramData()
    program_data.file_path = file_path

    # Extract useful information from file loading process.
    program_data.file_info = file_info
    program_data.data_types = data_types

    program_data.loader_entrypoint_segment_id = file_info.entrypoint_segment_id
    program_data.loader_entrypoint_offset = file_info.entrypoint_offset
    segments = program_data.loader_segments = file_info.segments
    loaderlib.cache_segment_data(file_path, segments)
    loaderlib.relocate_segment_data(segments, data_types, file_info.relocations_by_segment_id, program_data.loader_relocatable_addresses, program_data.loader_relocated_addresses)

    # Set up the disassembly API.
    arch_name = file_info.system.get_arch_name()
    for func_name, func in disassemblylib.get_api(arch_name):
        setattr(program_data, "dis_"+ func_name +"_func", func)

    # Start disassembling.
    entrypoint_address = loaderlib.get_segment_address(segments, program_data.loader_entrypoint_segment_id) + program_data.loader_entrypoint_offset

    # Pass 1: Create a block for each of the segments.
    for segment_id in range(len(segments)):
        address = loaderlib.get_segment_address(segments, segment_id)
        data_length = loaderlib.get_segment_data_length(segments, segment_id)
        segment_length = loaderlib.get_segment_length(segments, segment_id)

        block = SegmentBlock()
        if loaderlib.is_segment_type_bss(segments, segment_id):
            block.flags |= BLOCK_FLAG_ALLOC
        set_data_type(block, DATA_TYPE_LONGWORD)
        block.segment_id = segment_id

        block.segment_offset = 0
        block.address = address
        block.length = data_length
        calculate_line_count(program_data, block)
        program_data.block_addresses.append(block.address)
        program_data.block_line0s.append(None)
        program_data.blocks.append(block)

        if segment_length > data_length:
            block = SegmentBlock()
            block.flags |= BLOCK_FLAG_ALLOC
            set_data_type(block, DATA_TYPE_LONGWORD)
            block.segment_id = segment_id
            block.address = address + data_length
            block.segment_offset = data_length
            block.length = segment_length - data_length
            calculate_line_count(program_data, block)
            program_data.block_addresses.append(block.address)
            program_data.block_line0s.append(None)
            program_data.blocks.append(block)

    # Pass 2: Stuff.

    # Incorporate known symbols.
    for segment_id in range(len(segments)):
        symbols = file_info.symbols_by_segment_id[segment_id]
        address = loaderlib.get_segment_address(segments, segment_id)
        for symbol_offset, symbol_name, code_flag in symbols:
            insert_symbol(program_data, address + symbol_offset, symbol_name)

    # Pass 3: Do another block splitting pass.
    for address in program_data.symbols_by_address.iterkeys():
        split_block(program_data, address)
    for address in program_data.loader_relocated_addresses:
        split_block(program_data, address)

    # Pass 4: Do a disassembly pass.
    disassembly_offsets = [ entrypoint_address ]
    for address in program_data.branch_addresses:
        if address != entrypoint_address:
            disassembly_offsets.append(address)

    disassembly_checklist = {}
    while len(disassembly_offsets):
        address = disassembly_offsets.pop()
        #logger.debug("Processing address: %X", address)

        block, block_idx = lookup_block_by_address(program_data, address)
        if address - block.address > 0:
            # The middle of an existing block.
            if get_data_type(block.flags) == DATA_TYPE_CODE:
                # Code blocks are just split (if address is valid) and that's it.
                if address & 1 == 0:
                    split_block(program_data, address)
                continue
            # Split a block off at the processing point.
            new_block, block_idx = split_block(program_data, address)
            new_block.flags |= block.flags & BLOCK_FLAG_PROCESSED
            block = new_block

        if block.flags & BLOCK_FLAG_PROCESSED:
            #logger.debug("Address already processed: %X", address)
            continue

        block.flags |= BLOCK_FLAG_PROCESSED

        bytes_consumed = 0
        line_data = []
        found_terminating_instruction = False
        while bytes_consumed < block.length:
            data = loaderlib.get_segment_data(segments, block.segment_id)
            data_offset_start = block.segment_offset + bytes_consumed
            match, data_offset_end = program_data.dis_disassemble_one_line_func(data, data_offset_start, address + bytes_consumed)
            bytes_matched = data_offset_end - data_offset_start
            if match is None or bytes_consumed + bytes_matched > block.length:
                logger.error("unable to disassemble at %X (started at %X)", address + bytes_consumed, address)
                break
            line_data.append(match)
            bytes_consumed += bytes_matched
            found_terminating_instruction = program_data.dis_is_final_instruction_func(match)
            if found_terminating_instruction:
                break

        if len(line_data) == 0:
            continue

        # Discard any unprocessed block.
        if bytes_consumed < block.length:
            trailing_block, trailing_block_idx = split_block(program_data, address + bytes_consumed)
            set_data_type(trailing_block, DATA_TYPE_LONGWORD)
            if not found_terminating_instruction:
                trailing_block.flags |= BLOCK_FLAG_PROCESSED

        set_data_type(block, DATA_TYPE_CODE)
        block.line_data = line_data
        calculate_line_count(program_data, block)
        disassembly_checklist[block.address] = None

        # Extract any addresses which are referred to, for later use.
        for match in line_data:
            for match_address, is_code in program_data.dis_get_match_addresses_func(match):
                if is_code and match_address not in disassembly_checklist:
                    disassembly_offsets.insert(0, match_address)
                insert_branch_address(program_data, match_address, address)

    for address in program_data.loader_relocated_addresses:
        if address not in program_data.symbols_by_address:
            block, block_idx = lookup_block_by_address(program_data, address)
            if block.address != address:
                logger.error("Tried to label a relocated address without a block: %X", address)
                continue
            insert_symbol(program_data, address, "lb"+ char_by_data_type[get_data_type(block.flags)] + ("%06X" % address))

    if entrypoint_address not in program_data.symbols_by_address:
        insert_symbol(program_data, entrypoint_address, "ENTRYPOINT")

    for address in program_data.branch_addresses:
        if address not in program_data.symbols_by_address:
            block, block_idx = lookup_block_by_address(program_data, address)
            if block.address != address:
                logger.error("Tried to label a branch address without a block: %X", address)
                continue
            insert_symbol(program_data, address, "lb"+ char_by_data_type[get_data_type(block.flags)] + ("%06X" % address))

    recalculate_line_count_index(program_data)
    line_count = program_data.block_line0s[-1] + program_data.blocks[-1].line_count
    line_count += END_INSTRUCTION_LINES # blank line, then "end" instruction
    return program_data, line_count
    

if __name__ == "__main__":
    logger.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    logger.addHandler(ch)
