"""
    Peasauce - interactive disassembler
    Copyright (C) 2012, 2013 Richard Tew

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

from disassembly_data import *
import loaderlib
import disassemblylib
import disassembly_persistence
import persistence
import util


logger = logging.getLogger("disassembly")


END_INSTRUCTION_LINES = 2

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



## SegmentBlock flag helpers

def realise_instruction_entry(program_data, block, block_offset):
    data = loaderlib.get_segment_data(program_data.loader_segments, block.segment_id)
    data_offset_start = block.segment_offset + block_offset
    match, data_offset_end = program_data.dis_disassemble_one_line_func(data, data_offset_start, block.address + block_offset)
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
    elif get_block_data_type(block) in NUMERIC_DATA_TYPES:
        sizes = get_data_type_sizes(block)
        for size_char, num_bytes, size_count, size_lines in sizes:
            block.line_count += size_lines
    elif get_block_data_type(block) == DATA_TYPE_ASCII:
        block.line_count = len(block.line_data)
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
                entry = realise_instruction_entry(program_data, block, block.segment_offset + entry)
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
                logger.debug("get_code_block_info_for_line_number.1: %d, %d = %s", line_number, line_count, None if previous_result is None else hex(previous_result[0]))
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
    data_type = get_block_data_type(block)
    if data_type == DATA_TYPE_CODE:
        result = get_code_block_info_for_address(program_data, address)
        return result[0]
    elif data_type in NUMERIC_DATA_TYPES:
        block_lineN = program_data.block_line0s[block_idx] + calculate_block_leading_line_count(program_data, block)
        block_offsetN = 0
        address_block_offset = address - block.address
        for size_char, num_bytes, size_count, size_lines in get_data_type_sizes(block):
            block_offset0 = block_offsetN
            block_offsetN += num_bytes * size_count
            block_line0 = block_lineN
            block_lineN += size_lines
            if address_block_offset >= block_offset0 and address_block_offset < block_offsetN:
                return block_line0 + (address_block_offset - block_offset0) / num_bytes
    elif data_type == DATA_TYPE_ASCII:
        block_lineN = program_data.block_line0s[block_idx] + calculate_block_leading_line_count(program_data, block)
        block_offsetN = 0
        address_block_offset = address - block.address
        for byte_offset, byte_length in block.line_data:
            block_offset0 = block_offsetN
            block_offsetN += byte_length
            block_line0 = block_lineN
            block_lineN += 1
            if address_block_offset >= block_offset0 and address_block_offset < block_offsetN:
                return block_line0
    return None


def get_address_for_line_number(program_data, line_number):
    block, block_idx = lookup_block_by_line_count(program_data, line_number)

    data_type = get_block_data_type(block)
    logger.debug("get_address_for_line_number: data type = %d", data_type)

    if data_type == DATA_TYPE_CODE:
        result = get_code_block_info_for_line_number(program_data, line_number)
        if result is not None:
            address, match = result
            return address
    elif data_type in NUMERIC_DATA_TYPES:
        base_line_count = program_data.block_line0s[block_idx] + calculate_block_leading_line_count(program_data, block)
        block_lineN = base_line_count
        block_offsetN = 0
        for size_char, num_bytes, size_count, size_lines in get_data_type_sizes(block):
            block_offset0 = block_offsetN
            block_offsetN += num_bytes * size_count
            block_line0 = block_lineN
            block_lineN += size_lines
            if line_number >= block_line0 and line_number < block_lineN:
                return block.address + block_offset0 + (line_number - block_line0) * num_bytes
    elif data_type == DATA_TYPE_ASCII:
        base_line_count = program_data.block_line0s[block_idx] + calculate_block_leading_line_count(program_data, block)
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


def get_referenced_symbol_addresses_for_line_number(program_data, line_number):
    result = get_code_block_info_for_line_number(program_data, line_number)
    if result is not None:
        address, match = result
        return [ k for (k, v) in program_data.dis_get_match_addresses_func(match).iteritems() if k in program_data.symbols_by_address ]
    return []


"""
This may be of future use, but what it should return remains to be decided.

def get_all_references(program_data):
    for target_address, referring_addresses in program_data.reference_addresses.iteritems():
        target_block, target_block_idx = lookup_block_by_address(program_data, target_address)
        if target_block.address != target_address:
            logger.error("get_all_references: analysing reference referrers, target address mismatch: %X != %X", target_block.address, target_address)
            continue
        if get_block_data_type(target_block) == DATA_TYPE_LONGWORD:
            for source_address in referring_addresses:
                source_block, source_block_idx = lookup_block_by_address(program_data, source_address)
                if get_block_data_type(source_block) == DATA_TYPE_CODE:
                    line_number, match = get_code_block_info_for_address(program_data, source_address)
