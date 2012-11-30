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

import logging
import os
import struct
import time

from disassembly_data import *
import loaderlib
import persistence


logger = logging.getLogger("disassembly-persistence")


SEGMENTBLOCK_PACK_FORMAT = "<HIIIIHH"


def write_SegmentBlock(f, block):
    if block.line_data is None:
        line_data_count = 0
    else:
        line_data_count = len(block.line_data)

    s = struct.pack(SEGMENTBLOCK_PACK_FORMAT, block.segment_id, block.segment_offset, block.address, block.length, block.flags, block.line_count, line_data_count)
    f.write(s)

    if line_data_count > 0:
        block_offset = 0
        for i, (type_id, entry) in enumerate(block.line_data):
            persistence.write_uint8(f, type_id)
            if type_id == SLD_INSTRUCTION:
                if type(entry) is int:
                    persistence.write_uint16(f, entry)
                    # The length of this instruction is not stored, so we calculate it relative to the next one. 
                    j = i+1
                    while j < len(block.line_data):
                        next_type_id, next_entry = block.line_data[j]
                        if next_type_id == SLD_INSTRUCTION:
                            if type(next_entry) is int:
                                block_offset = next_entry
                            else:
                                block_offset = next_entry.pc-2
                            break
                        j += 1
                else:
                    persistence.write_uint16(f, block_offset)
                    block_offset += entry.num_bytes
            elif type_id == SLD_EQU_LOCATION_RELATIVE:
                persistence.write_uint32(f, entry) # block offset
            elif type_id in (SLD_COMMENT_TRAILING, SLD_COMMENT_FULL_LINE):
                persistence.write_string(f, entry) # string
            else:
                logger.error("Trying to save a savefile, did not know how to handle entry of type_id: %d, entry value: %s", type_id, entry)

def read_SegmentBlock(f):
    block = SegmentBlock()
    bytes_to_read = struct.calcsize(SEGMENTBLOCK_PACK_FORMAT)
    block.segment_id, block.segment_offset, block.address, block.length, block.flags, block.line_count, line_data_count = struct.unpack(SEGMENTBLOCK_PACK_FORMAT, f.read(bytes_to_read))

    if line_data_count > 0:
        block.line_data = [ None ] * line_data_count
        for i in xrange(line_data_count):
            type_id = persistence.read_uint8(f)
            if type_id == SLD_INSTRUCTION:
                block_offset = persistence.read_uint16(f)
                block.line_data[i] = (type_id, block_offset)
            elif type_id == SLD_EQU_LOCATION_RELATIVE:
                block_offset = persistence.read_uint32(f)
                block.line_data[i] = (type_id, block_offset)
            elif type_id in (SLD_COMMENT_TRAILING, SLD_COMMENT_FULL_LINE):
                text = persistence.read_string(f)
                block.line_data[i] = (type_id, text)
    return block

def read_segment_list(f):
    num_bytes = persistence.read_uint32(f)
    data_start_offset = f.tell()
    v = []
    while f.tell() - data_start_offset != num_bytes:
        v.append(read_segment_list_entry(f))
    return v

def write_segment_list(f, v):
    start_offset = f.tell()
    persistence.write_uint32(f, 0)
    data_start_offset = f.tell()
    for entry in v:
        write_segment_list_entry(f, entry)
    end_offset = f.tell()
    f.seek(start_offset, os.SEEK_SET)
    persistence.write_uint32(f, end_offset - data_start_offset)
    f.seek(end_offset, os.SEEK_SET)

def read_segment_list_entry(f):
    v = [ None ] * loaderlib.SIZEOF_SI
    v[loaderlib.SI_TYPE] = persistence.read_uint8(f)
    offset_value = persistence.read_uint32(f)
    if offset_value == 0xFFFFFFFF: # Unsigned, special value.
        offset_value = -1
    v[loaderlib.SI_FILE_OFFSET] = offset_value
    v[loaderlib.SI_DATA_LENGTH] = persistence.read_uint32(f)
    v[loaderlib.SI_LENGTH] = persistence.read_uint32(f)
    v[loaderlib.SI_ADDRESS] = persistence.read_uint32(f)
    return v

