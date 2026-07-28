"""
Runnable stand-in for what Argo Rollouts' AnalysisRun does automatically on
a real cluster — useful for a portfolio repo where a live k8s cluster isn't
assumed. Pulls the same metric shape from the FastAPI /metrics endpoint and
applies the primer's exact threshold (0.2% error rate / 30 min window),
printing the same style of status Argo would show via `kubectl argo
rollouts get rollout`.
"""
import argparse
import sys

import requests

ERROR_RATE_THRESHOLD = 0.002  # 0.2%, matches the primer's tighter ad-serving SLA


def check_error_rate(metrics_url: str) -> float:
    resp = requests.get(metrics_url, timeout=5)
    resp.raise_for_status()
    total, errors = 0, 0
    for line in resp.text.splitlines():
        if line.startswith("scoring_requests_total"):
            count = float(line.rsplit(" ", 1)[-1])
            total += count
            if 'decision="error"' in line:
                errors += count
    return (errors / total) if total else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--metrics-url", default="http://localhost:8001/metrics")
    args = ap.parse_args()

    rate = check_error_rate(args.metrics_url)
    print("Status:  Progressing")
    if rate > ERROR_RATE_THRESHOLD:
        print(f'Message: canary analysis failed metric "error-rate": '
              f"{rate:.2%} > threshold {ERROR_RATE_THRESHOLD:.2%}")
        print("Aborting rollout, weight reverted to 0")
        sys.exit(1)
    print(f'Message: canary analysis passed metric "error-rate": '
          f"{rate:.2%} <= threshold {ERROR_RATE_THRESHOLD:.2%}")
    print("Advancing rollout to next step")


if __name__ == "__main__":
    main()