"""

def get_data_type_sizes(block):
    data_type = get_block_data_type(block)
    if data_type == DATA_TYPE_LONGWORD:
        size_types = [ ("L", 4), ("W", 2), ("B", 1) ]
    elif data_type == DATA_TYPE_WORD:
        size_types = [ ("W", 2), ("B", 1) ]
    elif data_type == DATA_TYPE_BYTE:
        size_types = [ ("B", 1) ]

    sizes = []
    unconsumed_byte_count = block.length
    for size_char, num_bytes in size_types:
        size_count = unconsumed_byte_count / num_bytes
        if size_count == 0:
            continue
        if block.flags & BLOCK_FLAG_ALLOC:
            size_lines = 1
        else:
            size_lines = size_count
        sizes.append((size_char, num_bytes, size_count, size_lines))
        unconsumed_byte_count -= size_count * num_bytes
    return sizes


def get_line_count(program_data):
    if program_data.block_line0s is None:
        return 0
    recalculate_line_count_index(program_data)
    return program_data.block_line0s[-1] + program_data.blocks[-1].line_count + END_INSTRUCTION_LINES


def get_file_line(program_data, line_idx, column_idx): # Zero-based
    if line_idx is None:
        return "BAD ROW"
    if column_idx is None:
        return "BAD COLUMN"
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

    data_type = get_block_data_type(block)

    ## Block content line generation.
    if data_type == DATA_TYPE_CODE:
        block_offset0 = 0
        block_offsetN = 0
        line_count = block_line_count0 + leading_line_count
        line_type_id = None
        line_match = None
        line_num_bytes = None
        for type_id, entry in block.line_data:
            if type_id == SLD_INSTRUCTION:
                if type(entry) is int:
                    entry = realise_instruction_entry(program_data, block, entry)
                block_offsetN += entry.num_bytes
            if line_count == line_idx:
                line_type_id = type_id
                line_match = entry
                break
            if type_id == SLD_INSTRUCTION:
                block_offset0 = block_offsetN
                line_count += calculate_match_line_count(program_data, entry)
            elif type_id in (SLD_COMMENT_FULL_LINE, SLD_EQU_LOCATION_RELATIVE):
                line_count += 1
        else:
            # Trailing blank lines.
            return ""

        address0 = block.address + block_offset0
        addressN = block.address + block_offsetN
        if line_type_id == SLD_EQU_LOCATION_RELATIVE:
            segment_address = loaderlib.get_segment_address(segments, block.segment_id)
            block_offset0 = line_match
            address0 = segment_address + block.segment_offset + block_offset0
        line_num_bytes = addressN - address0

        if column_idx == LI_OFFSET:
            return "%08X" % address0
        elif column_idx == LI_BYTES:
            if line_type_id in (SLD_INSTRUCTION, SLD_EQU_LOCATION_RELATIVE):
                data = loaderlib.get_segment_data(segments, block.segment_id)
                data_offset = block.segment_offset + block_offset0
                return "".join([ "%02X" % c for c in data[data_offset:data_offset+line_num_bytes] ])
            return ""
        elif column_idx == LI_LABEL:
            label = get_symbol_for_address(program_data, address0)
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
    elif data_type in NUMERIC_DATA_TYPES:
        block_lineN = block_line_count0 + leading_line_count
        block_offsetN = block.segment_offset
        sizes = get_data_type_sizes(block)
        for i, (size_char, num_bytes, size_count, size_lines) in enumerate(sizes):
            block_offset0 = block_offsetN
            block_offsetN += num_bytes * size_count
            block_line0 = block_lineN
            block_lineN += size_lines

            if line_idx >= block_line0 and line_idx < block_lineN:
                data_idx = block_offset0 + (line_idx - block_line0) * num_bytes
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
                    if size_char == "L":
                        value = program_data.loader_data_types.uint32_value(data, data_idx)
                    elif size_char == "W":
                        value = program_data.loader_data_types.uint16_value(data, data_idx)
                    elif size_char == "B":
                        value = program_data.loader_data_types.uint8_value(data, data_idx)
                    label = None
                    # Only turn the value into a symbol if we actually relocated the value.
                    if size_char == "L" and value in program_data.loader_relocatable_addresses:
                        label = get_symbol_for_address(program_data, value)
                    if label is None:
                        label = ("$%0"+ str(num_bytes<<1) +"X") % value
                    return label
                elif DEBUG_ANNOTATE_DISASSEMBLY and column_idx == LI_ANNOTATIONS:
                    return "-"
    elif data_type == DATA_TYPE_ASCII:
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
                    return "".join([ "%02X" % c for c in data[data_idx:data_idx+byte_length] ])
                elif column_idx == LI_LABEL:
                    label = get_symbol_for_address(program_data, loaderlib.get_segment_address(segments, block.segment_id) + data_idx)
                    if label is None:
                        return ""
                    return label
                elif column_idx == LI_INSTRUCTION:
                    name = loaderlib.get_data_instruction_string(program_data.loader_system_name, segments, block.segment_id, True)
                    return name +".B"
                elif column_idx == LI_OPERANDS:
                    string = ""
                    last_value = None
                    data = loaderlib.get_segment_data(segments, block.segment_id)
                    for byte in data[data_idx:data_idx+byte_length]:
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
                            string += _get_byte_representation(byte)
                        last_value = value
                    if last_value is not None:
                        if type(last_value) is str:
                            string += "'"
                    return string
                elif DEBUG_ANNOTATE_DISASSEMBLY and column_idx == LI_ANNOTATIONS:
                    return "-"


def check_known_address(program_data, address):
    pre_ids = set()
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
    if not check_known_address(program_data, address):
        return False
    # These get split as their turn to be disassembled comes up.
    referring_addresses = program_data.branch_addresses.setdefault(address, set())
    referring_addresses.add(src_abs_idx)
    #program_data.branch_addresses[address] = referring_addresses
    pending_symbol_addresses.add(address)
    return True

def insert_reference_address(program_data, address, src_abs_idx, pending_symbol_addresses):
    if not check_known_address(program_data, address):
        return False
    referring_addresses = program_data.reference_addresses.setdefault(address, set())
    referring_addresses.add(src_abs_idx)
    #program_data.reference_addresses[address] = referring_addresses
    pending_symbol_addresses.add(address)
    return True

def get_referring_addresses(program_data, address):
    referring_addresses = set()
    referring_addresses.update(program_data.branch_addresses.get(address, set()))
    referring_addresses.update(program_data.reference_addresses.get(address, set()))
    return referring_addresses

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
    if not check_known_address(program_data, address):
        return
    program_data.symbols_by_address[address] = name
    if program_data.symbol_insert_func: program_data.symbol_insert_func(address, name)

def get_symbol_for_address(program_data, address, absolute_info=None):
    # If the address we want a symbol was relocated somewhere, verify the instruction got relocated.
    if absolute_info is not None:
        valid_address = False
        referring_instruction_address, num_instruction_bytes = absolute_info
        if program_data.flags & PDF_BINARY_FILE == PDF_BINARY_FILE:
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
        if dirtyidx > 0:
            line_count_start = program_data.block_line0s[dirtyidx-1] + program_data.blocks[dirtyidx-1].line_count
        for i in xrange(dirtyidx, len(program_data.block_line0s)):
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
        #import traceback
        #traceback.print_stack()
        return block, ERR_SPLIT_BOUNDS

    block_data_type = get_block_data_type(block)

    # How long the new block will be.
    split_offset = address - block.address
    excess_length = block.length - split_offset
    block_length_reduced = block.length - excess_length

    # Do some pre-split code block validation.
    if block_data_type == DATA_TYPE_CODE:
        offsetN = 0
        for i, (type_id, entry) in enumerate(block.line_data):
            # Comments are assumed to be related to succeeding instruction lines, so are grouped for purposes of splitting.
            if type_id in (SLD_INSTRUCTION, SLD_COMMENT_FULL_LINE):
                if block_length_reduced == offsetN:
                    break

            if type_id == SLD_INSTRUCTION:
                if type(entry) is int:
                    entry = realise_instruction_entry(program_data, block, entry)
                offsetN += entry.num_bytes
                if block_length_reduced < offsetN:
                    if own_midinstruction:
                        # Multiple consecutive entries of this type will be out of order.  Not worth bothering about.
                        block.line_data.insert(i+1, (SLD_EQU_LOCATION_RELATIVE, split_offset))
                        calculate_line_count(program_data, block)
                    else:
                        logger.debug("Attempting to split block mid-instruction (not handled here): %06X", address)
                    return block, ERR_SPLIT_MIDINSTRUCTION

        # Line data: divide between blocks at the given point.
        block_line_data = block.line_data[:i]
        split_block_line_data = block.line_data[i:]

        # Line data: rebase block offsets within new block entries.
        for i, (type_id, entry) in enumerate(split_block_line_data):
            if type_id in (SLD_EQU_LOCATION_RELATIVE, SLD_INSTRUCTION) and type(entry) is int:
                split_block_line_data[i] = (type_id, entry-split_offset)

        # References: divide between blocks at the given address.
        if block.references is not None:
            for i, entry in enumerate(block.references):
                if entry[0] >= address:
                    break
            new_block_references = block.references[i:]
            block.references[i:] = []
        else:
            new_block_references = None

        if address & 1:
            logger.debug("Splitting code block at odd address: %06X", address)

    # Truncate the preceding block the address is currently within.
    block.length = block_length_reduced

    # Create a new block for the address we are processing.
    new_block = disassembly_persistence.SegmentBlock()
    new_block.flags = block.flags & BLOCK_SPLIT_BITMASK
    new_block.segment_id = block.segment_id
    new_block.address = block.address + block.length
    new_block.segment_offset = block.segment_offset + block.length
    new_block.length = excess_length
    insert_block(program_data, block_idx + 1, new_block)

    if block_data_type == DATA_TYPE_CODE:
        block.line_data = block_line_data
        new_block.line_data = split_block_line_data
        new_block.references = new_block_references
    elif block_data_type == DATA_TYPE_ASCII:
        _process_block_as_ascii(program_data, block)
        _process_block_as_ascii(program_data, new_block)

    calculate_line_count(program_data, block)
    calculate_line_count(program_data, new_block)

    return new_block, block_idx + 1

def _locate_uncertain_data_references(program_data, address, block=None):
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
            line_idx = get_line_number_for_address(program_data, address + address_offset)
            code_string = get_file_line(program_data, line_idx, LI_INSTRUCTION)
            operands_text = get_file_line(program_data, line_idx, LI_OPERANDS)
            if len(operands_text):
                code_string += " "+ operands_text
            matches.append((address + address_offset, value, code_string))
        address_offset += 2
    return matches

def get_uncertain_data_references(program_data):
    results = []
    for block in program_data.blocks:
        data_type = get_block_data_type(block)
        if data_type != DATA_TYPE_CODE and block.references:
            results.extend(block.references)
    return results

def _locate_uncertain_code_references(program_data, address, block=None):
    """ Check for candidate operand values in instructions within the data block from address onwards. """
    if block is None:
        block, block_idx = lookup_block_by_address(program_data, address)
    matches = []
    addressN = block.address
    for i, (type_id, entry) in enumerate(block.line_data):
        if type_id == SLD_INSTRUCTION:
            if type(entry) is int:
                entry = realise_instruction_entry(program_data, block, entry)
            address0 = addressN
            addressN += entry.num_bytes
            if addressN >= address:
                # Is this statement suitable?  Need an 
                for value, flags in program_data.dis_get_match_addresses_func(entry).iteritems():
                    if flags & 2: # MAF_ABSOLUTE
                        line_idx = get_line_number_for_address(program_data, address0)
                        code_string = get_file_line(program_data, line_idx, LI_INSTRUCTION)
                        operands_text = get_file_line(program_data, line_idx, LI_OPERANDS)
                        if len(operands_text):
                            code_string += " "+ operands_text
                        matches.append((address0, value, code_string))
    return matches

def get_uncertain_code_references(program_data):
    results = []
    for block in program_data.blocks:
        data_type = get_block_data_type(block)
        if data_type == DATA_TYPE_CODE and block.references:
            results.extend(block.references)
    return results

def get_uncertain_references_by_address(program_data, address):
    # That the block is a data block is known.
    block, block_idx = lookup_block_by_address(program_data, address)
    return block.references

def set_uncertain_reference_modification_func(program_data, f):
    program_data.uncertain_reference_modification_func = f

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

    # At this point we are attempting to change a block from one data type to another.
    if data_type == DATA_TYPE_CODE:
        # This can fail, so we do not explicitly change the block ourselves.
        new_code_blocks = _process_address_as_code(program_data, address, set([ ]))

        # This needs to be updated before operating on the new blocks.
        recalculate_line_count_index(program_data, block_idx)

        for block in new_code_blocks:
            block.references = _locate_uncertain_code_references(program_data, block.address, block)
    else:
        set_block_data_type(block, data_type)
        if data_type == DATA_TYPE_ASCII:
            _process_block_as_ascii(program_data, block)
        else:
            block.line_data = None
        block.flags &= ~BLOCK_FLAG_PROCESSED

        calculate_line_count(program_data, block)
        recalculate_line_count_index(program_data, block_idx)

        block.references = _locate_uncertain_data_references(program_data, address)

    logger.debug("Changed data type at %X to %d", address, data_type)

    if program_data.uncertain_reference_modification_func is not None:
        program_data.uncertain_reference_modification_func(block_data_type, data_type, block.address, block.length)

def _process_block_as_ascii(program_data, block):
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
        if byte >= 32 and byte < 127:
            # Sequential displayable characters get collected into a contiguous string.
            value = chr(byte)
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
    if byte < 16:
        return "%d" % byte
    else:
        return "$%X" % byte

def _process_address_as_code(program_data, address, pending_symbol_addresses):
    debug_offsets = set()
    disassembly_offsets = set([ address ])
    new_code_block_addresses = []
    while len(disassembly_offsets):
        address = disassembly_offsets.pop()
        block, block_idx = lookup_block_by_address(program_data, address)
        block_data_type = get_block_data_type(block)
        # When the address is mid-block, split the associated portion of the block off.
        if address - block.address > 0:
            result = split_block(program_data, address)
            if IS_SPLIT_ERR(result[1]):
                logger.debug("_process_address_as_code/focus: At $%06X unexpected splitting error #%d", address, result[1])
                continue
            block, block_idx = result
            # address = block.address Superfluous due to it being the split address.

        if block_data_type == DATA_TYPE_CODE or (block.flags & BLOCK_FLAG_PROCESSED) == BLOCK_FLAG_PROCESSED:
            continue

        bytes_consumed = 0
        data_bytes_to_skip = 0
        line_data = []
        found_terminating_instruction = False
        # logger.debug("disassembling block: address=$%X length=%d", address, block.length)
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
                    line_data.append((SLD_EQU_LOCATION_RELATIVE, label_address - address))
                    #logger.debug("%06X: mid-instruction label = '%s' %d", match_address, label, label_address-match_address)
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
                    logger.error("_process_address_as_code/unrecognised-code: At $%06X unexpected splitting error #%d", address + bytes_consumed, result[1])
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
                        logger.error("_process_address_as_code/skipped-data: At $%06X unexpected splitting error #%d", new_code_address, result[1])
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
        new_code_block_addresses.append(block)

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
                    elif flags & 4 != 4: # !MAF_UNCERTAIN
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
                        logger.error("_process_address_as_code/labeling: At $%06X unexpected splitting error #%d", address, result[1])
                    continue
                block, block_idx = result
            label = "lb"+ { DATA_TYPE_CODE: "C", DATA_TYPE_ASCII: "A", DATA_TYPE_BYTE: "B", DATA_TYPE_WORD: "W", DATA_TYPE_LONGWORD: "L" }[get_block_data_type(block)] + ("%06X" % address)
            insert_symbol(program_data, address, label)

    for address in debug_offsets:
        block, block_idx = lookup_block_by_address(program_data, address)
        if get_block_data_type(block) == DATA_TYPE_CODE and block.flags & BLOCK_FLAG_PROCESSED:
            continue
        logger.debug("%06X (%06X): Found end of block boundary with processed code and no end instruction (data type: %d, processed: %d)", address, block.address, get_block_data_type(block), block.flags & BLOCK_FLAG_PROCESSED)

    #print "process code:", len(new_code_block_addresses)
    return new_code_block_addresses


def get_new_project_options(program_data):
    return NewProjectOptions()

def get_load_project_options(program_data):
    return LoadProjectOptions()

def get_save_project_options(program_data):
    return SaveProjectOptions()

def is_project_inputfile_cached(program_data):
    return program_data.input_file_cached

def get_project_save_count(program_data):
    return program_data.save_count

## Project loading and saving.

def save_project_file(save_file, program_data, save_options):
    return disassembly_persistence.save_project(save_file, program_data, save_options)


def load_project_file(save_file):
    program_data = disassembly_persistence.load_project(save_file)
    if program_data is None:
        return None, 0

    for block in program_data.blocks:
        if get_block_data_type(block) == DATA_TYPE_ASCII:
            _process_block_as_ascii(program_data, block)
    recalculate_line_count_index(program_data)

    onload_set_disassemblylib_functions(program_data)
    onload_make_address_ranges(program_data)
    onload_cache_uncertain_references(program_data)

    DEBUG_log_load_stats(program_data)

    return program_data, get_line_count(program_data)


def load_file(input_file, new_options):
    loader_options = None
    if new_options.is_binary_file:
        loader_options = loaderlib.BinaryFileOptions()
        loader_options.dis_name = new_options.dis_name
        loader_options.load_address = new_options.loader_load_address
        loader_options.entrypoint_offset = new_options.loader_entrypoint_offset

    result = loaderlib.load_file(input_file, loader_options)
    if result is None:
        return None, 0

    file_info, data_types = result

    program_data = disassembly_persistence.ProgramData()
    flags = 0
    if new_options.is_binary_file:
        flags |= PDF_BINARY_FILE
    program_data.flags |= flags
    program_data.block_addresses = []
    program_data.block_line0s = []
    program_data.block_line0s_dirtyidx = 0
    program_data.post_segment_addresses = {}

    program_data.loader_system_name = file_info.system.system_name
    program_data.loader_relocatable_addresses = set()
    program_data.loader_relocated_addresses = set()

    input_file.seek(0, os.SEEK_END)
    program_data.file_size = input_file.tell()
    program_data.file_checksum = util.calculate_file_checksum(input_file)
    program_data.dis_name = file_info.system.get_arch_name()

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

    # Pass 1: Create a block for each of the segments.
    for segment_id in range(len(segments)):
        address = loaderlib.get_segment_address(segments, segment_id)
        data_length = loaderlib.get_segment_data_length(segments, segment_id)
        segment_length = loaderlib.get_segment_length(segments, segment_id)

        block = disassembly_persistence.SegmentBlock()
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
            block = disassembly_persistence.SegmentBlock()
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
    _process_address_as_code(program_data, entrypoint_address, pending_symbol_addresses)

    # Split the blocks for existing symbols (so their label appears).
    for address in existing_symbol_addresses:
        result = split_block(program_data, address)
        if IS_SPLIT_ERR(result[1]):
            if result[1] in (ERR_SPLIT_EXISTING, ERR_SPLIT_MIDINSTRUCTION):
                continue
            logger.error("load_file: At $%06X unexpected splitting error #%d", address, result[1])

    recalculate_line_count_index(program_data)

    ## Any analysis / post-processing that does not change line count should go below.
    onload_cache_uncertain_references(program_data)

    DEBUG_log_load_stats(program_data)

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

def onload_cache_uncertain_references(program_data):
    if program_data.flags & PDF_BINARY_FILE == PDF_BINARY_FILE:
        for block in program_data.blocks:
            data_type = get_block_data_type(block)
            if data_type == DATA_TYPE_CODE:
                block.references = _locate_uncertain_code_references(program_data, block.address, block)
            else:
                block.references = _locate_uncertain_data_references(program_data, block.address, block)


def cache_segment_data(program_data, f):
    segments = program_data.loader_segments
    for i in range(len(segments)):
        loaderlib.cache_segment_data(f, segments, i)
    # program_data.loader_file_path = file_path
    # TODO: reconcile

def is_segment_data_cached(program_data):
    segments = program_data.loader_segments
    for i in range(len(segments)):
        if loaderlib.get_segment_data(segments, i) is not None:
            return True
    return False

def DEBUG_log_load_stats(program_data):
    # Log debug statistics
    num_code_blocks = 0
    num_code_bytes = 0
    for block in program_data.blocks:
        if get_block_data_type(block) == DATA_TYPE_CODE:
            num_code_bytes += block.length
            num_code_blocks += 1
    logger.debug("Initial result, code bytes: %d, code blocks: %d", num_code_bytes, num_code_blocks)

def DEBUG_locate_potential_code_blocks(program_data):
    blocks = []
    for block in program_data.blocks:
        if get_block_data_type(block) != DATA_TYPE_CODE and block.length >= 2:
            data = loaderlib.get_segment_data(program_data.loader_segments, block.segment_id)
            offset_start = block.length - 2
            data_offset_start = block.segment_offset + offset_start
            match, data_offset_end = program_data.dis_disassemble_one_line_func(data, data_offset_start, block.address + offset_start)
            if match is not None and data_offset_end < data_offset_start + block.length:
                if program_data.dis_is_final_instruction_func(match):
                    blocks.append(block)
    return blocks


if __name__ == "__main__":
    logger.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    logger.addHandler(ch)
