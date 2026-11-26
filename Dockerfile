FROM python:3.11-slim
RUN apt-get update && apt-get install -y ffmpeg fonts-nanum libsm6 libxext6 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8502 8503
CMD ["sh", "-c", "uvicorn api_server:app --host 0.0.0.0 --port 8503 & exec streamlit run app.py --server.port=8502 --server.address=0.0.0.0"]
