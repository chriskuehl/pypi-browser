from pypi_browser import app


def test_app_smoketest():
    assert app.app is not None
