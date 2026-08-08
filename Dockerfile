

FROM python:3.11-slim
WORKDIR /app

COPY services/click_fraud/serving/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/click_fraud/serving/app.py ./app.py
COPY services/click_fraud/serving/model.txt ./model.txt

EXPOSE 7860
ENV MODEL_PATH=model.txt
CMD ["uvicorn", "services.click_fraud.serving.app:app", "--host", "0.0.0.0", "--port", "7860"]