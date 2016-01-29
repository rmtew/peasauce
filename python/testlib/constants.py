#

# Keys under which options are stored.
OPTIONS_UNKNOWN = 0
OPTIONS_FILE_OUTPUT = 1
OPTIONS_CPU = 2
OPTIONS_STANDARD = 3

# General options that belong to no specific collection.
OPTION_UNKNOWN = 0
OPTION_DISABLE_OPTIMISATIONS = 1
OPTION_DEFAULT_FILE_NAME = 2

# CPU optons.
CPU_UNKNOWN = 0
CPU_MC60000 = 1
CPU_MC60010 = 2
CPU_MC60020 = 3
CPU_MC60030 = 4
CPU_MC60040 = 5
CPU_MC60060 = 7

def get_cpu_name_by_id(cpu_id):
    for k, v in globals().items():
        if k.startswith("CPU_") and v == cpu_id:
            return k

ASM_SYNTAX_UNKNOWN = 0
ASM_SYNTAX_MOTOROLA = 1

def get_syntax_name_by_id(syntax_id):
    for k, v in globals().items():
        if k.startswith("ASM_SYNTAX_") and v == syntax_id:
            return k

OUTPUT_FORMAT_UNKNOWN = 0
OUTPUT_FORMAT_BINARY = 1
OUTPUT_FORMAT_AMIGA_HUNK = 2
OUTPUT_FORMAT_ATARIST_TOS = 3

def get_output_format_name_by_id(output_format_id):
    for k, v in globals().items():
        if k.startswith("OUTPUT_FORMAT_") and v == output_format_id:
            return k

