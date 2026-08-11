"""
Click-windowing aggregator.

Consumes click events off SQS (batches of up to 10, per the event source
mapping in streaming.tf), computes a fixed tumbling 60s window per user,
and increments a counter in DynamoDB. This is a coarser guarantee than a
true sliding window -- documented in docs/decisions/0001, not hidden.

Expected SQS message body (JSON):
    {"user_id": "12345", "timestamp": 1723400000.0}

`timestamp` should be the click's event time (seconds since epoch). If
omitted, falls back to the time this Lambda processes the message, which
is fine for near-real-time ingestion but slightly wrong under SQS retry
delay -- acceptable for this use case, worth knowing if debugging counts
that look off by one window.
"""
import json
import os
import time

import boto3

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["TABLE_NAME"])

WINDOW_SECONDS = 60
TTL_BUFFER_SECONDS = 3600  # keep each window's row around for an hour after it closes


def handler(event, context):
    processed = 0
    for record in event.get("Records", []):
        body = json.loads(record["body"])
        user_id = str(body["user_id"])
        ts = float(body.get("timestamp", time.time()))
        window_start = int(ts // WINDOW_SECONDS) * WINDOW_SECONDS
        ttl = window_start + TTL_BUFFER_SECONDS

        table.update_item(
            Key={"user_id": user_id, "window_start": window_start},
            UpdateExpression="ADD click_count :inc SET #ttl = :ttl",
            ExpressionAttributeNames={"#ttl": "ttl"},
            ExpressionAttributeValues={":inc": 1, ":ttl": ttl},
        )
        processed += 1

    return {"statusCode": 200, "processed": processed}
