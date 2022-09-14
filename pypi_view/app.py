import io
import mimetypes
import os.path

import pygments.lexers
import pygments.lexers.special
import fluffy_code.code
import fluffy_code.prebuilt_styles
from identify import identify
from starlette.applications import Starlette
from starlette.staticfiles import StaticFiles
from starlette.requests import Request
from starlette.responses import Response
from starlette.responses import PlainTextResponse
from starlette.responses import StreamingResponse
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from pypi_view import packaging
from pypi_view import pypi

PACKAGE_TYPE_NOT_SUPPORTED_ERROR = (
    "Sorry, this package type is not yet supported (only .zip and .whl supported currently)."
)
TEXT_RENDER_FILESIZE_LIMIT = 20 * 1024  # 20 KiB

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

# Mime types which should be displayed inline in the browser, as opposed to
# being downloaded. This is used to populate the Content-Disposition header.
# Only binary MIMEs need to be whitelisted here, since detected non-binary
# files are always inline.
INLINE_DISPLAY_MIME_WHITELIST = (
    'application/pdf',
    'audio/',
    'image/',
    'video/',
)


install_root = os.path.dirname(__file__)

app = Starlette(debug=os.environ.get("PYPI_VIEW_DEBUG") == "1")
app.mount('/static', StaticFiles(directory=os.path.join(install_root, 'static')), name='static')

templates = Jinja2Templates(
    directory=os.path.join(install_root, "templates"),
)


@app.route('/')
async def home(request: Request) -> Response:
    return templates.TemplateResponse("home.html", {"request": request})


@app.route('/package/{package}')
async def package(request: Request) -> Response:
    package_name  = request.path_params["package"]
    try:
        version_to_files = await pypi.files_for_package(package_name)
    except pypi.PackageDoesNotExist:
        return PlainTextResponse(
            f"Package {package_name!r} does not exist on PyPI.",
            status_code=404,
        )
    else:
        return templates.TemplateResponse(
            "package.html",
            {
                "request": request,
                "package": package_name,
                "version_to_files": version_to_files,
            },
        )


@app.route('/package/{package}/{filename}')
async def package_file(request: Request) -> Response:
    package_name = request.path_params["package"]
    file_name = request.path_params["filename"]
    try:
        archive = await pypi.downloaded_file_path(package_name, file_name)
    except pypi.PackageDoesNotExist:
        return PlainTextResponse(
            f"Package {package_name!r} does not exist on PyPI.",
            status_code=404,
        )
    except pypi.CannotFindFileError:
        return PlainTextResponse(
            f"File {file_name!r} does not exist for package {package_name!r}.",
            status_code=404,
        )

    try:
        package = packaging.Package.from_path(archive)
    except packaging.UnsupportedPackageType:
        return PlainTextResponse(
            PACKAGE_TYPE_NOT_SUPPORTED_ERROR,
            status_code=501,
        )

    entries = await package.entries()
    return templates.TemplateResponse(
        "package_file.html",
        {
            "request": request,
            "package": package_name,
            "filename": file_name,
            "entries": entries,
        },
    )


@app.route('/package/{package}/{filename}/{archive_path:path}')
async def package_file_archive_path(request: Request) -> Response:
    package_name = request.path_params["package"]
    file_name = request.path_params["filename"]
    archive_path = request.path_params["archive_path"]
    try:
        archive = await pypi.downloaded_file_path(package_name, file_name)
    except pypi.PackageDoesNotExist:
        return PlainTextResponse(
            f"Package {package_name!r} does not exist on PyPI.",
            status_code=404,
        )
    except pypi.CannotFindFileError:
        return PlainTextResponse(
            f"File {file_name!r} does not exist for package {package_name!r}.",
            status_code=404,
        )
    try:
        package = packaging.Package.from_path(archive)
    except packaging.UnsupportedPackageType:
        return PlainTextResponse(
            PACKAGE_TYPE_NOT_SUPPORTED_ERROR,
            status_code=501,
        )

    entries = await package.entries()
    matching_entries = [entry for entry in entries if entry.path == archive_path]
    if len(matching_entries) == 0:
        return PlainTextResponse(
            f"Path {archive_path!r} does not exist in archive.",
            status_code=404,
        )
    entry = matching_entries[0]
    mimetype, _ = mimetypes.guess_type(archive_path)

    def _transfer_raw():
        """Return the file verbatim."""
        async def transfer_file():
            async with package.open_from_archive(archive_path) as f:
                data = None
                while data is None or len(data) > 0:
                    data = await f.read(1024)
                    yield data

        return StreamingResponse(
            transfer_file(),
            media_type=mimetype if mimetype.startswith(MIME_WHITELIST) else None,
            headers={"Content-Length": str(entry.size)},
        )

    if "raw" in request.query_params:
        return _transfer_raw()

    # There are a few cases to handle here:
    #   (1) Reasonable-length text: render syntax highlighted in HTML
    #   (2) Extremely long text: don't render, just show error and offer
    #       link to the raw file
    #   (3) Binary file that browsers can display (e.g. image): render raw
    #   (4) Binary file that browsers cannot display (e.g. tarball): don't
    #       render, just show warning and link to the raw file
    #
    # Note that except for images, the file extension isn't too useful to
    # determine the actual content since there are lots of files without
    # extensions (and lots of extensions not recognized by `mimetypes`).
    if mimetype is not None and mimetype.startswith(INLINE_DISPLAY_MIME_WHITELIST):
        # Case 3: render binary
        return _transfer_raw()

    # Figure out if it looks like text or not.
    async with package.open_from_archive(archive_path) as f:
        first_chunk = await f.read(TEXT_RENDER_FILESIZE_LIMIT)

    is_text = identify.is_text(io.BytesIO(first_chunk))

    if is_text:
        if entry.size <= TEXT_RENDER_FILESIZE_LIMIT:
            # Case 1: render syntax-highlighted.
            style_config = fluffy_code.prebuilt_styles.default_style()

            try:
                lexer = pygments.lexers.guess_lexer_for_filename(
                    archive_path,
                    first_chunk,
                )
            except pygments.lexers.ClassNotFound:
                lexer = pygments.lexers.special.TextLexer()

            return templates.TemplateResponse(
                "package_file_archive_path.html",
                {
                    "request": request,
                    "package": package_name,
                    "filename": file_name,
                    "archive_path": archive_path,
                    "rendered_text": fluffy_code.code.render(
                        first_chunk,
                        style_config=style_config,
                        highlight_config=fluffy_code.code.HighlightConfig(
                            lexer=lexer,
                            highlight_diff=False,
                        ),
                    ),
                    "extra_css": fluffy_code.code.get_global_css() + "\n" + style_config.css,
                    "extra_js": fluffy_code.code.get_global_javascript(),
                },
            )
        else:
            # Case 2: too long to syntax highlight.
            return templates.TemplateResponse(
                "package_file_archive_path_cannot_render.html",
                {
                    "request": request,
                    "package": package_name,
                    "filename": file_name,
                    "archive_path": archive_path,
                    "error": "This file is too long to syntax highlight.",
                },
            )

    # Case 4: link to binary
    return templates.TemplateResponse(
        "package_file_archive_path_cannot_render.html",
        {
            "request": request,
            "package": package_name,
            "filename": file_name,
            "archive_path": archive_path,
            "error": "This file appears to be a binary.",
        },
    )
