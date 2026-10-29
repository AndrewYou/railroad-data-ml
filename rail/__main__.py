"""Command line: python -m rail {init,load,backfill,refresh,watch}"""
import argparse
import logging

from rail import db, pipeline


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m rail")
    parser.add_argument("command", choices=["init", "load", "backfill", "refresh", "watch"],
                        help="init: create tables and views only. load: refresh the last five years now. "
                             "backfill: load the full history from 2017 (the first load does this). "
                             "refresh: load only if USDA has published new data (one watch cycle). "
                             "watch: check hourly and load whenever USDA publishes new data.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    db.init()
    if args.command == "load":
        pipeline.load_all()
    elif args.command == "backfill":
        pipeline.load_all(pipeline.HISTORY_START)
    elif args.command == "refresh":
        pipeline.refresh()
    elif args.command == "watch":
        pipeline.watch()


if __name__ == "__main__":
    main()
