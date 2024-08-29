import itertools
from typing import Type, Optional, BinaryIO

from unrpa.versions.version import Version, HeaderBasedVersion
from unrpa.view import ArchiveView


class RPA91(HeaderBasedVersion):
    name = "RPA-9.1"
    header = b"RPA-9.1"

    magic_bytes = (0xF6,0x02,0x3F,0x76,0x4D,0x0B,0x80,0x1B,0x29,0x10,0xDF,0xDD,0x74,0x85,0xDE,0xA6,0xDB,0x7D,0xC8,0x19,0xBA,0xE3,0xD0,0x63,0x2F,0x50,0xE7,0x55,0xB4,0x67,0x0B,0xFB)
    magic_bytes2 = (0xF602_3F76_4D0B_801B, 0x2910_DFDD_7485_DEA6, 0xDB7D_C819_BAE3_D063, 0x2F50_E755_B467_0BFB)
    magic = None

    def __init__(self):
        try:
            import numpy
            self.use_numpy = True
            self.magic = numpy.frombuffer(bytes(self.magic_bytes), dtype=numpy.uint8)
            print("Using numpy.")
        except ImportError:
            self.use_numpy = False
            print("Using itertools. Installing the numpy module would make this script 5-10 times faster.")

    def find_offset_and_key(self, archive: BinaryIO) -> tuple[int, Optional[int]]:
        chunk = archive.read(40)
        offset = int(chunk[8:24], 16) ^ 0x46D9_6FA8_FAD5_262B
        return offset, 0x126E_6680

    def postprocess(self, source: ArchiveView, sink: BinaryIO) -> None:
        if self.use_numpy:
            import numpy
            for segment in iter(source.read1, b""):
                segment_array = numpy.frombuffer(segment, dtype=numpy.uint8)
                xored_segment = segment_array ^ self.magic[numpy.arange(len(segment_array)) & 31]
                sink.write(xored_segment.tobytes())
        else:
            for segment in iter(source.read1, b""):
                magic_cycle = itertools.cycle(self.magic_bytes)
                sink.write(bytes(b ^ next(magic_cycle) for b in segment))


versions: Type[Version] = RPA91
