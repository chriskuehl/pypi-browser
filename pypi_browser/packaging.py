import asyncio
import base64
import contextlib
import enum
import os.path
import re
import stat
import tarfile
import typing
import zipfile
from dataclasses import dataclass
from types import TracebackType


def pep426_normalize(package_name: str) -> str:
    return re.sub(r'[-_.]+', '-', package_name).lower()


class UnsupportedPackageType(Exception):
    pass


class PackageType(enum.Enum):
    SDIST = enum.auto()
    WHEEL = enum.auto()
    EGG = enum.auto()


class PackageFormat(enum.Enum):
    ZIPFILE = enum.auto()
    TARBALL = enum.auto()


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


def _package_entries_from_tarball(path: str) -> typing.Set[PackageEntry]:
    with tarfile.open(path) as tf:
        return {
            PackageEntry(
                path=entry.name,
                size=entry.size,
                mode=stat.filemode(entry.mode),
            )
            for entry in tf.getmembers()
            if not entry.isdir()
        }


class AsyncArchiveFile:

    file_: typing.IO[bytes]

    def __init__(self, file_: typing.IO[bytes]) -> None:
        self.file_ = file_

    async def __aenter__(self) -> 'AsyncArchiveFile':
        return self

    async def __aexit__(
        self,
        exc_t: typing.Optional[typing.Type[BaseException]],
        exc_v: typing.Optional[BaseException],
        exc_tb: typing.Optional[TracebackType],
    ) -> None:
        await asyncio.to_thread(self.file_.close)

    async def read(self, n_bytes: int = -1) -> bytes:
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
        elif name.endswith('.egg'):
            package_type = PackageType.EGG
            package_format = PackageFormat.ZIPFILE
        elif name.endswith(('.tar', '.tar.gz', '.tgz', '.tar.bz2')):
            package_type = PackageType.SDIST
            package_format = PackageFormat.TARBALL
        else:
            raise UnsupportedPackageType(name)

        return cls(
            package_type=package_type,
            package_format=package_format,
            path=path,
        )

    async def entries(self) -> typing.Set[PackageEntry]:
        if self.package_format is PackageFormat.ZIPFILE:
            return await asyncio.to_thread(_package_entries_from_zipfile, self.path)
        elif self.package_format is PackageFormat.TARBALL:
            return await asyncio.to_thread(_package_entries_from_tarball, self.path)
        else:
            raise AssertionError(self.package_format)

    @contextlib.asynccontextmanager
    async def open_from_archive(self, path: str) -> typing.AsyncIterator[AsyncArchiveFile]:
        if self.package_format is PackageFormat.ZIPFILE:
            zf = await asyncio.to_thread(zipfile.ZipFile, self.path)  # type: ignore
            try:
                zip_archive_file = await asyncio.to_thread(zf.open, path)
                async with AsyncArchiveFile(zip_archive_file) as wrapped:
                    yield wrapped
            finally:
                await asyncio.to_thread(zf.close)
        elif self.package_format is PackageFormat.TARBALL:
            tf = await asyncio.to_thread(tarfile.open, self.path)
            try:
                tar_archive_file = await asyncio.to_thread(tf.extractfile, path)
                assert tar_archive_file is not None, path
                async with AsyncArchiveFile(tar_archive_file) as wrapped:
                    yield wrapped
            finally:
                await asyncio.to_thread(tf.close)
        else:
            raise AssertionError(self.package_format)
