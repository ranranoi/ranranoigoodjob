"""
개인용 채용공고 알리미
- 사람인 Open API + 원티드(공개 검색 엔드포인트)에서 공고를 수집
- 키워드/지역/경력 1차 필터링
- Claude API로 후보자 프로필과의 적합도(0~100점) 2차 판단
- 기준 점수 이상인 신규 공고만 골라 이메일로 발송
- 이미 보낸 공고는 seen_jobs.json에 기록해 중복 발송 방지

개인 용도로만 사용하세요. 사람인 API는 공식 발급 키를 쓰지만,
원티드 엔드포인트는 비공식이라 호출량을 적게 유지하고, 언제든 깨질 수 있다는 점을 감안하세요.
"""

import os
import sys
import json
import time
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ---------------------------------------------------------------------------
# 설정 (환경변수 / 시크릿으로 주입됨 — GitHub Actions의 secrets 참고)
# ---------------------------------------------------------------------------
SARAMIN_API_KEY = os.environ.get("SARAMIN_API_KEY", "")  # 아직 없으면 비워둬도 됨 (사람인만 건너뜀)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL", "ranplus7@gmail.com")

SEEN_JOBS_PATH = os.path.join(os.path.dirname(__file__), "seen_jobs.json")
PROFILE_PATH = os.path.join(os.path.dirname(__file__), "candidate_profile.txt")

SCORE_THRESHOLD = int(os.environ.get("SCORE_THRESHOLD", "70"))
SEND_EMPTY_EMAIL = os.environ.get("SEND_EMPTY_EMAIL", "false").lower() == "true"

# 검색 키워드 (사람인 / 원티드 공통으로 사용)
SEARCH_KEYWORDS = [
    "서비스기획",
    "프로덕트매니저",
    "프로덕트오너",
    "PM",
    "프로덕트디자이너",
    "UX디자이너",
    "UI디자이너",
    "UIUX디자이너",
]

LOCATION_OK_TOKENS = ["서울", "분당", "판교", "정자", "성남"]


# ---------------------------------------------------------------------------
# 유틸
# ---------------------------------------------------------------------------
def load_seen():
    try:
        with open(SEEN_JOBS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"saramin": [], "wanted": []}


def save_seen(seen):
    with open(SEEN_JOBS_PATH, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)


def location_ok(location_text: str) -> bool:
    if not location_text:
        return False
    return any(token in location_text for token in LOCATION_OK_TOKENS)


