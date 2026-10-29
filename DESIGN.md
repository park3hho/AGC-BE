# AGC Backend 설계 문서

> 참조: `ParadayDynamics/MES_BE` (FD MES 백엔드) — 기술 스택·레이어 구조·규칙을 그대로 가져오고,
> MES_BE 운영 중 드러난 문제점은 처음부터 고쳐서 시작한다.
> 작성: 2026-10-18 · 상태: 초안 (도메인 모델은 미정)

---

## 1. 기술 스택

| 구분 | 선택 | AGC 버전 (고정) | MES_BE | 비고 |
|---|---|---|---|---|
| 언어 | Python | 3.14 (`python:3.14-slim`, 3.14.8) | 3.11 | 3.15 는 출시 직후라 라이브러리 호환 대기 |
| 웹 프레임워크 | FastAPI | 0.144.0 | 0.109.0 | 비동기 라우터 |
| ASGI 서버 | uvicorn[standard] | 0.54.0 | 0.27.0 | dev 는 `--reload` |
| ORM | Tortoise ORM | 1.1.9 | 0.25.4 | 1.x — FastAPI 연동은 `RegisterTortoise` (§4.6) |
| DB 드라이버 | asyncpg | 0.32.0 | 0.31.0 | |
| DB | PostgreSQL | 16 (`postgres:16-alpine`, 16.15) | 16 | Docker Compose |
| 마이그레이션 | Aerich | 0.10.1 | 0.9.2 | 파일이 유일한 스키마 변경 경로 |
| 캐시 | Redis | 미도입 | 7 | MES_BE 는 컨테이너만 있고 클라이언트 미사용 — 필요할 때 도입 |
| 세션 | Starlette `SessionMiddleware` | (FastAPI 동반) | — | `itsdangerous` 서명 쿠키 |
| 비밀번호 | bcrypt | 5.0.0 | — | 로그인 비밀번호 해시 (72바이트 한계 — 스키마에서 막음) |
| 비밀값 암호화 | cryptography (`Fernet`) | 50.0.2 | — | 회사 계정 비밀번호는 다시 꺼내 봐야 해서 해시가 아닌 **복호화 가능한 암호화**가 필요. 직접 AES 를 조립하지 않고 검증된 Fernet(AES-CBC + HMAC) 사용. 키는 `ACCOUNT_SECRET_KEY` |
| 린터 | ruff | — | — | line 120, `E F I W` |
| 컨테이너 | Docker + Docker Compose | Docker 29.8 | — | |

**선택 의존성 (기능이 생길 때만):** `openpyxl`(엑셀), `boto3`(S3), `httpx`(외부 API), `python-multipart`(파일 업로드), `websockets`(실시간).

> 버전은 2026-10-18 `python:3.14-slim` 에서 설치를 확인한 값으로 `requirements.txt` 에 **정확히 고정**(`==`)했다.
> MES_BE 처럼 일부만 고정하고 나머지를 열어두면 빌드마다 버전이 달라진다.

---

## 2. 폴더 구조

```
BE/
├── main/                     # ★ 컨테이너 WORKDIR — import 는 이 폴더 기준
│   ├── main.py               # FastAPI 진입점 (lifespan, 미들웨어, 라우터 등록)
│   ├── database.py           # TORTOISE_ORM 설정 (모델 모듈 목록)
│   ├── pyproject.toml        # aerich + ruff 설정
│   ├── core/                 # 공통 관심사 (cross-cutting)
│   │   ├── config.py         #   미들웨어 (CORS, Session) + 경로 상수
│   │   ├── auth_deps.py      #   require_auth / require_feature / require_role
│   │   ├── permissions.py    #   Role · Feature enum + ROLE_FEATURES (FE permissions.js 와 동기)
│   │   ├── session.py        #   SessionMiddleware (로그인 유지 안 하면 브라우저 세션 쿠키)
│   │   ├── account_crypto.py #   회사 계정 비밀번호 Fernet 암호화/복호화
│   │   ├── response_utils.py #   success() / success_only()
│   │   └── {domain}_config.py#   도메인 상수 (상태값 등) — 진실의 원천
│   ├── models/               # Tortoise 모델 — 도메인별 하위 폴더
│   │   ├── base.py           #   BaseModel (id, created_at, updated_at)
│   │   └── {domain}/
│   ├── schemas/              # Pydantic 요청·응답 — 라우터와 1:1
│   ├── routers/              # HTTP 계층 — 얇게 (검증 → 서비스 호출 → 응답)
│   ├── services/             # 비즈니스 로직 — 도메인별 하위 폴더
│   │   └── {domain}/
│   ├── utils/                # 순수 헬퍼 (날짜, 시퀀스, 검증)
│   ├── scripts/              # 1회성 운영 스크립트
│   └── migrations/           # Aerich 생성물 (수정 금지)
├── Dockerfile
├── docker-compose.yml        # app + postgres + (redis)
├── requirements.txt
├── .dockerignore
├── .env                      # 커밋 금지
├── CLAUDE.md                 # 개발 가이드 (how-to)
└── DESIGN.md                 # 이 문서
```

**MES_BE 대비 변경점**

| MES_BE | AGC | 이유 |
|---|---|---|
| 라우터마다 `prefix` 를 붙였다 말았다 (`include_router` 50여 줄) | 라우터 파일 안에서 `APIRouter(prefix=..., tags=...)` 선언, `main.py` 는 등록만 | 경로 정의가 두 곳에 흩어짐 |
| 서비스 일부 평면 파일 (`services/model_registry_service.py`) | 서비스는 **반드시** `services/{domain}/` | 이동 예정 메모만 남고 방치됨 |
| 모델이 운영 중 3분해 이관 (`model_registry` DEPRECATED) | 설계 정체성 / 검사 기준 / 실행 기록을 **처음부터 분리**한 테이블로 | 한 테이블에 성격 다른 속성이 섞여 이관 비용 발생 |
| 응답 `{"status": "success", ...}` 직접 작성 101곳 | 처음부터 `success()` 헬퍼만 사용 | 형식 통일 |
| API 문서 기본 비공개 (`ENABLE_DOCS`) | 동일하게 유지 | 운영에서 엔드포인트 지도 노출 방지 |
| EC2 에서 Docker Compose 운영 | **이 PC (Windows 11 + Docker Desktop)** 에서 Docker Compose 운영 | 고도화 단계에서 로컬 BE 가 필요하므로 처음부터 이 PC 에서 운영. 구성은 동일 (§7) |
---

## 3. 레이어 책임

```
요청 → routers (인증·스키마 검증) → services (비즈니스 로직·DB) → models (Tortoise)
                 ↑ schemas (Pydantic)            ↑ core/*_config (상수) · utils (헬퍼)
```

| 레이어 | 하는 일 | 하지 않는 일 |
|---|---|---|
| `routers/` | 인증 의존성, 요청 스키마 검증, 서비스 호출, 응답 포맷 | 비즈니스 로직, 직접 DB 조회 |
| `schemas/` | 입력 검증·정규화 (`field_validator`), 응답 모양 | DB 접근 |
| `services/` | DB 조회·생성, 트랜잭션, 도메인 규칙 | HTTP 객체(`Request`) 의존 |
| `models/` | 테이블·필드·관계 정의 | 로직 |
| `core/` | 미들웨어, 인증, 권한, 상수 | 도메인 로직 |
| `utils/` | 상태 없는 순수 함수 | DB 쓰기 |

---

## 4. 코드 패턴

