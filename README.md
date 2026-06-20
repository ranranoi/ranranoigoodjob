# 채용공고 알리미 (개인용)

사람인 + 원티드에서 매일 오전 8시(KST)에 새 공고를 모아서 적합도를 채점하고,
조건에 맞는 공고만 이메일로 보내주는 개인용 자동화 봇입니다.

## 동작 방식
1. GitHub Actions가 매일 08:00 KST에 자동 실행
2. 사람인 Open API(키가 있을 때만) + 원티드 검색에서 키워드별 공고 수집
   → **사람인 키가 아직 없어도 괜찮습니다.** 원티드만으로 우선 작동하고, 나중에 사람인 키를 Secrets에 추가하면 자동으로 합쳐집니다.
3. 근무지(서울/판교/정자)·경력조건으로 1차 필터링
4. Gemini API가 후보자 프로필(`candidate_profile.txt`)과 비교해 0~100점 채점
5. 70점 이상 + 처음 보는 공고만 골라 이메일 발송
6. 한 번 채점한 공고는 `seen_jobs.json`에 기록되어 다시 보내지 않음

---

## 설정 단계

### 1. GitHub 저장소 만들기
1. github.com에서 새 저장소 생성 (Private 권장 — 개인정보가 들어가진 않지만 안전하게)
2. 이 폴더(zip 압축 해제한 내용) 전체를 그대로 저장소에 업로드
   - `.github/workflows/job_alert.yml` 경로가 반드시 그대로 유지되어야 합니다.

### 2. Gemini API 키 발급 (먼저 진행 — 무료)
1. https://aistudio.google.com/apikey 접속 → 구글 계정으로 로그인
2. "Create API key" 클릭 → 새 프로젝트 또는 기존 프로젝트 선택 후 키 생성
3. 생성된 키를 복사 (`AIza...`로 시작)
   - 채점 1건당 호출 1회, 하루 50~100건 내외는 무료 한도 안에서 충분히 처리됩니다.
   - 다만 Google의 무료 한도/모델 가용성은 시점에 따라 바뀔 수 있으니, 만약 스크립트 로그에 모델 관련 오류가 보이면
     https://ai.google.dev/gemini-api/docs/pricing 에서 현재 무료로 쓸 수 있는 모델명을 확인하고
     `job_alert.py`의 `GEMINI_MODEL` 기본값(`gemini-2.5-flash`)을 그 모델명으로 바꿔주세요.

### 3. 사람인 API 키 발급 (시간 걸리면 나중에 해도 됨)
1. https://oapi.saramin.co.kr 접속 → 회원가입/로그인
2. "이용신청" → 앱 등록 (개인 프로젝트 용도로 작성하면 됩니다)
3. 승인 후 발급되는 **access-key**를 복사
   - **승인 전까지는 이 단계를 건너뛰어도 됩니다.** `SARAMIN_API_KEY` Secret을 아예 등록하지 않으면
     스크립트가 자동으로 사람인 수집을 건너뛰고 원티드 결과만으로 정상 작동합니다.
   - 나중에 키가 발급되면 Secret만 추가하면 되고, 코드는 그대로 두면 됩니다.

### 4. Gmail 앱 비밀번호 발급 (ranplus7@gmail.com)
일반 Gmail 비밀번호로는 발송이 안 되고, **앱 비밀번호**가 따로 필요합니다.
1. 구글 계정 → 보안 → 2단계 인증을 먼저 켜야 합니다 (필수)
2. 구글 계정 → 보안 → "앱 비밀번호" 메뉴 진입
   (직접 링크: https://myaccount.google.com/apppasswords)
3. 앱 이름을 아무거나 입력(예: job-alert) 후 생성 → 16자리 비밀번호 복사
   - 이 16자리가 `GMAIL_APP_PASSWORD`입니다. 평소 쓰는 Gmail 비밀번호가 아닙니다.

### 5. GitHub 저장소에 Secrets 등록
저장소 → Settings → Secrets and variables → Actions → "New repository secret"

다음을 등록하세요 (`SARAMIN_API_KEY`는 발급 전이면 생략 가능):

| Secret 이름 | 값 | 필수 여부 |
|---|---|---|
| `GEMINI_API_KEY` | 2번에서 발급받은 Gemini API 키 | 필수 |
| `GMAIL_USER` | `ranplus7@gmail.com` | 필수 |
| `GMAIL_APP_PASSWORD` | 4번에서 발급받은 16자리 앱 비밀번호 | 필수 |
| `RECEIVER_EMAIL` | `ranplus7@gmail.com` | 필수 |
| `SARAMIN_API_KEY` | 3번에서 발급받은 사람인 access-key | 나중에 추가해도 됨 |

### 6. 테스트 실행
1. 저장소 → Actions 탭 → "Daily Job Alert" 워크플로 선택
2. 우측 "Run workflow" 버튼으로 수동 실행 (cron 시간까지 기다릴 필요 없음)
3. 실행 로그에서 사람인/원티드 수집 건수, 채점 결과를 확인 가능
4. 정상이면 메일함(스팸함도 확인!) 도착

이후로는 매일 08:00 KST에 자동으로 실행됩니다.

---

## 커스터마이징

- **채점 기준 점수 조정**: `job_alert.py`의 `SCORE_THRESHOLD` (기본 70점)
  → 너무 적게 오면 낮추고, 너무 많이 오면 높이세요.
- **검색 키워드 추가/수정**: `job_alert.py`의 `SEARCH_KEYWORDS` 리스트
- **근무지 조건 변경**: `LOCATION_OK_TOKENS` 리스트 (예: 판교 외 다른 지역 추가 시)
- **후보자 프로필 변경**: `candidate_profile.txt` — 이직 우선순위나 조건이 바뀌면 이 파일만 수정하면 됩니다.
- **공고가 없는 날도 메일 받고 싶다면**: Secrets에 `SEND_EMPTY_EMAIL` = `true` 추가

---

## 알아두면 좋은 점 (한계)

- **잡코리아는 제외**: 공식 API가 개인에게는 거의 승인되지 않아 포함하지 않았습니다.
- **기업 규모(직원 100명 이상) 자동 필터는 완벽하지 않음**: 사람인/원티드 공개 API 응답에 직원 수 필드가 없어서,
  Gemini가 회사명과 알려진 정보를 바탕으로 "추정 채점"합니다. 작은 회사가 가끔 섞여 들어올 수 있으니
  메일에서 회사명을 한 번 더 확인하는 걸 권장합니다.
- **원티드는 비공식 API**: 원티드가 내부 구조를 바꾸면 어느 날 갑자기 수집이 안 될 수 있습니다.
  이 경우 Actions 로그에 경고만 찍히고 스크립트 자체는 멈추지 않으며, 사람인 결과만이라도 정상 발송됩니다.
- **개인 용도로만 사용**: 호출량이 적어 문제될 가능성은 낮지만, 대량 수집/재배포는 피하세요.
