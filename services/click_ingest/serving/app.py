"""
Click ingestion endpoint.

Validates incoming click events and publishes them to the ad-clicks-queue
SQS queue. Deliberately decoupled from scoring -- mirrors the separation
the local Redpanda producer/serving split already has (producer.py is a
separate process from app.py), just expressed as its own Lambda + Function
URL instead of a separate process on the same host.

This has no local/docker-compose equivalent by design -- the local branch
publishes to Redpanda via producer.py, this is the AWS-native counterpart
and only runs on the aws-serverless branch.
"""
import os
import time

import boto3
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

QUEUE_URL = os.environ["QUEUE_URL"]

app = FastAPI(title="click-ingest")
sqs = boto3.client("sqs")


class ClickIngestEvent(BaseModel):
    user_id: str
    # Defaults to ingestion time if the caller doesn't supply one -- fine
    # for near-real-time ingestion, but pass an explicit timestamp if
    # replaying historical events, or every event will land in "now"'s
    # window regardless of when it actually happened.
    timestamp: float = Field(default_factory=time.time)


@app.post("/ingest")
def ingest(event: ClickIngestEvent):
    try:
        sqs.send_message(QueueUrl=QUEUE_URL, MessageBody=event.model_dump_json())
    except Exception as exc:
        # 502, not 500: the validation succeeded, publishing to the
        # downstream queue is what failed -- worth distinguishing in
        # logs/alarms from a bad request.
        raise HTTPException(status_code=502, detail=f"failed to publish to queue: {exc}")
    return {"status": "queued", "user_id": event.user_id, "timestamp": event.timestamp}


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


from mangum import Mangum  # noqa: E402
handler = Mangum(app)
