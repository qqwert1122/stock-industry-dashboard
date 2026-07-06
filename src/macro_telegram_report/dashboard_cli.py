from __future__ import annotations

import argparse
import sys

import requests

from .config import load_config, load_dotenv
from .dashboard import build_dashboard_site


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="산업별 핵심 지표 데이터를 수집해 정적 웹 대시보드를 생성합니다."
    )
    parser.add_argument("--config", default="config.yaml", help="설정 YAML 경로")
    parser.add_argument("--out", default="site", help="생성할 정적 사이트 폴더")
    parser.add_argument(
        "--env-file",
        default=".env",
        help="로컬 실행 때 읽을 env 파일 경로. GitHub Actions에서는 보통 사용하지 않습니다.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_dotenv(args.env_file)
    config = load_config(args.config)

    with requests.Session() as session:
        session.headers.update({"User-Agent": "industry-dashboard/0.1 (+personal-investing)"})
        payload = build_dashboard_site(config, args.out, session)

    for source in payload.get("source_status", []):
        print(f"{source['name']}: {source['status']} - {source['message']}")
    print(f"{args.out}/index.html 생성 완료: 표시 지표 {len(payload['metrics'])}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