def write_segment_list_entry(f, v):
    persistence.write_uint8(f, v[loaderlib.SI_TYPE])
    if v[loaderlib.SI_FILE_OFFSET] == -1:
        persistence.write_uint32(f, 0xFFFFFFFF) # Unsigned, special value.
    else:
        persistence.write_uint32(f, v[loaderlib.SI_FILE_OFFSET])
    persistence.write_uint32(f, v[loaderlib.SI_DATA_LENGTH])
    persistence.write_uint32(f, v[loaderlib.SI_LENGTH])
    persistence.write_uint32(f, v[loaderlib.SI_ADDRESS])


SAVEFILE_VERSION = 1

def save_project(savefile_path, program_data):
    program_data.savefile_path = savefile_path

    t0 = time.time()
    logger.debug("saving 'savefile' to: %s", savefile_path)

    with open(savefile_path, "wb") as f:
        persistence.write_uint16(f, SAVEFILE_VERSION)
        size_offset = f.tell()
        persistence.write_uint32(f, 0)

        data_start_offset = item_offset = f.tell()
        persistence.write_dict_uint32_to_set_of_uint32s(f, program_data.branch_addresses)
        if True:
            item_length = f.tell() - item_offset
            logger.debug("save item length: %d name: branch_addresses", item_length)
            item_offset = f.tell()
        persistence.write_dict_uint32_to_set_of_uint32s(f, program_data.reference_addresses)
        if True:
            item_length = f.tell() - item_offset
            logger.debug("save item length: %d name: reference_addresses", item_length)
            item_offset = f.tell()
        persistence.write_dict_uint32_to_string(f, program_data.symbols_by_address)
        if True:
            item_length = f.tell() - item_offset
            logger.debug("save item length: %d name: symbols_by_address", item_length)
            item_offset = f.tell()
        persistence.write_dict_uint32_to_list_of_uint32s(f, program_data.post_segment_addresses)
        if True:
            item_length = f.tell() - item_offset
            logger.debug("save item length: %d name: post_segment_addresses", item_length)
            item_offset = f.tell()
        persistence.write_uint32(f, program_data.flags)
        if True:
            item_length = f.tell() - item_offset
            logger.debug("save item length: %d name: dis_name", item_length)
            item_offset = f.tell()
        persistence.write_string(f, program_data.dis_name)
        if True:
            item_length = f.tell() - item_offset
            logger.debug("save item length: %d name: dis_name", item_length)
            item_offset = f.tell()
        persistence.write_string(f, program_data.file_name)
        if True:
            item_length = f.tell() - item_offset
            logger.debug("save item length: %d name: file_name", item_length)
            item_offset = f.tell()
        persistence.write_uint32(f, program_data.file_size)
        if True:
            item_length = f.tell() - item_offset
            logger.debug("save item length: %d name: file_size", item_length)
            item_offset = f.tell()
        persistence.write_bytes(f, program_data.file_checksum, 16)
        if True:
            item_length = f.tell() - item_offset
            logger.debug("save item length: %d name: file_checksum", item_length)
            item_offset = f.tell()
        persistence.write_string(f, program_data.loader_system_name)
        if True:
            item_length = f.tell() - item_offset
            logger.debug("save item length: %d name: loader_system_name", item_length)
            item_offset = f.tell()
        write_segment_list(f, program_data.loader_segments)
        if True:
            item_length = f.tell() - item_offset
            logger.debug("save item length: %d name: loader_segments", item_length)
            item_offset = f.tell()
        persistence.write_set_of_uint32s(f, program_data.loader_relocated_addresses)
        if True:
            item_length = f.tell() - item_offset
            logger.debug("save item length: %d name: loader_relocated_addresses", item_length)
            item_offset = f.tell()
        persistence.write_set_of_uint32s(f, program_data.loader_relocatable_addresses)
        if True:
            item_length = f.tell() - item_offset
            logger.debug("save item length: %d name: loader_relocatable_addresses", item_length)
            item_offset = f.tell()
        persistence.write_uint16(f, program_data.loader_entrypoint_segment_id)
        if True:
            item_length = f.tell() - item_offset
            logger.debug("save item length: %d name: loader_entrypoint_segment_id", item_length)
            item_offset = f.tell()
        persistence.write_uint32(f, program_data.loader_entrypoint_offset)
        if True:
            item_length = f.tell() - item_offset
            logger.debug("save item length: %d name: loader_entrypoint_offset", item_length)
            item_offset = f.tell()

        persistence.write_uint32(f, len(program_data.blocks))
        for block in program_data.blocks:
            write_SegmentBlock(f, block)
        data_end_offset = f.tell()
        if True:
            item_length = f.tell() - item_offset
            logger.debug("save item length: %d name: blocks", item_length)
            item_offset = f.tell()

        # Go back and write the size.
        f.seek(size_offset, os.SEEK_SET)
        persistence.write_uint32(f, data_end_offset - data_start_offset)

        f.seek(data_end_offset, os.SEEK_SET)
        persistence.write_uint32(f, 0)

        loader_data_start_offset = f.tell()
        system = loaderlib.get_system(program_data.loader_system_name)
        system.save_project_data(f, program_data.loader_internal_data)
        loader_data_end_offset = f.tell()

        # Go back and write the size.
        f.seek(data_end_offset, os.SEEK_SET)
        persistence.write_uint32(f, loader_data_end_offset - loader_data_start_offset)

    seconds_taken = time.time() - t0
    logger.info("Saved working data to: %s (length: %d, time taken: %0.1fs)", savefile_path, loader_data_end_offset, seconds_taken)


