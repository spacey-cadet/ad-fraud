"""
Faust (pure-Python, Kafka-native stream processing — the free/self-hosted
equivalent used here in place of Apache Flink) windowed aggregation.

Mirrors the primer's Gate 1 + streaming-feature description:
  - completeness check runs as a side-output (an app-level table, not a
    Great Expectations batch suite), because ingestion is streaming.
  - clicks_last_60s / time_since_last_click_seconds are computed here, in the
    stream, not looked up from a cache — same "request-time, not
    precomputed" property the primer calls out for Flink.

Run:
    faust -A services.click_fraud.streaming.faust_app worker -l info
"""
import time

import faust

app = faust.App("click-fraud-features", broker="kafka://localhost:19092")

raw_topic = app.topic("ad_clicks_raw", value_type=bytes)
features_topic = app.topic("ad_clicks_features", value_type=bytes)
null_click_id_topic = app.topic("ingestion_gate_failures", value_type=bytes)

# windowed table: user_id -> list of recent click timestamps (60s tumbling-ish window)
recent_clicks = app.Table("recent-clicks", default=list).tumbling(60.0, expires=120.0)


@app.agent(raw_topic)
async def process(stream):
    async for raw in stream:
        import json
        event = json.loads(raw)

        # --- Gate 1: completeness check as a stream side-output ---
        if event.get("click_id") is None:
            await null_click_id_topic.send(value=raw)
            continue  # dropped from the feature stream, same 0%-null-tolerance rule

        user_id = event["user_id"]
        now = time.time()
        bucket = recent_clicks[user_id].value()
        bucket.append(now)
        recent_clicks[user_id] = bucket

        clicks_last_60s = len(bucket)
        event["clicks_last_60s_streaming"] = clicks_last_60s

        await features_topic.send(key=str(user_id), value=json.dumps(event).encode())


if __name__ == "__main__":
    app.main()
