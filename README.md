PyPI Browser
============

**PyPI Browser** is a web application for browsing the contents of packages on
[the Python Package Index](https://pypi.org/).

You can view a live version which provides information about packages from pypi.org:

* [Search page](https://pypi-browser.org/)
* [Package page for the `django` package](https://pypi-browser.org/package/django)
* [Archive browse page for the `Django-4.1.1-py3-none-any.whl` file](https://pypi-browser.org/package/django/Django-4.1.1-py3-none-any.whl)
* [File viewing page for a random file from the same archive](https://pypi-browser.org/package/django/Django-4.1.1-py3-none-any.whl/django/forms/boundfield.py)

It can also be deployed with a private PyPI registry as its target in order to
be used for a company's internal registry.


## Features

![Search page](https://i.fluffy.cc/0lzgf46zcHZs90BZfMKp7cvspnk7QrZk.png)


### Browse uploaded package archives

![Browse uploaded archives](https://i.fluffy.cc/MnRscjgHrVw7DfnsrM3DV2rVQBB3SGNw.png)

You can see all uploaded package archives for a given package.


### Inspect package archive metadata and contents

![Inspect package archives](https://i.fluffy.cc/skXvnlvvhP8NwSN7RrjHBKrV1xMxKzqv.png)

You can inspect a package archive's metadata and its contents.


### Easily view files from package archives

![View file](https://i.fluffy.cc/6hp4VQmDF4pF6l54QWMfwjXdTpVGk27m.png)

You can display text files directly in your browser, with syntax highlighting
and other features like line selection provided by
[fluffy-code](https://github.com/chriskuehl/fluffy-code).

Binary files can also be downloaded.


## Deploying PyPI Browser

To run your own copy, install
[`pypi-browser-webapp`](https://pypi.org/project/pypi-browser-webapp/) using
pip, then run the `pypi_browser.app:app` ASGI application using any ASGI web
server (e.g. uvicorn).

You can set these environment variables to configure the server:

* `PYPI_BROWSER_PYPI_URL`: URL for the PyPI server to use (defaults to
  `https://pypi.org`)

  If your registry supports the pypi.org-compatible JSON API (e.g.
  `{registry}/pypi/{package}/json`), specify your base registry URL without
  appending `/simple` (e.g. `https://my-registry`).

  If your registry only supports the traditional HTML "simple" index, specify
  the registry URL with `/simple` at the end (e.g.
  `https://my-registry/simple`).

  Note that the [PEP691][pep691] JSON-based "simple" API is not yet supported.

* `PYPI_BROWSER_PACKAGE_CACHE_PATH`: Filesystem path to use for caching
  downloaded files. This will grow forever (the app does not clean it up) so
  you may want to use `tmpreaper` or similar to manage its size.

pypi-browser is an ASGI app, and while it performs a lot of I/O (downloading and
extracting packages on-demand), some effort has been made to keep all blocking
operations off of the main thread. It should be fairly performant.


## Contributing

To build this project locally, you'll need to [install
Poetry](https://python-poetry.org/docs/) and run `poetry install`.

Once installed, you can run

```bash
$ make start-dev
```

to run a copy of the application locally with hot reloading enabled.

[pep691]: https://peps.python.org/pep-0691/
