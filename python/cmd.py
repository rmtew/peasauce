import argparse
import logging
import os
import sys

import disassembly


logging.root.setLevel(logging.WARNING)
logging.root.addHandler(logging.StreamHandler())


def print_block_stats(disassembly_data):
    block_count = len(disassembly_data.blocks)
    code_block_count = 0
    for block in disassembly_data.blocks:
        if disassembly.get_block_data_type(block) == disassembly.DATA_TYPE_CODE:
            code_block_count += 1
    print "%d/%d code blocks" % (code_block_count, block_count)

def print_undetected_code_blocks(disassembly_data):
    print "Detecting data that is likely code..",
    blocks = disassembly.DEBUG_locate_potential_code_blocks(disassembly_data)
    print "%d blocks found." % len(blocks)

def run():
    parser = argparse.ArgumentParser(description='Command-line disassembly.')
    #parser.add_argument("-f", "--file")
    parser.add_argument("FILE")
    result = parser.parse_args()

    file_path = result.FILE
    if not os.path.isfile(file_path):
        sys.stderr.write(sys.argv[0] +": unable to open file '"+ file_path +"'"+ os.linesep)
        sys.exit(2)
    
    disassembly_data, line_count = disassembly.load_file(file_path)

    print_block_stats(disassembly_data)
    print_undetected_code_blocks(disassembly_data)

    print "Loaded with %d lines." % line_count

if __name__ == "__main__":
    run()
