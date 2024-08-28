import io
import os
import zlib
import pickle
from typing import Tuple, Type, BinaryIO, Optional, List, Dict

from unrpa.versions.version import Version, HeaderBasedVersion
from unrpa.view import ArchiveView


class RPA91(HeaderBasedVersion):
    """I haven't the slightest clue."""

    name = "RPA-9.1"
    header = b"RPA-9.1"

    magic_bytes = (0xF6,0x02,0x3F,0x76,0x4D,0x0B,0x80,0x1B,0x29,0x10,0xDF,0xDD,0x74,0x85,0xDE,0xA6,0xDB,0x7D,0xC8,0x19,0xBA,0xE3,0xD0,0x63,0x2F,0x50,0xE7,0x55,0xB4,0x67,0x0B,0xFB)
    magic = None

    def find_offset_and_key(self, archive: BinaryIO) -> Tuple[int, Optional[int]]:
        l = archive.read(40)
        offset = int(l[8:24], 16) ^ 0x46D9_6FA8_FAD5_262B
        return (offset, 0x126E_6680)

    def postprocess(self, source: ArchiveView, sink: BinaryIO) -> None:
        try:
            import numpy
            if self.magic is None:
                self.magic = numpy.frombuffer(bytes(self.magic_bytes), dtype=numpy.uint8)
            for segment in iter(source.read1, b""):
                segment_array = numpy.frombuffer(segment, dtype=numpy.uint8)
                xored_segment = segment_array ^ self.magic[numpy.arange(len(segment_array)) & 31]
                sink.write(xored_segment.tobytes()) 
        except ImportError:
            from itertools import cycle
            for segment in iter(source.read1, b""):
                magic_cycle = cycle(self.magic_bytes)
                for segment in iter(source.read1, b""):
                    sink.write(bytes(b ^ next(magic_cycle) for b in segment))


versions: Type[Version] = RPA91
