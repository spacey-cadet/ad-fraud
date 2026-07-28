"""
Gate 3 (serving) — statistical drift check, free/open-source via whylogs.

Same discipline the primer insists on: report magnitude (KS statistic) *and*
significance (p-value) together, and don't hard-code a "this p-value always
means drift" cutoff — a small p-value with a small statistic on a huge
sample is not the same finding as a large statistic.

Run:
    python drift_check.py --reference ref.parquet --current current.parquet --column clicks_last_60s
"""
import argparse

import pandas as pd
import whylogs as why
from scipy.stats import ks_2samp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference", required=True)
    ap.add_argument("--current", required=True)
    ap.add_argument("--column", required=True)
    args = ap.parse_args()

    ref = pd.read_parquet(args.reference)
    cur = pd.read_parquet(args.current)

    # whylogs profiles: cheap, mergeable statistical summaries suitable for
    # streaming or batch, free and self-hosted (no Whylabs account needed).
    ref_profile = why.log(ref).view()
    cur_profile = why.log(cur).view()
    ref_profile.write(f"profiles/reference_{args.column}.bin")
    cur_profile.write(f"profiles/current_{args.column}.bin")

    stat, p_value = ks_2samp(ref[args.column].dropna(), cur[args.column].dropna())

    print(f"column: {args.column}")
    print(f"KS statistic: {stat:.3f}  p-value: {p_value:.4f}")

    if p_value < 0.05 and stat > 0.1:
        print("ACTIONABLE: both magnitude and significance indicate real drift.")
    elif p_value < 0.05 and stat <= 0.1:
        print("NOT ACTIONABLE ALONE: statistically significant but small effect size "
              "— likely just a large-sample artifact. Watch, don't page.")
    else:
        print("No evidence of drift.")


if __name__ == "__main__":
    main()
