from __future__ import print_function

# From disassembly:

if False:
    # Copy the source/input file to a temporary path.
    program_data.temporary_file_path = os.path.join(tempfile.gettempdir(), program_data.file_name)
    with open(file_path, "rb") as rf:
        with open(program_data.temporary_file_path, "wb") as wf:
            data = rf.read(256 * 1024)
            while len(data):
                wf.write(data)
                data = rf.read(256 * 1024)

# From now deleted cmd.py:

if False:
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
        print("%d/%d code blocks" % (code_block_count, block_count))

    def print_undetected_code_blocks(disassembly_data):
        print("Detecting data that is likely code..")
        blocks = disassembly.DEBUG_locate_potential_code_blocks(disassembly_data)
        print("%d blocks found." % len(blocks))

    def run():
        parser = argparse.ArgumentParser(description='Command-line disassembly.')
        #parser.add_argument("-f", "--file")
        parser.add_argument("FILE")
        result = parser.parse_args()

        file_path = result.FILE
        if not os.path.isfile(file_path):
            sys.stderr.write(sys.argv[0] +": unable to open file '"+ file_path +"'"+ os.linesep)
            sys.exit(2)
        
        disassembly_data, line_count = disassembly.api_load_file(file_path)

        print_block_stats(disassembly_data)
        print_undetected_code_blocks(disassembly_data)

        print("Loaded with %d lines." % line_count)

    if __name__ == "__main__":
        run()
