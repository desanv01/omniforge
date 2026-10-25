# Dependency image only. Reviewed worker source/config and launch are a later gate.
# Accepted Linux CPython 3.11.15 bookworm image; no floating base tag.
FROM python@sha256:d29f48a31a8b408ed19272ca1e7b10ebae13b240a27e862d3d4217c528e2e0c3
LABEL omniforge.owner="OF-013-WORKER-LOCK"
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /opt/omniforge
COPY requirements.txt /opt/omniforge/requirements.txt
RUN python -m pip install --no-cache-dir --disable-pip-version-check --only-binary=:all: --require-hashes -r requirements.txt
USER 65532:65532
# No application, credential discovery, service connection or worker auto-start.
CMD ["python", "--version"]