### 4.1 모델
```python
from tortoise import fields
from models.base import BaseModel

class Example(BaseModel):
    name = fields.CharField(max_length=100)              # CharField 는 max_length 필수
    owner = fields.ForeignKeyField(
        "models.User", related_name="examples", null=True
    )

    class Meta:
        table = "example"                                 # snake_case
```
- 모든 모델은 `BaseModel` 상속 (`id`, `created_at`, `updated_at` 자동).
- 테이블·필드 모두 `snake_case`.
- 새 모델 모듈은 `database.py` 의 `models` 목록에 추가해야 인식된다.
- 시간은 UTC 로 저장하고 ISO 문자열로 내려준다 → FE 가 KST 로 표시.

### 4.2 스키마
```python
from typing import Optional
from pydantic import BaseModel, field_validator

class ExampleCreate(BaseModel):
    name: str
    memo: Optional[str] = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, v):
        if not v or not v.strip():
            raise ValueError("이름을 입력해주세요.")
        return v.strip()
```

### 4.3 라우터
```python
import logging
from fastapi import APIRouter, Depends, HTTPException

from core.auth_deps import require_feature
from core.permissions import Feature
from core.response_utils import success
from schemas.example import ExampleCreate
from services.example.example_service import ExampleService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/examples", tags=["Example"])

@router.post("")
async def create_example(body: ExampleCreate, auth=Depends(require_feature(Feature.EXAMPLE_EDIT))):
    try:
        item = await ExampleService.create(body, actor_id=auth["user_id"])
        return success(item=item)
    except HTTPException:
        raise                                    # 서비스가 낸 4xx 는 그대로
    except Exception as e:
        logger.error(f"예시 생성 실패: {e}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")
```
- 경로: `kebab-case`, 함수: `snake_case`.
- 응답: `{"status": "success", ...data}` (`success()` 헬퍼).
- 에러: `HTTPException` + 한국어 `detail`. **500 응답에 `str(e)` 노출 금지.**

### 4.4 서비스
```python
class ExampleService:
    @staticmethod
    async def create(body, actor_id: int) -> dict:
        obj = await Example.create(name=body.name, memo=body.memo)
        return {"id": obj.id, "name": obj.name}
```
- 클래스 + `@staticmethod` + `async`.
- 상태값 문자열 리터럴(`"active"` 등) 직접 사용 금지 → `core/{domain}_config.py` 상수 import.

### 4.5 import 순서
```python
# 1. 표준 라이브러리
# 2. FastAPI / 외부 패키지
# 3. 내부 모듈 (main/ 기준 절대 경로: core., models., schemas., services., utils.)
```

### 4.6 Tortoise 1.x 연동 (MES_BE 0.25 와 다름)
```python
from tortoise.contrib.fastapi import RegisterTortoise

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with RegisterTortoise(app, config=TORTOISE_ORM):
        yield
```
- MES_BE 처럼 lifespan 에서 `Tortoise.init()` 만 하면 요청 핸들러에서 `No TortoiseContext is currently active` 오류가 난다.
- 기본키는 `fields.IntField(primary_key=True)` (`pk=True` 는 구 표기).

---

## 5. 인증 · 권한

- **세션 쿠키 인증**: 로그인 시 세션에 `user_id` · `ver`(= `User.session_version`) · `remember` 만 저장. role 은 세션에 두지 않는다.
  - 서명 유효기간 7일. `require_auth` 를 지나는 요청마다 세션을 다시 써서 갱신(슬라이딩) — Starlette 는 세션이 바뀔 때만 쿠키를 다시 보내므로 시각 값을 갱신한다.
  - `remember=True` → 쿠키 `Max-Age` 7일. `False` → `Max-Age` 를 뺀 브라우저 세션 쿠키 (`core/session.py`).
- **운영 환경** (`ENV != dev`): `same_site="none"`, `https_only=True`, CORS 에서 `http://`·`localhost` origin 자동 제거.
- **비활성 계정 즉시 차단**: 미들웨어 가드 대신 `require_auth` 가 요청마다 DB 에서 사용자를 읽어 `active` · `session_version` 확인 → 비활성이거나 비밀번호가 바뀌었으면 세션 비우고 401.
  (어차피 role 을 DB 에서 읽어야 하므로 한 번의 조회로 같이 처리. 인증이 필요 없는 경로에는 DB 조회가 생기지 않는다.)
- **로그인**: 틀린 아이디·비밀번호는 400 (FE `client.js` 가 401 을 받으면 로그인 화면으로 보내므로), 비활성 계정은 비밀번호가 맞을 때만 403. 없는 아이디도 bcrypt 를 한 번 돌려 응답 시간 차이를 없앤다.
- **최초 관리자**: `docker compose exec app python -m scripts.create_admin` — 비밀번호는 실행 중 입력(화면에 안 보임).
- **API 키** (자동화용 — 리서처 skill): 헤더 `X-API-Key`. `api_key` 테이블에 sha256 해시만 저장, 원문은 발급 때 한 번만 출력.
  - 발급·목록·폐기는 BE PC 에서 스크립트로만: `docker compose exec app python -m scripts.api_key create|list|revoke`. API 로는 발급하지 않는다.
  - 키는 사용자 1명에 묶인다 (`researcher` 직원 계정, 비밀번호는 아무도 모르는 임의값 → 화면 로그인 불가). 사용자를 비활성화하면 키도 401.
  - **키로는 `require_auth` · `require_feature(RESEARCH)` 만 통과** (`API_KEY_FEATURES`). 그 밖 Feature · `require_role` 은 역할과 상관없이 403 → 키가 새도 회사 계정 비밀번호·사용자 관리에는 닿지 않는다.
  - 키 헤더를 보냈으면 키로만 판단한다 (틀린 키면 세션이 있어도 401). `last_used_at` 은 5분에 한 번만 갱신.
- **의존성 3종** (`core/auth_deps.py`)

| 의존성 | 통과 조건 |
|---|---|
| `require_auth` | 로그인만 |
| `require_feature(Feature.X)` | 해당 Feature 보유 (role 기본값 — 개인 override 는 아직 없음) |
| `require_role(Role.X)` | 해당 역할 |

| Role | Feature |
|---|---|
| `admin` | `research` · `account_view` · `account_edit` · `user_manage` · `detail_review` |
| `member` | `research` · `account_view` · `detail_review` |

- `detail_review` (2026-10-21) = 상세페이지 휴먼 체크 (승인 · 수정 요청 · 공통 안내 저장). `API_KEY_FEATURES` 에 없으므로 **API 키(리서처 등 자동화)로는 승인할 수 없다** — 사람이 로그인해서만. 초안 작성·저장·검수 요청은 `research`.

- role 은 **DB 우선** 조회 → 관리자가 권한을 내리면 다음 요청부터 즉시 반영.
- 사용자 관리 규칙: 자기 자신 비활성화·자기 역할 변경 금지, 마지막 활성 관리자는 비활성화·강등 금지. 비밀번호를 바꾸면 `session_version` +1 → 그 사용자의 기존 세션 모두 401.
- **회사 계정 비밀번호**: Fernet 암호문(`password_enc`)으로만 저장. 목록·등록 응답에 넣지 않고 `GET /company-accounts/{id}/password` 로 한 건씩만 복호화 → 그때마다 `company_account_password_view` 에 기록 (기록 실패 시 비밀번호도 안 줌).
  - 회사 계정 라우터 로그에는 `str(e)` 대신 예외 종류만 남긴다 (DB 오류 메시지에 행 값이 섞일 수 있음). 스키마 `__repr__` 도 비밀번호를 뺀다.
  - ⚠️ `ACCOUNT_SECRET_KEY` 를 잃으면 저장된 비밀번호를 복구할 수 없다 → `.env` 와 별도로 PC 밖 안전한 곳에 백업. `pg_dump` 백업과 **같은 곳에 두지 않는다** (둘 다 새면 평문과 같다).
