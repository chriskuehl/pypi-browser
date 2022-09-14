import mimetypes
import os.path

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

    async def transfer_file():
        async with package.open_from_archive(archive_path) as f:
            data = None
            while data is None or len(data) > 0:
                data = await f.read(1024)
                yield data

    mimetype, _ = mimetypes.guess_type(archive_path)
    return StreamingResponse(
        transfer_file(),
        media_type=mimetype or "text/plain",
        headers={"Content-Length": str(entry.size)},
    )
