        FROM python:3.12-slim

        RUN pip install --no-cache-dir pytest==8.3.3
        WORKDIR /workspace
        COPY src/ /workspace/src/
COPY tests/ /workspace/tests/
COPY Makefile /workspace/Makefile

