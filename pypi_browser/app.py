import email
import importlib.metadata
import io
import itertools
import mimetypes
import os.path
import re
import typing

import fluffy_code.code
import fluffy_code.prebuilt_styles
import packaging.version
import pygments.lexers.special
import starlette.config
from identify import identify
from markupsafe import Markup
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.responses import RedirectResponse
from starlette.responses import Response
from starlette.responses import StreamingResponse
from starlette.routing import Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

import pypi_browser.packaging
from pypi_browser import pypi
from pypi_browser.packaging import PackageFormat


PACKAGE_TYPE_NOT_SUPPORTED_ERROR = 'Sorry, this package type is not yet supported.'

ONE_KB = 2**10
ONE_MB = 2**20
ONE_GB = 2**30

TEXT_RENDER_FILESIZE_LIMIT = int(os.environ.get('PYPI_BROWSER_TEXT_RENDER_FILESIZE_LIMIT', ONE_MB))

# Mime types which are allowed to be presented as detected.
# TODO: I think we actually only need to prevent text/html (and any HTML
# variants like XHTML)?
MIME_WHITELIST = (
    'application/javascript',
    'application/json',
    'application/pdf',
    'application/x-ruby',
    'audio/',
    'image/',
    'text/css',
    'text/plain',
    'text/x-python',
    'text/x-sh',
    'video/',
)


install_root = os.path.dirname(__file__)


