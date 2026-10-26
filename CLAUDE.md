# 작업 규칙 (사용자 지시, 모든 프로젝트 공통)

## API 비용 절대 금지
- 유료 API 요금이 드는 호출(Anthropic API, OpenAI API, 그 밖의 종량제 API)은 절대 쓰지 않습니다.
- Claude는 로그인한 Claude 구독(Claude Code CLI `claude -p`)으로만, Codex는 ChatGPT 구독 로그인으로만 실행합니다.
  CLI를 띄울 때 `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `OPENAI_API_KEY`, `CODEX_API_KEY`를 환경에서 지웁니다.
- API 키를 코드·설정 파일·저장소에 넣지 않고, 키 값을 화면에 출력하지 않습니다.
- 유료 API가 꼭 필요해 보이면 구현하기 전에 사용자에게 먼저 안내하고 허락을 받습니다.
  사용자의 구독(Claude Pro, ChatGPT Plus, Genspark Plus)으로 할 수 있는 방법을 우선 찾고, 그중 가장 유리한 것을 알려 줍니다.
- 무료 API(네이버 검색광고·검색 API 무료 한도 등)는 그대로 씁니다. 무료 한도를 넘으면 요금이 생기는 경우에도 먼저 안내합니다.

## 그 밖의 공통 규칙
- 사용자에게는 항상 존댓말로, 결과 위주로 간결하게 답합니다. 모르는 것은 모른다고 합니다.
- 네이버 글은 임시저장까지만 하고 발행은 사용자가 직접 합니다.
