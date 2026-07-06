from __future__ import annotations

import argparse
import sys

import requests

from .config import load_config, load_dotenv
from .report import build_report
from .telegram import send_telegram


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="FRED, WSTS, 한국 수출 데이터를 모아 텔레그램으로 전송합니다."
    )
    parser.add_argument("--config", default="config.yaml", help="설정 YAML 경로")
    parser.add_argument(
        "--env-file",
        default=".env",
        help="로컬 실행 때 읽을 env 파일 경로. GitHub Actions에서는 보통 사용하지 않습니다.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="텔레그램으로 보내지 않고 표준출력에만 리포트를 표시합니다.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_dotenv(args.env_file)
    config = load_config(args.config)

    with requests.Session() as session:
        session.headers.update({"User-Agent": "macro-telegram-report/0.1"})
        report = build_report(config, session)
        if args.dry_run:
            print(report)
            return 0
        send_telegram(report, session)
    return 0


if __name__ == "__main__":
    sys.exit(main())
