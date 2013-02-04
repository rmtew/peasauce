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

from . import xfile


class System(object):
    big_endian = True

    def get_arch_name(self):
        return "m68k"

    def identify_input_file(self, input_file, file_info, data_types, f_offset=0, f_length=None):
        return xfile.identify_input_file(input_file, file_info, data_types, f_offset, f_length)

    def load_input_file(self, input_file, file_info, data_types, f_offset=0, f_length=None):
        return xfile.load_input_file(input_file, file_info, data_types, f_offset, f_length)

    def load_project_data(self, f):
        return xfile.load_project_data(f)

    def save_project_data(self, f, data):
        xfile.save_project_data(f, data)

    def print_summary(self, file_info):
        xfile.print_summary(file_info)

    def has_segment_headers(self):
        return False

    def get_segment_header(self, file_info, segment_id):
        return "this section header should never be seen"

    def get_data_instruction_string(self, is_bss_segment, with_file_data):
        if is_bss_segment:
            return "DS"
        return "DC"
