# core/shipping_config.py
# 배송비 규칙 — 진실의 원천은 여기.
#
# 요금: 타오바오 공식 집운-해운(集运-海运, 경제형) 한국행, "식품·민감 화물(食品敏货)" 0~30kg
#   확인일 2026-10-20 — 타오바오 상품 상세(배송지 한국) › 集运-海运 › 查看计费规则
#   https://world.taobao.com/wow/z/oversea/rule-guide/hFXyydtteWSdFtTPjENn
#   - 첫 1kg 33위안, 넘는 무게는 0.5kg 마다 2위안
#   - 1kg 미만도 1kg, 넘는 무게는 0.5kg 단위로 올림
#   - 실제 무게와 부피 무게 중 큰 값 — 부피 무게는 아직 반영하지 않는다 (음료는 실제 무게가 더 크다)
#   - 소형 한도 30kg (한 변 100cm, 세 변 합 180cm). 넘으면 이 요금표로 보낼 수 없다
#   - 관세·부가세는 포함되지 않음
#   음료가 주력이라 식품 요금으로 고정한다 (2026-10-20 사용자 결정)
#
# 무게: 용량(ml) × 1g + 박스 500g (2026-10-20 사용자 지정). 용량은 옵션 이름에서 읽는다 (utils/volume.py)

from decimal import Decimal

SHIPPING_SERVICE_LABEL = "타오바오 집운-해운"
SHIPPING_CATEGORY_LABEL = "식품"

SHIPPING_FIRST_KG = Decimal("1")       # 첫 무게 (kg)
SHIPPING_FIRST_CNY = Decimal("33")     # 첫 무게 요금 (위안)
SHIPPING_STEP_KG = Decimal("0.5")      # 추가 무게 단위 (kg)
SHIPPING_STEP_CNY = Decimal("2")       # 추가 단위당 요금 (위안)
SHIPPING_MAX_KG = Decimal("30")        # 소형 한도 (kg)

BOX_WEIGHT_G = 500                     # 박스 무게 (g)
G_PER_ML = 1                           # 음료 1ml = 1g 으로 본다
