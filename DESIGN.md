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
- **의존성 3종** (`core/auth_deps.py`)

| 의존성 | 통과 조건 |
|---|---|
| `require_auth` | 로그인만 |
| `require_feature(Feature.X)` | 해당 Feature 보유 (role 기본값 — 개인 override 는 아직 없음) |
| `require_role(Role.X)` | 해당 역할 |

| Role | Feature |
|---|---|
| `admin` | `research` · `account_view` · `account_edit` · `user_manage` |
| `member` | `research` · `account_view` |

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
| `photo_url` | varchar(1000) | | 제품 사진 — `/files/...` (업로드, 이 PC 디스크) 또는 외부 `http(s)` 주소 |
| `title_cn` | varchar(300) | ✅ | 중국어 제목 |
| `title_ko` | varchar(300) | | 한국어 제목 |
| `created_at` | timestamptz | ✅ | 제품 코드 추가일 (자동) |

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

**`price_survey_option` — 옵션별 가격**
| 컬럼 | 타입 | 필수 | 뜻 |
|---|---|---|---|
| `survey_id` | FK → price_survey (삭제 시 같이 삭제) | ✅ | 어느 조사의 옵션인지 |
| `option1` | varchar(200) | ✅ | 옵션1 (예: 검정) |
| `option2` | varchar(200) | | 옵션2 (예: L) |
| `price_cny` | numeric(12,2) | ✅ | 옵션별 가격 (위안) |

- **옵션 총 종류**는 컬럼으로 두지 않고 `price_survey_option` 행 수로 센다 — 따로 저장하면 실제 옵션 수와 어긋난다.
- 한 제품을 여러 날 다시 조사할 수 있도록 제품 : 조사 = 1 : N.

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

---

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
| `TZ` | `Asia/Seoul` |

**Docker Compose 구성**
| 서비스 | 이미지 | 포트 | 볼륨 |
|---|---|---|---|
| app | `Dockerfile` 빌드 | 8000 | `./main:/app` (dev 코드 마운트) |
| db | `postgres:16-alpine` | 5432 | `postgres_data` |
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
- FE 를 Vercel(HTTPS)에 두면 BE 도 HTTPS 주소가 필요하다 → 필요해지면 certbot 으로 발급 (§8).

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
  - 인증서는 90일 만료 → 갱신(`certbot renew`) 자동화 필요
- [x] 파일 저장소 → 이 PC 디스크 `BE/uploads/` (compose 가 `/uploads` 로 연결, `POST /uploads/photos` · `GET /files/...`). 정기 백업 대상에 포함
