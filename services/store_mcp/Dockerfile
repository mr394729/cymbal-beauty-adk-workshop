FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY services/store_mcp/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY agents /app/agents
COPY services/store_mcp /app/services/store_mcp
RUN useradd --uid 10001 --create-home appuser
USER 10001
EXPOSE 8080
CMD ["python", "-m", "services.store_mcp.server"]
