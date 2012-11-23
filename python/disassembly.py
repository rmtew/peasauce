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
import cPickle
import logging
import os
import struct
import sys
import time
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
BLOCK_SPLIT_BITMASK     = BLOCK_FLAG_ALLOC | DATA_TYPE_BITMASK | BLOCK_FLAG_PROCESSED

""" Used to map block data type to a character used in the label generation. """
char_by_data_type = { DATA_TYPE_CODE: "C", DATA_TYPE_ASCII: "A", DATA_TYPE_BYTE: "B", DATA_TYPE_WORD: "W", DATA_TYPE_LONGWORD: "L" }


## TODO: Move elsewhere and make per-arch.

class DisplayConfiguration(object):
    trailing_line_exit = True
    trailing_line_branch = True
    trailing_line_trap = True

display_configuration = DisplayConfiguration()


# Segment line data entry types.
SLD_INSTRUCTION = 1
SLD_COMMENT_TRAILING = 2
SLD_COMMENT_FULL_LINE = 3
SLD_EQU_LOCATION_RELATIVE = 4


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

    static_fmt = "<HIIIIHH"

    def write_savefile_data(self, f):
        if self.line_data is None:
            line_data_count = 0
        else:
            line_data_count = len(self.line_data)

        s = struct.pack(self.static_fmt, self.segment_id, self.segment_offset, self.address, self.length, self.flags, self.line_count, line_data_count)
        f.write(s)

        if line_data_count > 0:
            segment_offset = 0
            for type_id, entry in self.line_data:
                f.write(struct.pack("<H", type_id))
                if type_id == SLD_INSTRUCTION:
                    f.write(struct.pack("<I", segment_offset))
                    segment_offset += entry.num_bytes
                elif type_id == SLD_EQU_LOCATION_RELATIVE:
                    f.write(struct.pack("<I", entry))
                elif type_id in (SLD_COMMENT_TRAILING, SLD_COMMENT_FULL_LINE):
                    f.write(struct.pack("<H", len(entry)))
                    f.write(entry)
                else:
                    logger.error("Trying to save a savefile, did not know how to handle entry of type_id: %d, entry value: %s", type_id, entry)

    def read_savefile_data(self, f):
        bytes_to_read = struct.calcsize(self.static_fmt)
        self.segment_id, self.segment_offset, self.address, self.length, self.flags, self.line_count, line_data_count = struct.unpack(self.static_fmt, f.read(bytes_to_read))

        if line_data_count > 0:
            self.line_data = [ None ] * line_data_count
            for i in xrange(line_data_count):
                type_id = struct.unpack("<H", f.read(2))[0]
                if type_id in (SLD_INSTRUCTION, SLD_EQU_LOCATION_RELATIVE):
                    segment_offset = struct.unpack("<I", f.read(4))[0]
                    self.line_data[i] = (type_id, segment_offset)
                elif type_id in (SLD_COMMENT_TRAILING, SLD_COMMENT_FULL_LINE):
                    num_bytes = struct.unpack("<I", f.read(2))[0]
                    text = f.read(num_bytes)
                    self.line_data[i] = (type_id, text)

## SegmentBlock flag helpers

def get_block_data_type(block):
    return (block.flags >> DATA_TYPE_BIT0) & DATA_TYPE_BITMASK

def set_block_data_type(block, data_type):
    block.flags &= ~(DATA_TYPE_BITMASK << DATA_TYPE_BIT0)
    block.flags |= ((data_type & DATA_TYPE_BITMASK) << DATA_TYPE_BIT0)


def realise_instruction_entry(program_data, block, segment_extra_offset):
    data = loaderlib.get_segment_data(program_data.loader_segments, block.segment_id)
    data_offset_start = block.segment_offset + segment_extra_offset
    match, data_offset_end = program_data.dis_disassemble_one_line_func(data, data_offset_start, block.address + segment_extra_offset)
    return match


SEGMENT_HEADER_LINE_COUNT = 2

def calculate_block_leading_line_count(program_data, block):
    if block.segment_offset == 0 and loaderlib.has_segment_headers(program_data.loader_system_name):
        return SEGMENT_HEADER_LINE_COUNT
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

    if get_block_data_type(block) == DATA_TYPE_CODE:
        for type_id, entry in block.line_data:
            if type_id == SLD_INSTRUCTION:
                if type(entry) is int:
                    entry = realise_instruction_entry(program_data, block, entry)
                block.line_count += calculate_match_line_count(program_data, entry)
            elif type_id in (SLD_COMMENT_FULL_LINE, SLD_EQU_LOCATION_RELATIVE):
                block.line_count += 1
    elif get_block_data_type(block) in (DATA_TYPE_LONGWORD, DATA_TYPE_WORD, DATA_TYPE_BYTE):
        # If there are excess bytes that do not fit into the given data type, append them in the smaller data types.
        if get_block_data_type(block) == DATA_TYPE_LONGWORD:
            size_types = [ ("L", 4), ("W", 2), ("B", 1) ]
        elif get_block_data_type(block) == DATA_TYPE_WORD:
            size_types = [ ("W", 2), ("B", 1) ]
        elif get_block_data_type(block) == DATA_TYPE_BYTE:
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
        block.line_count = None
        return block.line_count - old_line_count

    segments = program_data.loader_segments
    if block.segment_offset + block.length == loaderlib.get_segment_length(segments, block.segment_id):
        # Any addresses not within a segment, get potentially displayed as extra lines after that segment.
        addresses = program_data.post_segment_addresses.get(block.segment_id)
        if addresses is not None:
            block.line_count += len(addresses)
        # Last block in a segment gets a trailing line, if it is not the last segment.
        if block.segment_id < len(segments)-1:
            block.line_count += 1 # SEGMENT FOOTER (blank line)
    return block.line_count - old_line_count


