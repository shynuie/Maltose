"""Print the ModelScope pipeline's derived keyword class count."""

from __future__ import annotations

import argparse

import yaml

import pipeline


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    args = parser.parse_args()
    with open(args.config, encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    print(f"keywords={config.get('keywords')}")
    print(f"num_syn={pipeline.compute_num_syn(config)}")


if __name__ == "__main__":
    main()
