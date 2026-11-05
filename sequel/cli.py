import argparse
import logging
import sys

from sequel.agent import ask


def main() -> int:
    parser = argparse.ArgumentParser(description="Ask the Sequel data analyst.")
    parser.add_argument("question", help="Natural-language question about the data")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        answer, sql = ask(args.question)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Answer: {answer}")
    print("SQL:")
    print(sql or "(no SQL used)")
    return 0
