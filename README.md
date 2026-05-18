# seeker-ai

seeker APM 데이터를 자연어로 조회하는 FastAPI 챗봇. [seeker-web](../seeker-web) REST API를 LangChain 도구로 호출하고 Gemini가 답한다.

## 기능

- 자연어 질의 → seeker-web 도구 호출 → Gemini 응답 (LangGraph ReAct)
- SSE 스트리밍 (`user_message` / `ai_message` / `tool_message` / `error` / `done`)
- 대화/메시지 MySQL 영속화, 첫 턴 후 자동 제목 생성
- 부팅 시 DB·마이그레이션 자동 적용

## 요구사항

- Python 3.11+
- MySQL 8.0+ (`seeker_ai` DB는 자동 생성)
- Gemini API key ([발급](https://aistudio.google.com/apikey))

## 실행

### Linux / macOS

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env          # GOOGLE_API_KEY 채우기
.venv/bin/uvicorn app.main:app --reload --port 8000
```

### Windows (PowerShell)

```powershell
py -3.12 -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
Copy-Item .env.example .env   # GOOGLE_API_KEY 채우기
.venv\Scripts\uvicorn app.main:app --reload --port 8000
```

- 헬스체크: http://127.0.0.1:8000/healthz
- Swagger: http://127.0.0.1:8000/docs

## 환경변수

| 이름 | 기본값 | 비고 |
|---|---|---|
| `GOOGLE_API_KEY` | — | **필수** |
| `DATABASE_URL` | `mysql+aiomysql://root:root@127.0.0.1:3306/seeker_ai` | |
| `SEEKER_WEB_BASE_URL` | `http://127.0.0.1:8080` | |
| `LLM_MODEL` | `google_genai:gemini-2.0-flash` | |
| `APP_ENV` / `LOG_LEVEL` | `local` / `INFO` | |

## API

| 메서드 | 경로 | 설명 |
|---|---|---|
| `POST` | `/conversations` | 대화 생성 |
| `GET` | `/conversations` | 목록 |
| `GET` `PATCH` `DELETE` | `/conversations/{id}` | 조회 / 제목 변경 / 소프트 삭제 |
| `GET` | `/conversations/{id}/messages` | 메시지 목록 |
| `POST` | `/conversations/{id}/messages` | 채팅 (SSE) |
