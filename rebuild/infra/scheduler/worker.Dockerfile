ARG PYTHON_IMAGE
FROM ${PYTHON_IMAGE}
LABEL omniforge.owner="OF-013-A"
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt
WORKDIR /app
# Only the deterministic worker source is mounted read-only at runtime.
CMD ["python", "-m", "services.worker.scheduler_fixture"]
