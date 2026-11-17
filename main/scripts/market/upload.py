"""마켓 상품 등록 도구 — 한 줄 실행 (2026-11-18, /tmp 에 있던 스크립트를 저장소로 옮김).

기본은 연습(--dry): 등록 내용(payload)만 만들고 로그·JSON 을 /private/market 에 남긴다. 실제 등록은 --apply 를 붙일 때만.
  docker exec -w /app agc_app python -m scripts.market.upload coupang 448 449            # 연습
  docker exec -w /app agc_app python -m scripts.market.upload coupang 448 449 --apply    # 실제 등록
  docker exec -w /app agc_app python -m scripts.market.upload naver 448 --snack --apply  # 과자 네이버 그룹
  docker exec -w /app agc_app python -m scripts.market.upload coupang 24 --add-flavor --apply   # 새 맛만 추가
  docker exec -w /app agc_app python -m scripts.market.upload record                     # 쿠팡 등록분 → market_listing
  docker exec -w /app agc_app python -m scripts.market.upload resubmit 16433993495        # 쿠팡 승인 재요청

명령: coupang · naver · record · resubmit. 옵션: --snack (과자 규격·카테고리) · --add-flavor (기존 상품 그대로, 새 옵션만) · --apply.
상태 파일(cp_done.txt · grp_migrated.txt · nv_pending.txt)과 로그는 /private/market (BE/private/market) — 컨테이너를 다시 띄워도 남는다."""

import os
import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = Path("/private/market")
SCRIPTS = {
    ("coupang", False): "cp_new.py",
    ("coupang", True): "snack_cp.py",
    ("naver", False): "nv_group.py",
    ("naver", True): "snack_nv.py",
}


def main(argv: list[str]) -> None:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return
    cmd, rest = argv[0], argv[1:]
    STATE.mkdir(parents=True, exist_ok=True)
    # 다른 스크립트가 읽는 로그·상태 파일 — 없으면 만들어 둔다 (첫 실행)
    for name in ("cp_create.log", "cp_new.log", "cp_done.txt", "nv_done.txt", "nv_new_done.txt"):
        (STATE / name).touch(exist_ok=True)
    apply = "--apply" in rest
    snack = "--snack" in rest
    flags = [a for a in rest if a == "--add-flavor"]
    ids = [a for a in rest if a.isdigit()]
    if cmd in ("coupang", "naver"):
        if not ids:
            sys.exit("제품 id 를 적어 주세요 (예: coupang 448 449)")
        script = SCRIPTS[(cmd, snack)]
        if cmd == "naver" and not snack:
            mode = ["--migrate"] if apply else ["--dry"]   # nv_group: --migrate = 실제 그룹 등록
        else:
            mode = [] if apply else ["--dry"]
        sys.argv = [script] + mode + flags + ids
    elif cmd == "record":
        script = "cp_record.py"
        sys.argv = [script]
    elif cmd == "resubmit":
        if not apply and "--yes" not in rest:
            print("resubmit 은 쿠팡에 승인 요청을 다시 보냅니다. --apply 를 붙여 주세요.")
            return
        script = "cpresub.py"
        sys.argv = [script] + ids
    else:
        sys.exit(f"알 수 없는 명령: {cmd} (coupang · naver · record · resubmit)")
    print(f"[market] {script} {' '.join(sys.argv[1:])} {'(실제 등록)' if apply else '(연습)'}")
    os.chdir("/app")
    runpy.run_path(str(HERE / script), run_name="__main__")


if __name__ == "__main__":
    main(sys.argv[1:])
