"""제품 분류 — 자사몰 메뉴와 AGC 제품 화면이 같은 값을 쓴다 (2026-10-29 사용자: DB 에서 나누고 자사몰은 그걸 따른다).

대분류 category = 어떻게 마시는가
  beverage(음료) : 따서 바로 마시는 완제품 (병·캔·팩·컵)
  tea(차)        : 물에 우려 마시는 차 (찻잎·티백 …) — 티백은 '형태'라 대분류가 아니다 (같은 우롱이 찻잎·티백 둘 다 나온다)
소분류 subcategory = 대분류마다 정해진 값만
형태 tea_form = 차(tea)만 · 음료는 비움

코드는 영문 고정 — 화면 이름은 바꿔도 되지만 코드를 바꾸면 자사몰 주소(/products?cat=…)가 깨진다.
경계 규칙: 탄산이 들어간 차·요구르트맛 탄산은 soda (마셨을 때 탄산이 먼저), 과즙차(果汁茶)는 tea,
           코코넛워터는 functional, 코코넛밀크는 milk, 꿀레몬수·식초 음료는 juice, 쏸메이탕·녹두탕·크바스는 traditional.
"""

CATEGORIES: dict[str, dict] = {
    "beverage": {
        "label": "음료",
        "sub": {
            "soda": "탄산",
            "juice": "주스",
            "tea": "차음료",
            "milktea": "밀크티",
            "coffee": "커피",
            "milk": "우유·두유",
            "functional": "이온·기능성",
            "traditional": "전통음료",
        },
    },
    "tea": {
        "label": "차",
        "sub": {
            "green": "녹차",
            "black": "홍차",
            "oolong": "우롱·암차",
            "white": "백차",
            "puer": "보이·흑차",
            "flower": "꽃차",
            "blend": "블렌드·과일차",
        },
        "forms": {
            "leaf": "찻잎",
            "bag": "티백",
            "coldbrew": "냉침 티백",
            "powder": "가루",
        },
    },
}

DEFAULT_CATEGORY = "beverage"


def check_category(category: str | None, subcategory: str | None, tea_form: str | None = None) -> None:
    """맞지 않으면 ValueError."""
    if category is not None and category not in CATEGORIES:
        raise ValueError(f"대분류는 {', '.join(CATEGORIES)} 중 하나입니다.")
    if subcategory is not None and category is not None and subcategory not in CATEGORIES[category]["sub"]:
        raise ValueError(f"'{category}' 소분류는 {', '.join(CATEGORIES[category]['sub'])} 중 하나입니다.")
    if tea_form is not None:
        if category is not None and category != "tea":
            raise ValueError("형태(tea_form)는 차(tea)만 씁니다.")
        if tea_form not in CATEGORIES["tea"]["forms"]:
            raise ValueError(f"형태는 {', '.join(CATEGORIES['tea']['forms'])} 중 하나입니다.")