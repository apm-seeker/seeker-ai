# seeker-ai

seeker APM 데이터를 자연어로 조회하는 FastAPI 챗봇.
사용자 질문을 받아 [seeker-web](../seeker-web) REST API를 LangChain 도구로 호출하고, Google Gemini가 답변을 생성한다.

대화 목록과 메시지 히스토리는 MySQL에 영속화되며, 응답은 SSE 스트리밍.

## 구성 요소

- **FastAPI**: HTTP 엔드포인트, SSE 스트림
- **LangGraph** `create_react_agent`: 도구 호출 루프
- **Google Gemini**: 외부 LLM (`gemini-2.0-flash` 기본)
- **MySQL**: 대화/메시지 영속화 (`seeker_ai` DB)
- **seeker-web**: APM 데이터 소스 (`localhost:8080`)

## 사전 요구사항

| 항목 | 설명 |
|---|---|
| Python | 3.11 이상 |
| MySQL | 8.0 이상. `seeker-mysql` 컨테이너 또는 로컬 인스턴스 |
| Google Gemini API key | [Google AI Studio](https://aistudio.google.com/apikey)에서 발급 |
| seeker-web (선택) | 챗봇이 실제 데이터를 조회할 때 필요. 미기동이어도 서버는 동작 |

## 빠른 시작

### 1. 가상환경 생성 및 의존성 설치 (Windows PowerShell)

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

### 2. `.env` 파일 작성

`.env.example`을 복사해 `.env`로 만들고 값을 채운다.

```powershell
Copy-Item .env.example .env
```

최소한 다음 값을 설정한다.

```
GOOGLE_API_KEY=<your-gemini-api-key>
```

DB/seeker-web이 기본 위치가 아니라면 `DATABASE_URL`, `SEEKER_WEB_BASE_URL`도 조정.

### 3. MySQL에 `seeker_ai` DB 생성

```powershell
docker exec -it seeker-mysql mysql -uroot -proot -e "CREATE DATABASE IF NOT EXISTS seeker_ai CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

또는 호스트에서 직접:

```powershell
mysql -h 127.0.0.1 -u root -proot -e "CREATE DATABASE IF NOT EXISTS seeker_ai CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

### 4. 마이그레이션

```powershell
.venv\Scripts\python.exe -m alembic upgrade head
```

→ `conversations`, `messages`, `alembic_version` 테이블이 생성된다.

### 5. 서버 실행

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

- 헬스체크: http://127.0.0.1:8000/healthz
- Swagger: http://127.0.0.1:8000/docs

## 환경변수 레퍼런스

`.env` 파일 또는 OS 환경변수로 설정. 이름은 대소문자 무관(`pydantic-settings`가 흡수).

| 이름 | 기본값 | 설명 |
|---|---|---|
| `APP_ENV` | `local` | 환경 식별자 (`local`, `staging`, `prod` 등). `/healthz` 응답에 노출 |
| `LOG_LEVEL` | `INFO` | 로깅 레벨 |
| `DATABASE_URL` | `mysql+aiomysql://root:root@127.0.0.1:3306/seeker_ai` | SQLAlchemy 비동기 DSN. 마이그레이션은 자동으로 `pymysql`로 변환 |
| `SEEKER_WEB_BASE_URL` | `http://127.0.0.1:8080` | seeker-web 베이스 URL |
| `SEEKER_WEB_TIMEOUT_SEC` | `10` | seeker-web HTTP 타임아웃 (초) |
| `LLM_MODEL` | `google_genai:gemini-2.0-flash` | `init_chat_model`이 해석하는 provider:model 문자열 |
| `GOOGLE_API_KEY` | (없음) | Gemini API 키. **필수** — 미설정 시 채팅 호출이 `error` 이벤트로 실패 |
| `DEFAULT_USER_ID` | `default` | v1 단일 사용자 ID. 멀티유저 도입 시 헤더로 대체 예정 |

## API 엔드포인트

### 대화 관리

| 메서드 | 경로 | 설명 |
|---|---|---|
| `POST` | `/conversations` | 새 대화 생성. Body: `{"title": "..."}` (선택) |
| `GET` | `/conversations?limit=50&offset=0` | 대화 목록 (보관 제외, `updated_at` 내림차순) |
| `GET` | `/conversations/{id}` | 대화 메타 |
| `PATCH` | `/conversations/{id}` | 제목 변경. Body: `{"title": "..."}` |
| `DELETE` | `/conversations/{id}` | 소프트 삭제 (`archived_at` 세팅) |
| `GET` | `/conversations/{id}/messages?limit=200&offset=0` | 대화의 메시지 목록 |

### 채팅 (SSE 스트리밍)

```
POST /conversations/{id}/messages
Content-Type: application/json

{"content": "지난 1시간 가장 느린 서비스 알려줘"}
```

응답은 `text/event-stream`. 이벤트 타입:

| event | data | 의미 |
|---|---|---|
| `user_message` | `{id, role, content, created_at}` | 영속화된 사용자 메시지 |
| `ai_message` | `{id, role, content, tool_calls, ...}` | LLM이 생성한 어시스턴트 메시지 (도구 호출 포함 가능) |
| `tool_message` | `{id, role, content, tool_call_id, tool_name}` | 도구 실행 결과 |
| `error` | `{detail}` | 스트림 중 발생한 오류 |
| `done` | `{}` | 정상 종료 |

대화의 첫 사용자/어시스턴트 턴이 완료되면 백그라운드에서 Gemini가 5~20자 제목을 생성해 `conversations.title`을 채운다. 이미 제목이 있으면 건너뜀.

### 사용 예 (curl)

```powershell
# 1. 대화 생성
$conv = (Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/conversations -ContentType 'application/json' -Body '{}').id

# 2. 스트리밍 채팅 (curl을 권장 — Invoke-RestMethod는 SSE를 잘 못 다룸)
curl.exe -N -X POST "http://127.0.0.1:8000/conversations/$conv/messages" `
  -H "Content-Type: application/json" `
  -d '{\"content\":\"지난 1시간 가장 느린 서비스 알려줘\"}'
```

## 프로젝트 구조

```
app/
├── main.py             FastAPI 엔트리 + lifespan
├── config.py           pydantic-settings 기반 Settings
├── deps.py             DB session / current_user_id 의존성
├── api/
│   └── conversations.py CRUD + 스트리밍 채팅 라우트
├── db/
│   ├── base.py         DeclarativeBase
│   ├── session.py      async engine / session 팩토리
│   └── models.py       Conversation / Message
├── repositories/
│   ├── conversation_repo.py
│   └── message_repo.py
├── schemas/
│   ├── conversation.py CRUD DTO
│   ├── message.py      MessageCreate / Read
│   └── seeker.py       seeker-web 응답 모델
├── services/
│   ├── chat_service.py SSE 스트림 오케스트레이션
│   └── title_service.py 백그라운드 제목 생성
├── llm/
│   ├── provider.py     init_chat_model 래퍼
│   ├── prompts.py      system prompt + 현재 시각 주입
│   ├── message_mapper.py DB ↔ LangChain BaseMessage 변환
│   └── graph.py        create_react_agent 빌더
├── tools/
│   ├── seeker_client.py httpx 비동기 클라이언트 (7개 메서드)
│   └── seeker_tools.py 7개 LangChain @tool 정의
└── utils/
    └── ids.py          UUID 발급

alembic/
├── env.py              async URL → sync 변환해서 마이그레이션
└── versions/
    └── 0001_init.py    conversations + messages 테이블
```

## 트러블슈팅

- **`API key required for Gemini Developer API`** → `.env`에 `GOOGLE_API_KEY` 설정 후 서버 재시작.
- **`(2003, "Can't connect to MySQL server on '127.0.0.1'")`** → `docker compose up -d` 또는 `seeker-mysql` 기동 여부 확인.
- **채팅 호출 시 도구가 항상 `network error`로 실패** → seeker-web이 안 떠 있음. `../seeker-web`을 실행하거나 `SEEKER_WEB_BASE_URL`을 올바른 호스트로 변경.
- **윈도우 콘솔에서 한글 깨짐** → 데이터는 정상. 콘솔 cp949 표시 문제. `chcp 65001` 또는 PowerShell의 UTF-8 모드로 해결.

## 라이선스

내부 사용.
