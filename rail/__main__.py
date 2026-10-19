"""Command line: python -m rail {init,load,watch}"""
import argparse
import logging

from rail import db, pipeline


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m rail")
    parser.add_argument("command", choices=["init", "load", "watch"],
                        help="init: create tables and views only. load: fetch and publish both datasets now. "
                             "watch: check hourly and load whenever USDA publishes new data.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    db.init()
    if args.command == "load":
        pipeline.load_all()
    elif args.command == "watch":
        pipeline.watch()


if __name__ == "__main__":
    main()
