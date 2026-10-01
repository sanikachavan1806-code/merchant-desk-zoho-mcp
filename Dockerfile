FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

ENV ZOHO_MODE=demo
EXPOSE 8000
CMD ["merchantops", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8000"]