- 데이터를 바꾸는 엔드포인트는 `require_auth` 로 두지 않는다 — 로그인만으로 누구나 호출 가능해진다.
- Feature 이름은 FE `constants/permissions.js` 와 문자열로 동기화한다.

---

## 6. DB · 마이그레이션

```bash
aerich init-db                          # 최초 1회
aerich migrate --name add_example       # 모델 변경 → 마이그레이션 파일 생성
aerich upgrade                          # 실제 적용
```
- 스키마 변경은 **Aerich 가 직접 실행**한다. 손으로 DDL 먼저 실행 금지 (다음 upgrade 가 실패한다).
- 생성된 마이그레이션 파일은 수정하지 않는다 — 틀렸으면 모델을 고치고 다시 생성.
- `--fake` 사용 금지.

### 6.1 데이터 모델 (2026-10-18)

```
product (제품) 1 ──< N price_survey (가격 조사) 1 ──< N price_survey_option (옵션별 가격)
```

**`product` — 제품 입력** (`models/product/product.py`)
| 컬럼 | 타입 | 필수 | 뜻 |
|---|---|---|---|
| `code` | varchar(50), unique | ✅ | 제품 코드 — BE 발급 `PR-YYMMDD-XXXX` (추가일 KST, 순번 16진수 4자리) |
| `photo_url` | varchar(1000) | | 제품 사진(대표이미지) — `/files/...` (업로드, 이 PC 디스크) 또는 외부 `http(s)` 주소. 2026-10-27부터 패키지를 그대로 둔 상품 연출컷(B), 기존 실물 사진은 `photos` 맨 앞으로 |
| `photo_hover_url` | varchar(1000) | | 대표이미지(전환용) — 자사몰 상품 카드 마우스오버 때 보이는 두 번째 연출컷. 두 연출컷 모두 오른쪽 아래에 '연출 이미지' 글씨가 들어간 파일이다. 마이그레이션 28 |
| `photos` | JSONB | | 추가 사진 갤러리 — 주소 목록(순서 있음, 최대 10장, 대표 제외). 판매 상세에 쓸 사진을 모아 둔다 (사진 5장 기준, 2026-10-25 사용자 결정). 마이그레이션 20 |
| `title_cn` | varchar(300) | ✅ | 중국어 제목 |
| `title_ko` | varchar(300) | | 한국어 제목 |
| `created_at` | timestamptz | ✅ | 제품 코드 추가일 (자동) |
| `deleted_at` | timestamptz | | 소프트 삭제 시각 |

**`price_survey` — 가격 입력** (`models/product/price_survey.py`)
| 컬럼 | 타입 | 필수 | 뜻 |
|---|---|---|---|
| `product_id` | FK → product (삭제 시 같이 삭제) | ✅ | 제품 코드 FK |
| `code` | varchar(50), unique | ✅ | 조사 코드번호 — BE 발급 `RS-YYMMDD-XXXX` (조사일 기준) |
| `survey_date` | date | ✅ | 조사일 |
| `photo_url` | varchar(1000) | | 제품 사진 link (보통 연결된 제품 사진) |
| `taobao_url` | varchar(1000) | ✅ | 구매할 타오바오 링크 (공식몰 위주) |
| `coupang_min_price` / `coupang_url` | int(원) / varchar | | 쿠팡 최저가 · 링크 (없어도 됨) |
| `naver_min_price` / `naver_url` | int(원) / varchar | | 네이버 최저가 · 링크 (없어도 됨) |
| `deleted_at` | timestamptz | | 소프트 삭제 시각 |

**`price_survey_option` — 옵션별 가격**
| 컬럼 | 타입 | 필수 | 뜻 |
|---|---|---|---|
| `survey_id` | FK → price_survey (삭제 시 같이 삭제) | ✅ | 어느 조사의 옵션인지 |
| `option1` | varchar(200) | ✅ | 옵션1 (예: 검정) |
| `option2` | varchar(200) | | 옵션2 (예: L) |
| `price_cny` | numeric(12,2) | ✅ | 옵션별 가격 (위안) |
| `photo_url` | varchar(1000) | | 옵션별 사진 (예: 맛별 사진) |

- **옵션 총 종류**는 컬럼으로 두지 않고 `price_survey_option` 행 수로 센다 — 따로 저장하면 실제 옵션 수와 어긋난다.
- 한 제품을 여러 날 다시 조사할 수 있도록 제품 : 조사 = 1 : N.
- ⚠️ **옵션 id 는 판매가와 마켓 등록의 열쇠다.** `option_price.option_id` 는 CASCADE, `product_pricing.base_option_id` 는 SET NULL, 마켓 등록 `items[].option_id` 는 값으로 참조한다. `PATCH /price-surveys/{id}` 에 `options` 를 보내면 행을 지우고 새 id 로 만들어 이 연결이 모두 끊긴다 (2026-10-25 사고). 이름·사진 수정은 `PATCH /price-surveys/{id}/options/{option_id}` (제자리 수정, id·`price_cny` 유지) 를 쓴다. (2026-10-26)
- **소프트 삭제**: `DELETE` 는 `deleted_at` 만 채운다. 조회는 `alive_products()` · `alive_surveys()` (제품이 삭제된 조사도 숨김)로만 한다. 코드 발급(`next_code`)은 삭제된 행까지 봐서 코드를 다시 쓰지 않는다.
- **사진 주소로 저장** (`POST /uploads/photos/from-url`): BE 가 받아 온다 → 연결 전 호스트를 IP 로 풀어 공인 주소만 허용, 리다이렉트는 직접 따라가며 매번 다시 검사 (최대 3번), 15초 · 10MB 제한. 표준 라이브러리 `urllib` 만 쓴다 (의존성 추가 없음).

### 6.2 계정 · 회사 계정 (2026-10-18)

```
app_user 1 ──< N company_account (created_by, 사용자 삭제 시 NULL)
app_user 1 ──< N company_account_password_view >── 1 company_account
```

**`app_user` — 로그인 계정** (`models/user/user.py`, 테이블명은 Postgres 예약어 `user` 를 피함)
| 컬럼 | 타입 | 필수 | 뜻 |
|---|---|---|---|
| `username` | varchar(50), unique | ✅ | 로그인 아이디 (소문자로 저장) |
| `name` | varchar(50) | ✅ | 표시 이름 |
| `password_hash` | varchar(100) | ✅ | bcrypt 해시 — 응답·로그 금지 |
| `role` | varchar(20) | ✅ | `admin` / `member` |
| `active` | bool | ✅ | false = 사용 중지 (다음 요청부터 401) |
| `session_version` | int | ✅ | 비밀번호 변경 시 +1 → 기존 세션 무효 |

**`company_account` — 회사 외부 서비스 계정** (`models/company_account/company_account.py`)
| 컬럼 | 타입 | 필수 | 뜻 |
|---|---|---|---|
| `platform` | varchar(100) | ✅ | 플랫폼 (타오바오·쿠팡·네이버 스마트스토어 등) |
| `login_id` | varchar(200) | ✅ | 그 플랫폼의 아이디 |
| `password_enc` | text | ✅ | Fernet 암호문 — 목록·로그 금지 |
| `usages` | jsonb | ✅ | 용도 문자열 배열 (`?usage=` 는 jsonb `@>` 로 정확히 일치) |
| `created_by_id` | FK → app_user (SET NULL) | | 추가한 사람 |

