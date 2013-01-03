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


class System(object):
    big_endian = True
    
    arch_name = None

    def get_arch_name(self):
        return self.arch_name

    def set_arch_name(self, arch_name):
        self.arch_name = arch_name

    def load_input_file(self, input_file, file_info, data_types):
        if file_info.loader_options is None or not file_info.loader_options.is_binary_file:
            return False
        self.set_arch_name(file_info.loader_options.dis_name)

        input_file.seek(0, os.SEEK_END)
        file_size = input_file.tell()
        relocations = []
        symbols = []
        file_info.add_code_segment(0, file_size, file_size, relocations, symbols)
        return True

    def identify_input_file(self, input_file, file_info, data_types):
        """ User selected files should not be identified as binary. """
        return None

    def load_project_data(self, f):
        return None

    def save_project_data(self, f, data):
        return None

    def print_summary(self, file_info):
        pass

    def has_segment_headers(self):
        return False

    def get_segment_header(self, file_info, segment_id):
        return "this section header should never be seen"

    def get_data_instruction_string(self, is_bss_segment, with_file_data):
        if is_bss_segment:
            return "DS"
        return "DC"
