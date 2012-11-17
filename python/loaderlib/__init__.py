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


logger = logging.getLogger("archlib")


def get_systems():
    return [
        amiga.System(),
        atarist.System(),
        human68k.System(),
    ]


def load_file(file_path):
    for system in get_systems():
        file_info = FileInfo(system, file_path)
        if system.load_file(file_info):
            file_info.event_loading_complete()
            return file_info


SEGMENT_TYPE_CODE = 1
SEGMENT_TYPE_DATA = 2
SEGMENT_TYPE_BSS = 3

SI_TYPE = 0
SI_FILE_OFFSET = 1
SI_DATA_LENGTH = 2
SI_LENGTH = 3



class FileInfo(object):
    """ The custom system data for the loaded file. """
    file_data = None

    def __init__(self, system, file_path):
        self.system = system

        self._endian_char = [ "<", ">" ][system.big_endian]

        self.file_path = file_path

        self.segments = []
        self.relocations_by_segment_id = {}
        self.symbols_by_segment_id = {}

        """ The addresses at which values changed / relocated were located. """
        self.relocatable_addresses = set()
        """ The address values which were changed / relocated. """
        self.relocated_addresses = set()

        """ The segment id and offset in that segment of the program entrypoint. """
        self.entrypoint = 0, 0

    def event_loading_complete(self):
        # While this does cache the segment data, it more importantly causes the
        # relocation information to be processed and stored for use by the
        # disassembly logic.
        for segment_id in range(self.get_segment_count()):
            if self.get_segment_data_file_offset(segment_id) != -1:
                self.get_segment_data(segment_id)

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
        self.segments.append((segment_type, file_offset, data_length, segment_length))
        self.relocations_by_segment_id[segment_id] = relocations
        self.symbols_by_segment_id[segment_id] = symbols

    def set_entrypoint(self, segment_id, offset):
        self.entrypoint = segment_id, offset

    def get_entrypoint(self):
        return self.entrypoint

    ## Segment querying related operations

    def get_segment_address(self, segment_id):
        """ Get the address the segment was loaded to in memory. """
        address = 0
        for i in range(len(self.segments)):
            if i == segment_id:
                break
            address += self.get_segment_length(i)
        return address

    def get_segment_type(self, segment_id):
        return self.segments[segment_id][SI_TYPE]

    def get_segment_data_file_offset(self, segment_id):
        return self.segments[segment_id][SI_FILE_OFFSET]

    def get_segment_data_length(self, segment_id):
        return self.segments[segment_id][SI_DATA_LENGTH]

    def get_segment_length(self, segment_id):
        return self.segments[segment_id][SI_LENGTH]

    def get_segment_count(self):
        return len(self.segments)

    def get_segment_data(self, segment_id):
        ## HACK START
        # Cache loaded file data, as it speeds things up significantly.
        if not hasattr(self, "_sdc"):
            self._sdc = {}
        if segment_id in self._sdc:
            return self._sdc[segment_id]
        ## HACK END

        file_offset = self.get_segment_data_file_offset(segment_id)
        if file_offset == -1:
            # This segment has no data.
            return None
        file_length = self.get_segment_data_length(segment_id)

        f = open(self.file_path, "rb")
        f.seek(file_offset, os.SEEK_SET)
        data = f.read(file_length)
        if len(data) != file_length:
            return None

        data = bytearray(data)

        # Generic longword-based relocation.
        local_address = self.get_segment_address(segment_id)
        relocation_offsets = self.relocations_by_segment_id.get(segment_id, [])
        for target_segment_id, local_offsets in relocation_offsets:
            target_address = self.get_segment_address(target_segment_id)
            for local_offset in local_offsets:
                value = self.uint32_value(data[local_offset:local_offset+4])
                address = value + target_address
                if address not in self.relocated_addresses:
                    self.relocated_addresses.add(address)
                self.relocatable_addresses.add(local_address + local_offset)
                data[local_offset:local_offset+4] = self.uint32_bytes(address)
        ## HACK START
        self._sdc[segment_id] = data
        ## HACK END
        return data

    ## 

    def has_section_headers(self):
        return self.system.has_section_headers()

    def get_section_header(self, segment_id):
        return self.system.get_section_header(self, segment_id)

    def get_data_instruction_string(self, segment_id, with_file_data):
        segment_type = self.get_segment_type(segment_id)
        is_bss_segment = segment_type == SEGMENT_TYPE_BSS
        return self.system.get_data_instruction_string(is_bss_segment, with_file_data)

    ## Data access related operations.

    def uint16_value(self, bytes):
        if self.system.big_endian:
            return (bytes[0] << 8) + bytes[1]
        else:
            return (bytes[1] << 8) + bytes[0]

    def uint32_value(self, bytes):
        if self.system.big_endian:
            return (bytes[0] << 24) + (bytes[1] << 16) + (bytes[2] << 8) + bytes[3]
        else:
            return (bytes[3] << 24) + (bytes[2] << 16) + (bytes[1] << 8) + bytes[0]

    def uint32_bytes(self, v):
        if self.system.big_endian:
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

