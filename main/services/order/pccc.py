"""개인통관고유부호 검증 — 관세청 UNI-PASS API028 (persEcmQry/retrievePersEcm).
필수: 통관부호 · 납세의무자명 · 전화번호(11자리) · 배송지 우편번호(5자리).
일회용 부호(O…)는 주문번호 · 주문일시(yyyyMMddHHmmss) · 인증번호가 더 필요하다.
응답 tCnt: 1 일치 · 0 불일치 · -1 시스템 장애. 불일치 사유는 errMsgCn 여러 개."""

import asyncio
import hashlib
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date

from services.company_account.api_credential_service import credential_values

UNIPASS_URL = "https://unipass.customs.go.kr:38010/ext/rest/persEcmQry/retrievePersEcm"
UNIPASS_SERVICE = "UNI-PASS OpenAPI"
UNIPASS_KEY_LABEL = "API028 인증키 (통관부호 검증)"


# ------------------------------------------------------------ 값 다듬기 · 가리기
def norm_pccc(v: str | None) -> str:
    return re.sub(r"\s|-", "", v or "").upper()


def norm_phone(v: str | None) -> str:
    """'+82-10-1234-5678' · '+821012345678' · '010-1234-5678' → '01012345678'."""
    d = re.sub(r"\D", "", v or "")
    if d.startswith("82"):
        d = "0" + d[2:]
    return d


def norm_zip(v: str | None) -> str:
    return re.sub(r"\D", "", v or "")


def mask_pccc(v: str) -> str:
    return v[:2] + "*" * max(0, len(v) - 5) + v[-3:] if len(v) > 5 else "*" * len(v)


def mask_phone(v: str) -> str:
    return f"{v[:3]}-****-{v[-4:]}" if len(v) >= 10 else "*" * len(v)


def mask_name(v: str) -> str:
    if not v:
        return ""
    if len(v) <= 2:
        return v[0] + "*"
    return v[0] + "*" * (len(v) - 2) + v[-1]


def receiver_fingerprint(pccc: str, name: str, phone: str, zip_code: str) -> str:
    return hashlib.sha256("|".join([pccc, name, phone, zip_code]).encode()).hexdigest()


# ------------------------------------------------------------ 검증
@dataclass
class PcccInput:
    pccc: str
    name: str
    phone: str
    zip_code: str
    order_no: str | None = None        # 일회용 부호용
    ordered_at: str | None = None      # yyyyMMddHHmmss
    otp: str | None = None

    def masked(self) -> dict:
        d = {"pccc": mask_pccc(self.pccc), "name": mask_name(self.name), "phone": mask_phone(self.phone), "zip": self.zip_code}
        if self.pccc.startswith("O"):
            d.update(order_no=self.order_no, ordered_at=self.ordered_at, otp="***" if self.otp else None)
        return d


@dataclass
class PcccResult:
    status: str                         # ok · mismatch · missing · error
    message: str
    reasons: list[str] = field(default_factory=list)
    valid_to: date | None = None
    t_cnt: int | None = None
    email_verified: str | None = None
    called: bool = False                # 관세청을 실제로 불렀는지


def precheck(inp: PcccInput) -> PcccResult | None:
    """관세청에 보내기 전에 걸러낼 것 — 빠진 값 · 형식 오류. 문제가 없으면 None."""
    missing = [k for k, v in (("통관부호", inp.pccc), ("이름", inp.name), ("전화번호", inp.phone), ("우편번호", inp.zip_code)) if not v]
    if missing:
        return PcccResult("missing", f"{' · '.join(missing)} 없음 — 마켓 주문서에 값이 없어요")
    if not re.fullmatch(r"[PO]\d{12}", inp.pccc):
        return PcccResult("mismatch", "통관부호 형식이 아니에요 (P 또는 O + 숫자 12자리)")
    if not re.fullmatch(r"01\d{8,9}", inp.phone):
        return PcccResult("missing", "휴대전화번호 형식이 아니에요 — 통관 검증은 휴대폰 번호만 받아요")
    if len(inp.zip_code) != 5:
        return PcccResult("missing", f"우편번호가 5자리가 아니에요 ({inp.zip_code}) — 옛 우편번호는 사람이 확인")
    if inp.pccc.startswith("O") and not (inp.order_no and inp.ordered_at and inp.otp):
        return PcccResult("missing", "일회용 통관부호 — 인증번호가 없어 자동 검증을 못 해요")
    return None


def _call(key: str, inp: PcccInput) -> str:
    q = {"crkyCn": key, "persEcm": inp.pccc, "pltxNm": inp.name, "cralTelno": inp.phone, "custPsno": inp.zip_code}
    if inp.pccc.startswith("O"):
        q.update(ordNo=inp.order_no, ordIssDttm=inp.ordered_at, pcccCrtfNo=inp.otp)
    with urllib.request.urlopen(UNIPASS_URL + "?" + urllib.parse.urlencode(q), timeout=20) as r:
        return r.read().decode("utf-8", "ignore")


def parse(xml_text: str) -> PcccResult:
    root = ET.fromstring(xml_text)
    t = root.findtext("tCnt")
    t_cnt = int(t) if t not in (None, "") else None
    reasons = [e.text.strip() for e in root.iter("errMsgCn") if e.text]
    notice = (root.findtext("ntceInfo") or "").strip()
    xp = root.findtext("valtPridXpirDt")
    valid_to = date(int(xp[:4]), int(xp[4:6]), int(xp[6:8])) if xp and len(xp) == 8 else None
    eml = root.findtext("emlCrftCmplYn") or root.findtext("emlCrtfCmplYn")
    if t_cnt == 1:
        return PcccResult("ok", "일치", [], valid_to, t_cnt, eml, True)
    if t_cnt == 0:
        return PcccResult("mismatch", " / ".join(reasons) or notice or "불일치", reasons, valid_to, t_cnt, eml, True)
    return PcccResult("error", notice or "관세청 시스템 응답 오류", reasons, valid_to, t_cnt, eml, True)


async def check_pccc(inp: PcccInput) -> PcccResult:
    pre = precheck(inp)
    if pre:
        return pre
    _, secrets = await credential_values(UNIPASS_SERVICE)
    try:
        text = await asyncio.to_thread(_call, secrets[UNIPASS_KEY_LABEL], inp)
    except (urllib.error.URLError, TimeoutError) as e:
        return PcccResult("error", f"관세청 연결 실패 ({type(e).__name__}) — 나중에 다시 검증", called=True)
    try:
        return parse(text)
    except ET.ParseError:
        return PcccResult("error", "관세청 응답을 읽지 못했어요", called=True)