def get_code_block_info_for_address(program_data, address):
    block, block_idx = lookup_block_by_address(program_data, address)
    base_address = program_data.block_addresses[block_idx]

    bytes_used = 0
    line_number = program_data.block_line0s[block_idx] + calculate_block_leading_line_count(program_data, block)
    previous_result = None
    for type_id, entry in block.line_data:
        if type_id == SLD_INSTRUCTION:
            # Within but not at the start of the previous instruction.
            if address < base_address + bytes_used:
                return previous_result

            if type(entry) is int:
                entry = realise_instruction_entry(program_data, block, entry)
            current_result = line_number, entry

            # Exactly this instruction.
            if address == base_address + bytes_used:
                return current_result

            previous_result = current_result
            bytes_used += entry.num_bytes
            line_number += calculate_match_line_count(program_data, entry)
        elif type_id in (SLD_COMMENT_FULL_LINE, SLD_EQU_LOCATION_RELATIVE):
            line_number += 1

    # Within but not at the start of the previous instruction.
    if address < base_address + bytes_used:
        return previous_result
    # return None, previous_result


def get_code_block_info_for_line_number(program_data, line_number):
    block, block_idx = lookup_block_by_line_count(program_data, line_number)
    if get_block_data_type(block) != DATA_TYPE_CODE:
        return
    base_address = program_data.block_addresses[block_idx]

    bytes_used = 0
    line_count = program_data.block_line0s[block_idx] + calculate_block_leading_line_count(program_data, block)
    previous_result = None
    for type_id, entry in block.line_data:
        if type_id == SLD_INSTRUCTION:
            # Within but not at the start of the previous instruction.
            if line_number < line_count:
                logger.debug("get_code_block_info_for_line_number.1: %d, %d = %s", line_number, line_count, hex(previous_result[0]))
                return previous_result

            if type(entry) is int:
                entry = realise_instruction_entry(program_data, block, entry)
            current_result = base_address + bytes_used, entry

            # Exactly this instruction.
            if line_number == line_count:
                logger.debug("get_code_block_info_for_line_number.1: %d, %d = %s", line_number, line_count, hex(current_result[0]))
                return current_result

            previous_result = current_result
            bytes_used += entry.num_bytes
            line_count += calculate_match_line_count(program_data, entry)
        elif type_id in (SLD_COMMENT_FULL_LINE, SLD_EQU_LOCATION_RELATIVE):
            line_count += 1
    # Within but not at the start of the previous instruction.
    if line_number < line_count:
        logger.debug("get_code_block_info_for_line_number.2: %d, %d = %s", line_number, line_count, hex(previous_result[0]))
        return previous_result

    logger.debug("get_code_block_info_for_line_number.3: %d, %d", line_number, line_count)
    # return None, previous_result


def get_line_number_for_address(program_data, address):
    block, block_idx = lookup_block_by_address(program_data, address)
    if get_block_data_type(block) == DATA_TYPE_CODE:
        result = get_code_block_info_for_address(program_data, address)
        return result[0]

    base_address = program_data.block_addresses[block_idx]
    line_number0 = program_data.block_line0s[block_idx]
    line_number1 = line_number0 + block.line_count

    # Account for leading lines.
    line_number0 += calculate_block_leading_line_count(program_data, block)

    if get_block_data_type(block) in (DATA_TYPE_LONGWORD, DATA_TYPE_WORD, DATA_TYPE_BYTE):
        if get_block_data_type(block) == DATA_TYPE_LONGWORD:
            size_types = [ ("L", 4), ("W", 2), ("B", 1) ]
        elif get_block_data_type(block) == DATA_TYPE_WORD:
            size_types = [ ("W", 2), ("B", 1) ]
        elif get_block_data_type(block) == DATA_TYPE_BYTE:
            size_types = [ ("B", 1) ]

        line_address0 = base_address
        line_count0 = line_number0
        excess_length = block.length
        for i, (size_char, num_bytes) in enumerate(size_types):
            size_count = excess_length / num_bytes
            if size_count > 0:
                #print size_count, line_number, (line_count0, size_count), line_count0 + size_count
                num_size_bytes = size_count * num_bytes
                if num_size_bytes <= excess_length:
                    if block.flags & BLOCK_FLAG_ALLOC:
                        return line_count0 + i
                    return line_count0 + (address - line_address0) / num_bytes
                    
                excess_length -= size_count * num_bytes
                if (block.flags & BLOCK_FLAG_ALLOC) != BLOCK_FLAG_ALLOC:
                    line_address0 += num_size_bytes
                    line_count0 += size_count

    return None


def get_address_for_line_number(program_data, line_number):
    block, block_idx = lookup_block_by_line_count(program_data, line_number)
    base_line_count = program_data.block_line0s[block_idx] + calculate_block_leading_line_count(program_data, block)
    address0 = program_data.block_addresses[block_idx]
    address1 = address0 + block.length

    data_type = get_block_data_type(block)
    logger.debug("get_address_for_line_number: data type = %d", data_type)

    if data_type == DATA_TYPE_CODE:
        result = get_code_block_info_for_line_number(program_data, line_number)
        if result is not None:
            address, match = result
            return address
    elif data_type in (DATA_TYPE_LONGWORD, DATA_TYPE_WORD, DATA_TYPE_BYTE):
        if data_type == DATA_TYPE_LONGWORD:
            size_types = [ ("L", 4), ("W", 2), ("B", 1) ]
        elif data_type == DATA_TYPE_WORD:
            size_types = [ ("W", 2), ("B", 1) ]
        elif data_type == DATA_TYPE_BYTE:
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
    result = get_code_block_info_for_line_number(program_data, line_number)
    if result is not None:
        address, match = result
        return [ k for (k, v) in program_data.dis_get_match_addresses_func(match, extra=True).iteritems() if k in program_data.symbols_by_address ]
    return []


