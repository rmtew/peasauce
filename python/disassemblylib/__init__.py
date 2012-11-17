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


def get_api(arch_name):
    if arch_name == "m68k":
        import archm68k as module

    api_func_names = [
        "is_final_instruction",
        "get_match_addresses",
        "get_instruction_string",
        "get_operand_string",
        "disassemble_one_line",
    ]

    api = []
    for func_name in api_func_names:
        func = getattr(module, func_name)
        api.append((func_name, func))
    return api