**`company_account_password_view` — 비밀번호 열람 기록** (지우지 않는다)
| 컬럼 | 타입 | 필수 | 뜻 |
|---|---|---|---|
| `account_id` | FK → company_account (CASCADE) | ✅ | 어느 계정 |
| `user_id` | FK → app_user (RESTRICT) | ✅ | 누가 — 열람 기록이 있는 사용자는 지울 수 없다 (비활성화만) |
| `ip` | varchar(64) | | 요청 IP |
| `created_at` | timestamptz | ✅ | 언제 |

**회사 정보 = 기본 정보 · 로그인 계정 · API 키** (2026-10-23). 세 개념은 만료일 유무가 아니라 **무엇인지**로 나눈다:
로그인 계정 = 아이디·비밀번호로 들어가는 것, API 키 = 비밀값(열람 기록)·재인증·허용 IP 가 있는 키, 기본 정보 = 그 밖의 회사 정보 전부 (번호·계좌·연락처·서류, 값은 숨기지 않음).

**`company_info` — 기본 정보 1건** (`models/company_account/company_info.py`)
| 컨럼 | 타입 | 필수 | 뜻 |
|---|---|---|---|
| `category` | varchar(30) | ✅ | 분류 — 자유 입력 (사업자 · 인허가·신고 · 계좌 · 연락처 · 서류) |
| `name` | varchar(100) | ✅ | 이름 |
| `value` | varchar(500) | | 대표 값. 서류처럼 파일만 있으면 비움 |
| `details` | jsonb | ✅ | 세부 값 `[{label, value}]` |
| `issuer` · `issued_on` · `expires_on` | | | 발급기관 · 발급일 · 만료일 |
| `remind` | bool | ✅ | 만료 임박 시 홈 할 일에 띄움 (납세증명서처럼 다시 떼는 서류는 false) |
| `url` | varchar(500) | | 관련 사이트 |
| `link` | varchar(50) | | 앱에서 쓰는 곳 (`core/company_info_config.INFO_LINKS`). 살아 있는 항목 중 하나에만 (서비스에서 409) |
| `sort` | smallint | ✅ | 분류 안 순서 |
| `deleted_at` | timestamptz | | 소프트 삭제 |

**`company_info_file` — 기본 정보에 붙인 서류** — `PRIVATE_DIR/company_info/YYYY/{임의}.{pdf|jpg|png|webp}` 에 저장. **`/files` (공개 StaticFiles) 로 내리지 않고** `GET /company-info/{id}/files/{file_id}` 가 `account_view` 확인 후 내려준다 (주민번호·계좌가 든 서류). 형식은 앞부분 바이트로 판단, 20MB, 항목당 10개.

- **상세페이지 등록번호 연결**: `link = food_agency_reg_no` 항목이 있으면 `detail_page_common.reg_no` 는 그 값을 따른다. 항목을 추가·수정하면 `DetailPageService.sync_linked_reg_no` 가 값을 맞추고(바뀌면 승인된 상세페이지는 검수 대기로), `PUT /detail-pages/common` 은 보낸 `reg_no` 대신 연결 값을 쓴다. 연결 항목을 지우면 마지막 값이 남고 S6 에서 다시 고칠 수 있다.

### 6.3 가격 책정 (2026-10-19)

```
product 1 ──< N product_pricing (판매처별 1개) 1 ──< N option_price >── 1 price_survey_option
exchange_rate (날짜별 위안 환율, 독립 — 최근 행 = 현재 환율)
exchange_rate_log (저장할 때마다 한 줄 — 추이 그래프, 독립)
```

**`product_pricing` — 판매처별 가격 설정** (`models/product/pricing.py`, unique `product + platform`)
| 컬럼 | 타입 | 필수 | 뜻 |
|---|---|---|---|
| `product_id` | FK → product (CASCADE) | ✅ | 제품 |
| `survey_id` | FK → price_survey | ✅ | 기준으로 쓴 가격 조사 |
| `platform` | varchar(20) | ✅ | `coupang` / `naver` (`core/pricing_config.Platform`) |
| `fx_rate` | numeric(12,4) | ✅ | **저장 시점 환율 (기록용)** — 계산은 현재 환율로 한다 (2026-10-20). 나중에 환율 변동으로 차익이 바뀐 걸 비교할 때 쓴다 |
| `fx_date` | date | | 그 환율의 기준일. 고정값(200)을 쓰면 비어 있음 |
| `fx_markup_pct` | numeric(5,2) | ✅ | 실결제 가산율 %. 기본 `DEFAULT_FX_MARKUP_PCT` (실결제 내역으로 확정 전 0) |
| `shipping_fee` | int(원) | ✅ | **쓰지 않음** (2026-10-20 부터 옵션별 무게로 계산). 컨럼만 남아 있고 기본값 10000 으로 채워진다 |
| `platform_fee_rate` / `payment_fee_rate` | numeric(5,2) | ✅ | 플랫폼 · 결제 수수료 % |
| `base_option_id` | FK → price_survey_option (SET NULL) | | 대표 옵션 — 네이버 추가금 0원인 옵션. 비면 자동 (FE 가 한도를 만족하는 가장 싼 옵션). 마이그레이션 6 (2026-10-20) |

**`option_price` — 옵션별 판매가** (unique `pricing + option`)
| 컬럼 | 타입 | 필수 | 뜻 |
|---|---|---|---|
| `pricing_id` | FK → product_pricing (CASCADE) | ✅ | 어느 판매처 설정 |
| `option_id` | FK → price_survey_option (CASCADE) | ✅ | 어느 옵션 |
| `sale_price` | int(원) | ✅ | 판매가 — 사용자가 입력 |

**`exchange_rate` — 위안 환율** (`date` unique(KST), `cny_krw`, `source`) — 가격 책정 · 배송비가 같이 쓰는 하나의 값
- 하루 1건 — 같은 날은 덮어쓴다. **현재 환율** = 날짜 최근 행 (`services/pricing/exchange_rate_service.py`). 없으면 `DEFAULT_FX_RATE` 200 (`source = default`, DB 에 저장하지 않음).
- **자동 받기** (2026-10-21): `main.py` lifespan 이 `fx_auto_loop` 를 띄운다 — 매일 `FX_DAILY_HOUR:FX_DAILY_MINUTE`(오전 9시 KST)에 오늘 값을 한 번 저장 (사용자 결정 2026-10-21 — 하나은행 1회차 고시는 8시 25분쯤). 실패하면 `FX_RETRY_SEC`(10분) 간격 `FX_RETRY_MAX`(6)번까지 다시. 서버가 켜질 때 오늘 값이 없고 9시가 지났으면(또는 저장값이 하나도 없으면) 바로 받는다. 주말·공휴일엔 직전 영업일 고시가 그대로 저장된다.
  - 출처 (`services/pricing/fx_fetch.py`, 표준 라이브러리 urllib): ① 하나은행 고시 매매기준율 — 네이버 금융 데이터 (`source = hana`, 키 불필요, 비공식 경로라 바뀔 수 있음) → ② open.er-api (`open_er_api`, 하루 1번 갱신). 범위(`FX_SANE_MIN~MAX`) 밖 값은 버린다.
  - 둘 다 실패하면 로그만 남기고 마지막 저장값으로 계속 계산한다 (다음 차례에 다시).
  - 한국수출입은행 공식 API 는 인증키가 필요해 쓰지 않는다 (필요하면 `.env` 키 + 출처 추가).
- **직접 입력** (`PUT /exchange-rate`, `source = manual`)은 그날 자동으로 덮어쓰지 않는다. 화면의 '지금 받아오기'(`POST /exchange-rate/refresh`)는 직접 입력값도 바꾼다.

