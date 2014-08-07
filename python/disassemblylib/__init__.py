"""
    Peasauce - interactive disassembler
    Copyright (C) 2012, 2013, 2014 Richard Tew
    Licensed using the MIT license.
"""

M68K_NAME = "m68k"
MIPS_NAME = "mips"

def get_arch_names():
    return [
        M68K_NAME,
        MIPS_NAME,
    ]

def get_arch(arch_name):
    if arch_name == M68K_NAME:
        from archm68k import ArchM68k as ArchClass
        from archm68k import instruction_table
        from archm68k import operand_type_table
    elif arch_name == MIPS_NAME:
        from archmips import ArchMIPS as ArchClass
        from archmips import instruction_table
        from archmips import operand_type_table

    arch = ArchClass()
    arch.set_operand_type_table(operand_type_table)
    arch.set_instruction_table(instruction_table)
    return arch
