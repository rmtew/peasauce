# This needs to lie outside the disassemblylib directory because of Python's arbitrary
# decision to limit relative importing to "packages".

import unittest

from disassemblylib import archmips, archm68k, util


class archmipsTestCase(unittest.TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def testInstructionParsing(self):
        pass

        
class archm68kTestCase(unittest.TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def testInstructionParsing(self):
        pass

class binaryConversionTestCase(unittest.TestCase):
    def testToNumber(self):
        self.assertTrue(util._b2n("1") == 1)
        self.assertTrue(util._b2n("10") == (1<<1))
        self.assertTrue(util._b2n("11") == (1<<1) + 1)
        self.assertTrue(util._b2n("11111111") == 0xFF)
        self.assertTrue(util._b2n("11110000") == 0xF0)
        self.assertTrue(util._b2n("00000000") == 0x00)

    def testFromNumber(self):
        self.assertTrue(util._n2b(1) == "1")
        self.assertTrue(util._n2b(7) == "111")
        self.assertTrue(util._n2b(255) == "11111111")
        self.assertTrue(util._n2b(254) == "11111110")
        self.assertTrue(util._n2b(256) == "100000000")
        
    def testFromNumberPadded(self):
        """ Padded out to multiples of 4 bits (octets). """
        self.assertTrue(util._n2b(1, dynamic_padding=True) == "0001")
        self.assertTrue(util._n2b(15, dynamic_padding=True) == "1111")
        self.assertTrue(util._n2b(16, dynamic_padding=True) == "00010000")
        self.assertTrue(util._n2b(255, dynamic_padding=True) == "11111111")

    def testFromNumberPaddingLength(self):
        self.assertTrue(util._n2b(util._b2n("1"), padded_length=2) == "01")
        self.assertTrue(util._n2b(util._b2n("1"), padded_length=3) == "001")
        for text in ("111", "001", "00001111"):
            value = util._b2n(text)
            self.assertTrue(util._n2b(value, padded_length=len(text)) == text)


if __name__ == "__main__":
    unittest.main()