**`exchange_rate_log` — 환율 기록** (`cny_krw`, `source`, `observed_at`(출처 기준 시각, 문자열), `created_at` = 저장 시각) — 마이그레이션 11, 2026-10-21
- `exchange_rate` 에 저장할 때마다(`_upsert_today`) 한 줄 추가 — 자동(매일 9시) · 지금 받아오기 · 직접 입력. 직접 입력 때문에 자동 저장을 건너뛴 때는 안 남는다.
- 추이 그래프(`GET /exchange-rate?days=`)는 **이 서버 기록만** 쓴다 — 외부 과거 데이터를 채우지 않는다 (사용자 결정 2026-10-21). `FX_TREND_DAILY_AFTER_DAYS`(31)일보다 긴 기간은 하루 마지막 값 하나씩.
- 계산에는 쓰지 않는다 (기록용). 지우지 않음 — 하루 1줄 남짓.

**배송비 — 저장하지 않고 계산** (`core/shipping_config.py`, `services/pricing/shipping_service.py`, 2026-10-20)
- 요금: 타오바오 공식 집운-해운 한국행 **식품·민감 화물** 고정 — 첫 1kg 33위안, 넘는 무게 0.5kg 마다 2위안 (0.5kg 단위 올림), 소형 한도 30kg.
- 무게: 옵션 이름의 총 용량(ml) × 1g + 박스 500g. 용량은 `utils/volume.py` 가 `245ml×24팩` · `1L×6팩` 같은 이름에서 읽는다 (못 읽으면 배송비 `null`). g·kg 로 적힌 옵션(요거트 등)은 1g = 1ml 로 본다 (2026-10-24 사용자 결정).
- 배송비는 위안으로 내려주고 원화는 FE 가 현재 환율로 환산 → 환율을 바꾸면 배송비도 자동으로 바뀐다.
- 부피 무게 · 관세는 아직 반영하지 않는다.
- 배송비 화면은 제품별 목록이 아니라 무게 구간별 요금표만 보여준다 (`GET /shipping-fees/rule`, 2026-10-20 사용자 결정). 옵션별 배송비는 가격 책정에서 본다.

**출고지·반품지 주소록 · 배송 경로** (`models/shipping/address.py`, 마이그레이션 13 · 15)
- `shipping_address` — 실제 장소 1곳 = 1행. `market_codes`(jsonb) 에 마켓 주소록 번호. 구매대행은 배대지(해외) 주소 하나를 출고지·반품지로 쓴다.
- `route`(jsonb, null 가능, 2026-10-24) — 배송 경로: 국제 물류사 · 해운/항공 · 입항 항구 · **국내 택배사(`courier`, `core/shipping_config.COURIERS` 키)** · 국내 송장 나오는 시점 · UNI-PASS 조회 번호 · 확인 여부. 응답에 `courier_codes`(쿠팡·네이버 택배사 코드)를 붙여 주문 발송처리가 그대로 쓴다. 택배사 코드는 두 마켓 문서에서 확인한 값만 `COURIERS` 에 둔다.

- **차익 · 마진율은 저장하지 않는다** — 계산값이라 따로 두면 어긋난다. 판매가만 저장하고, 화면을 열 때마다 현재 환율로 다시 계산한다.
  `실결제환율 = 현재 환율 × (1 + fx_markup_pct/100)`, `원가+배송 = (price_cny + shipping_cny) × 실결제환율`,
  `차익 = sale_price − 원가+배송 − sale_price × (platform_fee_rate + payment_fee_rate)/100`, `마진율 = 차익 / sale_price`.
- 네이버 추가금은 저장하지 않고 등록할 때 계산한다: 대표가 = `base_option` 의 판매가 (없으면 자동 선택), 추가금 = 옵션 판매가 − 대표가 (마이너스 가능).
  한도: 대표가 1만 원 이상 −50%~+50%, 2천~1만 원 −50%~+100%, 2천 원 미만 0~+100% (2026-10-20 확인).

### 6.4 상세페이지 (디자인) · 휴먼 체크 (2026-10-21)

```
product 1 ── 0..1 detail_page 1 ──< N detail_page_review (검수 기록)
                           detail_page 1 ──< N detail_page_export (상세 이미지 · 판매처별 버전)
detail_page_common (행 1개, id=1 — S6 해외구매대행 안내 + 등록번호, 모든 페이지가 같이 씀)
```

템플릿 = S1 대표 사진 · S2 포인트 · S3 맛 선택 · S4 제품 정보 · S5 마시는 법·보관 · S6 해외구매대행 안내(공통), 폭 860px (기준: 루트 `detail-page-mockup.pdf`, 2026-10-21 사용자 승인한 구조). S1~S5 칸 값은 `detail_page.content`, S6 는 `detail_page_common` 한 곳에서만 고친다.

**`detail_page`** (`models/product/detail_page.py`)
| 컬럼 | 타입 | 필수 | 뜻 |
|---|---|---|---|
| `product_id` | FK → product, unique (CASCADE) | ✅ | 제품 1 : 상세페이지 1 |
| `content` | jsonb | ✅ | 템플릿 칸 값 — 모양은 `schemas/detail_page.DetailContent` (모르는 키는 버리고 빠진 칸은 빈 값) |
| `status` | varchar(20) | ✅ | `draft` 초안 → `review` 검수 대기 → `approved` 승인 / `changes` 수정 필요 (`core/detail_page_config.DetailStatus`) |
| `updated_by_id` | FK → app_user (SET NULL) | | 마지막으로 내용을 바꾼 사람 |
| `reviewed_by_id` · `reviewed_at` · `review_note` | FK · timestamptz · text | | 마지막 검수 (승인 또는 수정 요청) — 누가 · 언제 · 메모 |
| `review_checks` | jsonb | | 예전 기록용 (5개 체크리스트 폐지 2026-10-22 이후 항상 null) |

**`detail_page_review`** — `action`(`submit` 검수 요청 · `approve` · `changes` · `reset` 자동 되돌림), `user_id`, `note`, `checks`, `created_at`. 지우지 않는다.

**`detail_page_common`** — `reg_no`(수입식품등 인터넷 구매대행업 등록번호) · `seller` · `notice_title` · `notice`(jsonb `[{title, body}]`). 행이 없으면 `DEFAULT_COMMON` 으로 만든다.

**`detail_page_export`** — 상세 이미지 내보내기 (마이그레이션 12, 2026-10-22). 지우지 않는다.
| 컨럼 | 타입 | 필수 | 뜻 |
|---|---|---|---|
| `page_id` | FK → detail_page (CASCADE) | ✅ | |
| `platform` | varchar(20) | ✅ | `naver` (폭 860) · `coupang` (폭 780) — `core/detail_page_config.ExportPlatform` · `EXPORT_WIDTHS` |
| `version` | int | ✅ | 판매처별 1, 2, 3 … (`page_id, platform, version` unique) |
| `content_hash` | varchar(64) | ✅ | 그린 시점 content + 공통 안내의 sha256 — 지금 해시와 같으면 `current` |
| `template` | varchar(50) | ✅ | FE 템플릿 버전 (`DETAIL_TEMPLATE_VERSION`) |
| `files` | jsonb | ✅ | 조각 순서대로 `[{url, width, height, size, sha256}]` |
| `created_by_id` | FK → app_user (SET NULL) | | 올린 사람 |

