"""
Publishes synthetic ad-click events to Redpanda (Kafka-API-compatible, free,
single-binary — the OSS stand-in for a managed Kafka cluster). This plays
the role of the raw event stream that would, in the interview-doc version,
feed a Flink job.
"""
import argparse
import json
import time

import pandas as pd
from confluent_kafka import Producer

TOPIC = "ad_clicks_raw"


def delivery_report(err, msg):
    if err is not None:
        print(f"delivery failed: {err}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--brokers", default="localhost:19092")
    p.add_argument("--source", default="../../../data/raw/ad_clicks.parquet")
    p.add_argument("--rate", type=float, default=500, help="events/sec")
    args = p.parse_args()

    producer = Producer({"bootstrap.servers": args.brokers})
    df = pd.read_parquet(args.source)

    sleep_s = 1.0 / args.rate
    for _, row in df.iterrows():
        event = row.to_dict()
        event["event_ts"] = str(event["event_ts"])
        producer.produce(TOPIC, json.dumps(event, default=str).encode("utf-8"),
                          callback=delivery_report)
        producer.poll(0)
        time.sleep(sleep_s)
    producer.flush()


if __name__ == "__main__":
    main()
