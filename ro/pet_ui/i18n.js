/* 화면 언어. 원문은 그대로 두고(기능 화면은 한국어, 꾸미기 화면은 영어로 쓰여 있다) 보일 때 한 언어로 맞춘다.
   en: 한국어 원문 → 영어 · ko: 영어 원문 → 한국어 · source: 손대지 않음(테스트가 원문을 본다).
   언어는 상태창이 아니라 설정(⋯ 메뉴의 Language)에서 고른다. 표에 없는 문장은 원문 그대로 보인다. */
const RO_LANG = "__RO_LANG__";
const RoI18n = (() => {
  const HAN = /[가-힣]/;
  const KO_EN = {
    // ro pro 확인 카드·배운 것(RO-AUD-108)
    "고른 것 적용": "Apply selected", "고정": "Pin", "고정됨": "Pinned", "고정 풀기": "Unpin", "꺼 둠": "Off", "배움": "Learned",
    "보는 중": "Watching", "지우기": "Erase", "모두 지우기": "Erase all", "정말 모두 지우기": "Yes, erase all",
    "격리": "To holding", "이 Mac 사본 내보내기": "Remove the copy on this Mac",
    "학습 켜기": "Turn on learning", "학습 끄기": "Turn off learning", "먼저 알림 켜기": "Turn on heads-ups", "먼저 알림 끄기": "Turn off heads-ups",
    "되돌리지 못했어요.": "Couldn't undo.", "카드를 열지 못했어요.": "Couldn't open the card.", "배운 것을 읽지 못했어요.": "Couldn't read what ro learned.",
    "아직 배운 것이 없어요.": "Nothing learned yet.", "학습을 켜기 전에는 아무것도 배우지 않아요.": "ro learns nothing until you turn learning on.",
    "격리한 것은 ~/.ro/cleanup/trash에 있고 되돌릴 수 있어요. 이 Mac 사본 내보내기는 iCloud에 남고 다시 내려받을 수 있어요.":
      "Held items stay in ~/.ro/cleanup/trash and can be undone. Removing the copy on this Mac keeps the file in iCloud, and you can download it again.",
    "확장자·시간대·폴더 위치 같은 통계만 이 Mac(~/.ro)에 남겨요. 파일 이름·경로·내용은 남기지 않고, 서로 다른 3일에 보인 것만 배워요.":
      "Only stats like file types, times of day, and folder locations stay on this Mac (~/.ro). File names, paths, and contents are never kept, and ro only learns what it sees on 3 different days.",
    "확장자": "File type", "찾는 종류": "Searched kind", "시간대": "Time of day", "폴더": "Folder", "사라진 폴더": "Missing folder",
    "새벽": "Late night", "오전": "Morning", "오후": "Afternoon", "저녁": "Evening",
    "찾기 헤맴": "Searching around", "옛 판본": "Old version", "용량 부족": "Low space", "설치 파일": "Installer",
    "중복 파일": "Duplicate file", "다운로드 묶음": "Download batch", "도구 전환": "Tool switch",
    "통과": "on track", "표본 부족": "not enough data yet", "M5 목표 미달": "below target", "개정 전으로 되돌리기 검토": "review: may turn heads-ups back",
    "설치 파일 격리": "Hold installer", "압축 원본 격리": "Hold unpacked archive", "중복 정리 카드": "Duplicate cleanup card",
    "정리 후보 보기": "See tidy candidates", "인수인계 보기": "See handoff",
    "같은 이름의 폴더가 풀려 있음": "A folder with a matching name is unpacked",
    "내용이 같은 중복 사본": "Duplicate copy with identical content",
    "확인 카드 · 용량 정리 후보": "Confirm card & space cleanup",
    "용량 정리 후보": "Space cleanup candidates", "파일 정리 후보": "File tidy candidates",
    "확인 카드로 정리": "Tidy with confirm card", "ro pro 시작 설정": "ro pro setup", "ro pro 시작하기": "Get started with ro pro", "ro가 배운 것 · 먼저 알림": "What ro learned · Heads-ups",
    "배운 것 보기": "View learned", "알림 힌트": "Heads-up hint", "지금 정리할 파일이 없어요": "Nothing to tidy right now",
    "동의를 켜기 전에는 배우거나 먼저 알리지 않아요.": "ro won't learn or nudge until you turn it on.",
    "동의를 켜기 전에는 배우거나 먼저 알리지 않아요. 파일 이름·본문은 남기지 않아요.": "ro won't learn or nudge until you turn it on. File names and contents are never kept.",
    "Finder 이동·열린 문서 감지를 쓰려면 시스템 설정 > 개인정보 보호 및 보안 > 손쉬운 사용에서 ro를 허용해 주세요.": "To detect Finder hops and open documents, allow ro in System Settings > Privacy & Security > Accessibility.",
    "죽은 빌드 폴더·남은 설치 파일·iCloud 사본 정리 카드 열기": "Open space cleanup card (stale builds, installers, iCloud copies)",
    "다운로드 파일 정리 확인 카드 열기(C안 · 저널 V2 되돌리기)": "Open Downloads tidy confirm card (Journal V2 undo)",
    "이름이 맞는 앱이 설치돼 있음": "An app with a matching name is installed",
    "설치 파일을 격리했어요 · 되돌리기는 카드에서": "Moved the installer to holding · undo from the card", "격리하지 못했어요": "Couldn't move it to holding",
    "지금 치울 만한 후보를 찾지 못했어요": "Found nothing worth clearing right now", "Finder에서 보여 주지 못했어요": "Couldn't show it in Finder",
    "카드가 없거나 시간이 지났어요.": "The card is gone or has expired.", "알 수 없는 요청이에요.": "Unknown request.",
    // 홈
    "확인할 일": "To review", "확인할 일이 있어요": "Needs your review", "정상 동작 중": "All good",
    "오늘 새로 시작했어요.": "A fresh start today.", "기록이 시작되면 여기에 요약이 표시됩니다": "Your summary shows up here once you log something",
    "보기": "View", "최근 기록": "Recent", "통계": "Stats", "기록": "Logged", "프로젝트": "Projects",
    "눌러서 확인할 일 보기": "Show what needs review", "오늘 종류별": "Today by kind", "오늘 타임라인": "Today's timeline",
    "오늘 아직 기록이 없습니다.": "Nothing logged yet today.", "오늘 아직 아무 일도 없었어요.": "Nothing has happened yet today.",
    "기록된 내역이 없습니다.": "Nothing here yet.", "타임라인에서 전체 보기": "See all in Timeline", "다음: ": "Next: ",
    "이 기록의 분류 바꾸기": "Change this entry's project", "없음": "None",
    // 종류 이름(서버)
    "메모": "Note", "활동": "Activity", "질문": "Question", "평가": "Rating", "펫": "Pet", "펫 시작": "Pet started", "라이선스를 받아 pro로 다시 시작": "Restarted as pro", "라이선스 변경으로 다시 시작": "Restarted after a plan change", "정리": "Tidy", "정리안": "Tidy plan",
    "정리 수정": "Plan edit", "보관함 비움": "Holding emptied", "실행 취소": "Cancelled", "점검": "Check", "요약 전송": "Summary sent",
    "수집": "Collect", "규칙 승인": "Rule approved", "규칙 거절": "Rule rejected", "이름 없음": "Untitled",
    "지도": "Map", "평가 실행": "Eval", "벤치": "Bench", "용량": "Storage", "인수인계": "Handoff", "인수인계 평가": "Handoff rating",
    "새 기록": "new note",
    // 정리 탭
    "다운로드 정리 (승인 전에는 옮기지 않음)": "Tidy Downloads (nothing moves until you approve)",
    "정리안이 없습니다. 먼저 정리안을 만드세요.": "No plan yet. Make a plan first.", "정리안 만들기": "Make a plan",
    "정리안 다시 만들기": "Remake the plan", "되돌리기": "Undo", "파일 목록 보기": "Show files",
    "목록을 불러오지 못했어요. 정리안을 다시 만들어 주세요.": "Couldn't load the list. Remake the plan.",
    "아래 확인 카드에서 승인하면 실행합니다.": "Approve in the card below to run it.",
    "아래 확인 카드에서 승인하면 되돌립니다.": "Approve in the card below to undo it.",
    "지금은 옮기거나 치울 파일이 없습니다.": "Nothing to move or clear right now.",
    "직접 분류하려면 터미널에서": "To sort them yourself, run in Terminal", "로 비울 수 있어요.": " can empty it.",
    "옮기기": "Move", "보관함으로": "To holding",
    "정리안을 만드는 중... (파일은 옮기지 않습니다)": "Making a plan… (no files are moved)",
    "정리안을 새로 만들었습니다.": "Made a new plan.", "정리안을 만들지 못했어요.": "Couldn't make a plan.",
    "서버에 연결하지 못해 정리안을 만들지 못했어요. 다시 시도해 주세요.": "Couldn't reach the server, so no plan was made. Try again.",
    "서버에 연결하지 못했어요. 다시 시도해 주세요.": "Couldn't reach the server. Try again.",
    "서버에 연결하지 못했어요. 실행 여부를 확인한 뒤 다시 시도해 주세요.": "Couldn't reach the server. Check whether it ran, then try again.",
    "서버에 연결하지 못했어요.": "Couldn't reach the server.",
    "문서": "Docs", "재무": "Finance", "계약·서류": "Contracts", "학습·자료": "Study", "표·데이터": "Sheets and data",
    "이미지": "Images", "이미지/스크린샷": "Screenshots", "웹페이지": "Web pages", "압축·설치": "Archives and installers", "기타": "Other",
    "보관함": "Holding", "중복": "Duplicates", "풀린 압축": "Unpacked archives", "옛 버전": "Old versions", "오래됨": "Stale", "직접 지정": "Picked by you",
    // 실행 전 확인
    "실행 전 확인": "Confirm before running", "처리할 파일 전체 목록(스크롤)": "Every file this will touch (scroll)",
    "승인하고 실행": "Approve and run", "취소": "Cancel",
    "대기 중인 쓰기 요청이 없습니다.": "Nothing is waiting for approval.",
    "확인 카드가 바뀌었어요. 지금 보이는 요청을 다시 확인해 주세요.": "The card changed. Check the request shown now.",
    "쓰기 작업을 취소했습니다.": "Cancelled. Nothing was changed.",
    "지원하지 않는 쓰기 요청이라 실행하지 않았어요.": "That request isn't supported, so nothing ran.",
    "이 종류의 치울 후보가 없습니다. 정리안을 먼저 만드세요.": "Nothing of this kind to clear. Make a plan first.",
    "이 카테고리에 옮길 항목이 없습니다. 정리안을 먼저 만드세요.": "Nothing to move in this category. Make a plan first.",
    "되돌릴 정리 기록이 없습니다.": "Nothing to undo.",
    "승인 요청 뒤에 정리안이 바뀌었습니다(파일·이름·위치). 다시 요청하세요.": "The plan changed after you asked (files, names, or places). Ask again.",
    // 안내 카드·입력
    "안내": "What next", "어떻게 할까요? ro는 기록과 파일 찾기를 하고, 질문은 AI 도구로 넘겨요.": "What should ro do? It logs and finds files. Questions go to an AI tool.",
    "기록으로만 남기기": "Just log it", "내 파일에서 이름·내용으로 찾아요": "Searches your files by name and content",
    "내 파일에서 찾기": "Find in my files", "Claude·Codex·Antigravity로 넘겨요": "Hands off to Claude, Codex, or Antigravity",
    "AI로 넘기기": "Hand off to AI", "기록하거나 파일을 찾아보세요 · / 명령": "Log or find a file · / for commands",
    "기록하거나 찾기": "Log or find", "직접 기록": "Logged by you", "끌어다 놓은 텍스트": "Dropped text", "링크": "Link",
    // 팔레트·명령
    "명령 팔레트": "Command palette", "명령을 고르거나 기록·파일 검색어를 쓰세요": "Pick a command, or type to search logs and files",
    "명령 목록": "Commands", "명령": "Commands", "최근 입력": "Recent", "입력": "Typed", "다시": "Again",
    "이동": "move", "실행": "run", "닫기": "close", "고르기": "pick", "완성": "complete",
    "맞는 명령이 없어요 · ↵ 그대로 보내기": "No matching command · ↵ send as typed",
    "지금 한 일 한 줄로 남기기": "Log what you just did in a line", "내용": "text",
    "내 파일 찾기 (이름·내용·기간)": "Find my files (name, content, date)", "검색어": "search terms",
    "지난 기록에서 검색": "Search past logs", "오늘 요약 보기": "See today's summary", "오늘 뭐 했지?": "What did I do today?",
    "흩어진 기록을 프로젝트별로 분류 (파일 정리는 '정리' 탭)": "Sort loose logs into projects (file tidying is on the Organize tab)",
    "집중 모드 켜고 끄기": "Turn focus mode on or off",
    "활동 기록 켜기·끄기·상태 (앞 앱·웹 AI 탭 제목만)": "Activity log on, off, or status (front app and web AI tab titles only)",
    "Claude·Codex·Antigravity 연결 상태": "Claude, Codex, and Antigravity connections",
    "하던 작업을 다른 AI로 인수인계 (예: /이어가기 agy claude)": "Hand work off to another AI (e.g. /handoff agy claude)",
    "원래 도구 받을 도구": "from-tool to-tool",
    "Claude Code로 넘기기 (클립보드 + 앱 열기)": "Hand off to Claude Code (clipboard, then open the app)",
    "Codex로 넘기기 (클립보드 + 앱 열기)": "Hand off to Codex (clipboard, then open the app)",
    "Antigravity로 넘기기 (클립보드 + 앱 열기)": "Hand off to Antigravity (clipboard, then open the app)",
    // 기록 토스트
    "기록했어요": "Logged", "기록하지 못했어요": "Couldn't log that", "기록하지 못했어요.": "Couldn't log that.",
    "기록하지 못했어요(서버 연결 실패). 입력은 그대로 남겨 두었어요.": "Couldn't log that (no server connection). Your text is still in the box.",
    "프로젝트 분류": "Project", "분류 없음": "No project", "분류": "Project", "분류 바꾸기": "Change project",
    "분류 없음으로 저장했어요": "Saved with no project", "저장하지 못했어요 — 다시 골라 주세요": "Couldn't save. Pick again.",
    "내용을 보고 Ro가 골랐어요": "ro picked this from the text", "분류를 골라주세요": "Pick a project",
    "되돌렸어요": "Undone", "되돌리지 못했어요": "Couldn't undo", "놓으면 기록해요": "Drop to log it", "집중 모드": "Focus mode",
    "알 수 없는 프로젝트예요.": "That project isn't known.", "해당 기록을 찾을 수 없어요.": "Couldn't find that entry.",
    "올바른 링크가 아니에요.": "That isn't a valid link.", "읽을 수 있는 텍스트가 없어요.": "There's no readable text.",
    "지원하지 않는 종류예요.": "That kind isn't supported.",
    // 회상
    "메모로 저장": "Save as a note", "답변 메모": "Answer note", "기록에 없어요.": "Not in your logs.",
    "기록에 없는 건 지어내지 않아요": "ro doesn't make up what isn't logged", "어제 뭐 했지?": "What did I do yesterday?",
    "이번 주 뭐 했지?": "What did I do this week?",
    // 파일 찾기
    "내려받기 필요": "Needs download", "Finder에서 보기": "Show in Finder", "열기  ↵": "Open  ↵", "열기": "Open",
    "찾는 중…": "Searching…", "이름·종류·기간을 먼저 보고, 없으면 내용까지 봐요.": "Checks name, type, and date first, then content.",
    "찾지 못했어요": "Couldn't search", "다시 시도해 주세요.": "Try again.", "내용까지 보고 찾았어요": "Found by looking inside files",
    "이름도 내용도 못 찾았어요": "No match by name or content", "못 찾았어요": "No match", "내용까지 보기": "Look inside files",
    "찾은 파일": "Files found", "원하는 파일이 없어요": "It's not here", "원하는 파일이 없었나요?": "Wasn't it here?",
    "찾던 파일 경로": "Path of the file you wanted",
    "찾던 파일 경로 (Finder에서 선택 후 ⌥⌘C로 복사)": "Path of the file you wanted (select it in Finder, then ⌥⌘C)",
    "알려 주기": "Tell ro", "목록에 없던 파일이에요. 기억했어요.": "That file wasn't in the list. Noted.",
    "알려 주시면 다음부터 더 잘 찾아요. 기록은 이 컴퓨터에만 남아요.": "Telling ro helps it find better next time. This stays on your Mac.",
    "고른 걸 기억하면 찾던 파일을 알려 줄 수 있어요. (지금은 꺼져 있어요)": "With remembering on, you can tell ro which file you wanted. (It's off now)",
    "기억하기 켜기": "Turn on remembering", "고른 걸 기억할까요?": "Remember what you pick?",
    "찾은 뒤 어떤 결과를 열었는지만 기록해서, 자주 쓰는 폴더나 내가 부르는 말을 배워요.": "ro notes only which result you opened, to learn your usual folders and wording.",
    "질문 원문과 파일 내용은 저장하지 않아요": "Your question and file contents aren't saved",
    "이 컴퓨터 밖으로 나가지 않아요": "Nothing leaves this Mac",
    "언제든 끄고 지울 수 있어요 (ro find-signals off · clear)": "Turn it off or clear it anytime (ro find-signals off · clear)",
    "나중에": "Not now", "배운 건 제안으로만 보여 줘요. 승인한 것만 반영돼요.": "What ro learns is only suggested. Only what you approve is used.",
    "기억하기를 켰어요": "Remembering is on", "켜지 못했어요": "Couldn't turn it on",
    "끄기: ro find-signals off · 지우기: ro find-signals clear": "Off: ro find-signals off · Clear: ro find-signals clear",
    "Finder에서 보여 드렸어요": "Shown in Finder", "열었어요": "Opened",
    "찾을 파일을 말해 주세요.": "Say which file to find.", "검색 범위 또는 본문 색인을 확인하지 못했어요.": "Couldn't check the search scope or content index.",
    "검색한 지 오래돼서 목록이 사라졌어요. 다시 찾아 주세요.": "That search is too old. Search again.",
    "화면에 표시된 번호가 아니에요.": "That number isn't on screen.", "그 파일은 이제 없거나 열 수 없는 위치예요.": "That file is gone or can't be opened from there.",
    "iCloud에서 아직 내려받지 않은 파일이에요. Finder에서 보기로 내려받아 주세요.": "That file isn't downloaded from iCloud yet. Use Show in Finder to download it.",
    "파일을 열지 못했어요.": "Couldn't open the file.", "기억하기가 꺼져 있어요.": "Remembering is off.",
    "번호가 올바르지 않아요.": "That number isn't valid.", "파일 경로를 확인해 주세요.": "Check the file path.",
    "설정을 저장하지 못했어요.": "Couldn't save the setting.",
    // 기록 분류
    "확인 필요": "Needs a pick", "적용하기": "Apply", "적용하지 못했어요": "Couldn't apply",
    "적용해도 24시간 안에 한 번에 되돌릴 수 있어요": "You can undo this in one step within 24 hours", "이렇게 묶을게요": "Here's the grouping",
    "적용할 변경이 없어요.": "Nothing to apply.", "되돌릴 정리가 없어요.": "Nothing to undo.",
    "24시간이 지나 되돌릴 수 없어요.": "It's been over 24 hours, so this can't be undone.",
    // AI 도구 연결
    "AI 도구 연결": "Connect AI tools", "닫기 (Esc)": "Close (Esc)", "입력창에서": "In the input, type", "/claude 질문": "/claude question",
    "으로 바로 넘기기": " to hand off right away", "규칙 원본": "Rules source", "규칙 연결": "Rules linked", "따로 쓰는 규칙": "Own rules",
    "규칙 없음": "No rules", "안전 훅": "Safety hook", "안전 훅 없음": "No safety hook", "안전 훅 갱신 필요": "Safety hook needs update",
    "안전 훅 작동 안 함": "Safety hook not working", "공통 규칙 원본:": "Shared rules source:", "· 바꾸려면 터미널에서": "· to change it, run in Terminal",
    "ro connect --source 파일": "ro connect --source FILE", "설치된 도구는 모두 연결돼 있어요.": "Every installed tool is connected.",
    "승인하고 연결": "Approve and connect", "연결하지 못했어요": "Couldn't connect", "/연결에서 상태를 다시 볼 수 있어요": "See the status again with /connect",
    "연결할 항목": "To connect", "되돌리기는 ro가 넣은 줄·훅·링크만 빼요. 그 뒤에 바뀐 설정은 그대로 둬요.": "Undo removes only the lines, hooks, and links ro added. Later changes stay.",
    "확인하는 중…": "Checking…", "넘기기": "Hand off", "명령 복사": "Copy command", "앱": "App", "앱 없음": "No app",
    "응용 프로그램 폴더에 없음": "Not in Applications", "터미널에서 실행 가능": "Runs in Terminal", "PATH에 없음": "Not on PATH", "규칙": "Rules",
    "위험한 명령 문자열을 찾아 승인을 묻는 보조 장치(모든 우회를 막지는 못함)": "A helper that spots risky commands and asks first (it can't catch everything)",
    "넘기지 못했어요": "Couldn't hand off", "터미널에 붙여 넣을 명령을 복사했어요": "Copied a command to paste in Terminal",
    "터미널에서 ⌘V 후 ↵": "In Terminal, ⌘V then ↵", "입력을 복사했어요 · ⌘V로 붙여 넣으세요": "Copied your text · paste with ⌘V",
    "· 비밀값으로 보이는 부분은 가렸어요": "· parts that look like secrets are masked",
    "공통 규칙 원본이 정해지지 않아 규칙은 연결하지 않아요.": "No shared rules source is set, so rules aren't linked.", "로 정하세요.": " sets it.",
    "안전 훅은 위험한 명령 문자열을 찾는 보조 장치예요. 모든 우회를 막지는 못해요.": "The safety hook spots risky commands. It can't catch everything.",
    "알 수 없는 도구예요.": "That tool isn't known.", "클립보드에 넣지 못했어요.": "Couldn't copy to the clipboard.",
    "그사이 상태가 바뀌었어요. 다시 확인해 주세요.": "Things changed meanwhile. Check again.", "되돌릴 연결이 없어요.": "No connection to undo.",
    "Antigravity는 이미 따로 쓰는 전역 규칙이 있어 그대로 둬요.": "Antigravity already has its own global rules, so they stay.",
    // 활동 기록
    "활동 기록 상태를 읽지 못했어요.": "Couldn't read the activity log status.", "꺼짐": "Off", "멈춤": "Paused",
    "켜짐 · 멈춰 있음": "On · paused", "켜짐": "On", "끄기": "Turn off", "다시 켜기": "Resume", "1시간 멈춤": "Pause 1 hour", "켜기": "Turn on",
    "앞 앱과 웹 AI 탭 제목만 이 Mac에 7일 남겨요. 키 입력·화면·메신저·비밀번호 앱은 남기지 않아요.": "Keeps only front-app and web AI tab titles on this Mac for 7 days. No keystrokes, screens, messengers, or password apps.",
    "브라우저 탭을 못 읽어요: 시스템 설정 > 개인정보 보호 및 보안 > 자동화에서 허용하세요.": "Can't read browser tabs. Allow it in System Settings › Privacy & Security › Automation.",
    // 인수인계
    "인수인계를 만들지 못했어요": "Couldn't make the handoff",
    "이 폴더로 새 세션을 열면 자동으로 이어받아요 · 채팅이면 ⌘V": "Open a new session in this folder and it picks up · in chat, ⌘V",
    "작업 폴더에서 ⌘V 후 ↵": "In the work folder, ⌘V then ↵", "인수인계 문서를 복사했어요 · 새 대화에 ⌘V": "Copied the handoff · paste into a new chat with ⌘V",
    "넘길 문서 본문": "Handoff text", "내용 보기": "Show text", "본문을 불러오지 못했어요.": "Couldn't load the text.", "내용 접기": "Hide text",
    "· 비밀값은 가림": "· secrets masked", "이 작업이 아니면 다른 세션:": "Not this work? Other sessions:", "반대로": "Reverse",
    "작업 폴더 모름": "work folder unknown",
    // 라이선스·결제 (서버 응답 → 영어)
    "라이선스 키가 없습니다(mini).": "No license key (Free mini).",
    "키가 비어 있습니다.": "License key is empty.",
    "키가 너무 깁니다.": "License key is too long.",
    "ro 라이선스 키가 아닙니다.": "Not a ro license key.",
    "키 형식이 올바르지 않습니다.": "Invalid license key format.",
    "지원하지 않는 키 버전입니다. ro를 업데이트해 보세요.": "Unsupported key version. Try updating ro.",
    "이 버전의 ro가 알지 못하는 키입니다. ro를 업데이트해 보세요.": "This version of ro doesn't recognize this key. Try updating ro.",
    "키 서명이 맞지 않습니다. 받은 키를 그대로 붙여 넣었는지 확인하세요.": "Key signature didn't match. Check that you pasted the full key.",
    "키 내용이 올바르지 않습니다.": "License key contents are invalid.",
    "자동 구매가 아직 준비되지 않았어요. 잠시 뒤 다시 시도해 주세요.": "Online checkout isn't ready yet. Please try again shortly.",
  };
  const T = (s) => text(s);
  const SINGULAR = {
    duplicates: "duplicate",
    "unpacked archives": "unpacked archive",
    "old versions": "old version",
  };
  const kindWord = (l, n) => {
    const w = T(l).toLowerCase();
    return +n === 1 ? (SINGULAR[w] || w) : w;
  };
  const KO_EN_RULES = [
    // ro pro 확인 카드·배운 것(RO-AUD-108). 일반 규칙보다 먼저 본다
    [/^확실한 것 (\d+)개( \(선택됨\))?$/, (m, n, s) => `Sure ${n}${s ? " (selected)" : ""}`],
    [/^아마도요 (\d+)개 — 직접 골라 주세요$/, "Maybe $1 — pick them yourself"],
    [/^옮김 (\d+)건 · 사본 내보냄 (\d+)건(?: · 건너뜀 (\d+)건)?$/, (m, a, b, k) => `Moved ${a} · removed ${b} local copies${k ? ` · skipped ${k}` : ""}`],
    [/^되돌렸어요 · 파일 (\d+)개 제자리로(?: · 바뀐 것 (\d+)개는 그대로)?$/, (m, n, k) => `Undone · ${n} back in place${k ? ` · ${k} changed since were left alone` : ""}`],
    [/^ro가 배운 것 · 학습 (켜짐|꺼짐) · 먼저 알림 (켜짐|꺼짐)$/, (m, a, b) => `What ro learned · learning ${a === "켜짐" ? "on" : "off"} · heads-ups ${b === "켜짐" ? "on" : "off"}`],
    [/^학습 (켜짐|꺼짐) · 먼저 알림 (켜짐|꺼짐)( · 손쉬운 사용 권한 필요)?$/,
      (m, a, b, ax) => `Learning ${a === "켜짐" ? "on" : "off"} · heads-ups ${b === "켜짐" ? "on" : "off"}${ax ? " · Accessibility needed" : ""}`],
    [/^(.+) 앱이 설치돼 있어요 · (.+) 남음$/, "$1 is installed · $2 left behind"],
    [/^시동 디스크 남은 공간 (\S+)GB$/, "$1 GB free on startup disk"],
    [/^다운로드에 새 파일 (\d+)개가 들어왔어요$/, "$1 new files arrived in Downloads"],
    [/^(.+) 압축이 이미 풀려 있어요$/, "$1 is already unpacked"],
    [/^다운로드에 중복 사본 (\d+)개가 있어요$/, "$1 duplicate copies in Downloads"],
    [/^(.+)에서 (.+)\(으\)로 도구를 바꿨어요$/, "Switched from $1 to $2"],
    [/^2분 동안 폴더를 (\d+)번 오가셨어요$/, "Switched folders $1 times in 2 minutes"],
    [/^같은 폴더에 더 새 판이 있어요 · (.+)$/, "Newer version in the same folder · $1"],
    [/^먼저 알림 30일: (\d+)번 · 도움 (\S+) · 끄기 (\S+) · (.+?)(?: · 1단계로 낮춘 유형 (.+))?$/,
      (m, n, a, b, v, d) => `Heads-ups, 30 days: ${n} · helped ${a} · turned off ${b} · ${T(v)}${d ? ` · now shown as a look only: ${d.split(", ").map(T).join(", ")}` : ""}`],
    [/^(.+) 다시 켜기$/, (m, t) => T(t) === t ? m : `Turn ${T(t).toLowerCase()} back on`],
    [/^(\d+)일$/, (m, n) => +n === 1 ? "1 day" : `${n} days`],
    [/^(.+?) · (\d+)개 · (.+)$/, (m, t, n, b) => T(t) === t ? m : `${T(t)} · ${n} · ${b}`],
    [/^(.+) · (\d+)일 안 바뀜 · 다시 만들 수 있음$/, "$1 · unchanged for $2 days · can be rebuilt"],
    [/^(\d+)일 안 씀 · iCloud에 남고 이 Mac 사본만 내보냄$/, "Unused for $1 days · stays in iCloud, only the copy on this Mac is removed"],
    [/^(.+) 설치됨$/, "$1 installed"],
    [/^지난번에 끝나지 않은 정리 (\d+)건을 되돌렸어요$/, "Undid $1 unfinished tidy-ups from last time"],
    [/^오늘 (\d+)건 기록했어요\.$/, "$1 logged today."],
    [/^마지막 기록 (\S+) · (.+)$/, (m, t, h) => `Last at ${t} · ${T(h)}`],
    [/^외 (\d+)건$/, "and $1 more"], [/^(\d+)건$/, "$1"], [/^(\d+)개$/, "$1"],
    [/^타임라인에서 전체 보기 \((\d+)건\)$/, "See all in Timeline ($1)"],
    [/^분류: (.+)$/, (m, p) => `Project: ${T(p)}`],
    [/^이전 (\d+)건은 터미널의 ro log에서 볼 수 있어요$/, "$1 earlier entries are in ro log (Terminal)"],
    [/^(.+) 파일 목록$/, (m, l) => `Files in ${T(l)}`],
    [/^옮길 파일 (\d+)개(?: · 치울 후보 (\d+)개\((.+?)\))? — 줄을 누르면 파일 목록이 펼쳐져요\. 옮기기는 승인 뒤에 실행됩니다\.$/,
      (m, a, b, c) => `${a} to move${b ? ` · ${b} to clear (${c})` : ""}. Click a row to see its files. Nothing moves until you approve.`],
    [/^치울 후보 (\d+)개\((.+?)\) — 줄을 누르면 파일 목록이 펼쳐져요\. 옮기기는 승인 뒤에 실행됩니다\.$/,
      "$1 to clear ($2). Click a row to see its files. Nothing moves until you approve."],
    [/^최근 10분 안에 받거나 고친 파일 (\d+)개는 아직 쓰는 중일 수 있어 건너뛰었어요\.$/,
      (m, n) => `Skipped ${n} ${+n === 1 ? "file" : "files"} from the last 10 minutes. You may still be using ${+n === 1 ? "it" : "them"}.`],
    [/^(?:분류가 애매한|검토가 필요한) (\d+)개는 옮기지 않아요$/,
      (m, n) => `${n} ${+n === 1 ? "file needs" : "files need"} review (won't be moved)`],
    [/^보관함에 (.+) 보관 중\. 7일 지난 것은 터미널에서$/, "$1 in holding. After 7 days, in Terminal"],
    [/^되돌리기 · (\S+ \S+) (\d+)개$/, "Undo · $1 ($2)"],
    [/^(.+?) (\d+)개를 보관함으로\(지우지 않음, 되돌리기 가능\) — 승인 카드에서 한 번 더 확인합니다$/,
      (m, l, n) => `Send ${n} ${kindWord(l, n)} to holding (not deleted, can be undone). You confirm once more in the card.`],
    [/^(.+?) (\d+)개 옮기기 — 승인 카드에서 한 번 더 확인합니다$/, (m, c, n) => `Move ${n} in ${T(c)}. You confirm once more in the card.`],
    [/^(.+?) (\d+)개 · (\S+)$/, (m, l, n, s) => T(l) === l ? m : `${T(l)} · ${n} · ${s}`],
    [/^(.+?) (\d+)개$/, (m, c, n) => T(c) === c ? m : `${T(c)} · ${n}`],
    [/^알림 (\d+)건 모아둠$/, "$1 notifications held"],
    [/^(.+)\(으\)로 저장했어요$/, "Saved to $1"],
    [/^(.*) 기록이라 오늘 타임라인에는 없어요\.$/, (m, d) => `That's from ${d === "다른 날" ? "another day" : d}, so it isn't in today's timeline.`],
    [/^근거 줄에 저장된 내용이 모두 보여요\. 그날 요약: 터미널에서 (.+)$/, "The evidence row shows everything saved. That day's summary, in Terminal: $1"],
    [/^근거 · 기록 (\d+)건$/, "Evidence · $1 logged"], [/^기록 (\d+) 열기$/, "Open entry $1"],
    [/^↳ 비슷한 파일 · (.+?)( · 수정 (.+))?$/, (m, n, _, d) => `↳ Similar file · ${n}${d ? ` · edited ${d}` : ""}`],
    [/^후보 (\d+)개를 찾았어요$/, "Found $1 candidates"], [/^나머지 (\d+)개 보기$/, "Show $1 more"],
    [/^(\d+)ms · Downloads · Documents · Desktop · iCloud Drive 안에서만 찾아요\. 비밀 파일은 보지 않아요\.$/,
      "$1ms · Searches only Downloads, Documents, Desktop, and iCloud Drive. Secret files are skipped."],
    [/^목록 (\d+)번에 있었어요\. 기억했어요\.$/, "It was number $1 in the list. Noted."],
    [/^이름 전체 '(.+)' 일치(.*)$/, (m, q, r) => `Whole name matches '${q}'${tail(r)}`],
    [/^이름이 '(.+)'(?:으로|로) 시작(.*)$/, (m, q, r) => `Name starts with '${q}'${tail(r)}`],
    [/^이름에 '(.+)' 포함(.*)$/, (m, q, r) => `Name contains '${q}'${tail(r)}`],
    [/^(\d+)건 골라주기$/, "$1 to pick"], [/^(.+) 분류$/, (m, a) => a.length > 40 ? m : `Project for ${a}`],
    [/^적용했어요 · (\d+)건$/, "Applied · $1"], [/^되돌렸어요 · (\d+)건(?: · 그사이 바뀐 (\d+)개는 그대로 둠)?$/, (m, n, k) => `Undone · ${n}${k ? ` · ${k} changed since were left alone` : ""}`],
    [/^기록 (\d+)건 → 프로젝트 (\d+)개\. 아직 아무것도 바뀌지 않았어요\.$/, "$1 entries → $2 projects. Nothing has changed yet."],
    [/^(.+) 기록 찾아줘$/, "Search logs for $1"], [/^(.+)을\(를\) 써 주세요$/, (m, h) => `type ${T(h)}`],
    [/^(.+), 연결할 항목 (\d+)개$/, "$1, $2 to connect"], [/^연결했어요 · (\d+)건$/, "Connected · $1"],
    [/^연결할 항목 (\d+)개 · 아직 아무것도 바뀌지 않았어요$/, "$1 to connect · nothing has changed yet"],
    [/^넘길 내용: “(.*)”$/, "To hand off: “$1”"], [/^(.+) 로 넘기기$/, "Hand off to $1"], [/^(.+)로 넘기기$/, "Hand off to $1"], [/^(.+) 열기$/, "Open $1"],
    [/^(.+)을\(를\) 열었어요$/, "Opened $1"], [/^(.+) 앱을 열었어요$/, "Opened $1"], [/^(.+) 앱을 열지 못했어요$/, "Couldn't open $1"],
    [/^(.+)이\(가\) 이 Mac에 없어요\.$/, "$1 isn't on this Mac."], [/^(.+)을\(를\) 열지 못했어요\.$/, "Couldn't open $1."],
    [/^안전 훅 등록: 비밀값 차단·파괴적 명령 승인 \(스크립트는 (.+)에 복사\)$/, "Add the safety hook: blocks secrets, asks before destructive commands (script copied to $1)"],
    [/^갈아타기 훅 등록: 다른 AI에서 넘긴 작업을 Claude Code 새 세션이 붙여 넣기 없이 이어받음\(같은 폴더·24시간·한 번만, 스크립트는 (.+)에 복사\)$/,
      "Add the handoff hook: a new Claude Code session picks up work from another AI without pasting (same folder, 24 hours, once; script copied to $1)"],
    [/^활동 기록 · (.+)$/, (m, s) => `Activity log · ${T(s)}`],
    [/^시험 (\d+)일째 \/ 14일 · 최근 활동이 들어간 인수인계 (\d+)번 · 평가 ok (\d+) \/ miss (\d+)$/, "Trial day $1 of 14 · $2 handoffs used recent activity · rated ok $3 / miss $4"],
    [/^(.+) → (.+) 인수인계$/, "Handoff: $1 → $2"], [/^자동 선택 · (.+)$/, "Picked automatically · $1"],
    [/^마지막 활동 (.+?) · (.+)$/, (m, u, c) => `Last active ${u} · ${T(c)}`],
    [/^남은 할 일 (\d+) · 요청 (\d+) · 바꾼 파일 (\d+) · 명령 (\d+) · 산출물 (\d+) · (\d+)자$/, "To-dos $1 · requests $2 · files changed $3 · commands $4 · outputs $5 · $6 chars"],
    [/^(.+) (\S+) 세션으로 바꾸기: (.+)$/, "Switch to the $1 session from $2: $3"], [/^(.+) → (.+)로 바꾸기$/, "Switch to $1 → $2"],
    [/^(.+) \(요청 (\d+)\)$/, "$1 ($2 requests)"],
    // 서버 문장
    [/^파일 정리: (.+?) (\d+)건을 (.+)로 옮기고 이름을 바꿉니다\.$/, (m, c, n, d) => `Tidy: move ${n} in ${T(c)} to ${d} and rename them.`],
    [/^(.+?) (\d+)건\((.+?)\)을 보관함\((.+?)\)으로 옮깁니다\. 지우지 않고, 되돌릴 수 있어요\.$/,
      (m, l, n, s, d) => `Send ${n} ${kindWord(l, n)} (${s}) to holding (${d}). Nothing is deleted, and you can undo it.`],
    [/^(\S+ \S+)에 정리한 (\d+)건을 원래 이름·위치로 되돌립니다\.$/,
      (m, when, n) => +n === 1 ? `Put the 1 file tidied at ${when} back to its original name and place.` : `Put the ${n} files tidied at ${when} back to their original names and places.`],
    [/^(.+?) (\d+)건 격리 \(되돌리기 가능, 삭제 아님\)(?:, 건너뜀 (\d+)건)?$/,
      (m, l, n, k) => `${n} ${kindWord(l, n)} sent to holding (can be undone, not deleted)${k ? `, ${k} skipped` : ""}`],
    [/^(.+?) (\d+)건 이동 \(되돌리기 가능\)(?:, 건너뜀 (\d+)건)?$/, (m, c, n, k) => `Moved ${n} in ${T(c)} (can be undone)${k ? `, ${k} skipped` : ""}`],
    [/^(\d+)건을 원래 자리로 되돌림(?:, 건너뜀 (\d+)건)?$/, (m, n, k) => `Put ${n} back${k ? `, ${k} skipped` : ""}`],
    [/^정리 (\d+)건$/, "Tidied $1"], [/^정리안 (\d+)건$/, (m, n) => `Plan with ${n} ${+n === 1 ? "file" : "files"}`], [/^되돌림 (\d+)건$/, "Put back $1"],
    [/^보관함 (\d+)$/, "Holding $1"], [/^(.+) — 링크 저장$/, "$1 · link saved"], [/^(.+) — 요약 (\d+)줄 추출$/, "$1 · $2 lines kept"],
    [/^권한 과다 (\S+): (.+)$/, "Permissions too open ($1): $2"],
    [/^(\d+)건을 찾았어요\.$/, "Found $1."],
    [/^\+ (.+)$/, (m, h) => T(h) === h ? m : `+ ${T(h).toLowerCase()}`],
    [/^([✓–]) (.+)$/, (m, a, b) => T(b) === b ? m : `${a} ${T(b)}`],
    // '문서 2 · 보관함 1' 같은 종류별 건수: 모든 조각이 아는 이름일 때만
    [/^.+ \d+( · .+ \d+)*$/, (m) => {
      const parts = m.split(" · ").map(p => p.match(/^(.+) (\d+)$/));
      return parts.every(p => p && T(p[1]) !== p[1]) ? parts.map(p => `${T(p[1])} ${p[2]}`).join(" · ") : m;
    }],
    // '메모 · 본문' 같은 종류 머리말: 아는 종류일 때만. 뒤는 서버 요약이면 번역되고 사용자가 쓴 말이면 그대로다
    [/^(\S+(?: \S+)?) · (.+)$/, (m, k, r) => T(k) === k ? m : `${T(k)} · ${T(r)}`], [/^최근 (\d+)건만 근거로 보여 줘요\.$/, "Showing only the latest $1 as evidence."],
    [/^pro 사용 중 · (\d{4}-\d{2}-\d{2})까지$/, "Pro active · until $1"],
    [/^키가 (\d{4}-\d{2}-\d{2})에 만료됐습니다\. 구독을 갱신하면 새 키가 이메일로 옵니다\.$/, "Key expired on $1. Renew your subscription to get a new key by email."],
  ];
  // 뒤에 붙는 ' · 마지막 열람 …' 같은 꼬리
  function tail(r) {
    return String(r || "").replace(/ · 마지막 열람 /g, " · last opened ").replace(/ · 다른 버전 (\d+)개/g, " · $1 other versions")
      .replace(/ · 수정 /g, " · edited ");
  }
  const EN_KO = {
    "Home": "홈", "Timeline": "타임라인", "Organize": "정리", "Settings": "설정", "Close panel": "닫기", "Close panel (Esc)": "닫기 (Esc)",
    "Menu": "메뉴", "Menu (panel color, bring to desktop, send to menu bar)": "메뉴",
    "Focus mode": "집중 모드", "Turn on focus mode": "집중 모드 켜기", "Turn off focus mode": "집중 모드 끄기",
    "What ro learned · Heads-ups": "ro가 배운 것 · 먼저 알림",
    "ro won't learn or nudge until you turn it on.": "동의를 켜기 전에는 배우거나 먼저 알리지 않아요.",
    "Turn on learning": "학습 켜기", "Turn off learning": "학습 끄기",
    "Turn on heads-ups": "먼저 알림 켜기", "Turn off heads-ups": "먼저 알림 끄기",
    "View learned": "배운 것 보기",
    "Closes its eyes and holds notifications": "눈을 감고 알림을 잠시 모아 둬요", "Connect AI tools": "AI 도구 연결",
    "Connect shared rules and safety hooks to installed tools (preview, then approve) and hand off input": "공통 규칙과 안전 훅을 연결해요. 바뀔 내용을 먼저 보여 드려요",
    "Material": "재질", "Clay": "클레이", "Glass": "글래스", "ro color": "색상", "System": "자동", "Light": "라이트", "Dark": "다크", "Orange": "오렌지",
    "Size": "크기", "Small": "작게", "Medium": "보통", "Big": "크게", "Wander": "돌아다니기",
    "Slowly strolls along the bottom of the screen": "화면 위를 천천히 걸어요", "Reactions": "앱 반응",
    "Notices when you open an app or switch to mail or messages. Only the app in front is checked, nothing is read or saved": "앱을 열거나 메일·메시지로 넘어가면 알아봐요. 어떤 앱이 앞에 있는지만 보고, 내용은 읽지 않아요",
    "Expression": "표정", "Motion": "동작", "Idle": "평소", "Recording": "기록", "Focus": "집중", "Attention": "주의", "Discovery": "발견", "Resolved": "해결",
    "Press": "꾹", "Breathe": "숨쉬기", "Look around": "두리번", "Walk": "걷기", "Think": "생각", "Startle": "깜짝", "Drowsy": "꾸벅", "Gaze": "시선",
    "Pet": "쓰다듬기", "Drag": "잡기", "Shake": "흔들기", "Land": "착지", "Success": "성공", "Failure": "실패",
    "Release to menu bar": "놓으면 메뉴 막대로", "Could not save the setting, so it was reverted. Please try again.": "저장하지 못해 원래대로 돌렸어요. 다시 시도해 주세요.",
    "Could not reach the server": "서버에 연결하지 못했어요", "That setting cannot be saved.": "저장할 수 없는 설정이에요.",
    "Not available in Mini.": "이 에디션에서는 쓸 수 없어요.",
    "Morning": "오전", "Afternoon": "오후", "Evening": "저녁",
    "A JSON object is required.": "JSON object가 필요합니다.",
    "Invalid Content-Length.": "잘못된 Content-Length입니다.",
    "on must be true or false.": "on은 true/false여야 합니다.",
    "Unsupported activity action.": "지원하지 않는 활동 기록 명령이에요.",
    // 인앱 결제·라이선스 화면 (영어 원문 → 한국어)
    "Free": "무료", "Pro": "Pro", "Upgrade to Pro": "Pro 업그레이드", "License key": "라이선스 키", "License": "라이선스", "Manage license": "라이선스 관리",
    "Upgrade": "업그레이드", "Close (Esc)": "닫기 (Esc)", "Close": "닫기", "Pro and license": "Pro 및 라이선스",
    "Find files by asking, tidy Downloads with undo, and hand off between AI tools — all on this Mac.":
      "말로 파일 찾기, 되돌릴 수 있는 다운로드 정리, AI 도구 인수인계 — 모두 이 Mac 안에서만 동작해요.",
    "Pro active on this Mac.": "이 Mac에서 Pro를 사용 중이에요.",
    "Pro active": "Pro 사용 중", "Free (mini)": "무료 (mini)",
    "Find files by asking (⌥R) by name, date, and text inside": "이름·기간·본문으로 파일 찾기 (⌥R)",
    "Tidy Downloads with one-step undo — nothing deleted": "삭제 없이 한 번에 되돌리는 다운로드 정리",
    "AI tool handoff and safety hooks, 100% on this Mac": "AI 도구 인수인계·안전 훅, 100% 이 Mac 로컬 실행",
    "Billing plan": "요금제 선택", "Yearly": "연간", "Monthly": "월간", "Save 33%": "33% 절약",
    "/ year": "/ 년", "/ month": "/ 월", "Early supporters $19 first year": "얼리 서포터 첫해 $19", "Cancel any time": "언제든 해지 가능",
    "Continue to checkout": "결제 계속하기",
    "Checkout opened in your browser. Once payment completes, ro activates Pro automatically.":
      "브라우저에서 결제창을 열었어요. 결제가 끝나면 ro가 자동으로 Pro를 켜요.",
    "Online checkout opens soon.": "온라인 결제가 곧 열려요.",
    "Check activation now": "활성화 지금 확인", "Paste key instead": "키 직접 입력",
    "Still waiting for payment confirmation.": "결제 확인을 기다리고 있어요.",
    "Pro license active!": "Pro 라이선스가 활성화됐어요!",
    "14-day refund · All your personal Macs · Secure checkout via Polar":
      "14일 환불 · 개인 Mac 여러 대 사용 · Polar 안전 결제",
    "Checking license status…": "라이선스 상태 확인 중…",
    "Paste the key from your purchase email (starts with RO1.)": "구매 이메일로 받은 키를 붙여 넣으세요 (RO1.로 시작)",
    "Save key": "키 저장", "Paste a license key starting with RO1.": "RO1.로 시작하는 라이선스 키를 입력해 주세요.",
    "License saved.": "라이선스를 저장했어요.", "Could not save the key.": "키를 저장하지 못했어요.",
    "Restart ro to apply your license change. Your files and records stay as they are.":
      "라이선스 변경을 적용하려면 ro를 다시 시작하세요. 파일과 기록은 그대로 남아요.",
    "Restart ro now": "지금 ro 다시 시작",
    "Get my key automatically": "키 자동으로 받기",
    "Picks up keys and renewals using a random install ID only": "무작위 설치 ID만 사용해 키와 갱신을 자동으로 받아요",
    "Remove key": "키 지우기", "Confirm remove": "정말 지우기", "Cancel": "취소",
    "Key removed. Your files and records stay as they are.": "키를 지웠어요. 파일과 기록은 그대로예요.",
    "Checked offline on this Mac": "이 Mac에서 오프라인으로 검사해요", "close": "닫기",
    "Color, size & app reactions": "색상 · 크기 · 앱 반응",
    "AI tools & learning": "AI 도구 연결 · 배운 것",
    "Preview expressions & motion": "표정·동작 미리보기",
  };
  const EN_KO_RULES = [
    [/^Update failed · showing data as of (\S+)\. (.+)$/, (m, at, why) => `새로 고치지 못했어요 · ${at} 기준이에요. ${EN_KO_WHY[why] || why}`],
    [/^(Morning|Afternoon|Evening) · (\d+)$/, (m, b, n) => `${{ Morning: "오전", Afternoon: "오후", Evening: "저녁" }[b]} · ${n}`],
  ];
  const EN_KO_WHY = { "Retrying shortly.": "곧 다시 시도해요.", "Could not reach the local server.": "로컬 서버에 연결하지 못했어요.",
    "Please reopen the pet (the server may have restarted).": "ro를 다시 열어 주세요." };

  function text(s) {
    if (RO_LANG !== "en" && RO_LANG !== "ko") return s;
    const core = String(s).trim();
    if (!core) return s;
    const en = RO_LANG === "en";
    if (en !== HAN.test(core) && !(en === false && EN_KO[core])) return s;  // 이미 그 언어다
    const table = en ? KO_EN : EN_KO, rules = en ? KO_EN_RULES : EN_KO_RULES;
    let out = Object.prototype.hasOwnProperty.call(table, core) ? table[core] : null;
    if (out == null) {
      for (const [re, rep] of rules) {
        if (!re.test(core)) continue;
        const got = core.replace(re, rep);
        if (got !== core) { out = got; break; }  // 규칙이 손대지 않기로 했으면(모르는 이름) 다음 규칙을 본다
      }
    }
    return out == null || out === core ? s : String(s).replace(core, () => out);
  }
  const ATTRS = ["title", "aria-label", "aria-description", "placeholder"];
  const RAW = ".rc-q, .fd-name, .fd-where, .gate-files, .org-files, .stage-name, input, textarea";
  function markInlineLang(el, hasKo) {
    if (!el || typeof el.setAttribute !== "function") return;
    const tag = el.tagName;
    if (!tag || tag === "BODY" || tag === "HTML" || tag === "HEAD") return;
    if (RO_LANG === "en" && hasKo) el.setAttribute("lang", "ko");
    else if (el.getAttribute && el.getAttribute("lang") === "ko") el.removeAttribute("lang");
  }
  function attrs(el) {
    for (const a of ATTRS) {
      const v = el.getAttribute(a);
      if (!v) continue;
      const t = text(v);
      if (t !== v) el.setAttribute(a, t);
    }
  }
  function node(n) {
    if (n.nodeType === 3) {
      const t = text(n.nodeValue);
      if (t !== n.nodeValue) n.nodeValue = t;
      if (RO_LANG === "en") markInlineLang(n.parentElement, HAN.test(t));
      return;
    }
    if (n.nodeType !== 1 || n.tagName === "SCRIPT" || n.tagName === "STYLE") return;
    attrs(n);
    if (n.matches(RAW)) {  // 사용자가 쓴 말·파일 이름·폴더 경로는 번역하지 않되 언어만 표시한다
      if (RO_LANG === "en" && n.tagName !== "INPUT" && n.tagName !== "TEXTAREA") {
        markInlineLang(n, HAN.test(n.textContent || ""));
      }
      return;
    }
    n.childNodes.forEach(node);
  }
  function start() {
    if (RO_LANG !== "en" && RO_LANG !== "ko") return;
    document.documentElement.lang = RO_LANG;
    node(document.body);
    // 그리기 전에(마이크로태스크) 돌아 원문이 잠깐 보였다 바뀌는 일이 없다. 바꾼 글자는 다시 번역되지 않아 맴돌지 않는다
    new MutationObserver((muts) => {
      for (const m of muts) {
        if (m.type === "childList") m.addedNodes.forEach(node);
        else if (m.type === "characterData") node(m.target);
        else attrs(m.target);
      }
    }).observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS });
  }
  return { lang: RO_LANG, text, start };
})();
RoI18n.start();
