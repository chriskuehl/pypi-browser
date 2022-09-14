import os.path

from starlette.applications import Starlette
from starlette.staticfiles import StaticFiles
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from pypi_view import pypi


install_root = os.path.dirname(__file__)

app = Starlette(debug=os.environ.get("PYPI_VIEW_DEBUG") == "1")
app.mount('/static', StaticFiles(directory=os.path.join(install_root, 'static')), name='static')

templates = Jinja2Templates(
    directory=os.path.join(install_root, "templates"),
)


@app.route('/')
async def home(request: Request) -> templates.TemplateResponse:
    return templates.TemplateResponse("home.html", {"request": request})


@app.route('/package/{package}')
async def package(request: Request) -> templates.TemplateResponse:
    package = request.path_params["package"]
    version_to_files = await pypi.files_for_package(package)
    return templates.TemplateResponse(
        "package.html",
        {
            "request": request,
            "package": package,
            "version_to_files": version_to_files,
        },
    )


@app.route('/package/{package}/{filename}')
async def package_file(request: Request) -> templates.TemplateResponse:
    package = request.path_params["package"]
    filename = request.path_params["filename"]
    archive = await pypi.downloaded_file_path(package, filename)
    return PlainTextResponse(
        f"Path: {archive} Size: {os.stat(archive)}",
    )


@app.route('/package/{package}/{filename}/{archive_path:path}')
async def package_file_archive_path(request: Request) -> templates.TemplateResponse:
    print(request.path_params["package"])
    print(request.path_params["filename"])
    print(request.path_params["archive_path"])
    raise NotImplementedError()