**규칙**
- 목록 대상 = **가격 책정 완료** 제품 (모든 판매처 판매가 저장 — FE `pricingStatusOf` 의 `done`).
- 템플릿 채우기 (`build_template`): 제품 이름 · 최근 가격 조사의 옵션(option1 = 맛, option2 = 용량·입수) · 옵션별 사진으로 칸을 채우고, 사람이 써야 하는 칸은 `[[...]]` **확인 표시**로 남긴다. 페이지가 없으면 GET 이 템플릿만 주고(저장 안 함), 첫 PUT 이 초안으로 만든다.
  - 사진 (2026-10-25): 대표(`hero.photo_url`) = 제품 대표 사진, 맛 카드 = 옵션별 사진, 포인트 사진(`points.items[].photo_url`)은 자동으로 채우지 않는다(null — 2026-10-25b, 사람·에이전트가 비율에 맞는 사진만 고른다). 스키마에 `points.items[].photo_url` · `flavors.gallery{title, items[{photo_url, caption}] ≤ 4}` · `info.label_photo_url` · `info.label_caption` 추가 (모두 선택, 마이그레이션 없음 — content 는 JSON).
- **확인 표시 `[[...]]`** (`MARKER_RE`): 미리보기에 노란 표시로 보인다 (가안 문구는 `[[가안]]`). 남아 있어도 승인은 되고 FE 가 경고만 한다 (`marker_count`).
- **승인 = 휴먼 체크 '확인' 한 번** (2026-10-22 사용자 결정: "확인 누르면 휴먼체크한 걸로"). 예전 5항목 체크리스트 · 등록번호 필수 · 확인 표시 0개 조건은 없얗다. 남은 조건: 사람 로그인(`detail_review`, API 키 불가) · 아직 승인 안 됨(`draft` · `review` · `changes` 어디서든). 등록번호 미입력(`reg_no_ready` false) · 확인 표시는 FE 경고만. `checks` 는 받아도 무시, `review_checks` 는 null.
- **승인 = 지금 보이는 그대로를 사람이 확인함.** 승인 뒤 content 가 바뀌면 그 페이지는 검수 대기로, 공통 안내가 바뀌면 승인된 페이지 전부 검수 대기로 돌아간다 (`reset` 기록).
- 수정 요청은 메모 필수, `review` · `approved` 에서만. 수정 필요는 고친 뒤 다시 검수 요청(`submit`)해야 검수 대기가 된다.
- **상품 등록(다음 단계)은 `approved` 상세페이지만 받는다.** 등록 직전에 상태를 다시 읽어 확인한다 (등록 중 내용이 바뀌면 검수 대기가 되므로).
- **상세 이미지** 는 BE 가 그리지 않는다 — FE 가 같은 템플릿을 Pretendard(앱에 실은 글꼴)로 그려 섹션 경계에서 3000px 이하로 자르고, **네이버 860 PNG(무손실) · 쿠팡 780 JPG(품질 100)** 를 올린다 (2026-10-24 품질 최대 결정, FE DESIGN §4.7). BE(`services/product/detail_export_service.py`)는 받기만 한다:
  - 상태 `approved` · `content_hash` 가 지금 해시와 같아야 한다 (그 사이 바뀌면 409) · 사람 로그인(`detail_review`).
  - 조각마다 파일 머리(PNG IHDR · JPEG SOF)를 읽어 형식 = 판매처 형식(`EXPORT_FORMATS`), 폭 = 판매처 폭, 높이 ≤ `EXPORT_MAX_HEIGHT`(3000), 장당 ≤ `EXPORT_MAX_FILE_BYTES`(네이버 20MB · 쿠팡 10MB), 쿠팡은 높이 합계 ≤ 30,000px, 20장 이하, 합계 ≤ 45MB (nginx `client_max_body_size 50m`). 판매처 하나씩 올린다.
  - 저장: `{UPLOAD_DIR}/detail/{제품 코드}/v{버전}/{코드}_{판매처}_{순번}.{png|jpg}` → `/files/detail/…` (버전마다 새 폴더, 덮어쓰지 않음). 기록 저장이 실패하면 쓴 파일을 지운다.
  - 내용이 바뀌어 검수 대기로 돌아가도 옛 이미지 기록은 남는다 (`current: false`). 상품 등록은 `approved` + `current` 인 이미지만 쓴다.

---

### 6.5 고객 주문 코드 · 타오바오 구매 (2026-10-24)

- **`market_order.code`** — 자사 주문 코드 `OR-YYMMDD-XXXX` (unique, 날짜 = 마켓 주문일 KST). `order_service.issue_code` 가 새 주문 생성 직후 발급, 동시 발급 충돌(IntegrityError)은 `CODE_ISSUE_RETRIES` 번까지 다시. 발급 = `OrderEvent(kind=code_issued)`. 마켓 주문번호는 `order_no` + `line_no` 그대로.
- **`taobao_purchase`** (`models/order/purchase.py`) — 타오바오 주문번호 1개 = 1행, `order` FK → market_order (RESTRICT). 필수 `taobao_order_no`(살아 있는 행끼리 중복이면 서비스에서 409), 선택: `shop_name` · `item_url` · `items` jsonb `[{name, qty, price_cny}]` · `paid_cny` decimal(12,2) · `purchased_at` · `purchased_by` · 중국 내 배송 `cn_status`(ordered/shipped/arrived/problem/cancelled) · `shipped_at` · `cn_courier` · `cn_tracking_no` · `arrived_at`(집운 창고 입고) · `status_source` manual/poll · `status_checked_at`. 소프트 삭제.
- 기본은 고객 주문 1건 = 타오바오 주문 1건 (여러 개도 허용). 집운 쪽 매칭은 나중에 집운 번호로 따로.
- **주문 단계 판정 (2026-10-27)**: `order_service.decide_stage` — 취소·반품 > 완료 > 배송중 또는 타오바오 구매 기록 있음(처리) > 접수. `restage()` 를 타오바오 구매 등록·수정·삭제에서 부르고, 수집(upsert_line)도 같은 규칙. 처리 목록 진행 위치 `progress_of()`.
- **주문 금액 (2026-10-27)**: `order_service.amount_of` 가 저장된 원본(raw)으로 총액 · 할인(마켓/판매자 부담) · 고객 결제 · 수수료 · 정산 예정을 만든다. 네이버는 마켓이 준 정산 예정, 쿠팡은 수수료율(11.66%)로 추정 → 매출내역(revenue-history)이 오면 `settlement_actual`·`settlement_date` (마이그레이션 30) 로 실제 값.
- **클레임 (2026-10-27)**: 쿠팡은 CC(완료)도 본다 — releaseStatus=S 면 취소 완료(판매자 취소 포함), 아니면 반품 완료, 단계 취소 + `claim_reason` (마이그레이션 31). 발주서 단건 400 "취소 또는 반품" 이면 취소로 바꾸고 사유 보강. `market_order.claim_type · claim_status · claim_at` (마이그레이션 29). 네이버는 주문 응답의 claimType·claimStatus, 쿠팡은 수집 때 반품/취소 요청 목록(returnRequests: CANCEL · RU 출고중지 · UC 반품)으로 채운다. 새 클레임·변화 = OrderEvent `claim`. 수집 이벤트(collected·changed·claim)의 data.run = {id, trigger, auto} — 자동/수동 추적. 알림용 `GET /orders/updates?after=`.
- **발주확인 먼저** (2026-10-25): 타오바오 구매 등록 전에 `POST /orders/{id}/confirm` 으로 마켓에 발주확인(쿠팡 상품준비중 · 네이버 발주 확인)을 보내야 한다 — 결제완료 상태에선 고객 취소가 바로 돼서 산 뒤 손해. 미확인·취소 주문은 등록 409. 성공·실패는 `OrderEvent` `market_confirmed` / `market_confirm_failed`.
- 바꿀 때마다 그 고객 주문의 `OrderEvent` (`purchase_*`, data = 이전값 → 새값, 시각은 UTC 로 맞춰 비교). 상태 이름은 `core/purchase_config.CN_STATUS`.

