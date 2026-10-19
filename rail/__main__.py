"""Command line: python -m rail {load,watch}"""
import argparse
import logging

from rail import db, pipeline


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m rail")
    parser.add_argument("command", choices=["load", "watch"],
                        help="load: fetch and publish both datasets now. "
                             "watch: check hourly and load whenever USDA publishes new data.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    db.init()
    if args.command == "load":
        pipeline.load_all()
    else:
        pipeline.watch()


if __name__ == "__main__":
    main()
