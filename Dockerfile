FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY .streamlit .streamlit
COPY rail rail
COPY sql sql
COPY dashboard dashboard
COPY tests tests
CMD ["python", "-m", "rail", "watch"]
