FROM public.ecr.aws/docker/library/python:3.13
RUN apt-get update && apt-get install -y dumb-init && apt-get clean
ARG WHEEL
COPY "$WHEEL" /tmp/
USER nobody
RUN python -m venv /tmp/venv
RUN /tmp/venv/bin/pip install /tmp/*.whl uvicorn
VOLUME /cache
ENV PYPI_BROWSER_PACKAGE_CACHE_PATH=/cache
CMD ["/usr/bin/dumb-init", "/tmp/venv/bin/uvicorn", "--forwarded-allow-ips=*", "--host", "0.0.0.0", "pypi_browser.app:app"]
