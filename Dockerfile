# Build stage: keep the runtime image free of build tooling.
FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim AS runtime
RUN useradd --create-home --uid 10001 app
COPY --from=build /install /usr/local
WORKDIR /work
USER app
ENTRYPOINT ["schemasentry"]
CMD ["version"]
