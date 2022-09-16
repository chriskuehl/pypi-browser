import base64
import contextlib
import dataclasses
import itertools
import os.path
import typing

import aiofiles.os
import httpx


@dataclasses.dataclass(frozen=True)
class PyPIConfig:
    cache_path: str
    pypi_url: str


class PackageDoesNotExist(Exception):
    pass


async def package_metadata(config: PyPIConfig, client: httpx.AsyncClient, package: str) -> typing.Dict:
    resp = await client.get(f'{config.pypi_url}/pypi/{package}/json')
    if resp.status_code == 404:
        raise PackageDoesNotExist(package)
    resp.raise_for_status()
    return resp.json()


async def files_for_package(config: PyPIConfig, package: str) -> typing.Dict[str, typing.Set[str]]:
    async with httpx.AsyncClient() as client:
        metadata = await package_metadata(config, client, package)

    return {
        version: {file_['filename'] for file_ in files}
        for version, files in metadata['releases'].items()
        if len(files) > 0
    }


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
async def _atomic_file(path: str, mode: str = 'w') -> typing.Any:
    async with aiofiles.tempfile.NamedTemporaryFile(mode, dir=os.path.dirname(path), delete=False) as f:
        try:
            yield f
        except BaseException:
            await aiofiles.os.remove(f.name)
            raise
        else:
            # This is atomic since the temporary file was created in the same directory.
            await aiofiles.os.rename(f.name, path)


async def downloaded_file_path(config: PyPIConfig, package: str, filename: str) -> str:
    """Return path on filesystem to downloaded PyPI file.

    May be instant if the file is already cached; otherwise it will download
    it and may take a while.
    """
    stored_path = _storage_path(config, package, filename)
    if await aiofiles.os.path.exists(stored_path):
        return stored_path

    async with httpx.AsyncClient() as client:
        metadata = await package_metadata(config, client, package)

        # Parsing versions from non-wheel Python packages isn't perfectly
        # reliable, so just search through all releases until we find a
        # matching file.
        for file_ in itertools.chain.from_iterable(metadata['releases'].values()):
            if file_['filename'] == filename:
                url = file_['url']
                break
        else:
            raise CannotFindFileError(package, filename)

        await aiofiles.os.makedirs(os.path.dirname(stored_path), exist_ok=True)

        async with _atomic_file(stored_path, 'wb') as f:
            async with client.stream('GET', url) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes():
                    await f.write(chunk)

        return stored_path
