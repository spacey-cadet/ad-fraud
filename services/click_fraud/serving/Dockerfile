FROM python:3.11-slim
WORKDIR /app

COPY serving/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY serving/app.py ./app.py
COPY training/model.txt ./model.txt

EXPOSE 8001
ENV MODEL_PATH=model.txt
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001"]