def get_line_count(program_data):
    if program_data.block_line0s is None:
        return 0
    recalculate_line_count_index(program_data)
    return program_data.block_line0s[-1] + program_data.blocks[-1].line_count + END_INSTRUCTION_LINES


def get_file_line(program_data, line_idx, column_idx): # Zero-based
    block, block_idx = lookup_block_by_line_count(program_data, line_idx)
    block_line_count0 = program_data.block_line0s[block_idx]
    block_line_countN = block_line_count0 + block.line_count
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
    final_line_countN = program_data.block_line0s[-1] + program_data.blocks[-1].line_count

    # Second to last line is a blank line.
    if line_idx == final_line_countN:
        return ""

    # Last line is an end instruction.
    if line_idx == final_line_countN+1:
        if column_idx == LI_INSTRUCTION:
            return "END"
        return ""

    ## Block content line generation.
    if get_block_data_type(block) == DATA_TYPE_CODE:
        bytes_used = 0
        line_count = block_line_count0 + leading_line_count
        line_type_id = None
        line_match = None
        line_num_bytes = None
        for type_id, entry in block.line_data:
            if type_id == SLD_INSTRUCTION and type(entry) is int:
                entry = realise_instruction_entry(program_data, block, entry)
            if line_count == line_idx:
                line_type_id = type_id
                line_match = entry
                break
            if type_id == SLD_INSTRUCTION:
                bytes_used += entry.num_bytes
                line_count += calculate_match_line_count(program_data, entry)
            elif type_id in (SLD_COMMENT_FULL_LINE, SLD_EQU_LOCATION_RELATIVE):
                line_count += 1
        else:
            # Trailing blank lines.
            return ""

        end_address = address = block.address + bytes_used
        if line_type_id == SLD_INSTRUCTION:
            line_num_bytes = line_match.num_bytes
        elif line_type_id == SLD_EQU_LOCATION_RELATIVE:
            segment_address = loaderlib.get_segment_address(segments, block.segment_id)
            bytes_used = line_match - block.segment_offset
            address = segment_address + line_match
            line_num_bytes = end_address - address

        if column_idx == LI_OFFSET:
            return "%08X" % end_address
        elif column_idx == LI_BYTES:
            if line_type_id in (SLD_INSTRUCTION, SLD_EQU_LOCATION_RELATIVE):
                data = loaderlib.get_segment_data(segments, block.segment_id)
                data_offset = block.segment_offset+bytes_used
                return "".join([ "%02X" % c for c in data[data_offset:data_offset+line_num_bytes] ])
            return ""
        elif column_idx == LI_LABEL:
            label = get_symbol_for_address(program_data, address)
            if label is None:
                return ""
            return label
        elif column_idx == LI_INSTRUCTION:
            if line_type_id == SLD_INSTRUCTION:
                return program_data.dis_get_instruction_string_func(line_match, line_match.vars)
            elif line_type_id == SLD_EQU_LOCATION_RELATIVE:
                return "EQU"
            return ""
        elif column_idx == LI_OPERANDS:
            if line_type_id == SLD_INSTRUCTION:
                lookup_symbol = lambda address, absolute_info=None: get_symbol_for_address(program_data, address, absolute_info)
                opcode_string = ""
                if len(line_match.opcodes) >= 1:
                    opcode_string += program_data.dis_get_operand_string_func(line_match, line_match.opcodes[0], line_match.opcodes[0].vars, lookup_symbol=lookup_symbol)
                if len(line_match.opcodes) == 2:
                    opcode_string += ", "+ program_data.dis_get_operand_string_func(line_match, line_match.opcodes[1], line_match.opcodes[1].vars, lookup_symbol=lookup_symbol)
                return opcode_string
            elif line_type_id == SLD_EQU_LOCATION_RELATIVE:
                return "*-%d" % line_num_bytes
            return ""
        elif DEBUG_ANNOTATE_DISASSEMBLY and column_idx == LI_ANNOTATIONS:
            if line_type_id == SLD_INSTRUCTION:
                l = []
                for o in line_match.opcodes:
                    key = o.specification.key
                    if o.key is not None and key != o.key:
                        l.append(o.key)
                    else:
                        l.append(key)
                return line_match.specification.key +" "+ ",".join(l)
            return ""
    elif get_block_data_type(block) in (DATA_TYPE_LONGWORD, DATA_TYPE_WORD, DATA_TYPE_BYTE):
        # If there are excess bytes that do not fit into the given data type, append them in the smaller data types.
        size_types = []
        if get_block_data_type(block) == DATA_TYPE_LONGWORD:
            size_types.append((4, "L", program_data.loader_data_types.uint32_value))
        if get_block_data_type(block) in (DATA_TYPE_LONGWORD, DATA_TYPE_WORD):
            size_types.append((2, "W", program_data.loader_data_types.uint16_value))
        if get_block_data_type(block) in (DATA_TYPE_LONGWORD, DATA_TYPE_WORD, DATA_TYPE_BYTE):
            size_types.append((1, "B", program_data.loader_data_types.uint8_value))

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
                    name = loaderlib.get_data_instruction_string(program_data.loader_system_name, segments, block.segment_id, (block.flags & BLOCK_FLAG_ALLOC) != BLOCK_FLAG_ALLOC)
                    return name +"."+ size_char
                elif column_idx == LI_OPERANDS:
                    if block.flags & BLOCK_FLAG_ALLOC:
                        return str(size_count)
                    data = loaderlib.get_segment_data(segments, block.segment_id)
                    value = read_func(data, data_idx)
                    label = None
                    # Only turn the value into a symbol if we actually relocated the value.
                    if size_char == "L" and value in program_data.loader_relocatable_addresses:
                        label = get_symbol_for_address(program_data, value)
                    if label is None:
                        label = ("$%0"+ str(num_bytes<<1) +"X") % value
                    return label
                elif DEBUG_ANNOTATE_DISASSEMBLY and column_idx == LI_ANNOTATIONS:
                    return "-"