class CacheControlHeaderMiddleware(BaseHTTPMiddleware):

    async def dispatch(
        self,
        request: Request,
        call_next: typing.Callable[[Request], typing.Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        # TODO: There should be a better way to do this...
        response.headers['Cache-Control'] = 'no-cache'
        return response


config = starlette.config.Config()
pypi_url = config('PYPI_BROWSER_PYPI_URL', default='https://pypi.org').rstrip('/')
repo: pypi.PythonRepository
if pypi_url.endswith('/simple'):
    repo = pypi.SimpleRepository(pypi_url)
else:
    repo = pypi.LegacyJsonRepository(pypi_url)

pypi_config = pypi.PyPIConfig(
    repo=repo,
    cache_path=config('PYPI_BROWSER_PACKAGE_CACHE_PATH', default='/tmp'),
)

templates = Jinja2Templates(
    directory=os.path.join(install_root, 'templates'),
)


def _pluralize(n: int) -> str:
    return '' if n == 1 else 's'


def _human_size(size: int) -> str:
    if size >= ONE_GB:
        return f'{size / ONE_GB:.1f} GiB'
    elif size >= ONE_MB:
        return f'{size / ONE_MB:.1f} MiB'
    elif size >= ONE_KB:
        return f'{size / ONE_KB:.1f} KiB'
    else:
        return '{} {}{}'.format(size, 'byte', _pluralize(size))


templates.env.filters['human_size'] = _human_size
templates.env.filters['pluralize'] = _pluralize
templates.env.globals['pypi_browser_version'] = importlib.metadata.version('pypi-browser-webapp')


async def home(request: Request) -> Response:
    return templates.TemplateResponse('home.html', {'request': request})


async def package(request: Request) -> Response:
    package_name = request.path_params['package']
    normalized_package_name = pypi_browser.packaging.pep426_normalize(package_name)
    if package_name != normalized_package_name:
        return RedirectResponse(request.url_for('package', package=normalized_package_name))

    try:
        version_to_files = await pypi.files_by_version(pypi_config, package_name)
    except pypi.PackageDoesNotExist:
        return PlainTextResponse(
            f'Package {package_name!r} does not exist on PyPI.',
            status_code=404,
        )
    else:
        def _version_sort_key(version: str | None) -> packaging.version.Version:
            if version is not None:
                try:
                    return packaging.version.parse(version)
                except packaging.version.InvalidVersion:
                    pass
            # Not really correct, but just throw everything we can't parse at the bottom.
            return packaging.version.Version('0.0.0')

        version_to_files_sorted = sorted(
            version_to_files.items(),
            key=lambda item: _version_sort_key(item[0]),
            reverse=True,
        )
        return templates.TemplateResponse(
            'package.html',
            {
                'request': request,
                'package': package_name,
                'version_to_files': version_to_files_sorted,
                'total_files': len(set(itertools.chain.from_iterable(version_to_files.values()))),
            },
        )


async def package_file(request: Request) -> Response:
    package_name = request.path_params['package']
    file_name = request.path_params['filename']

    normalized_package_name = pypi_browser.packaging.pep426_normalize(package_name)
    if package_name != normalized_package_name:
        return RedirectResponse(
            request.url_for(
                'package_file',
                package=normalized_package_name,
                filename=file_name,
            ),
        )

    try:
        archive = await pypi.downloaded_file_path(pypi_config, package_name, file_name)
    except pypi.PackageDoesNotExist:
        return PlainTextResponse(
            f'Package {package_name!r} does not exist on PyPI.',
            status_code=404,
        )
    except pypi.CannotFindFileError:
        return PlainTextResponse(
            f'File {file_name!r} does not exist for package {package_name!r}.',
            status_code=404,
        )

    try:
        package = pypi_browser.packaging.Package.from_path(archive)
    except pypi_browser.packaging.UnsupportedPackageType:
        return PlainTextResponse(
            PACKAGE_TYPE_NOT_SUPPORTED_ERROR,
            status_code=501,
        )

    entries = await package.entries()
    metadata_entries = [
        entry
        for entry in entries
        if re.match(r'(?:[^/]+\.dist-info/METADATA|^[^/]+/PKG-INFO)$', entry.path)
        and entry.size <= TEXT_RENDER_FILESIZE_LIMIT
    ]
    if len(metadata_entries) > 0:
        metadata_path = metadata_entries[0].path
        metadata = {}

        async with package.open_from_archive(metadata_path) as f:
            metadata_file = io.StringIO((await f.read()).decode('utf8', errors='ignore'))

        message = email.message_from_file(metadata_file)
        metadata = {
            key: message.get_all(key)
            for key in set(message.keys())
        }
    else:
        metadata_path = None
        metadata = {}

    return templates.TemplateResponse(
        'package_file.html',
        {
            'request': request,
            'package': package_name,
            'package_is_tarball': package.package_format is PackageFormat.TARBALL,
            'filename': file_name,
            'entries': entries,
            'metadata_path': metadata_path,
            'metadata': metadata,
        },
    )


async def package_file_archive_path(request: Request) -> Response:
    package_name = request.path_params['package']
    file_name = request.path_params['filename']
    archive_path = request.path_params['archive_path']

    normalized_package_name = pypi_browser.packaging.pep426_normalize(package_name)
    if package_name != normalized_package_name:
        return RedirectResponse(
            request.url_for(
                'package_file_archive_path',
                package=normalized_package_name,
                filename=file_name,
                archive_path=archive_path,
            ),
        )

    try:
        archive = await pypi.downloaded_file_path(pypi_config, package_name, file_name)
    except pypi.PackageDoesNotExist:
        return PlainTextResponse(
            f'Package {package_name!r} does not exist on PyPI.',
            status_code=404,
        )
    except pypi.CannotFindFileError:
        return PlainTextResponse(
            f'File {file_name!r} does not exist for package {package_name!r}.',
            status_code=404,
        )
    try:
        package = pypi_browser.packaging.Package.from_path(archive)
    except pypi_browser.packaging.UnsupportedPackageType:
        return PlainTextResponse(
            PACKAGE_TYPE_NOT_SUPPORTED_ERROR,
            status_code=501,
        )

    entries = await package.entries()
    matching_entries = [entry for entry in entries if entry.path == archive_path]
    if len(matching_entries) == 0:
        return PlainTextResponse(
            f'Path {archive_path!r} does not exist in archive.',
            status_code=404,
        )
    entry = matching_entries[0]
    mimetype, _ = mimetypes.guess_type(archive_path)
    metadata = (
        ('Size', _human_size(entry.size)),
        ('Mimetype', Markup(f'<tt>{mimetype}</tt>') if mimetype else 'Unknown'),
        ('Mode', Markup(f'<tt>{entry.mode}</tt>')),
    )

    def _transfer_raw() -> Response:
        """Return the file verbatim."""
        async def transfer_file() -> typing.AsyncIterator[bytes]:
            async with package.open_from_archive(archive_path) as f:
                data = None
                while data is None or len(data) > 0:
                    data = await f.read(1024)
                    yield data

        return StreamingResponse(
            transfer_file(),
            media_type=mimetype if (mimetype or '').startswith(MIME_WHITELIST) else None,
            headers={'Content-Length': str(entry.size)},
        )

    if 'raw' in request.query_params:
        return _transfer_raw()

    # There are a few cases to handle here:
    #   (1) Reasonable-length text: render syntax highlighted in HTML
    #   (2) Extremely long text: don't render, just show error and offer
    #       link to the raw file
    #   (3) Binary file: don't render, just show warning and link to the raw
    #       file

    # Figure out if it looks like text or not.
    async with package.open_from_archive(archive_path) as f:
        first_chunk = await f.read(TEXT_RENDER_FILESIZE_LIMIT)

    is_text = identify.is_text(io.BytesIO(first_chunk))

    if is_text:
        if entry.size <= TEXT_RENDER_FILESIZE_LIMIT:
            text = first_chunk.decode('utf8', errors='replace')

            # Case 1: render syntax-highlighted.
            style_config = fluffy_code.prebuilt_styles.default_style()

            try:
                # TODO: Remove this cast once
                # https://github.com/python/typeshed/pull/8777 is merged.
                lexer = typing.cast(
                    pygments.lexer.Lexer,
                    pygments.lexers.guess_lexer_for_filename(
                        archive_path,
                        text,
                        stripnl=False,
                    ),
                )
            except pygments.lexers.ClassNotFound:
                lexer = pygments.lexers.special.TextLexer(stripnl=False)

            return templates.TemplateResponse(
                'package_file_archive_path.html',
                {
                    'request': request,
                    'package': package_name,
                    'package_is_tarball': package.package_format is PackageFormat.TARBALL,
                    'filename': file_name,
                    'archive_path': archive_path,
                    'rendered_text': fluffy_code.code.render(
                        text,
                        style_config=style_config,
                        highlight_config=fluffy_code.code.HighlightConfig(
                            lexer=lexer,
                            highlight_diff=False,
                        ),
                    ),
                    'metadata': metadata,
                    'extra_css': fluffy_code.code.get_global_css() + '\n' + style_config.css,
                    'extra_js': fluffy_code.code.get_global_javascript(),
                },
            )
        else:
            # Case 2: too long to syntax highlight.
            return templates.TemplateResponse(
                'package_file_archive_path.html',
                {
                    'request': request,
                    'package': package_name,
                    'package_is_tarball': package.package_format is PackageFormat.TARBALL,
                    'filename': file_name,
                    'archive_path': archive_path,
                    'metadata': metadata,
                    'cannot_render_error': 'This file is too long to display inline with syntax highlighting.',
                },
            )

    # Case 3: link to binary
    return templates.TemplateResponse(
        'package_file_archive_path.html',
        {
            'request': request,
            'package': package_name,
            'package_is_tarball': package.package_format is PackageFormat.TARBALL,
            'filename': file_name,
            'archive_path': archive_path,
            'metadata': metadata,
            'cannot_render_error': 'This file appears to be a binary.',
        },
    )


async def search(request: Request) -> Response:
    return RedirectResponse(request.url_for('package', package=request.query_params['package']))


app = Starlette(
    debug=os.environ.get('PYPI_BROWSER_DEBUG') == '1',
    middleware=[
        Middleware(CacheControlHeaderMiddleware),
    ],
    routes=[
        Route('/', endpoint=home),
        Route('/package/{package}', endpoint=package),
        Route('/package/{package}/{filename}', endpoint=package_file),
        Route('/package/{package}/{filename}/{archive_path:path}', endpoint=package_file_archive_path),
        Route('/search', endpoint=search),
    ],
)
app.mount('/static', StaticFiles(directory=os.path.join(install_root, 'static')), name='static')
