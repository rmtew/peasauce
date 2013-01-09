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

from . import doshunks
from . import hunkfile


class System(object):
    big_endian = True

    def get_arch_name(self):
        return "m68k"

    def load_input_file(self, input_file, file_info, data_types):
        return hunkfile.load_input_file(input_file, file_info, data_types)

    def identify_input_file(self, input_file, file_info, data_types):
        return hunkfile.identify_input_file(input_file, file_info, data_types)

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