def insert_address_check(program_data, address):
    pre_ids = set()
    for address0, addressN, segment_ids in program_data.address_ranges:
        if address < address0:
            pass #post_ids.update(segment_ids)
        elif address > addressN:
            pre_ids.update(segment_ids)
        else:
            return

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
    #if len(post_ids): post_segment_id = min(post_ids)
    logger.debug("Found address not within segment address spaces: %X, excess: %d, pre segment_id: %d", address, address - addressN, pre_segment_id)

def insert_branch_address(program_data, address, src_abs_idx, pending_symbol_addresses):
    insert_address_check(program_data, address)
    # These get split as their turn to be disassembled comes up.
    referring_addresses = program_data.branch_addresses.get(address, set())
    referring_addresses.add(src_abs_idx)
    program_data.branch_addresses[address] = referring_addresses
    pending_symbol_addresses.add(address)

def insert_reference_address(program_data, address, src_abs_idx, pending_symbol_addresses):
    insert_address_check(program_data, address)
    referring_addresses = program_data.reference_addresses.get(address, set())
    referring_addresses.add(src_abs_idx)
    program_data.reference_addresses[address] = referring_addresses
    pending_symbol_addresses.add(address)

def get_entrypoint_address(program_data):
    return loaderlib.get_segment_address(program_data.loader_segments, program_data.loader_entrypoint_segment_id) + program_data.loader_entrypoint_offset

def get_address_for_symbol(program_data, symbol_name):
    symbol_name = symbol_name.lower()
    for k, v in program_data.symbols_by_address.iteritems():
        if v.lower() == symbol_name:
            return k

def set_symbol_insert_func(program_data, f):
    program_data.symbol_insert_func = f

def insert_symbol(program_data, address, name):
    insert_address_check(program_data, address)
    program_data.symbols_by_address[address] = name
    if program_data.symbol_insert_func: program_data.symbol_insert_func(address, name)

def get_symbol_for_address(program_data, address, absolute_info=None):
    # If the address we want a symbol was relocated somewhere, verify the instruction got relocated.
    if absolute_info is not None:
        valid_address = False
        if address in program_data.loader_relocated_addresses:
            # For now, check all instruction bytes as addresses to see if they were relocated within.
            search_address = absolute_info[0]
            while search_address < absolute_info[0] + absolute_info[1]:
                if search_address in program_data.loader_relocatable_addresses:
                    # print "ABSOLUTE SYMBOL LOCATION: %X" % absolute_info[0]
                    valid_address = True
                    break
                search_address += 1
    else:
        valid_address = True
    if valid_address:
        return program_data.symbols_by_address.get(address)

def set_symbol_for_address(program_data, address, symbol):
    program_data.symbols_by_address[address] = symbol

def recalculate_line_count_index(program_data, dirtyidx=None):
    if dirtyidx is None:
        dirtyidx = program_data.block_line0s_dirtyidx
    elif program_data.block_line0s_dirtyidx is not None:
        dirtyidx = min(dirtyidx, program_data.block_line0s_dirtyidx)

    if dirtyidx is not None:
        logger.debug("Recalculated line counts")
        line_count_start = 0
        if program_data.block_line0s_dirtyidx > 0:
            line_count_start = program_data.block_line0s[program_data.block_line0s_dirtyidx-1] + program_data.blocks[program_data.block_line0s_dirtyidx-1].line_count
        for i in xrange(program_data.block_line0s_dirtyidx, len(program_data.block_line0s)):
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

def get_next_data_line_number(program_data, line_idx, dir=1):
    block, block_idx = lookup_block_by_line_count(program_data, line_idx)
    block_idx += dir
    while block_idx < len(program_data.blocks) and block_idx >= 0:
        if get_block_data_type(program_data.blocks[block_idx]) != DATA_TYPE_CODE:
            return program_data.block_line0s[block_idx]
        block_idx += dir

def insert_block(program_data, insert_idx, block):
    program_data.block_addresses.insert(insert_idx, block.address)
    program_data.block_line0s.insert(insert_idx, None)
    program_data.blocks.insert(insert_idx, block)
    # Update how much of the sorted line number index needs to be recalculated.
    if program_data.block_line0s_dirtyidx is not None and insert_idx < program_data.block_line0s_dirtyidx:
        program_data.block_line0s_dirtyidx = insert_idx

ERR_SPLIT_EXISTING = -1
ERR_SPLIT_BOUNDS = -2
ERR_SPLIT_MIDINSTRUCTION = -3

def IS_SPLIT_ERR(value): return value < 0

