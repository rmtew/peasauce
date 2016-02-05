"""
    Peasauce - interactive disassembler
    Copyright (C) 2012-2016 Richard Tew
    Licensed using the MIT license.
"""

import cPickle
import os
import struct
import sys
import logging

from .. import constants

logger = logging.getLogger("loader-zxspectrum-z80")

OFFSET_V1_PROGRAM_COUNTER = 6
OFFSET_V23_HEADER_LENGTH = 30

LENGTH_V1_HEADER = 30
LENGTH_V2_HEADER = 23
LENGTH_V3_HEADER_A = 54
LENGTH_V3_HEADER_B = 55

class File(object):
    EXPECTED_SUFFIX = "z80"


def identify_input_file(input_file, file_info, data_types, f_offset=0, f_length=None):
    result = constants.MatchResult()

    if file_info.has_file_name_suffix(File.EXPECTED_SUFFIX):
        result.confidence = constants.MATCH_POSSIBLE

    # Check expected values
    input_file.seek(f_offset + OFFSET_V1_PROGRAM_COUNTER)
    header1_pc = data_types.uint16(input_file.read(2))
    if header1_pc == 0:
        input_file.seek(f_offset + OFFSET_V23_HEADER_LENGTH)
        header2_length = data_types.uint16(input_file.read(2))
        if header2_length == LENGTH_V2_HEADER:
            result.file_format_id = constants.FILE_FORMAT_ZXSPECTRUM_Z80_2
        elif header2_length in (LENGTH_V3_HEADER_A, LENGTH_V3_HEADER_B):
            result.file_format_id = constants.FILE_FORMAT_ZXSPECTRUM_Z80_3

        if result.file_format_id != constants.FILE_FORMAT_UNKNOWN:
            result.confidence = MATCH_PROBABLE
    else:
        result.file_format_id = constants.FILE_FORMAT_ZXSPECTRUM_Z80_1

    if result.file_format_id != constants.FILE_FORMAT_UNKNOWN:
        result.platform_id = constants.PLATFORM_ZXSPECTRUM

    return result

def load_input_file(input_file, file_info, data_types, f_offset=0, f_length=None):
    return load_z80_file(file_info, data_types, input_file, f_offset, f_length)

def load_z80_file(file_info, data_types, f, f_offset=0, f_length=None):
    f.seek(f_offset, os.SEEK_SET)

    # Offset    Bytes   ...
    data = File()
    # 0         2       8kb page count
    data._header_page_count_8kb = data_types.uint16(f.read(2))
    # 2         1       emulation mode?
    f.read(1)
    # 3         5       reserved
    f.read(5)
    # 8         1       0xAA
    id_byte1 = data_types.uint8(f.read(1))
    if id_byte1 != 0xAA:
        logger.debug("snes/romfile.py: load_smc_file: expected 0xAA at offset 8, got %02X." % id_byte1)
        return False
    # 9         1       0xBB
    id_byte2 = data_types.uint8(f.read(1))
    if id_byte2 != 0xBB:
        logger.debug("snes/romfile.py: load_smc_file: expected 0xBB at offset 9, got %02X." % id_byte2)
        return False
    # 10        1       game type?
    game_type = data_types.uint8(f.read(1))
    if game_type != 4:
        logger.debug("snes/romfile.py: load_smc_file: unknown game type %d." % game_type)
        return False

    rom_offset = f_offset + 512
    f.seek(f_offset + 512, os.SEEK_SET)

    lohi_page_sizes = [ 0x8000, 0x10000 ]

    def read_rom_header(page_size):
        """
        There are several types of ROM:
            LoROM               $20
            HiROM               $21
            LoROM / FastROM     $30
            HiROM / FastROM     $31
            ExLoROM             $32
            ExHiROM             $35

        The checksum and checksum complement once or'd together, should produce 0xFFFF.
        """
        f.seek(rom_offset + page_size - 64, os.SEEK_SET)

        game_title = f.read(21)                             # xxC0-xxD4
        lohifastex_byte = data_types.uint8(f.read(1))       # xxD5
        rom_type = data_types.uint8(f.read(1))              # xxD6
        rom_size = data_types.uint8(f.read(1))              # xxD7
        sram_size = data_types.uint8(f.read(1))             # xxD8
        license_id_code = data_types.uint16(f.read(2))      # xxD9-xxDA
        version_number = data_types.uint8(f.read(1))        # xxDB
        checksum_complement = data_types.uint16(f.read(2))  # xxDC-xxDD
        checksum = data_types.uint16(f.read(2))             # xxDE-xxDF

        if checksum | checksum_complement != 0xFFFF:
            logger.debug("snes/romfile.py: load_smc_file: skipping page ending %06X, checksum mismatch." % page_size)
            return False

        idx_HiROM = lohifastex_byte & 0x01
        if page_size != lohi_page_sizes[idx_HiROM]:
            logger.debug("snes/romfile.py: load_smc_file: skipping page ending %06X, size mismatch." % page_size)
            return False

        f.read(4)                                                   # xxE0-xxE3
        native_mode_vector_COP = data_types.uint16(f.read(2))       # xxE4-xxE5
        native_mode_vector_BRK = data_types.uint16(f.read(2))       # xxE6-xxE7
        native_mode_vector_ABORT = data_types.uint16(f.read(2))     # xxE8-xxE9
        native_mode_vector_NMI = data_types.uint16(f.read(2))       # xxEA-xxEB
        native_mode_vector_RESET = data_types.uint16(f.read(2))     # xxEC-xxED
        native_mode_vector_IRQ = data_types.uint16(f.read(2))       # xxEE-xxEF

        f.read(4)                                                   # xxF0-xxF3
        emulation_mode_vector_COP = data_types.uint16(f.read(2))    # xxF4-xxF5
        emulation_mode_vector_ABORT = data_types.uint16(f.read(2))  # xxF6-xxF7
        emulation_mode_vector_NMI = data_types.uint16(f.read(2))    # xxF8-xxF9
        emulation_mode_vector_RESET = data_types.uint16(f.read(2))  # xxFA-xxFB
        emulation_mode_vector_BRK = data_types.uint16(f.read(2))    # xxFC-xxFD
        emulation_mode_vector_IRQ = data_types.uint16(f.read(2))    # xxFE-xxFF

        return True

    for page_size in lohi_page_sizes:
        if read_rom_header(page_size):
            break
    else:
        logger.debug("snes/romfile.py: load_smc_file: failed to locate valid header.")
        return False

    return True


SAVEFILE_VERSION = 1

def save_project_data(f, data):
    f.write(struct.pack("<H", SAVEFILE_VERSION))
    cPickle.dump(data, f, -1)
    return True

def load_project_data(f):
    savefile_version = struct.unpack("<H", f.read(2))[0]
    if savefile_version != SAVEFILE_VERSION:
        logger.error("Unable to load old savefile data, got: %d, wanted: %d", savefile_version, SAVEFILE_VERSION)
        return
    data = cPickle.load(f)
    return data


def print_summary(file_info):
    data = file_info.file_data
