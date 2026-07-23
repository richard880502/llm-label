FROM node:20-alpine AS frontend-builder
ENV TZ=Asia/Taipei
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ .
RUN npm run build

FROM python:3.12-slim
ENV TZ=Asia/Taipei
ENV PYTHONPATH=/app
ENV ANNOTATION_API_URL=http://127.0.0.1:8001
ENV MCP_TRANSPORT=streamable-http
ENV MCP_HOST=127.0.0.1
ENV MCP_PORT=8000
RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx supervisor tzdata \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt .
COPY mcp_server/requirements.txt ./mcp-requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r mcp-requirements.txt
COPY backend/ ./backend/
COPY mcp_server/server.py ./mcp_server/server.py
COPY scripts/ ./scripts/
COPY deploy/nginx.conf /etc/nginx/nginx.conf
COPY deploy/supervisord.conf /etc/supervisor/conf.d/annotation.conf
COPY --from=frontend-builder /app/static ./static/
EXPOSE 8080
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/annotation.conf"]
