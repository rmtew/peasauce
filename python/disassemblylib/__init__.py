"""
    Peasauce - interactive disassembler
    Copyright (C) 2012, 2013, 2014 Richard Tew
    Licensed using the MIT license.
"""

def get_arch_names():
    return [ "m68k" ]

def get_api(arch_name):
    if arch_name == "m68k":
        import archm68k as module

    api_func_names = [
        "is_final_instruction",
        "get_match_addresses",
        "get_instruction_string",
        "get_operand_string",
        "disassemble_one_line",
        "disassemble_as_data",
    ]

    api = []
    for func_name in api_func_names:
        func = getattr(module, func_name)
        api.append((func_name, func))
    return api