### 6.6 마켓 등록 기록 (2026-10-24)

- **`market_listing`** (`models/product/listing.py`) — 제품을 판매처에 올린 상품 1건. `product` FK (CASCADE) · `platform` (coupang/naver) · `market_product_id` (쿠팡 sellerProductId · 네이버 원상품번호, `platform` 과 unique) · `title` · `url` · `status`(마켓이 준 상태) · `listed_at`(업로드 일시) · `items` jsonb `[{option_id, name, sale_price, market_item_id, sku}]` · `source` api/manual · `synced_at` · `memo` · `created_by` · `deleted_at`.
- 쿠팡에서 불러오기(`services/product/listing_service.py`): 셀러 상품 목록 → 상세 → 옵션 SKU `{제품 코드}-{옵션 id}` 로 제품을 찾는다. 같은 번호는 덮어쓰고, 사람이 지운 번호는 살리지 않는다. 쿠팡 호출은 `services/order/market_clients._coupang_get`(서명) 을 같이 쓴다.
- 권한 `listing` (member 포함, API 키 불가). 보기는 로그인만.
- 상세페이지 응답(`DetailPageSummary`)에 `created_at`(디자인 시작) 추가 — 상품 상세의 '디자인 시간' 계산용.

### 6.7 상품 등록 배송 조건 — 무료배송 고정 (2026-10-25 사용자 결정)

배송비(국제 + 국내)는 판매가에 이미 들어 있다 (§ 가격 책정). 그래서 **AGC 가 만드는 모든 마켓 등록은 무료배송**으로 올린다 — 네이버쇼핑 · 쿠팡 검색 목록에 '무료배송' 표시가 떠야 한다. 상세페이지 S1 끝의 무료배송 띠와 S6 '배송 · 배송비' 문구도 같은 전제다. 상품 등록(API) 코드는 아직 없다(쿠팡 0038 3건은 수동·일회성 스크립트로 등록) — 만들 때 아래를 기본값으로 쓴다.

| 판매처 | 필드 | 값 |
|---|---|---|
| 쿠팡 | `deliveryChargeType` / `deliveryCharge` / `freeShipOverAmount` | `FREE` / `0` / `0` |
| 쿠팡 | `deliveryChargeOnReturn` (초도 반품배송비) | `0` |
| 쿠팡 | `returnCharge` (반품배송비, 단순변심 실비) | 대표가 ≤ 20,000원 → `5000`, 초과 → `10000` (2026-10-24 규칙 유지) |
| 쿠팡 | `remoteAreaDeliverable` | `N` (제주·도서산간 추가비 없음) |
| 쿠팡 | `deliveryMethod` · `deliveryCompanyCode` · 출고지 · 반품지 | `AGENT_BUY` · `CJGLS` · 출고지 25556899(집운 웨이하이) · 반품지 1002733719 |
| 네이버 | `deliveryInfo.deliveryFee.deliveryFeeType` / `baseFee` | `FREE` / `0` |
| 네이버 | `claimDeliveryInfo.returnDeliveryFee` · `exchangeDeliveryFee` | 단순변심 실비 — 쿠팡과 같은 금액 규칙 (편도 반품비 5,000 / 10,000, 교환은 왕복 = 2배) |
| 네이버 | 제주·도서산간 추가 배송비 | 넣지 않음 |

- 2026-10-25 읽기 확인(쿠팡 GET): 제품 38 의 3건 모두 `FREE` · `deliveryCharge 0` · `remoteAreaDeliverable N` · `returnCharge` 5,000(18,400원 2건) / 10,000(26,300·42,000원 1건) — 위 규칙과 같다.
- 하자·오배송·설명과 다름의 반품비는 판매자 부담(전자상거래법 §18). 단순변심만 실비 청구, 반품위약금·보관비 등 추가 청구 금지.
- 무료배송에 조건(제주·도서산간 추가비 등)을 붙이려면 상세페이지 S6 와 무료배송 띠 문구도 같이 고친다.

## 7. 환경 · 실행

**.env**
| 변수 | 용도 |
|---|---|
| `DATABASE_URL` | `postgres://USER:PASS@db:5432/DB` |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | Compose 의 postgres 컨테이너 |
| `SESSION_SECRET_KEY` | 세션 서명 키 |
| `ALLOWED_ORIGINS` | CORS 허용 origin (쉼표 구분) |
| `ENV` | `dev` / `production` |
| `ENABLE_DOCS` | `1` 이면 `/docs` 공개 (dev 전용) |
| `SESSION_MAX_AGE_SEC` | 세션 유효기간 override (선택) |
| `ACCOUNT_SECRET_KEY` | 회사 계정 비밀번호 암호화 키 (Fernet). 만들기: `openssl rand -base64 32 \| tr '+/' '-_'`. **바꾸거나 잃으면 기존 비밀번호 복호화 불가** — 별도 백업 (§5) |
| `BE_DOMAIN` | BE 공개 주소 — 도메인 또는 공인 IP (현재 공인 IP, 도메인 없음). nginx 가 사용. 비어 있으면 nginx 는 발급용 http 만 연다 |
| `SESSION_SAME_SITE` | production 쿠키 SameSite. `lax` 권장 (Vercel rewrite 로 같은 출처). FE 가 다른 도메인에서 BE 를 직접 부르면 `none` |
| `TZ` | `Asia/Seoul` |
| `ORDER_POLL_MINUTES` | 주문 자동 수집 주기(분). 0 = 끔. 운영 **5** (2026-10-25 사용자 결정 — 쿠팡 발주서는 결제 뒤 몇 분 늦게 잡혀서 자동으로 다시 받음). 바꾸면 `docker compose up -d app` |

**Docker Compose 구성**
| 서비스 | 이미지 | 포트 | 볼륨 |
|---|---|---|---|
| app | `Dockerfile` 빌드 | 127.0.0.1:8000 (이 PC 에서만) | `./main:/app` (dev 코드 마운트) |
| db | `postgres:16-alpine` | 127.0.0.1:5432 (이 PC 에서만) | `postgres_data` |
| nginx | `nginx:1.30.1-alpine` | 80 · 443 (외부) | `./nginx` (설정), `letsencrypt`, `certbot_www` |
| certbot | `certbot/certbot:v5.5.0` | — | `letsencrypt`, `certbot_www` — 12시간마다 `certbot renew` |
| redis (선택) | `redis:7-alpine` | 6379 | `redis_data` |

```bash
docker compose up -d --build
docker compose logs -f app
```
- `.env` 변경은 `docker compose restart` 로 반영되지 않는다 → `up -d` 로 재생성.
- Dockerfile 은 BuildKit pip 캐시 마운트(`# syntax=docker/dockerfile:1`)로 재빌드 시간을 줄인다.

**운영 위치: 이 PC (EC2 대신)**
- 호스트: Windows 11 + Docker Desktop (WSL2 백엔드). Compose 구성은 MES_BE 와 동일하게 쓴다.
- Docker Desktop 은 "Windows 로그인 시 자동 시작"을 켜고, `db`·`redis` 는 `restart: always`, `app` 은 `restart: unless-stopped` 로 둔다 → PC 재부팅 후 자동 복구.
- PC 가 꺼져 있거나 절전 상태면 서버도 멈춘다 → 전원·절전 설정에서 절전 끄기.
- DB 데이터는 Docker 볼륨(`postgres_data`)에 있다 → 정기 `pg_dump` 백업을 PC 밖(클라우드 드라이브 등)에 둔다.
- FE 를 Vercel(HTTPS)에 두면 BE 도 HTTPS 주소가 필요하다 → certbot 으로 발급 (§7.1).