# ---------------------------------------------------------------------------
# 1. 사람인 Open API 수집
# ---------------------------------------------------------------------------
def fetch_saramin_jobs():
    if not SARAMIN_API_KEY:
        print("[경고] SARAMIN_API_KEY가 없어 사람인 수집을 건너뜁니다.")
        return []

    jobs = []
    for keyword in SEARCH_KEYWORDS:
        try:
            resp = requests.get(
                "https://oapi.saramin.co.kr/job-search",
                params={
                    "access-key": SARAMIN_API_KEY,
                    "keywords": keyword,
                    "count": 50,
                    "sort": "pd",  # 게시일 역순(최신순)
                },
                headers={"Accept": "application/json"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            job_list = data.get("jobs", {}).get("job", [])
            if isinstance(job_list, dict):  # 결과가 1건이면 dict로 옴
                job_list = [job_list]

            for job in job_list:
                position = job.get("position", {})
                location = (position.get("location") or {}).get("name", "")
                if not location_ok(location):
                    continue

                exp = position.get("experience-level", {}) or {}
                exp_max = exp.get("max")
                # 신입 전용(0~0년) 공고는 5년차에게 부적합하므로 제외
                try:
                    if exp_max is not None and int(exp_max) == 0 and exp.get("code") not in (3, "3", 0, "0"):
                        continue
                except (ValueError, TypeError):
                    pass

                jobs.append(
                    {
                        "source": "saramin",
                        "id": str(job.get("id")),
                        "title": position.get("title", ""),
                        "company": (job.get("company", {}) or {}).get("name", ""),
                        "location": location,
                        "experience": exp.get("name", ""),
                        "url": job.get("url", ""),
                        "keyword": job.get("keyword", ""),
                    }
                )
        except Exception as e:
            print(f"[경고] 사람인 검색 실패 (키워드: {keyword}): {e}")
        time.sleep(0.5)  # API 호출 간격

    return jobs


# ---------------------------------------------------------------------------
# 2. 원티드 공개 검색 엔드포인트 수집 (비공식 — 실패해도 전체 스크립트는 계속 진행)
# ---------------------------------------------------------------------------
def fetch_wanted_jobs():
    jobs = []
    headers = {
        "User-Agent": "Mozilla/5.0 (personal job alert script)",
        "Accept": "application/json",
    }
    for keyword in SEARCH_KEYWORDS:
        try:
            resp = requests.get(
                "https://www.wanted.co.kr/api/v4/jobs",
                params={
                    "query": keyword,
                    "country": "kr",
                    "job_sort": "job.latest_order",
                    "years": -1,
                    "limit": 20,
                    "offset": 0,
                },
                headers=headers,
                timeout=15,
            )
            if resp.status_code != 200:
                print(f"[경고] 원티드 응답 코드 {resp.status_code} (키워드: {keyword}) — 건너뜀")
                continue
            data = resp.json()
            for job in data.get("data", []):
                address = job.get("address", {}) or {}
                location = address.get("location", "") or address.get("full_location", "")
                if not location_ok(location):
                    continue

                job_id = str(job.get("id"))
                title = job.get("position", "")
                company = (job.get("company", {}) or {}).get("name", "")

                jobs.append(
                    {
                        "source": "wanted",
                        "id": job_id,
                        "title": title,
                        "company": company,
                        "location": location,
                        "experience": "",  # 원티드 검색 응답에는 상세 경력조건이 없는 경우가 많음
                        "url": f"https://www.wanted.co.kr/wd/{job_id}",
                        "keyword": keyword,
                    }
                )
        except Exception as e:
            print(f"[경고] 원티드 검색 실패 (키워드: {keyword}): {e} — 원티드는 비공식 API라 발생할 수 있습니다.")
        time.sleep(0.5)

    return jobs


# ---------------------------------------------------------------------------
# 3. Gemini API로 적합도 채점
# ---------------------------------------------------------------------------
def load_profile():
    with open(PROFILE_PATH, "r", encoding="utf-8") as f:
        return f.read()


def score_job_with_gemini(job, profile_text):
    if not GEMINI_API_KEY:
        print("[경고] GEMINI_API_KEY가 없어 적합도 채점을 건너뜁니다 (모두 통과 처리).")
        return 100, "AI 채점 비활성화 상태(키 없음)"

    prompt = f"""아래는 구직자의 프로필과 채용공고 정보입니다.
이 공고가 구직자에게 얼마나 적합한지 0~100점으로 채점하고, 한 줄 이유를 작성해주세요.

[구직자 프로필]
{profile_text}

[채용공고]
- 제목: {job['title']}
- 회사명: {job['company']}
- 근무지: {job['location']}
- 경력조건: {job.get('experience', '명시 없음')}
- 출처: {job['source']}
- 키워드: {job.get('keyword', '')}

반드시 아래 JSON 형식으로만 답하세요. 다른 텍스트는 절대 포함하지 마세요.
{{"score": 0-100 사이 정수, "reason": "한 줄 이유 (한국어, 50자 이내)"}}
"""

    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
            params={"key": GEMINI_API_KEY},
            headers={"content-type": "application/json"},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",  # JSON 강제 출력 → 파싱 실패 줄임
                    "temperature": 0.2,
                },
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()

        # 혹시 코드블록(```json ... ```)으로 감싸져 오는 경우 대비
        text = text.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(text)
        return int(parsed.get("score", 0)), parsed.get("reason", "")
    except Exception as e:
        print(f"[경고] Gemini 채점 실패 ({job['title']}): {e}")
        return 0, "채점 실패"


# ---------------------------------------------------------------------------
# 4. 이메일 발송
# ---------------------------------------------------------------------------
def build_email_html(scored_jobs):
    rows = ""
    for job, score, reason in scored_jobs:
        rows += f"""
        <tr>
          <td style="padding:10px;border-bottom:1px solid #eee;">
            <div style="font-weight:bold;font-size:15px;">
              <a href="{job['url']}" style="color:#1a73e8;text-decoration:none;">{job['title']}</a>
            </div>
            <div style="color:#555;font-size:13px;margin-top:4px;">
              {job['company']} · {job['location']} · {job.get('experience') or '경력조건 미상'} · 출처: {job['source']}
            </div>
            <div style="color:#888;font-size:13px;margin-top:4px;">
              적합도 {score}점 — {reason}
            </div>
          </td>
        </tr>
        """

    return f"""
    <html>
      <body style="font-family:-apple-system,sans-serif;">
        <h2>오늘의 추천 채용공고 ({len(scored_jobs)}건)</h2>
        <table style="width:100%;border-collapse:collapse;">
          {rows}
        </table>
        <p style="color:#999;font-size:12px;margin-top:20px;">
          이 메일은 개인용 채용공고 알리미 스크립트가 자동 발송했습니다.
        </p>
      </body>
    </html>
    """


def send_email(scored_jobs):
    if not scored_jobs and not SEND_EMPTY_EMAIL:
        print("새 공고가 없어 이메일을 발송하지 않습니다.")
        return

    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print("[경고] GMAIL_USER / GMAIL_APP_PASSWORD가 없어 이메일을 발송할 수 없습니다.")
        return

    subject = f"[채용공고 알리미] 오늘의 추천 공고 {len(scored_jobs)}건"
    if not scored_jobs:
        subject = "[채용공고 알리미] 오늘은 조건에 맞는 새 공고가 없어요"

    html_body = build_email_html(scored_jobs) if scored_jobs else "<p>오늘은 조건에 맞는 새 공고가 없었습니다.</p>"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = RECEIVER_EMAIL
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, [RECEIVER_EMAIL], msg.as_string())

    print(f"이메일 발송 완료: {len(scored_jobs)}건")


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------
def main():
    seen = load_seen()
    profile_text = load_profile()

    print("사람인 공고 수집 중...")
    saramin_jobs = fetch_saramin_jobs()
    print(f"사람인 1차 필터 통과: {len(saramin_jobs)}건")

    print("원티드 공고 수집 중...")
    wanted_jobs = fetch_wanted_jobs()
    print(f"원티드 1차 필터 통과: {len(wanted_jobs)}건")

    all_jobs = saramin_jobs + wanted_jobs

    # 신규 공고만 필터링 (이미 보낸 공고 제외)
    new_jobs = [j for j in all_jobs if j["id"] not in seen.get(j["source"], [])]
    print(f"신규 공고: {len(new_jobs)}건")

    scored_jobs = []
    for job in new_jobs:
        score, reason = score_job_with_gemini(job, profile_text)
        print(f"  - [{score}점] {job['title']} ({job['company']}) — {reason}")
        if score >= SCORE_THRESHOLD:
            scored_jobs.append((job, score, reason))
        # 점수와 무관하게 한 번 채점한 공고는 다시 보내지 않도록 seen에 기록
        seen.setdefault(job["source"], []).append(job["id"])
        time.sleep(0.3)

    scored_jobs.sort(key=lambda x: x[1], reverse=True)

    send_email(scored_jobs)
    save_seen(seen)


if __name__ == "__main__":
    main()
