import io
import os
import pickle
import sys
import traceback
import zlib
from typing import (
    Union,
    Tuple,
    Optional,
    Dict,
    cast,
    Iterable,
    Type,
    BinaryIO,
    FrozenSet,
)

from unrpa.errors import (
    OutputDirectoryNotFoundError,
    ErrorExtractingFile,
    AmbiguousArchiveError,
    UnknownArchiveError,
)
from unrpa.versions import rpa, alt, zix
from unrpa.versions.version import Version
from unrpa.view import ArchiveView

# Offset, Length
SimpleIndexPart = Tuple[int, int]
SimpleIndexEntry = Iterable[SimpleIndexPart]
# Offset, Length, Prefix
ComplexIndexPart = Tuple[int, int, bytes]
ComplexIndexEntry = Iterable[ComplexIndexPart]
IndexPart = Union[SimpleIndexPart, ComplexIndexPart]
IndexEntry = Iterable[IndexPart]


class UnRPA:
    """Extraction tool for RPA archives."""

    name = "unrpa"

    error = 0
    info = 1
    debug = 2

    provided_versions: FrozenSet[Type[Version]] = frozenset(
        {*rpa.versions, *alt.versions, *zix.versions}
    )

    def __init__(
        self,
        filename: str,
        verbosity: int = -1,
        path: Optional[str] = None,
        mkdir: bool = False,
        version: Optional[Type[Version]] = None,
        continue_on_error: bool = False,
        offset_and_key: Optional[Tuple[int, int]] = None,
        extra_versions: FrozenSet[Type[Version]] = frozenset(),
    ) -> None:
        self.verbose = verbosity
        if path:
            self.path = os.path.abspath(path)
        else:
            self.path = os.getcwd()
        self.mkdir = mkdir
        self.version = version
        self.archive = filename
        self.continue_on_error = continue_on_error
        self.offset_and_key = offset_and_key
        self.tty = sys.stdout.isatty()
        self.versions = UnRPA.provided_versions | extra_versions

    def log(
        self, verbosity: int, human_message: str, machine_message: str = None
    ) -> None:
        if self.tty and self.verbose > verbosity:
            print(
                human_message if self.tty else machine_message,
                file=sys.stderr if verbosity == UnRPA.error else sys.stdout,
            )

    def extract_files(self) -> None:
        self.log(UnRPA.error, "Extracting files.")
        if self.mkdir:
            self.make_directory_structure(self.path)
        if not os.path.isdir(self.path):
            raise OutputDirectoryNotFoundError(self.path)

        version = self.version() if self.version else self.detect_version()

        with open(self.archive, "rb") as archive:
            index = self.get_index(archive, version)
            total_files = len(index)
            for file_number, (path, data) in enumerate(index.items()):
                try:
                    self.make_directory_structure(
                        os.path.join(self.path, os.path.split(path)[0])
                    )
                    file_view = self.extract_file(
                        path,
                        data,
                        file_number,
                        total_files,
                        cast(io.BufferedReader, archive),
                    )
                    with open(os.path.join(self.path, path), "wb") as output_file:
                        version.postprocess(file_view, output_file)
                except BaseException as error:
                    if self.continue_on_error:
                        self.log(
                            0,
                            f"Error extracting from the archive, but directed to continue on error. Detail: "
                            f"{traceback.format_exc()}.",
                        )
                    else:
                        raise ErrorExtractingFile(traceback.format_exc()) from error

    def list_files(self) -> None:
        self.log(UnRPA.info, "Listing files:")
        with open(self.archive, "rb") as archive:
            paths = self.get_index(archive).keys()
        for path in sorted(paths):
            print(path)

    def extract_file(
        self,
        name: str,
        data: ComplexIndexEntry,
        file_number: int,
        total_files: int,
        archive: io.BufferedIOBase,
    ) -> ArchiveView:
        self.log(
            UnRPA.info, f"[{file_number / float(total_files):04.2%}] {name:>3}", name
        )
        offset, length, start = next(iter(data))
        return ArchiveView(archive, offset, length, start)

    def make_directory_structure(self, name: str) -> None:
        self.log(UnRPA.debug, f"Creating directory structure: {name}")
        if not os.path.exists(name):
            os.makedirs(name)

    def get_index(
        self, archive: BinaryIO, version: Optional[Version] = None
    ) -> Dict[str, ComplexIndexEntry]:
        if not version:
            version = self.version() if self.version else self.detect_version()

        offset = 0
        key: Optional[int] = None
        if self.offset_and_key:
            offset, key = self.offset_and_key
        else:
            offset, key = version.find_offset_and_key(archive)
        archive.seek(offset)
        index: Dict[bytes, IndexEntry] = pickle.loads(
            zlib.decompress(archive.read()), encoding="bytes"
        )
        if key is not None:
            normal_index = UnRPA.deobfuscate_index(key, index)
        else:
            normal_index = UnRPA.normalise_index(index)

        return {
            UnRPA.ensure_str_path(path).replace("/", os.sep): data
            for path, data in normal_index.items()
        }

    def detect_version(self) -> Version:
        potential = (version() for version in self.versions)
        ext = os.path.splitext(self.archive)[1].lower()
        with open(self.archive, "rb") as f:
            header = f.readline()
            detected = {version for version in potential if version.detect(ext, header)}
            if len(detected) > 1:
                raise AmbiguousArchiveError(detected)
            try:
                return next(iter(detected))
            except StopIteration:
                raise UnknownArchiveError(header)

    @staticmethod
    def ensure_str_path(path: Union[str, bytes]) -> str:
        if isinstance(path, str):
            return path
        else:
            return path.decode("utf-8", "replace")

    @staticmethod
    def deobfuscate_index(
        key: int, index: Dict[bytes, IndexEntry]
    ) -> Dict[bytes, ComplexIndexEntry]:
        return {
            path: UnRPA.deobfuscate_entry(key, entry) for path, entry in index.items()
        }

    @staticmethod
    def deobfuscate_entry(key: int, entry: IndexEntry) -> ComplexIndexEntry:
        return [
            (offset ^ key, length ^ key, start)
            for offset, length, start in UnRPA.normalise_entry(entry)
        ]

    @staticmethod
    def normalise_index(
        index: Dict[bytes, IndexEntry]
    ) -> Dict[bytes, ComplexIndexEntry]:
        return {path: UnRPA.normalise_entry(entry) for path, entry in index.items()}

    @staticmethod
    def normalise_entry(entry: IndexEntry) -> ComplexIndexEntry:
        return [
            (*cast(SimpleIndexPart, part), b"")
            if len(part) == 2
            else cast(ComplexIndexPart, part)
            for part in entry
        ]
