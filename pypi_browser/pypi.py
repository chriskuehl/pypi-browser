import abc
import base64
import collections
import contextlib
import dataclasses
import html.parser
import itertools
import os.path
import typing
import urllib.parse

import aiofiles.os
import httpx

from pypi_browser import packaging


class PythonRepository(abc.ABC):

    @abc.abstractmethod
    async def files_for_package(self, package_name: str) -> dict[str, str]:
        """Return mapping from filename to file URL for files in a package."""


class HTMLAnchorParser(html.parser.HTMLParser):
    anchors: set[str]

    def __init__(self) -> None:
        super().__init__()
        self.anchors = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == 'a':
            if href := dict(attrs).get('href'):
                self.anchors.add(href)


@dataclasses.dataclass(frozen=True)
class SimpleRepository(PythonRepository):
    """Old-style "simple" PyPI registry serving HTML files."""
    # TODO: Also handle PEP691 JSON simple repositories.
    pypi_url: str

    async def files_for_package(self, package_name: str) -> dict[str, str]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f'{self.pypi_url}/{package_name}',
                follow_redirects=True,
            )
            if resp.status_code == 404:
                raise PackageDoesNotExist(package_name)
            parser = HTMLAnchorParser()
            parser.feed(resp.text)

            def clean_url(url: str) -> str:
                parsed = urllib.parse.urlparse(urllib.parse.urljoin(str(resp.url), url))
                return parsed._replace(fragment='').geturl()

            return {
                (urllib.parse.urlparse(url).path).split('/')[-1]: clean_url(url)
                for url in parser.anchors
            }


@dataclasses.dataclass(frozen=True)
class LegacyJsonRepository(PythonRepository):
    """Non-standardized JSON API compatible with pypi.org's /pypi/*/json endpoints."""
    pypi_url: str

    async def files_for_package(self, package_name: str) -> dict[str, str]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f'{self.pypi_url}/pypi/{package_name}/json',
                follow_redirects=True,
            )
            if resp.status_code == 404:
                raise PackageDoesNotExist(package_name)
            resp.raise_for_status()
            return {
                file_['filename']: urllib.parse.urljoin(str(resp.url), file_['url'])
                for file_ in itertools.chain.from_iterable(resp.json()['releases'].values())
            }


@dataclasses.dataclass(frozen=True)
class PyPIConfig:
    repo: PythonRepository
    cache_path: str


class PackageDoesNotExist(Exception):
    pass


async def files_by_version(config: PyPIConfig, package: str) -> dict[str | None, set[str]]:
    ret = collections.defaultdict(set)
    for filename in await config.repo.files_for_package(package):
        try:
            version = packaging.guess_version_from_filename(filename)
        except ValueError:
            # Possible with some very poorly-formed packages that used to be
            # allowed on PyPI. Just skip them when this happens.
            pass
        else:
            ret[version].add(filename)
    return ret


class CannotFindFileError(Exception):
    pass


def _storage_path(config: PyPIConfig, package: str, filename: str) -> str:
    return os.path.join(
        config.cache_path,
        # Base64-encoding the names to calculate the storage path just to be
        # extra sure to avoid any path traversal vulnerabilities.
        base64.urlsafe_b64encode(package.encode('utf8')).decode('ascii'),
        base64.urlsafe_b64encode(filename.encode('utf8')).decode('ascii'),
    )


@contextlib.asynccontextmanager
async def _atomic_file(path: str) -> typing.AsyncIterator[aiofiles.threadpool.binary.AsyncBufferedIOBase]:
    async with aiofiles.tempfile.NamedTemporaryFile('wb', dir=os.path.dirname(path), delete=False) as f:
        tmp_path = typing.cast(str, f.name)
        try:
            yield f
        except BaseException:
            await aiofiles.os.remove(tmp_path)
            raise
        else:
            # This is atomic since the temporary file was created in the same directory.
            await aiofiles.os.rename(tmp_path, path)


async def downloaded_file_path(config: PyPIConfig, package: str, filename: str) -> str:
    """Return path on filesystem to downloaded PyPI file.

    May be instant if the file is already cached; otherwise it will download
    it and may take a while.
    """
    stored_path = _storage_path(config, package, filename)
    if await aiofiles.os.path.exists(stored_path):
        return stored_path

    filename_to_url = await config.repo.files_for_package(package)
    try:
        url = filename_to_url[filename]
    except KeyError:
        raise CannotFindFileError(package, filename)

    await aiofiles.os.makedirs(os.path.dirname(stored_path), exist_ok=True)

    async with httpx.AsyncClient() as client:
        async with _atomic_file(stored_path) as f:
            async with client.stream('GET', url) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes():
                    await f.write(chunk)

        return stored_path
