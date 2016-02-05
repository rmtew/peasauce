"""
    Peasauce - interactive disassembler
    Copyright (C) 2012-2016 Richard Tew
    Licensed using the MIT license.
"""

from .. import constants
from . import doshunks
from . import hunkfile


class System(object):
    endian_id = constants.ENDIAN_BIG


    def get_processor_id(self):
        return constants.PROCESSOR_M680x0

    def load_input_file(self, input_file, file_info, data_types, f_offset=0, f_length=None):
        return hunkfile.load_input_file(input_file, file_info, data_types, f_offset, f_length)

    def identify_input_file(self, input_file, file_info, data_types, f_offset=0, f_length=None):
        matches = []
        for handler in (hunkfile,):
            match = handler.identify_input_file(input_file, file_info, data_types, f_offset, f_length)
            if match.platform_id != constants.PLATFORM_UNKNOWN:
                matches.append(match)
        return matches

    def load_project_data(self, f):
        return hunkfile.load_project_data(f)

    def save_project_data(self, f, data):
        return hunkfile.save_project_data(f, data)

    def print_summary(self, file_info):
        hunkfile.print_summary(file_info)

    def has_segment_headers(self):
        return True

    def get_segment_header(self, segment_id, data):
        hunk_id = hunkfile.get_hunk_type(data, segment_id)
        s = "SECTION name{address:06X}"
        if hunk_id == doshunks.HUNK_DATA:
            s += ", DATA"
        elif hunk_id == doshunks.HUNK_CODE:
            s += ", CODE"
        elif hunk_id == doshunks.HUNK_BSS:
            s += ", BSS"
        memf_mask = hunkfile.get_hunk_memory_flags(data, segment_id)
        if memf_mask:
            s += ", "+ hunkfile.MEMF_NAMES[memf_mask & hunkfile.MEMF_MASK]
        return s

    def get_data_instruction_string(self, is_bss_segment, with_file_data):
        if with_file_data:
            return "DC"
        if is_bss_segment:
            return "DS"
        return "DX"
