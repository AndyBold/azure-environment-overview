FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY overview overview
COPY checker checker
COPY queries queries
USER 65532:65532
ENTRYPOINT ["python", "-m", "checker.main"]
