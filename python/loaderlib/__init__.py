"""
    Peasauce - interactive disassembler
    Copyright (C) 2012-2016 Richard Tew
    Licensed using the MIT license.
"""

import os
import logging
import struct

from . import amiga
from . import atarist
from . import binary
from . import human68k
from . import snes
from . import zxspectrum
from . import constants


logger = logging.getLogger("loader")


systems_by_name = {}

def _generate_module_data():
    global systems_by_name
    for module in (amiga, atarist, human68k, binary, snes, zxspectrum):
        system_name = module.__name__
        system = systems_by_name[system_name] = module.System()
        system.system_name = system_name
_generate_module_data()

def get_system(system_name):
    return systems_by_name[system_name]

def get_system_data_types(system_name):
    system = systems_by_name[system_name]
    return DataTypes(system.endian_id)

def load_file(input_file, file_name, loader_options=None, file_offset=0, file_length=None):
    for system_name, system in systems_by_name.iteritems():
        file_info = FileInfo(system, file_name, loader_options)
        data_types = get_system_data_types(system_name)
        if system.load_input_file(input_file, file_info, data_types, f_offset=file_offset, f_length=file_length):
            return file_info, data_types

def identify_file(input_file, file_name, file_offset=0, file_length=None):
    matches = []
    for system_name, system in systems_by_name.iteritems():
        file_info = FileInfo(system, file_name)
        data_types = get_system_data_types(system_name)
        system_matches = system.identify_input_file(input_file, file_info, data_types, f_offset=file_offset, f_length=file_length)
        matches.extend(((file_info, match) for match in system_matches))

    if len(matches):
        # For now take the match we are most confident in.
        matches.sort(lambda n0, n1: cmp(n1[1].confidence, n0[1].confidence))
        file_info, match = matches[0]

        if match.file_format_id != constants.FILE_FORMAT_UNKNOWN and match.confidence != constants.MATCH_NONE:
            result = {}
            result["processor"] = system.get_processor_id()
            result["platform"] = match.platform_id
            result["filetype"] = match.file_format_id
            result["endian"] = system.endian_id
            return file_info, result


SEGMENT_TYPE_CODE = 1
SEGMENT_TYPE_DATA = 2
SEGMENT_TYPE_BSS = 3

SI_TYPE = 0
SI_FILE_OFFSET = 1
SI_DATA_LENGTH = 2
SI_LENGTH = 3
SI_ADDRESS = 4
SI_CACHED_DATA = 5
SIZEOF_SI = 6


def get_segment_type(segments, segment_id):
    return segments[segment_id][SI_TYPE]

def get_segment_data_file_offset(segments, segment_id):
    return segments[segment_id][SI_FILE_OFFSET]

def get_segment_data_length(segments, segment_id):
    return segments[segment_id][SI_DATA_LENGTH]

def get_segment_length(segments, segment_id):
    return segments[segment_id][SI_LENGTH]

def get_segment_address(segments, segment_id):
    return segments[segment_id][SI_ADDRESS]

def get_segment_data(segments, segment_id):
    return segments[segment_id][SI_CACHED_DATA]

def is_segment_type_code(segments, segment_id):
    return segments[segment_id][SI_TYPE] == SEGMENT_TYPE_CODE

def is_segment_type_data(segments, segment_id):
    return segments[segment_id][SI_TYPE] == SEGMENT_TYPE_DATA

def is_segment_type_bss(segments, segment_id):
    return segments[segment_id][SI_TYPE] == SEGMENT_TYPE_BSS

def cache_segment_data(input_file, segments, segment_id, base_file_offset=0):
    """
    base_file_offset: when the input file is located within a containing file.
    """
    data = None
    file_offset = get_segment_data_file_offset(segments, segment_id)
    # No data for segments that have no data..
    if file_offset != -1:
        file_length = get_segment_data_length(segments, segment_id)

        input_file.seek(base_file_offset + file_offset, os.SEEK_SET)
        file_data = input_file.read(file_length)
        if len(file_data) == file_length:
            data = bytearray(file_data)
        else:
            logger.error("Unable to cache segment %d data, got %d bytes, wanted %d", segment_id, len(file_data), file_length)
    segments[segment_id][SI_CACHED_DATA] = data

def relocate_segment_data(segments, data_types, relocations, relocatable_addresses, relocated_addresses):
    for segment_id in range(len(segments)):
        # Generic longword-based relocation.
        data = get_segment_data(segments, segment_id)
        local_address = get_segment_address(segments, segment_id)
        for target_segment_id, local_offsets in relocations[segment_id]:
            target_address = get_segment_address(segments, target_segment_id)
            for local_offset in local_offsets:
                value = data_types.uint32_value(data[local_offset:local_offset+4])
                address = value + target_address
                relocated_addresses.setdefault(address, set()).add(local_address + local_offset)
                relocatable_addresses.add(local_address + local_offset)
                data[local_offset:local_offset+4] = data_types.uint32_bytes(address)


def has_segment_headers(system_name):
    return get_system(system_name).has_segment_headers()

def get_segment_header(system_name, segment_id, data):
    return get_system(system_name).get_segment_header(segment_id, data)

def get_data_instruction_string(system_name, segments, segment_id, with_file_data):
    segment_type = get_segment_type(segments, segment_id)
    is_bss_segment = segment_type == SEGMENT_TYPE_BSS
    return get_system(system_name).get_data_instruction_string(is_bss_segment, with_file_data)


def get_load_address(file_info):
    return file_info.load_address