def split_block(program_data, address, own_midinstruction=False):
    """ This function should preserve line count. """
    block, block_idx = lookup_block_by_address(program_data, address)
    if block.address == address:
        return block, ERR_SPLIT_EXISTING

    segments = program_data.loader_segments
    segment_address = loaderlib.get_segment_address(segments, block.segment_id)
    segment_length = loaderlib.get_segment_length(segments, block.segment_id)
    if address < segment_address or address >= segment_address + segment_length:
        logger.error("Tried to split at out of bounds address: %06X not within %06X-%06X", address, segment_address, segment_address+segment_length-1)
        return block, ERR_SPLIT_BOUNDS

    block_data_type = get_block_data_type(block)

    # How long the new block will be.
    excess_length = block.length - (address - block.address)
    block_length_reduced = block.length - excess_length

    # Do some pre-split code block validation.
    if block_data_type == DATA_TYPE_CODE:
        num_bytes = 0
        for i, (type_id, entry) in enumerate(block.line_data):
            if type_id == SLD_INSTRUCTION:
                if type(entry) is int:
                    entry = realise_instruction_entry(program_data, block, entry)
                if num_bytes == block_length_reduced:
                    break
                num_bytes += entry.num_bytes
                if block_length_reduced < num_bytes:
                    if own_midinstruction:
                        # Multiple consecutive entries of this type will be out of order.  Not worth bothering about.
                        block.line_data.insert(i+1, (SLD_EQU_LOCATION_RELATIVE, address-segment_address))
                        calculate_line_count(program_data, block)
                    else:
                        logger.debug("Attempting to split block mid-instruction (not handled here): %06X", address)
                    return block, ERR_SPLIT_MIDINSTRUCTION
        block_line_data = block.line_data[:i]
        split_block_line_data = block.line_data[i:]

        if address & 1:
            logger.debug("Splitting code block at odd address: %06X", address)

    # Truncate the preceding block the address is currently within.
    block.length = block_length_reduced

    # Create a new block for the address we are processing.
    new_block = SegmentBlock()
    new_block.flags = block.flags & BLOCK_SPLIT_BITMASK
    new_block.segment_id = block.segment_id
    new_block.address = block.address + block.length
    new_block.segment_offset = block.segment_offset + block.length
    new_block.length = excess_length
    insert_block(program_data, block_idx + 1, new_block)

    if block_data_type == DATA_TYPE_CODE:
        block.line_data = block_line_data
        new_block.line_data = split_block_line_data

    calculate_line_count(program_data, block)
    calculate_line_count(program_data, new_block)

    return new_block, block_idx + 1


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

SAVEFILE_VERSION = 1

def save_savefile(savefile_path, program_data):
    t0 = time.time()
    logger.debug("saving 'savefile' to: %s", savefile_path)

    with open(savefile_path, "wb") as f:
        f.write(struct.pack("<H", SAVEFILE_VERSION))
        size_offset = f.tell()
        f.write(struct.pack("<I", 0))

        data_start_offset = item_offset = f.tell()
        cPickle.dump(program_data.branch_addresses, f, -1)
        if True:
            item_length = f.tell() - item_offset
            logger.debug("save item length: %d name: branch_addresses", item_length)
            item_offset = f.tell()
        cPickle.dump(program_data.reference_addresses, f, -1)
        if True:
            item_length = f.tell() - item_offset
            logger.debug("save item length: %d name: reference_addresses", item_length)
            item_offset = f.tell()
        cPickle.dump(program_data.symbols_by_address, f, -1)
        if True:
            item_length = f.tell() - item_offset
            logger.debug("save item length: %d name: symbols_by_address", item_length)
            item_offset = f.tell()
        cPickle.dump(program_data.post_segment_addresses, f, -1)
        if True:
            item_length = f.tell() - item_offset
            logger.debug("save item length: %d name: post_segment_addresses", item_length)
            item_offset = f.tell()
        cPickle.dump(program_data.dis_name, f, -1)
        if True:
            item_length = f.tell() - item_offset
            logger.debug("save item length: %d name: dis_name", item_length)
            item_offset = f.tell()
        cPickle.dump(program_data.file_name, f, -1)
        if True:
            item_length = f.tell() - item_offset
            logger.debug("save item length: %d name: file_name", item_length)
            item_offset = f.tell()
        cPickle.dump(program_data.file_size, f, -1)
        if True:
            item_length = f.tell() - item_offset
            logger.debug("save item length: %d name: file_size", item_length)
            item_offset = f.tell()
        cPickle.dump(program_data.file_checksum, f, -1)
        if True:
            item_length = f.tell() - item_offset
            logger.debug("save item length: %d name: file_checksum", item_length)
            item_offset = f.tell()
        cPickle.dump(program_data.loader_system_name, f, -1)
        if True:
            item_length = f.tell() - item_offset
            logger.debug("save item length: %d name: loader_system_name", item_length)
            item_offset = f.tell()
        cPickle.dump(program_data.loader_segments, f, -1)
        if True:
            item_length = f.tell() - item_offset
            logger.debug("save item length: %d name: loader_segments", item_length)
            item_offset = f.tell()
        cPickle.dump(program_data.loader_relocated_addresses, f, -1)
        if True:
            item_length = f.tell() - item_offset
            logger.debug("save item length: %d name: loader_relocated_addresses", item_length)
            item_offset = f.tell()
        cPickle.dump(program_data.loader_relocatable_addresses, f, -1)
        if True:
            item_length = f.tell() - item_offset
            logger.debug("save item length: %d name: loader_relocatable_addresses", item_length)
            item_offset = f.tell()
        cPickle.dump(program_data.loader_entrypoint_segment_id, f, -1)
        if True:
            item_length = f.tell() - item_offset
            logger.debug("save item length: %d name: loader_entrypoint_segment_id", item_length)
            item_offset = f.tell()
        cPickle.dump(program_data.loader_entrypoint_offset, f, -1)
        if True:
            item_length = f.tell() - item_offset
            logger.debug("save item length: %d name: loader_entrypoint_offset", item_length)
            item_offset = f.tell()
        f.write(struct.pack("<I", len(program_data.blocks)))
        for block in program_data.blocks:
            block.write_savefile_data(f)
        data_end_offset = f.tell()
        if True:
            item_length = f.tell() - item_offset
            logger.debug("save item length: %d name: blocks", item_length)
            item_offset = f.tell()

        # Go back and write the size.
        f.seek(size_offset, os.SEEK_SET)
        f.write(struct.pack("<I", data_end_offset - data_start_offset))

        f.seek(data_end_offset, os.SEEK_SET)
        f.write(struct.pack("<I", 0))
        loader_data_start_offset = f.tell()
        system = loaderlib.get_system(program_data.loader_system_name)
        system.save_savefile_data(f, program_data.loader_internal_data)
        loader_data_end_offset = f.tell()

        # Go back and write the size.
        f.seek(data_end_offset, os.SEEK_SET)
        f.write(struct.pack("<I", loader_data_end_offset - loader_data_start_offset))

    seconds_taken = time.time() - t0
    logger.info("Saved working data to: %s (length: %d, time taken: %0.1fs)", savefile_path, loader_data_end_offset, seconds_taken)


