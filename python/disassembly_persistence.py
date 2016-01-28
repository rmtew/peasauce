"""
    Peasauce - interactive disassembler
    Copyright (C) 2012-2016 Richard Tew
    Licensed using the MIT license.
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
        if get_block_data_type(block) == DATA_TYPE_CODE:
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
        if get_block_data_type(block) == DATA_TYPE_CODE:
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


SAVEFILE_ID = 0x5053504a
SAVEFILE_VERSION = 3

SAVEFILE_HUNK_SOURCEDATA = 2001            # The entire source input file that the disassembly was created from.
SAVEFILE_HUNK_SOURCEDATAINFO = 2002        # The metadata about the source input file.
SAVEFILE_HUNK_LOADER = 2003                # Loader related data used by the disassembly logic.
SAVEFILE_HUNK_LOADERINTERNAL = 2004        # Internal loader data.
SAVEFILE_HUNK_DISASSEMBLY = 2005           # General disassembly state.

CURRENT_HUNK_VERSIONS = {
    SAVEFILE_HUNK_SOURCEDATA: 1,
    SAVEFILE_HUNK_SOURCEDATAINFO: 1,
    SAVEFILE_HUNK_LOADER: 1,
    SAVEFILE_HUNK_LOADERINTERNAL: 1,
    SAVEFILE_HUNK_DISASSEMBLY: 1,
}

# 4: Save file ID.
# 4: Save file version.
# ...
# 2: Hunk ID.
# 4: Hunk data length in bytes (N).
# N: Hunk data.
# ...


def check_is_project_file(f):
    f.seek(0, os.SEEK_SET)
    return persistence.read_uint32(f) == SAVEFILE_ID

def save_project(f, program_data, save_options):
    f.seek(0, os.SEEK_SET)

    persistence.write_uint32(f, SAVEFILE_ID)
    persistence.write_uint16(f, SAVEFILE_VERSION)
    program_data.save_count += 1
    persistence.write_uint32(f, program_data.save_count)

    # The input file / source data is saved in the first hunk, so we can skip repersisting it in subsequent saves to the same file.
    for hunk_id in (SAVEFILE_HUNK_SOURCEDATA, SAVEFILE_HUNK_SOURCEDATAINFO, SAVEFILE_HUNK_LOADER, SAVEFILE_HUNK_LOADERINTERNAL, SAVEFILE_HUNK_DISASSEMBLY):
        if SAVEFILE_HUNK_SOURCEDATA == hunk_id and save_options.input_file is None:
            continue

        persistence.write_uint16(f, hunk_id)
        # Remember the hunk length offset and write a dummy value.
        length_offset = f.tell()
        persistence.write_uint32(f, 0)
        hunk_data_offset = f.tell()
        persistence.write_uint16(f, CURRENT_HUNK_VERSIONS[hunk_id])
        if SAVEFILE_HUNK_DISASSEMBLY == hunk_id:
            save_disassembly_hunk(f, program_data)
        elif SAVEFILE_HUNK_LOADER == hunk_id:
            save_loader_hunk(f, program_data)
        elif SAVEFILE_HUNK_LOADERINTERNAL == hunk_id:
            save_loaderinternaldata_hunk(f, program_data)
        elif SAVEFILE_HUNK_SOURCEDATAINFO == hunk_id:
            save_sourcedatainfo_hunk(f, program_data)
        elif SAVEFILE_HUNK_SOURCEDATA == hunk_id:
            save_sourcedata_hunk(f, program_data, save_options.input_file)
        else:
            raise RuntimeError("Trying to save a hunk with no handling to do so")
        hunk_length = f.tell() - hunk_data_offset
        # Go back and fill in the hunk length field.
        f.seek(length_offset, os.SEEK_SET)
        persistence.write_uint32(f, hunk_length)
        # Return to the end of the hunk to perhaps write the next.
        f.seek(hunk_length, os.SEEK_CUR)

    logger.info("Saved project (%d bytes)", f.tell())


def save_disassembly_hunk(f, program_data):
    persistence.write_dict_uint32_to_set_of_uint32s(f, program_data.branch_addresses)
    persistence.write_dict_uint32_to_set_of_uint32s(f, program_data.reference_addresses)
    persistence.write_dict_uint32_to_string(f, program_data.symbols_by_address)
    persistence.write_dict_uint32_to_list_of_uint32s(f, program_data.post_segment_addresses)
    persistence.write_uint32(f, program_data.flags)
    persistence.write_string(f, program_data.dis_name)

    persistence.write_uint32(f, len(program_data.blocks))
    for block in program_data.blocks:
        write_SegmentBlock(f, block)

def save_loader_hunk(f, program_data):
    persistence.write_string(f, program_data.loader_system_name)
    write_segment_list(f, program_data.loader_segments)
    persistence.write_set_of_uint32s(f, program_data.loader_relocated_addresses)
    persistence.write_set_of_uint32s(f, program_data.loader_relocatable_addresses)
    persistence.write_uint16(f, program_data.loader_entrypoint_segment_id)
    persistence.write_uint32(f, program_data.loader_entrypoint_offset)

def save_loaderinternaldata_hunk(f, program_data):
    system = loaderlib.get_system(program_data.loader_system_name)
    system.save_project_data(f, program_data.loader_internal_data)

def save_sourcedatainfo_hunk(f, program_data):
    persistence.write_uint32(f, program_data.file_size)
    persistence.write_bytes(f, program_data.file_checksum, 16)

def save_sourcedata_hunk(f, program_data, input_file):
    data = input_file.read(256 * 1024)
    while len(data):
        f.write(data)
        data = input_file.read(256 * 1024)


import tempfile

def convert_project_format_2_to_3(input_file):
    """
    This function should encapsulate all application-specific logic involved to
    make it independent of as many changes as possible.

    From version: 2.
    To version: 3.
    Modifications:
    - Inserts a version number into all hunks.
    """
    SNAPSHOT_HUNK_VERSIONS = {
        SAVEFILE_HUNK_SOURCEDATA: 1,
        SAVEFILE_HUNK_SOURCEDATAINFO: 1,
        SAVEFILE_HUNK_LOADER: 1,
        SAVEFILE_HUNK_LOADERINTERNAL: 1,
        SAVEFILE_HUNK_DISASSEMBLY: 1,
    }

    input_file.seek(0, os.SEEK_END)
    file_size = input_file.tell()
    input_file.seek(0, os.SEEK_SET)

    savefile_id = persistence.read_uint32(input_file)
    savefile_version = persistence.read_uint16(input_file)
    if savefile_version != 2:
        return None

    logger.info("Upgrading save-file from version 2 to version 3: Hunk versioning..")
    save_count = persistence.read_uint32(input_file)

    output_file = tempfile.TemporaryFile()
    persistence.write_uint32(output_file, savefile_id)
    persistence.write_uint16(output_file, 3)
    persistence.write_uint32(output_file, save_count)

    while input_file.tell() < file_size:
        # This should be pretty straightforward.
        hunk_id = persistence.read_uint16(input_file)
        persistence.write_uint16(output_file, hunk_id)

        input_hunk_length = persistence.read_uint32(input_file)
        output_length_offset = output_file.tell()
        persistence.write_uint32(output_file, 0)
        output_data_offset = output_file.tell()
        # Modification.
        persistence.write_uint16(output_file, CURRENT_HUNK_VERSIONS[hunk_id])

        input_data = input_file.read(input_hunk_length)
        output_file.write(input_data)
        output_hunk_length = output_file.tell() - output_data_offset
        output_file.seek(output_length_offset, os.SEEK_SET)
        persistence.write_uint32(output_file, output_hunk_length)
        output_file.seek(output_hunk_length, os.SEEK_CUR)

    return output_file


def load_project(f, work_state=None):
    while True:
        if work_state is not None and work_state.check_exit_update(0.1, "TEXT_LOAD_CONVERTING_PROJECT_FILE"):
            return None

        f.seek(0, os.SEEK_END)
        file_size = f.tell()
        f.seek(0, os.SEEK_SET)

        savefile_id = persistence.read_uint32(f)
        if savefile_id != SAVEFILE_ID:
            logger.error("Save-file does not have first four bytes of '%X', has '%X' instead.", SAVEFILE_ID, savefile_id)
            return None
        savefile_version = persistence.read_uint16(f)
        if savefile_version != SAVEFILE_VERSION:
            new_f = None
            if savefile_version == 2:
                new_f = convert_project_format_2_to_3(f)
                savefile_version = 3
            if new_f is None or savefile_version != SAVEFILE_VERSION:
                logger.error("Save-file is version %s, only version %s is supported at this time.", savefile_version, SAVEFILE_VERSION)
                return None
            f = new_f
            logger.info("Save-file upgraded to version %d", SAVEFILE_VERSION)
            continue
        break

    program_data = ProgramData()
    program_data.save_count = persistence.read_uint32(f)

    sourcedata_offset = sourcedata_length = None
    while f.tell() < file_size:
        if work_state is not None and work_state.check_exit_update(0.1 + 0.8 * (file_size-f.tell()), "TEXT_LOAD_READING_PROJECT_DATA"):
            return None

        hunk_id = persistence.read_uint16(f)
        hunk_length = persistence.read_uint32(f)
        expected_hunk_version = CURRENT_HUNK_VERSIONS[hunk_id]
        offset0 = f.tell()
        actual_hunk_version = persistence.read_uint16(f)
        if SAVEFILE_HUNK_DISASSEMBLY == hunk_id:
            load_disassembly_hunk(f, program_data)
        elif SAVEFILE_HUNK_LOADER == hunk_id:
            load_loader_hunk(f, program_data)
        elif SAVEFILE_HUNK_LOADERINTERNAL == hunk_id:
            load_loaderinternaldata_hunk(f, program_data)
        elif SAVEFILE_HUNK_SOURCEDATAINFO == hunk_id:
            load_sourcedatainfo_hunk(f, program_data)
        elif SAVEFILE_HUNK_SOURCEDATA == hunk_id:
            skip_bytes = (f.tell() - offset0)
            sourcedata_offset, sourcedata_length = offset0 + skip_bytes, hunk_length - skip_bytes 
            f.seek(sourcedata_length, os.SEEK_CUR)
        else:
            logger.error("load_project encountered unknown hunk, with id: %d", hunk_id)
            return None

        offsetN = f.tell()
        if offsetN - offset0 != hunk_length:
            logger.error("load_project encountered hunk length mismatch, expected: %d, got: %d, hunk id: %d", hunk_length, offsetN - offset0, hunk_id)
            return None

    if work_state is not None and work_state.check_exit_update(0.95 * (file_size-f.tell()), "TEXT_LOAD_POSTPROCESSING"):
        return None

    if sourcedata_offset is not None:
        logger.info("Caching input file segments from embedded source file.")
        segments = program_data.loader_segments
        for i in range(len(segments)):
            loaderlib.cache_segment_data(f, segments, i, sourcedata_offset)
        # Avoid doing relocations if there weren't any.   e.g. binary files.
        if len(program_data.loader_relocatable_addresses):
            logger.info("Re-extracting relocations from embedded source file.")
            file_info, data_types = loaderlib.load_file(f, None, file_offset=sourcedata_offset, file_length=sourcedata_length)
            loaderlib.relocate_segment_data(segments, data_types, file_info.relocations_by_segment_id, program_data.loader_relocatable_addresses, program_data.loader_relocated_addresses)
        program_data.input_file_cached = True

    logger.info("Project loaded")
    return program_data

def load_disassembly_hunk(f, program_data):
    program_data.branch_addresses = persistence.read_dict_uint32_to_set_of_uint32s(f)
    program_data.reference_addresses = persistence.read_dict_uint32_to_set_of_uint32s(f)
    program_data.symbols_by_address = persistence.read_dict_uint32_to_string(f)
    program_data.post_segment_addresses = persistence.read_dict_uint32_to_list_of_uint32s(f)
    program_data.flags = persistence.read_uint32(f)
    program_data.dis_name = persistence.read_string(f)

    # Reconstitute the segment block list.
    num_blocks = persistence.read_uint32(f)
    program_data.blocks = [ None ] * num_blocks
    for i in xrange(num_blocks):
        program_data.blocks[i] = read_SegmentBlock(f)

    ## POST PROCESSING
    # Rebuild the segment block list indexing lists.
    program_data.block_addresses = [ 0 ] * num_blocks
    program_data.block_line0s_dirtyidx = 0
    program_data.block_line0s = program_data.block_addresses[:]
    for i in xrange(num_blocks):
        program_data.block_addresses[i] = program_data.blocks[i].address

def load_loader_hunk(f, program_data):
    program_data.loader_system_name = persistence.read_string(f)
    program_data.loader_segments = read_segment_list(f)
    program_data.loader_relocated_addresses = persistence.read_set_of_uint32s(f)
    program_data.loader_relocatable_addresses = persistence.read_set_of_uint32s(f)
    program_data.loader_entrypoint_segment_id = persistence.read_uint16(f)
    program_data.loader_entrypoint_offset = persistence.read_uint32(f)

    ## POST PROCESSING
    program_data.loader_data_types = loaderlib.get_system_data_types(program_data.loader_system_name)

def load_loaderinternaldata_hunk(f, program_data):
    system = loaderlib.get_system(program_data.loader_system_name)
    program_data.loader_internal_data = system.load_project_data(f)

def load_sourcedatainfo_hunk(f, program_data):
    program_data.file_size = persistence.read_uint32(f)
    program_data.file_checksum = persistence.read_bytes(f, 16)
