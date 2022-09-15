import asyncio
import base64
import contextlib
import enum
import os.path
import re
import stat
import typing
import zipfile
from dataclasses import dataclass


def pep426_normalize(package_name: str) -> str:
    return re.sub(r'[-_.]+', '-', package_name).lower()


class UnsupportedPackageType(Exception):
    pass


class PackageType(enum.Enum):
    SDIST = enum.auto()
    WHEEL = enum.auto()


class PackageFormat(enum.Enum):
    ZIPFILE = enum.auto()
    TARBALL = enum.auto()
    TARBALL_GZ = enum.auto()
    TARBALL_BZ2 = enum.auto()


@dataclass(frozen=True)
class PackageEntry:
    path: str
    mode: str
    size: int


def _package_entries_from_zipfile(path: str) -> typing.Set[PackageEntry]:
    with zipfile.ZipFile(path) as zf:
        return {
            PackageEntry(
                path=entry.filename,
                size=entry.file_size,
                mode=stat.filemode(entry.external_attr >> 16),
            )
            for entry in zf.infolist()
            if not entry.is_dir()
        }


ArchiveFile = typing.Union[zipfile.ZipExtFile]


class AsyncArchiveFile:

    file_: ArchiveFile

    def __init__(self, file_: ArchiveFile) -> None:
        self.file_ = file_

    async def __aenter__(self) -> 'AsyncArchiveFile':
        return self

    async def __aexit__(self, exc_t, exc_v, exc_tb) -> None:
        await asyncio.to_thread(self.file_.close)

    async def read(self, n_bytes: typing.Optional[int] = None) -> bytes:
        return await asyncio.to_thread(self.file_.read, n_bytes)


@dataclass(frozen=True)
class Package:
    package_type: PackageType
    package_format: PackageFormat
    path: str

    @classmethod
    def from_path(cls, path: str) -> 'Package':
        name = base64.b64decode(os.path.basename(path).encode('ascii')).decode('utf8')

        if name.endswith('.whl'):
            package_type = PackageType.WHEEL
            package_format = PackageFormat.ZIPFILE
        elif name.endswith('.zip'):
            package_type = PackageType.SDIST
            package_format = PackageFormat.ZIPFILE
        else:
            # TODO: Add support for tarballs
            raise UnsupportedPackageType(name)

        return cls(
            package_type=package_type,
            package_format=package_format,
            path=path,
        )

    async def entries(self) -> typing.Set[PackageEntry]:
        if self.package_format is PackageFormat.ZIPFILE:
            return await asyncio.to_thread(_package_entries_from_zipfile, self.path)
        else:
            raise AssertionError(self.package_format)

    @contextlib.asynccontextmanager
    async def open_from_archive(self, path: str) -> str:
        if self.package_format is PackageFormat.ZIPFILE:
            zf = await asyncio.to_thread(zipfile.ZipFile, self.path)
            archive_file = await asyncio.to_thread(zf.open, path)
            try:
                async with AsyncArchiveFile(archive_file) as zip_archive_file:
                    yield zip_archive_file
            finally:
                await asyncio.to_thread(zf.close)
        else:
            raise AssertionError(self.package_format)