def load_savefile(savefile_path):
    t0 = time.time()
    logger.debug("loading 'savefile' from: %s", savefile_path)

    program_data = ProgramData()
    with open(savefile_path, "rb") as f:
        savefile_version = struct.unpack("<H", f.read(2))[0]
        if savefile_version != SAVEFILE_VERSION:
            logger.error("Save-file is version %s, only version %s is supported at this time.", savefile_version, SAVEFILE_VERSION)
            return None, 0

        localdata_size = struct.unpack("<I", f.read(4))[0]

        data_start_offset = f.tell()
        program_data.branch_addresses = cPickle.load(f)
        program_data.reference_addresses = cPickle.load(f)
        program_data.symbols_by_address = cPickle.load(f)
        program_data.post_segment_addresses = cPickle.load(f)
        program_data.dis_name = cPickle.load(f)
        program_data.file_name = cPickle.load(f)
        program_data.file_size = cPickle.load(f)
        program_data.file_checksum = cPickle.load(f)
        program_data.loader_system_name = cPickle.load(f)
        program_data.loader_segments = cPickle.load(f)
        program_data.loader_relocated_addresses = cPickle.load(f)
        program_data.loader_relocatable_addresses = cPickle.load(f)
        program_data.loader_entrypoint_segment_id = cPickle.load(f)
        program_data.loader_entrypoint_offset = cPickle.load(f)
        # Reconstitute the segment block list.
        num_blocks = struct.unpack("<I", f.read(4))[0]
        program_data.blocks = [ None ] * num_blocks
        for i in xrange(num_blocks):
            program_data.blocks[i] = block = SegmentBlock()
            block.read_savefile_data(f)
        data_end_offset = f.tell()

        if localdata_size != data_end_offset - data_start_offset:
            logger.error("Save-file localdata length mismatch, got: %d wanted: %d", data_end_offset - data_start_offset, localdata_size)
            return None, 0

        # Rebuild the segment block list indexing lists.
        program_data.block_addresses = [ 0 ] * num_blocks
        program_data.block_line0s_dirtyidx = 0
        program_data.block_line0s = program_data.block_addresses[:]
        recalculate_line_count_index(program_data)
        for i in xrange(num_blocks):
            program_data.block_addresses[i] = program_data.blocks[i].address

        # The loaders internal data comes next, hand off reading that in as we do not use or care about it.
        loaderdata_size = struct.unpack("<I", f.read(4))[0]
        loader_data_start_offset = f.tell()
        system = loaderlib.get_system(program_data.loader_system_name)
        program_data.loader_internal_data = system.load_savefile_data(f)
        loader_data_end_offset = f.tell()

        if loaderdata_size != loader_data_end_offset - loader_data_start_offset:
            logger.error("Save-file loaderdata length mismatch, got: %d wanted: %d", loader_data_end_offset - loader_data_start_offset, loaderdata_size)
            return None, 0

    program_data.loader_data_types = loaderlib.get_system_data_types(program_data.loader_system_name)
    onload_set_disassemblylib_functions(program_data)
    onload_make_address_ranges(program_data)

    seconds_taken = time.time() - t0
    logger.info("Loaded working data from: %s (time taken: %0.1fs)", savefile_path, seconds_taken)

    DEBUG_log_load_stats(program_data)

    return program_data, get_line_count(program_data)

def set_data_type_at_address(program_data, address, data_type):
    block, block_idx = lookup_block_by_address(program_data, address)
    # If the block is already the given data type, no need to do anything.
    block_data_type = get_block_data_type(block)
    if data_type == block_data_type:
        return
    result = split_block(program_data, address)
    # If the address was within the address range of another block, split a block at the given address off and use that.
    if IS_SPLIT_ERR(result[1]):
        if result[1] != ERR_SPLIT_EXISTING:
            logger.error("set_data_type_at_address: At $%06X unexpected splitting error #%d", address, result[1])
            return
    else:
        block, block_idx = result

    if data_type == DATA_TYPE_CODE:
        process_address_as_code(program_data, address, set([ ]))
    else:
        set_block_data_type(block, data_type)
        block.line_data = None
        # Is this correct?
        block.flags &= ~BLOCK_FLAG_PROCESSED

    program_data.block_line0s_dirtyidx = block_idx
    calculate_line_count(program_data, block)

    logger.debug("Changed data type at %X to %d", address, data_type)