### 7.1 HTTPS (nginx + certbot)

```
브라우저 → eido-agc.vercel.app/api/* (예전 주소 agc-fe.vercel.app 도 같이 연결) ─(Vercel rewrite)→ https://BE_DOMAIN/* → nginx:443 → agc_app:8000   (2026-10-27 까지. 지금은 아래 Cloudflare Tunnel)
```
- FE 는 `/api` 를 같은 출처로 부르고 Vercel 이 BE 로 넘긴다 → 브라우저 입장에선 쿠키가 vercel.app 것이라 CORS·제3자 쿠키 차단 문제가 없다.
- nginx(`nginx/start.sh`)는 인증서가 있으면 `https.conf.template`, 없으면 발급 확인만 받는 `http.conf.template` 를 쓴다. 1시간마다 다시 골라 reload → 첫 발급·갱신이 재시작 없이 반영된다.
- 인증서 없이는 API 를 열지 않는다 (80 은 `/.well-known/acme-challenge/` 외 503) — 비밀번호가 평문으로 오가지 않게.
- 8000·5432 는 `127.0.0.1` 에만 연다. 외부에서 들어오는 길은 nginx 뿐 → uvicorn `--proxy-headers` 로 실제 접속 IP 를 써도 위조할 수 없다.

**Cloudflare Tunnel (2026-10-27~, 지금 쓰는 길)**
```
브라우저 → eido-agc.vercel.app/api/* ─(Vercel rewrite)→ https://api.eidofood.com/* → Cloudflare → agc_cloudflared(밖으로 나가는 연결) → https://agc_nginx:443 → agc_app:8000 (/mkt/ → mkt_app:8000)
```
- 도메인 `eidofood.com` (Cloudflare Registrar, 2027-10-27 만료·자동 갱신). Tunnel 이름 `eido-home` (ID `54cda0f1-b339-464f-8ced-2f122f75a850`).
- 호스트 이름 → 서비스 연결은 Cloudflare 대시보드(Networking › Tunnels › eido-home › Routes)에서 관리. `api.eidofood.com` → `https://agc_nginx:443`, "Disable TLS certificate verification" 켬 (nginx 인증서가 IP 용이라 — 이 구간은 이 PC 안 Docker 네트워크).
- 토큰은 `.env` 의 `CF_TUNNEL_TOKEN` (커밋 금지). 새어 나가면 대시보드에서 Rotate token → `.env` 갱신 → `docker compose up -d cloudflared`.
- 실제 접속 IP: cloudflared 가 X-Forwarded-For 를 넘기고 nginx·uvicorn 이 그대로 이어받는다 (확인함).
- 아래 "공인 IP 직접" 방식(80·443 포트포워딩)은 아직 열려 있다. 마켓 상세 이미지 주소가 IP 를 쓰는지 확인하고 옮긴 뒤 공유기 포트를 닫는다.

**처음 켜기 (1회, 공인 IP 직접 방식)**
1. 공유기(ipTIME, `192.168.0.1`) NAT/라우터 관리 → 포트포워드: TCP 80·443 → 이 PC 내부 IP (`192.168.0.5`, DHCP 고정 할당 권장). 도메인을 쓰면 A 레코드 → 공인 IP.
2. `.env` 에 `BE_DOMAIN=<공인IP 또는 도메인>`, `ENV=production`, `ENABLE_DOCS=` (비움 — 외부에 API 문서 노출 금지), `SESSION_SAME_SITE=lax`.
3. `docker compose up -d` (nginx 가 http 설정으로 뜬다)
4. 인증서 발급 (Let's Encrypt 약관 동의 포함). `--cert-name agc` 는 꼭 유지 — nginx 가 `live/agc` 를 본다.
   ```bash
   # 공인 IP (현재 방식, 도메인 없음 — Let's Encrypt IP 인증서는 shortlived 6일짜리만 나온다)
   docker compose run --rm --entrypoint certbot certbot certonly --webroot -w /var/www/certbot --cert-name agc --ip-address <공인IP> --preferred-profile shortlived --agree-tos --register-unsafely-without-email --no-eff-email
   # 도메인이면 --ip-address ... --preferred-profile shortlived 대신 -d <도메인>
   ```
   먼저 `--dry-run` 으로 연습하면 실제 발급 한도를 쓰지 않는다.
5. `docker compose restart nginx` → https 설정으로 전환. `curl https://<주소>/health` 확인.
6. FE `vercel.json` 에 `/api/:path*` → `https://<주소>/:path*` rewrite (SPA rewrite 보다 앞에).

**자동 갱신**: `certbot` 컨테이너가 12시간마다 `certbot renew` → nginx 가 1시간 안에 reload. 갱신 시점은 certbot 이 ARI(Let's Encrypt 가 알려주는 시점) 또는 수명 절반(6일 인증서면 약 3일)으로 정한다.
- **PC 가 3일 넘게 꺼져 있으면 인증서가 만료**될 수 있다 → 켜지면 바로 다시 받는다 (그 사이 HTTPS 오류).
- **공인 IP 가 바뀌면** (가정용 회선은 가끔 바뀐다): `.env` 의 `BE_DOMAIN` · FE `vercel.json` 을 새 IP 로 바꾸고 4번으로 다시 발급. 자주 바뀌면 무료 도메인(DuckDNS 등)으로 옮긴다.
**백업**: `letsencrypt` 볼륨 (없어져도 4번으로 다시 발급 가능 — 단 Let's Encrypt 주간 발급 한도 주의).

**.gitignore**: `__pycache__/`, `*.pyc`, `.env`, `secrets/`, `*.key`, `*.pem`, `runtime/`, `.idea/`

---

## 8. 미정 · 결정 필요

- [ ] AGC 서비스 도메인 → `models/`·`services/` 하위 도메인 폴더 목록
- [x] 계정 모델 → 사람 계정 `User`(`app_user`) + 역할 2개(admin/member), Feature 는 FE permissions.js 와 동일 (§5, §6.2)
- [ ] Redis 사용 여부 (캐시·세션 저장소·작업 큐)
- [x] 배포 대상 → 이 PC (Docker Desktop + Compose)
- [x] HTTPS (필요해지면) → 이 PC 에서 certbot(Let's Encrypt) 인증서 발급. certbot 은 Windows 지원이 끝났으므로 Docker 컨테이너(`certbot/certbot`)로 돌리고, nginx 컨테이너가 443 을 받아 `app:8000` 으로 넘긴다
  - 전제: 도메인 → 이 PC 공인 IP (유동 IP 면 DDNS), 공유기에서 80·443 포트포워딩, Windows 방화벽 허용
  - 80 포트를 못 열면 DNS 챌린지(`--preferred-challenges dns`)로 발급
  - 인증서는 90일 만료 → `certbot` 컨테이너가 자동 갱신 (§7.1)
- [x] 파일 저장소 → 이 PC 디스크 `BE/uploads/` (compose 가 `/uploads` 로 연결, `POST /uploads/photos` · `GET /files/...`). 정기 백업 대상에 포함
- [x] 비공개 파일 → `BE/private/` (compose 가 `/private` 로 연결, env `PRIVATE_DIR`). 회사 서류처럼 공개 주소로 내리면 안 되는 파일. API 가 권한 확인 후 내려준다. 커밋 금지, 정기 백업 대상
