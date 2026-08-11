FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends make \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pytest==8.3.3
WORKDIR /workspace
COPY kelvra/ /workspace/kelvra/
COPY brivols/ /workspace/brivols/
COPY tomakfile /workspace/tomakfile
COPY tomak /usr/local/bin/tomak
