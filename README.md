PyPI Browser
============

**PyPI Browser** is a web application for browsing the contents of packages on
[the Python Package Index](https://pypi.org/).

You can view a live version which provides information about packages from pypi.org:

* [Search page](https://pypi-browser.ckuehl.me/)
* [Package page for the `django` package](https://pypi-browser.ckuehl.me/package/django)
* [Archive browse page for the `Django-4.1.1-py3-none-any.whl` file](https://pypi-browser.ckuehl.me/package/django/Django-4.1.1-py3-none-any.whl)
* [File viewing page for a random file from the same archive](https://pypi-browser.ckuehl.me/package/django/Django-4.1.1-py3-none-any.whl/django/forms/boundfield.py)

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

Note that this is currently only supported for `.zip` and `.whl` files, but
support for tarballs is planned.


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


## Roadmap

* Add support for non-ZIP files (e.g. `.tar.gz` source distributions).

  This shouldn't be too hard, but it may be slow at runtime since unlike zip,
  tarballs don't contain an index or support extracting individual files
  without reading the entire tarball.
