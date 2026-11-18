# 마켓 상품 등록 도구 (쿠팡 · 네이버)

2026-11-18: 컨테이너 /tmp 에 있던 스크립트를 저장소로 옮겼어요. 컨테이너를 다시 띄워도 사라지지 않아요.
상태·로그 파일은 `/private/market` (PC 의 `BE/private/market`) 에 남아요.

**기본은 연습이에요.** 등록 내용만 만들어 `/private/market/*.json`·로그에 남기고, 실제 등록은 `--apply` 를 붙일 때만 해요.

```
docker exec -w /app agc_app python -m scripts.market.upload coupang 448 449              # 쿠팡 연습
docker exec -w /app agc_app python -m scripts.market.upload coupang 448 449 --apply      # 쿠팡 실제 등록
docker exec -w /app agc_app python -m scripts.market.upload coupang 451 --snack --apply  # 과자 (규격 파서 · 과자 카테고리)
docker exec -w /app agc_app python -m scripts.market.upload naver 43 --apply             # 네이버 그룹 등록 (음료·차)
docker exec -w /app agc_app python -m scripts.market.upload naver 450 --snack --apply    # 네이버 과자 그룹
docker exec -w /app agc_app python -m scripts.market.upload coupang 24 --add-flavor --apply   # 이미 올린 제품에 새 맛만
docker exec -w /app agc_app python -m scripts.market.upload naver 24 --add-flavor --apply     # 〃 (기존 그룹·상품 안 지움)
docker exec -w /app agc_app python -m scripts.market.upload record                       # 쿠팡 등록분 → market_listing
docker exec -w /app agc_app python -m scripts.market.upload resubmit <spid> --apply      # 쿠팡 승인 재요청
```

## 파일

| 파일 | 하는 일 |
|---|---|
| `upload.py` | 한 줄 실행 입구 (연습/실제, 스크립트 고르기) |
| `cp_base.py` | 쿠팡 공통 (payload · 카테고리 예측 · 고시 · 옵션 읽기, `BRAND_IDS`) |
| `cp_new.py` | 쿠팡 신상품 (사진 500px 확인 · 태그 · 바코드 · 이미 올린 제품 건너뛰기 · `--add-flavor`) |
| `snack_cp.py` | 쿠팡 과자 (`parse_spec` · 상품명 규격 제거 · 과자 태그 · 제품별 카테고리) |
| `nv_base.py` · `nv_new.py` | 네이버 공통 (토큰 · 이미지 업로드 · 고시 · 카테고리 맵) |
| `nv_group.py` | 네이버 그룹상품 등록 (`--migrate` = 실제), 예전 개별 상품 지우고 market_listing 기록 |
| `snack_nv.py` | 네이버 과자 그룹 (`CATBY_PID` 과자 카테고리 맵 · 상품명 오버라이드) |
| `cp_record.py` | `cp_done.txt` 의 쿠팡 등록분을 seller-product 조회로 market_listing 에 기록 |
| `cpresub.py` | 쿠팡 상품 승인 재요청 |
| `cp_template.json` | 쿠팡 배송·반품지·업체 정보 틀 (판매자상품 16425945667 에서 뽑음) |
| `nv_catmap.json` | 네이버 음료 제품 코드 → 카테고리 |

## 규칙 (반영돼 있음)

- 옵션은 `product_option` (migration 46). 지운 옵션(`deleted_at`)은 안 올려요.
- 쿠팡 브랜드: 공식 브랜드(`BRAND_IDS`: 미닛메이드 · 코카콜라 · 스타벅스 · 북빙양 · 농부산천 KR-69617 · 오리온 KR-68537)는 바코드 없는 옵션을 빼고 올려요. 같은 바코드를 쓰는 옵션(12병·15병 등)은 첫 옵션만 바코드, 나머지는 emptyBarcode.
- 네이버 그룹 등록은 **한 번만 POST** 해요. 보낸 요청 id 는 `/private/market/nv_pending.txt` 에 남기고, 결과(COMPLETED)를 본 뒤에만 기록해요. 결과를 못 받으면(TIMEOUT) 다음 실행 때 다시 POST 하지 않고 그 요청의 상태만 봐요 (11-17 중복 그룹 9개 사고 재발 방지).
- `--add-flavor`: 이미 등록 기록(market_listing)에 있는 sku 는 빼고 새 옵션만 올려요. 네이버는 새 옵션만 담은 그룹을 하나 더 만들고, 기존 그룹·상품은 지우지 않아요. (연습 실행에서는 네이버 필터가 아직 적용되지 않아요 — 실제 실행 경로에만 있음.)
- 진행 기록: `cp_done.txt`(쿠팡) · `grp_migrated.txt`(네이버 그룹) · `nv_pending.txt` — 모두 `/private/market`.

## 이미 올린 상품에 묶음(2배수 등) 옵션 추가 (2026-11-18 오리온 452~454)

새 상품을 만들면 쿠팡이 'GTIN 중복 — 기존 상품에 추가하라'고 거절해요. 그래서 기존 상품에 옵션을 붙여요. 먼저 option_price 에 bundle_qty=2 판매가를 넣어 두세요 (1배수 이익 유지 + 묶음 배송비).

- 쿠팡: `docker exec -w /app -e PYTHONPATH=/app agc_app python scripts/market/cp_add_bundle.py [spid]` — 기존 seller-product 를 GET 해서 x2 아이템(이름 숫자 ×2 · emptyBarcode · GTIN 속성 유지)을 붙여 PUT. 승인완료 그대로 유지됨. 끝나면 `ListingService.sync_coupang(full=True)`. (제품 id 452~454 고정 — 다른 제품은 스크립트의 id 목록을 바꿔요)
- 네이버: `python scripts/market/nv_add_bundle.py <그룹번호,…> [--apply]` — 그룹 GET → 새 specificProduct(수량 값 ×2, valueOrder 는 값마다 하나씩 새 번호) 붙여 PUT. 그룹 수정은 한 번에 하나만(ALREADY_RESERVED). 결과는 `/v2/standard-group-products/status?type=UPDATE&requestId=` 의 productNos 로 채널 상품번호를 얻어 market_listing 에 기록.