def get_entrypoint_address(file_info):
    #if file_info.entrypoint_address is not None:
    #    return file_info.entrypoint_address
    return get_segment_address(file_info.segments, file_info.entrypoint_segment_id) + file_info.entrypoint_offset


class DataTypes(object):
    def __init__(self, endian_id):
        self.endian_id = endian_id
        self._endian_char = [ "<", ">" ][endian_id == constants.ENDIAN_BIG]

    ## Data access related operations.

    def uint8_value(self, bytes, idx=None):
        if idx:
            bytes = bytes[idx:idx+1]
        return bytes[0]

    def uint16_value(self, bytes, idx=None):
        if idx:
            bytes = bytes[idx:idx+2]
        if self.endian_id == constants.ENDIAN_BIG:
            return (bytes[0] << 8) + bytes[1]
        else:
            return (bytes[1] << 8) + bytes[0]

    def uint32_value(self, bytes, idx=None):
        if idx:
            bytes = bytes[idx:idx+4]
        if self.endian_id == constants.ENDIAN_BIG:
            return (bytes[0] << 24) + (bytes[1] << 16) + (bytes[2] << 8) + bytes[3]
        else:
            return (bytes[3] << 24) + (bytes[2] << 16) + (bytes[1] << 8) + bytes[0]

    def uint32_bytes(self, v):
        if self.endian_id == constants.ENDIAN_BIG:
            return [ (v >> 24) & 0xFF, (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF ]
        else:
            return [ v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF, (v >> 24) & 0xFF ]

    # String to value.

    def uint16(self, s):
        return struct.unpack(self._endian_char +"H", s)[0]

    def int16(self, s):
        return struct.unpack(self._endian_char +"h", s)[0]

    def uint32(self, s):
        return struct.unpack(self._endian_char +"I", s)[0]

    def int32(self, s):
        return struct.unpack(self._endian_char +"i", s)[0]

    def uint8(self, s):
        return struct.unpack(self._endian_char +"B", s)[0]

    def int8(self, s):
        return struct.unpack(self._endian_char +"b", s)[0]



class FileInfo(object):
    """ The custom system data for the loaded file. """
    internal_data = None
    savefile_data = None

    def __init__(self, system, file_name, loader_options=None):
        self.system = system
        self.file_name = file_name
        self.loader_options = loader_options

        self.segments = []
        self.relocations_by_segment_id = []
        self.symbols_by_segment_id = []

        if loader_options is not None and loader_options.is_binary_file:
            self.load_address = loader_options.load_address
        else:
            self.load_address = 0

        """ The segment id and offset in that segment of the program entrypoint. """
        if loader_options is not None:
            self.entrypoint_segment_id = loader_options.entrypoint_segment_id
            self.entrypoint_offset = loader_options.entrypoint_offset
        else:
            self.entrypoint_segment_id = 0
            self.entrypoint_offset = 0

    ## Query..

    def has_file_name_suffix(self, suffix):
        return self.file_name.lower().endswith("."+ suffix.lower())

    ## Segment registration related operations

    def set_internal_data(self, file_data):
        self.internal_data = file_data

    def get_internal_data(self):
        return self.internal_data

    def set_savefile_data(self, file_data):
        self.savefile_data = file_data

    def get_savefile_data(self):
        return self.savefile_data

    def print_summary(self):
        self.system.print_summary(self)

    def add_code_segment(self, file_offset, data_length, segment_length, relocations, symbols):
        logger.debug("Added code segment %d %d %d #relocs %d", file_offset, data_length, segment_length, len(relocations))
        self.add_segment(SEGMENT_TYPE_CODE, file_offset, data_length, segment_length, relocations, symbols)

    def add_data_segment(self, file_offset, data_length, segment_length, relocations, symbols):
        logger.debug("Added data segment %d %d %d #relocs %d", file_offset, data_length, segment_length, len(relocations))
        self.add_segment(SEGMENT_TYPE_DATA, file_offset, data_length, segment_length, relocations, symbols)

    def add_bss_segment(self, file_offset, data_length, segment_length, relocations, symbols):
        logger.debug("Added bss segment %d %d %d #relocs %d", file_offset, data_length, segment_length, len(relocations))
        self.add_segment(SEGMENT_TYPE_BSS, file_offset, data_length, segment_length, relocations, symbols)

    def add_segment(self, segment_type, file_offset, data_length, segment_length, relocations, symbols):
        segment_id = len(self.segments)
        segment_address = self.load_address
        if segment_id > 0:
            segment_address = get_segment_address(self.segments, segment_id-1) + get_segment_length(self.segments, segment_id-1)
        segment = [ None ] * SIZEOF_SI
        segment[SI_TYPE] = segment_type
        segment[SI_FILE_OFFSET] = file_offset
        segment[SI_DATA_LENGTH] = data_length
        segment[SI_LENGTH] = segment_length
        segment[SI_ADDRESS] = segment_address
        segment[SI_CACHED_DATA] = None
        self.segments.append(segment)

        self.relocations_by_segment_id.append(relocations)
        self.symbols_by_segment_id.append(symbols)

    def set_entrypoint(self, segment_id, offset):
        self.entrypoint_segment_id = segment_id
        self.entrypoint_offset = offset

    def get_entrypoint(self):
        return self.entrypoint

    ## Segment querying related operations

class BinaryFileOptions(object):
    is_binary_file = True
    processor_id = None
    load_address = None
    entrypoint_segment_id = 0
    entrypoint_offset = None
