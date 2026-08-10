FROM python:3.12-slim

WORKDIR /app

# No network at trial time: an agent that can pip-install its way out is an
# agent solving a different task than the one the arm was given.
ENV PIP_NO_INDEX=1
