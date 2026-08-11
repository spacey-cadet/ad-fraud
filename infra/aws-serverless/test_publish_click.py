"""
Manual test: publish one click event to the ad-clicks-queue and print
the DynamoDB item that should appear once the aggregator processes it.

This is NOT a production event source -- nothing currently publishes real
click events to this queue. Use this only to confirm the SQS -> aggregator
-> DynamoDB pipeline actually works end to end (open item #2 from the
checklist), then decide separately where real click events should
originate from before relying on this in production.

Usage:
    python test_publish_click.py --user-id 12345
"""
import argparse
import json
import time

import boto3

QUEUE_NAME = "ad-clicks-queue"
TABLE_NAME = "click-windows"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--user-id", default="test-user-1")
    p.add_argument("--region", default="us-east-1")
    args = p.parse_args()

    sqs = boto3.client("sqs", region_name=args.region)
    queue_url = sqs.get_queue_url(QueueName=QUEUE_NAME)["QueueUrl"]

    ts = time.time()
    body = {"user_id": args.user_id, "timestamp": ts}
    sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(body))
    print(f"Sent test click for user_id={args.user_id} at ts={ts}")

    window_start = int(ts // 60) * 60
    print("Waiting 10s for the aggregator Lambda to process it...")
    time.sleep(10)

    table = boto3.resource("dynamodb", region_name=args.region).Table(TABLE_NAME)
    resp = table.get_item(Key={"user_id": args.user_id, "window_start": window_start})
    item = resp.get("Item")
    if item:
        print(f"Confirmed: {item}")
    else:
        print(
            "No item found yet -- check CloudWatch Logs for the "
            "click-windowing-aggregator function to see if it errored."
        )


if __name__ == "__main__":
    main()
