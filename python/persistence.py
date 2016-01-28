"""
    Peasauce - interactive disassembler
    Copyright (C) 2012-2016 Richard Tew
    Licensed using the MIT license.
"""

"""
Pickle is great, and lets you just save and load whatever you like.  However,
if you change your code and wish previously pickled objects to load, then you
have one problem.  Another problem is that you don't really control what is
or is not saved, and unnecessary state might be getting mixed in.

The purpose of this module is to implement backwards compatible persistence
of the disassembly state, at some point.
"""

import cStringIO, os, struct


def sizeof_uint32():
    return struct.calcsize("<I")

def read_uint32(f):
    return struct.unpack("<I", f.read(4))[0]

def read_int32(f):
    return struct.unpack("<i", f.read(4))[0]

def read_uint16(f):
    return struct.unpack("<H", f.read(2))[0]

def read_int16(f):
    return struct.unpack("<h", f.read(2))[0]

def read_uint8(f):
    return struct.unpack("<B", f.read(1))[0]

def read_int8(f):
    return struct.unpack("<b", f.read(1))[0]

def read_bytes(f, num_bytes):
    return f.read(num_bytes)

def read_string(f):
    s = ""
    while 1:
        v = f.read(1)
        if v == '\0':
            break
        s += v
    return s


def write_uint32(f, value):
    f.write(struct.pack("<I", value))

def write_int32(f, value):
    f.write(struct.pack("<i", value))

def write_uint16(f, value):
    f.write(struct.pack("<H", value))

def write_int16(f, value):
    f.write(struct.pack("<h", value))

def write_uint8(f, value):
    f.write(struct.pack("<B", value))

def write_int8(f, value):
    f.write(struct.pack("<b", value))

def write_bytes(f, value, num_bytes):
    f.write(value[:num_bytes])

def write_string(f, value):
    f.write(value)
    f.write("\0")


def read_set_of_uint32s(f):
    chunk_size = read_uint32(f)
    set_entry_count = chunk_size / sizeof_uint32()
    v = set()
    while set_entry_count:
        v.add(read_uint32(f))
        set_entry_count -= 1
    return v

def write_set_of_uint32s(f, v):
    chunk_size_offset = f.tell()
    write_uint32(f, 0)

    data_offset = f.tell()
    for k in v:
        write_uint32(f, k)

    end_offset = f.tell()
    # Write the chunk size at the beginning.
    f.seek(chunk_size_offset, os.SEEK_SET)
    write_uint32(f, end_offset - data_offset)
    # Ensure the current file position is after our new data.
    f.seek(end_offset, os.SEEK_SET)

def read_dict_uint32_to_set_of_uint32s(f):
    # Read number of dictionary entries.
    d = {}
    dict_entry_count = read_uint32(f)
    while dict_entry_count:
        # Read key uint.
        k = read_uint32(f)
        # Read number of set entries 'N'.
        set_entry_count = read_uint16(f)
        # Read N set entry uints.
        v = set()
        while set_entry_count:
            v.add(read_uint32(f))
            set_entry_count -= 1
        d[k] = v
        dict_entry_count -= 1
    return d

def write_dict_uint32_to_set_of_uint32s(f, d):
    # Write number of dictionary entries.
    write_uint32(f, len(d))
    for k, v in d.iteritems():
        # Write key uint.
        write_uint32(f, k)
        # Write number of set entries 'N'.
        write_uint16(f, len(v))
        # Write N set entry uints.
        for set_entry in v:
            write_uint32(f, set_entry)


def read_dict_uint32_to_list_of_uint32s(f):
    # Read number of dictionary entries.
    d = {}
    dict_entry_count = read_uint32(f)
    while dict_entry_count:
        # Read key uint.
        k = read_uint32(f)
        # Read number of set entries 'N'.
        set_entry_count = read_uint16(f)
        # Read N set entry uints.
        v = []
        while set_entry_count:
            v.append(read_uint32(f))
            set_entry_count -= 1
        d[k] = v
        dict_entry_count -= 1
    return d

def write_dict_uint32_to_list_of_uint32s(f, d):
    # Write number of dictionary entries.
    write_uint32(f, len(d))
    for k, v in d.iteritems():
        # Write key uint.
        write_uint32(f, k)
        # Write number of list entries 'N'.
        write_uint16(f, len(v))
        # Write N list entry uints.
        for list_entry in v:
            write_uint32(f, list_entry)


