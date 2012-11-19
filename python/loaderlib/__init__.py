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

import os
import logging
import struct

import amiga
import atarist
import human68k


logger = logging.getLogger("loader")


systems_by_name = {}

def _generate_module_data():
    global systems_by_name
    for module in (amiga, atarist, human68k):
        system_name = module.__name__
        system = systems_by_name[system_name] = module.System()
        system.system_name = system_name
_generate_module_data()

def get_system_data_types(system_name):
    system = systems_by_name[system_name]
    return DataTypes(system.big_endian)
 
def load_file(file_path):
    for system_name, system in systems_by_name.iteritems():
        file_info = FileInfo(system, file_path)
        data_types = get_system_data_types(system_name)
        if system.load_file(file_info, data_types):
            return file_info, data_types


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

def cache_segment_data(file_path, segments):
    for segment_id in range(len(segments)):
        data = None
        file_offset = get_segment_data_file_offset(segments, segment_id)
        # No data for segments that have no data..
        if file_offset != -1:
            file_length = get_segment_data_length(segments, segment_id)

            f = open(file_path, "rb")
            f.seek(file_offset, os.SEEK_SET)
            file_data = f.read(file_length)
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
                if relocated_addresses is not None:
                    if address not in relocated_addresses:
                        relocated_addresses.add(address)
                if relocatable_addresses is not None:
                    relocatable_addresses.add(local_address + local_offset)
                data[local_offset:local_offset+4] = data_types.uint32_bytes(address)


class DataTypes(object):
    def __init__(self, big_endian):
        self.big_endian = big_endian
        self._endian_char = [ "<", ">" ][big_endian]

    ## Data access related operations.

    def uint8_value(self, bytes, idx=None):
        if idx:
            bytes = bytes[idx:idx+1]
        return bytes[0]

    def uint16_value(self, bytes, idx=None):
        if idx:
            bytes = bytes[idx:idx+2]
        if self.big_endian:
            return (bytes[0] << 8) + bytes[1]
        else:
            return (bytes[1] << 8) + bytes[0]

    def uint32_value(self, bytes, idx=None):
        if idx:
            bytes = bytes[idx:idx+4]
        if self.big_endian:
            return (bytes[0] << 24) + (bytes[1] << 16) + (bytes[2] << 8) + bytes[3]
        else:
            return (bytes[3] << 24) + (bytes[2] << 16) + (bytes[1] << 8) + bytes[0]

    def uint32_bytes(self, v):
        if self.big_endian:
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
    file_data = None

    def __init__(self, system, file_path):
        self.system = system

        self.file_path = file_path

        self.segments = []
        self.relocations_by_segment_id = []
        self.symbols_by_segment_id = []

        """ The segment id and offset in that segment of the program entrypoint. """
        self.entrypoint_segment_id = 0
        self.entrypoint_offset = 0

    ## Query..

    ## Segment registration related operations

    def set_file_data(self, file_data):
        self.file_data = file_data

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
        segment_address = 0
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

    def has_section_headers(self):
        return self.system.has_section_headers()

    def get_section_header(self, segment_id):
        return self.system.get_section_header(self, segment_id)

    def get_data_instruction_string(self, segment_id, with_file_data):
        segment_type = get_segment_type(self.segments, segment_id)
        is_bss_segment = segment_type == SEGMENT_TYPE_BSS
        return self.system.get_data_instruction_string(is_bss_segment, with_file_data)
