import os.path

from starlette.applications import Starlette
from starlette.staticfiles import StaticFiles
from starlette.requests import Request
from starlette.routing import Route
from starlette.templating import Jinja2Templates


install_root = os.path.dirname(__file__)

app = Starlette(debug=os.environ.get("PYPI_VIEW_DEBUG") == "1")
app.mount('/static', StaticFiles(directory=os.path.join(install_root, 'static')), name='static')

templates = Jinja2Templates(
    directory=os.path.join(install_root, "templates"),
)


@app.route('/')
async def home(request: Request) -> templates.TemplateResponse:
    return templates.TemplateResponse("home.html", {"request": request})
