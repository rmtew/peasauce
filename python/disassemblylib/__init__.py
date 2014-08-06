"""
    Peasauce - interactive disassembler
    Copyright (C) 2012, 2013, 2014 Richard Tew
    Licensed using the MIT license.
"""

def get_arch_names():
    return [
        "m68k",
        #"mips32", # Assume little endian for now.  Can be both apparently.
    ]

def get_arch(arch_name):
    if arch_name == "m68k":
        from archm68k import ArchM68k as ArchClass
        from archm68k import instruction_table
        from archm68k import operand_type_table

    arch = ArchClass()
    arch.set_operand_type_table(operand_type_table)
    arch.set_instruction_table(instruction_table)
    return arch
