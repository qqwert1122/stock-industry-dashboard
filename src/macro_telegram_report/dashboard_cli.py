from __future__ import annotations

import argparse
import sys

from .config import load_config, load_dotenv
from .dashboard import build_dashboard_site, refresh_briefing_site, refresh_prices_site
from .http_client import build_session


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
    parser.add_argument(
        "--prices-only",
        action="store_true",
        help="대표주/시장지수 시세만 갱신하는 경량 빌드(장중 갱신용).",
    )
    parser.add_argument(
        "--briefing-only",
        choices=["intraday", "close", "us_close"],
        help="기존 dashboard.json을 기반으로 AI/룰 기반 브리핑 카드만 추가 생성합니다.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_dotenv(args.env_file)
    config = load_config(args.config)

    with build_session() as session:
        if args.prices_only and args.briefing_only:
            raise SystemExit("--prices-only와 --briefing-only는 함께 사용할 수 없습니다.")
        if args.briefing_only:
            payload = refresh_briefing_site(config, args.out, session, args.briefing_only)
        elif args.prices_only:
            payload = refresh_prices_site(config, args.out, session)
        else:
            payload = build_dashboard_site(config, args.out, session)

    for source in payload.get("source_status", []):
        print(f"{source['name']}: {source['status']} - {source['message']}")
    print(f"{args.out}/index.html 생성 완료: 표시 지표 {len(payload['metrics'])}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
