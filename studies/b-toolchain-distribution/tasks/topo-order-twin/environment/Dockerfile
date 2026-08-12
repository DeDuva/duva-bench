FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends make \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pytest==8.3.3
WORKDIR /workspace
COPY fiz/ /workspace/fiz/
COPY hulor/ /workspace/hulor/
COPY mapufile /workspace/mapufile
COPY mapu /usr/local/bin/mapu