def load_project(savefile_path):
    t0 = time.time()
    logger.debug("loading 'savefile' from: %s", savefile_path)

    program_data = ProgramData()
    with open(savefile_path, "rb") as f:
        savefile_version = persistence.read_uint16(f)
        if savefile_version != SAVEFILE_VERSION:
            logger.error("Save-file is version %s, only version %s is supported at this time.", savefile_version, SAVEFILE_VERSION)
            return None, 0

        localdata_size = persistence.read_uint32(f)

        data_start_offset = f.tell()
        program_data.branch_addresses = persistence.read_dict_uint32_to_set_of_uint32s(f)
        program_data.reference_addresses = persistence.read_dict_uint32_to_set_of_uint32s(f)
        program_data.symbols_by_address = persistence.read_dict_uint32_to_string(f)
        program_data.post_segment_addresses = persistence.read_dict_uint32_to_list_of_uint32s(f)
        program_data.flags = persistence.read_uint32(f)
        program_data.dis_name = persistence.read_string(f)
        program_data.file_name = persistence.read_string(f)
        program_data.file_size = persistence.read_uint32(f)
        program_data.file_checksum = persistence.read_bytes(f, 16)
        program_data.loader_system_name = persistence.read_string(f)
        program_data.loader_segments = read_segment_list(f)
        program_data.loader_relocated_addresses = persistence.read_set_of_uint32s(f)
        program_data.loader_relocatable_addresses = persistence.read_set_of_uint32s(f)
        program_data.loader_entrypoint_segment_id = persistence.read_uint16(f)
        program_data.loader_entrypoint_offset = persistence.read_uint32(f)

        # Reconstitute the segment block list.
        num_blocks = persistence.read_uint32(f)
        program_data.blocks = [ None ] * num_blocks
        for i in xrange(num_blocks):
            program_data.blocks[i] = read_SegmentBlock(f)
        data_end_offset = f.tell()

        if localdata_size != data_end_offset - data_start_offset:
            logger.error("Save-file localdata length mismatch, got: %d wanted: %d", data_end_offset - data_start_offset, localdata_size)
            return None, 0

        # Rebuild the segment block list indexing lists.
        program_data.block_addresses = [ 0 ] * num_blocks
        program_data.block_line0s_dirtyidx = 0
        program_data.block_line0s = program_data.block_addresses[:]
        for i in xrange(num_blocks):
            program_data.block_addresses[i] = program_data.blocks[i].address

        # The loaders internal data comes next, hand off reading that in as we do not use or care about it.
        loaderdata_size = persistence.read_uint32(f)
        loader_data_start_offset = f.tell()
        system = loaderlib.get_system(program_data.loader_system_name)
        program_data.loader_internal_data = system.load_project_data(f)
        loader_data_end_offset = f.tell()

        if loaderdata_size != loader_data_end_offset - loader_data_start_offset:
            logger.error("Save-file loaderdata length mismatch, got: %d wanted: %d", loader_data_end_offset - loader_data_start_offset, loaderdata_size)
            return None, 0

    program_data.loader_data_types = loaderlib.get_system_data_types(program_data.loader_system_name)

    seconds_taken = time.time() - t0
    logger.info("Loaded working data from: %s (time taken: %0.1fs)", savefile_path, seconds_taken)

    program_data.savefile_path = savefile_path

    return program_data