def process_address_as_code(program_data, address, pending_symbol_addresses):
    debug_offsets = set()
    disassembly_offsets = set([ address ])
    while len(disassembly_offsets):
        address = disassembly_offsets.pop()
        # logger.debug("Processing address: %X", address)

        block, block_idx = lookup_block_by_address(program_data, address)
        block_data_type = get_block_data_type(block)
        # When the address is mid-block, split the associated portion of the block off.
        if address - block.address > 0:
            result = split_block(program_data, address)
            if IS_SPLIT_ERR(result[1]):
                logger.debug("process_address_as_code/focus: At $%06X unexpected splitting error #%d", address, result[1])
                continue
            block, block_idx = result
            # address = block.address Superfluous due to it being the split address.

        if block_data_type == DATA_TYPE_CODE or (block.flags & BLOCK_FLAG_PROCESSED) == BLOCK_FLAG_PROCESSED:
            continue

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
                data_bytes_to_skip = program_data.dis_disassemble_as_data_func(data, data_offset_start)
                if data_bytes_to_skip == 0:
                    logger.error("unable to disassemble data at %X (started at %X)", match_address, address)
                break
            bytes_matched = data_offset_end - data_offset_start
            if bytes_consumed + bytes_matched > block.length:
                logger.error("unable to disassemble due to a block length overrun at %X (started at %X)", match_address, address)
                break
            line_data.append((SLD_INSTRUCTION, match))
            for label_offset in range(1, bytes_matched):
                label_address = match_address + label_offset
                label = program_data.symbols_by_address.get(label_address)
                if label is not None:
                    line_data.append((SLD_EQU_LOCATION_RELATIVE, block.segment_offset + (label_address - block.address)))
                    # logger.debug("%06X: mid-instruction label = '%s'", match_address, label)
            bytes_consumed += bytes_matched
            found_terminating_instruction = program_data.dis_is_final_instruction_func(match)
            if found_terminating_instruction:
                break

        # Discard any unprocessed block / jump over isolatible unprocessed instructions.
        if bytes_consumed < block.length:
            new_code_address = None
            if bytes_consumed == 0:
                # If we encountered an unknown instruction at the start of a block.
                if data_bytes_to_skip:
                    # We'll split at this address, leaving the current block as a processed longword block.
                    new_code_address = address + data_bytes_to_skip
                else:
                    logger.error("Skipping block at %X with no code (length: %X)", data_offset_start, block.length)
            else:
                result = split_block(program_data, address + bytes_consumed)
                if IS_SPLIT_ERR(result[1]):
                    logger.error("process_address_as_code/unrecognised-code: At $%06X unexpected splitting error #%d", address + bytes_consumed, result[1])
                    block.flags |= BLOCK_FLAG_PROCESSED
                    continue
                trailing_block, trailing_block_idx = result
                set_block_data_type(trailing_block, DATA_TYPE_LONGWORD)

                # If an unknown instruction was encountered.
                if not found_terminating_instruction:
                    # We are marking the code past any bytes to skip as processed here, so we need to mark that as unprocessed again when we split it off brlow.
                    trailing_block.flags |= BLOCK_FLAG_PROCESSED
                    # If code resumes after analysis determines we can skip the unknown instruction as data.
                    if data_bytes_to_skip:
                        new_code_address = address + bytes_consumed + data_bytes_to_skip

            if new_code_address is not None:
                # TODO: Verify that the split "trailing" block was within the original block.
                result = split_block(program_data, new_code_address)
                if IS_SPLIT_ERR(result[1]):
                    if result[1] == ERR_SPLIT_EXISTING:
                        # We've skipped into an existing block, only continue disassembling if it is unprocessed.
                        trailing_block, trailing_block_idx = lookup_block_by_address(program_data, new_code_address)
                        if not trailing_block.flags & BLOCK_FLAG_PROCESSED:
                            disassembly_offsets.add(new_code_address)
                    else:
                        logger.error("process_address_as_code/skipped-data: At $%06X unexpected splitting error #%d", new_code_address, result[1])
                        block.flags |= BLOCK_FLAG_PROCESSED
                        continue
                else:
                    # We've split off a new block and will continue disassembling here.
                    trailing_block, trailing_block_idx = result
                    set_block_data_type(trailing_block, DATA_TYPE_LONGWORD)
                    trailing_block.flags &= ~BLOCK_FLAG_PROCESSED
                    disassembly_offsets.add(new_code_address)

        # If there were no code statements identified, this will just be processed data.
        block.flags |= BLOCK_FLAG_PROCESSED
        if len(line_data) == 0:
            continue

        set_block_data_type(block, DATA_TYPE_CODE)
        block.line_data = line_data
        calculate_line_count(program_data, block)

        # Extract any addresses which are referred to, for later use.
        for type_id, entry in line_data:
            if type_id == SLD_INSTRUCTION:
                for match_address, flags in program_data.dis_get_match_addresses_func(entry).iteritems():
                    if flags & 1: # MAF_CODE
                        disassembly_offsets.add(match_address)
                        insert_branch_address(program_data, match_address, entry.pc-2, pending_symbol_addresses)
                    elif flags & 2: # MAF_ABSOLUTE
                        if match_address in program_data.loader_relocated_addresses:
                            search_address = match_address
                            while search_address < match_address + entry.num_bytes:
                                if search_address in program_data.loader_relocatable_addresses:
                                    insert_reference_address(program_data, match_address, entry.pc-2, pending_symbol_addresses)
                                    # print "ABS REF LOCATION: %X FOUND Imm ADDRESS %X INS %s" % (entry.pc, match_address, entry.specification.key)
                                    break
                                search_address += 1
                    else:
                        insert_reference_address(program_data, match_address, entry.pc-2, pending_symbol_addresses)

        # DEBUG BLOCK SPILLING BASED ON LOGICAL ASSUMPTION OF MORE CODE.
        if bytes_consumed == block.length and not found_terminating_instruction and not data_bytes_to_skip:
            debug_offsets.add(block.address+block.length)

    # Add in all the detected new addresses with default labeling, and split accordingly.
    for address in pending_symbol_addresses:
        if address not in program_data.symbols_by_address:
            block, block_idx = lookup_block_by_address(program_data, address)
            if block.address != address:
                result = split_block(program_data, address, own_midinstruction=True)
                # Add in labels for out of bounds addresses, they should be displayed.
                if IS_SPLIT_ERR(result[1]):
                    # These are the only possible block splitting errors.
                    if result[1] == ERR_SPLIT_BOUNDS:
                        insert_symbol(program_data, address, "lbZ%06X" % address)
                    elif result[1] == ERR_SPLIT_MIDINSTRUCTION:
                        insert_symbol(program_data, address, "SYM%06X" % address)
                    else:
                        logger.error("process_address_as_code/labeling: At $%06X unexpected splitting error #%d", address, result[1])
                    continue
                block, block_idx = result
            label = "lb"+ char_by_data_type[get_block_data_type(block)] + ("%06X" % address)
            insert_symbol(program_data, address, label)

    for address in debug_offsets:
        block, block_idx = lookup_block_by_address(program_data, address)
        if get_block_data_type(block) == DATA_TYPE_CODE and block.flags & BLOCK_FLAG_PROCESSED:
            continue
        logger.debug("%06X (%06X): Found end of block boundary with processed code and no end instruction (data type: %d, processed: %d)", address, block.address, get_block_data_type(block), block.flags & BLOCK_FLAG_PROCESSED)