def read_dict_uint32_to_string(f):
    chunk_size_offset = f.tell()
    # Read chunk size.
    chunk_size = read_uint32(f)
    # Read number of dictionary entries.
    dict_entry_count = read_uint32(f)
    # Preread the 
    values_offset = f.tell()
    f.seek(4 * dict_entry_count, os.SEEK_CUR)
    strings_offset = f.tell()
    string_data = f.read(chunk_size - (strings_offset - chunk_size_offset))
    string_file = cStringIO.StringIO(string_data)
    f.seek(values_offset, os.SEEK_SET)
    d = {}
    while dict_entry_count:
        k = read_uint32(f)
        v = read_string(string_file)
        d[k] = v
        dict_entry_count -= 1
    f.seek(chunk_size_offset + chunk_size, os.SEEK_SET)
    return d

def write_dict_uint32_to_string(f, d):
    # Write number of dictionary entries.
    chunk_size_offset = f.tell()
    write_uint32(f, 0)
    write_uint32(f, len(d))

    # Write keys, and collect values.
    values = []
    for k, v in d.iteritems():
        values.append(v)
        # Write key.
        write_uint32(f, k)

    # Write collected values.
    for v in values:
        write_string(f, v)

    end_offset = f.tell()
    f.seek(chunk_size_offset, os.SEEK_SET)
    write_uint32(f, end_offset - chunk_size_offset)
    f.seek(end_offset, os.SEEK_SET)



if __name__ == "__main__":
    import random, sys, unittest

    class Tests(unittest.TestCase):
        def test_dict_uint32_to_set_of_uint32s(self):
            dict_uint32_to_set_of_uint32s_value = { sys.maxint: set([ sys.maxint-1, 1, sys.maxint, 0 ]), 32: set([ 16, 8, 32, 64 ]), }

            f = cStringIO.StringIO()
            write_dict_uint32_to_set_of_uint32s(f, dict_uint32_to_set_of_uint32s_value)
            write_offset = f.tell()

            f.seek(0, os.SEEK_SET)
            dict_uint32_to_set_of_uint32s_value2 = read_dict_uint32_to_set_of_uint32s(f)
            read_offset = f.tell()

            self.assertEqual(dict_uint32_to_set_of_uint32s_value, dict_uint32_to_set_of_uint32s_value2)
            self.assertEqual(write_offset, read_offset)

        def test_dict_uint32_to_list_of_uint32s(self):
            test_value = { sys.maxint: [ sys.maxint-1, 1, sys.maxint, 0 ], 32: [ 16, 8, 32, 64 ], }

            f = cStringIO.StringIO()
            write_dict_uint32_to_list_of_uint32s(f, test_value)
            write_offset = f.tell()

            f.seek(0, os.SEEK_SET)
            test_value2 = read_dict_uint32_to_list_of_uint32s(f)
            read_offset = f.tell()

            self.assertEqual(test_value, test_value2)
            self.assertEqual(write_offset, read_offset)

        def test_dict_uint32_to_string(self):
            test_value = {}
            for i in range(10):
                k = random.randint(0, sys.maxint)
                v = "".join(chr(random.randint(ord('A'), ord('z')+1)) for i in range(10))
                test_value[k] = v

            f = cStringIO.StringIO()
            write_dict_uint32_to_string(f, test_value)
            write_offset = f.tell()

            f.seek(0, os.SEEK_SET)
            test_value2 = read_dict_uint32_to_string(f)
            read_offset = f.tell()

            self.assertEqual(test_value, test_value2)
            self.assertEqual(write_offset, read_offset)

        def test_set_of_uint32s(self):
            test_value = set(random.randint(0, sys.maxint) for v in range(random.randint(15, 30)))

            f = cStringIO.StringIO()
            write_set_of_uint32s(f, test_value)
            write_offset = f.tell()

            f.seek(0, os.SEEK_SET)
            test_value2 = read_set_of_uint32s(f)
            read_offset = f.tell()

            self.assertEqual(test_value, test_value2)
            self.assertEqual(write_offset, read_offset)
    
    unittest.main()