def load_file(file_path):
    result = loaderlib.load_file(file_path)
    if result is None:
        return None, 0

    file_info, data_types = result

    program_data = ProgramData()
    program_data.block_addresses = []
    program_data.block_line0s = []
    program_data.block_line0s_dirtyidx = 0
    program_data.post_segment_addresses = {}

    program_data.loader_file_path = file_path
    program_data.loader_system_name = file_info.system.system_name
    program_data.loader_relocatable_addresses = set()
    program_data.loader_relocated_addresses = set()

    program_data.dis_name = file_info.system.get_arch_name()

    segments = program_data.loader_segments = file_info.segments

    # Extract useful information from file loading process.
    program_data.loader_data_types = data_types
    program_data.loader_internal_data = file_info.get_savefile_data()

    onload_set_disassemblylib_functions(program_data)
    onload_make_address_ranges(program_data)

    program_data.loader_entrypoint_segment_id = file_info.entrypoint_segment_id
    program_data.loader_entrypoint_offset = file_info.entrypoint_offset
    loaderlib.cache_segment_data(file_path, segments)
    loaderlib.relocate_segment_data(segments, data_types, file_info.relocations_by_segment_id, program_data.loader_relocatable_addresses, program_data.loader_relocated_addresses)

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
        set_block_data_type(block, DATA_TYPE_LONGWORD)
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
            set_block_data_type(block, DATA_TYPE_LONGWORD)
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

    # Pass 3: Do a disassembly pass.
    # Static pre-known addresses to make into symbols / labels.
    existing_symbol_addresses = program_data.symbols_by_address.keys()
    pending_symbol_addresses = program_data.loader_relocated_addresses.copy()
    pending_symbol_addresses.add(entrypoint_address)

    # Follow the disassembly at the given address, as far as it takes us.
    process_address_as_code(program_data, entrypoint_address, pending_symbol_addresses)

    # Split the blocks for existing symbols (so their label appears).
    for address in existing_symbol_addresses:
        result = split_block(program_data, address)
        if IS_SPLIT_ERR(result[1]):
            if result[1] in (ERR_SPLIT_EXISTING, ERR_SPLIT_MIDINSTRUCTION):
                continue
            logger.error("load_file: At $%06X unexpected splitting error #%d", address, result[1])

    DEBUG_log_load_stats(program_data)

    recalculate_line_count_index(program_data)
    return program_data, get_line_count(program_data)


def onload_set_disassemblylib_functions(program_data):
    for func_name, func in disassemblylib.get_api(program_data.dis_name):
        setattr(program_data, "dis_"+ func_name +"_func", func)

def onload_make_address_ranges(program_data):
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
            elif address0 == new_addressN+1:
                segment_ids.add(segment_id)
                program_data.address_ranges[i] = new_address0, addressN-1, segment_ids
                break
        else:
            program_data.address_ranges.append((new_address0, new_addressN-1, set([segment_id])))

def DEBUG_log_load_stats(program_data):
    # Log debug statistics
    num_code_blocks = 0
    num_code_bytes = 0
    for block in program_data.blocks:
        if get_block_data_type(block) == DATA_TYPE_CODE:
            num_code_bytes += block.length
            num_code_blocks += 1
    logger.debug("Initial result, code bytes: %d, code blocks: %d", num_code_bytes, num_code_blocks)


if __name__ == "__main__":
    logger.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    logger.addHandler(ch)
