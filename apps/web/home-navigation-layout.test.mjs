import { strict as assert } from "node:assert";
import { existsSync, readFileSync } from "node:fs";
import { test } from "node:test";

const authClientUrl = new URL("./src/app/auth-client.ts", import.meta.url);
const legacyStorageCleanupUrl = new URL("./src/app/legacy-storage-cleanup.tsx", import.meta.url);
const profilePageUrl = new URL("./src/app/profile/page.tsx", import.meta.url);
const pageSource = readFileSync(new URL("./src/app/page.tsx", import.meta.url), "utf8");
const reportSource = readFileSync(new URL("./src/app/report/page.tsx", import.meta.url), "utf8");
const reportModelSource = readFileSync(new URL("./src/app/report/report-model.ts", import.meta.url), "utf8");
const profileSource = existsSync(profilePageUrl) ? readFileSync(profilePageUrl, "utf8") : "";
const historySource = readFileSync(new URL("./src/app/history/page.tsx", import.meta.url), "utf8");
const casesSource = readFileSync(new URL("./src/app/cases/page.tsx", import.meta.url), "utf8");
const safetySource = readFileSync(new URL("./src/app/safety/page.tsx", import.meta.url), "utf8");
const sourcesSource = readFileSync(new URL("./src/app/sources/page.tsx", import.meta.url), "utf8");
const globalsSource = readFileSync(new URL("./src/app/globals.css", import.meta.url), "utf8");
const layoutSource = readFileSync(new URL("./src/app/layout.tsx", import.meta.url), "utf8");
const authClientSource = existsSync(authClientUrl) ? readFileSync(authClientUrl, "utf8") : "";
const legacyStorageCleanupSource = existsSync(legacyStorageCleanupUrl) ? readFileSync(legacyStorageCleanupUrl, "utf8") : "";
const webDockerfileSource = readFileSync(new URL("./Dockerfile", import.meta.url), "utf8");
const webReadmeSource = readFileSync(new URL("./README.md", import.meta.url), "utf8");
const recordingPlanSource = readFileSync(new URL("../../docs/10分钟完整录屏测试方案.md", import.meta.url), "utf8");

function getInteractiveElementsWithLabel(source, label) {
  return (source.match(/<(?:button|Link|a)\b[\s\S]*?<\/(?:button|Link|a)>/g) ?? []).filter((element) => element.includes(label));
}

function assertInteractiveLabelsDoNotWrap(sourceName, source, labels) {
  for (const label of labels) {
    const matchingElements = getInteractiveElementsWithLabel(source, label);
    assert.ok(matchingElements.length > 0, `${sourceName} should render an interactive action labelled ${label}`);

    for (const element of matchingElements) {
      assert.match(element, /whitespace-nowrap/, `${sourceName} action ${label} should prevent multi-line button text`);
    }
  }
}

test("home shell removes the top navigation bar", () => {
  assert.doesNotMatch(pageSource, /<header[\s\S]*?<\/header>/);
  assert.doesNotMatch(pageSource, /className="flex h-12 shrink-0 items-center justify-end border-b border-border bg-background px-4"/);
  assert.doesNotMatch(pageSource, /href="\/safety"[\s\S]*?>\s*安全声明\s*<\/Link>[\s\S]*<header/);
  assert.doesNotMatch(pageSource, /href="\/sources"[\s\S]*?>\s*数据来源\s*<\/Link>[\s\S]*<header/);
});

test("root layout and logout purge legacy personal training data", () => {
  assert.ok(existsSync(legacyStorageCleanupUrl), "root layout should have a client-side legacy storage cleanup");
  assert.match(legacyStorageCleanupSource, /"use client";/);
  assert.match(legacyStorageCleanupSource, /useEffect\(\(\) => \{\s+clearTrainingHistoryRecords\(\);\s+\}, \[\]\);/);
  assert.match(layoutSource, /import \{ LegacyStorageCleanup \} from "\.\/legacy-storage-cleanup";/);
  assert.match(layoutSource, /<LegacyStorageCleanup \/>/);
  assert.match(authClientSource, /import \{ clearTrainingHistoryRecords \} from "\.\/training-history";/);
  assert.match(
    authClientSource,
    /export async function logoutUser\(\): Promise<void> \{\s+try \{[\s\S]*?\} finally \{\s+clearTrainingHistoryRecords\(\);\s+\}\s+\}/,
  );
});

test("home page does not render large safety and source panels", () => {
  assert.doesNotMatch(pageSource, /<Panel title="安全声明"/);
  assert.doesNotMatch(pageSource, /<Panel title="数据来源"/);
});

test("student inputs enforce the API business limits before submission", () => {
  for (const contract of [
    /const AUTH_EMAIL_MAX_CHARS = 254;/,
    /const AUTH_PASSWORD_MAX_CHARS = 256;/,
    /const QUESTION_MAX_CHARS = 500;/,
    /const PROCEDURE_REQUEST_MAX_CHARS = 500;/,
    /const DIAGNOSIS_MAX_CHARS = 128;/,
    /const DIAGNOSIS_REASONING_MAX_CHARS = 4096;/,
    /const SPEECH_INPUT_MAX_CHARS = 2000;/,
    /const AUDIO_TRANSCRIPTION_MAX_BYTES = 10 \* 1024 \* 1024;/,
  ]) {
    assert.match(pageSource, contract);
  }

  assert.match(pageSource, /id="history-question"[\s\S]*?maxLength=\{QUESTION_MAX_CHARS\}/);
  assert.match(pageSource, /maxLength=\{PROCEDURE_REQUEST_MAX_CHARS\}[\s\S]*?setAdvancedProcedureRequestText/);
  assert.match(pageSource, /id="diagnosis-input"[\s\S]*?maxLength=\{DIAGNOSIS_MAX_CHARS\}/);
  assert.match(pageSource, /id="supporting-evidence-input"[\s\S]*?maxLength=\{DIAGNOSIS_DETAIL_MAX_CHARS\}/);
  assert.match(pageSource, /if \(message\.length > QUESTION_MAX_CHARS\)/);
  assert.match(pageSource, /if \(requestText\.length > PROCEDURE_REQUEST_MAX_CHARS\)/);
  assert.match(pageSource, /if \(reasoning\.length > DIAGNOSIS_REASONING_MAX_CHARS\)/);
});

test("history request failures distinguish rejection from uncertain writes", () => {
  assert.match(pageSource, /type ApiRequestOutcome = "rejected" \| "uncertain";/);
  assert.match(pageSource, /response\.status >= 500 \|\| response\.status === 408[\s\S]*?\? "uncertain"[\s\S]*?: "rejected"/);
  assert.match(pageSource, /let optimisticQuestionId: string \| null = null;/);
  assert.match(
    pageSource,
    /catch \(error\) \{[\s\S]*?wasDefinitivelyRejected[\s\S]*?setPendingPatientMessage\([\s\S]*?if \(wasDefinitivelyRejected && optimisticQuestionId\)[\s\S]*?setOptimisticHistoryMessage\([\s\S]*?if \(wasDefinitivelyRejected\) \{[\s\S]*?setInputValue\(\(currentValue\) => currentValue \|\| message\);/,
  );
  assert.match(pageSource, /error\.status === 401[\s\S]*?setAuthUser\(null\);[\s\S]*?setIsAuthDialogOpen\(true\);/);
  assert.match(pageSource, /deliveryState: "uncertain"/);
  assert.match(pageSource, /message\.deliveryState === "uncertain"[\s\S]*?待确认/);
  assert.match(pageSource, /const trainingContextEpochRef = useRef\(0\);/);
  assert.match(pageSource, /trainingContextEpochRef\.current \+= 1;[\s\S]*?\[authUser\?\.user_id, requestedSessionId\]/);
  assert.match(pageSource, /requestContextEpoch = trainingContextEpochRef\.current;[\s\S]*?await ensureActiveSession\(requestContextEpoch\);[\s\S]*?requestContextEpoch !== trainingContextEpochRef\.current/);
  assert.match(pageSource, /async function ensureActiveSession\([\s\S]*?expectedContextEpoch[\s\S]*?createSession\([\s\S]*?expectedContextEpoch !== trainingContextEpochRef\.current/);
  assert.match(pageSource, /requestContextEpoch !== trainingContextEpochRef\.current/);
  assert.match(pageSource, /hasUncertainHistoryMessage[\s\S]*?上一轮问诊仍待确认/);
  assert.match(pageSource, /hasUncertainHistoryMessage \? "等待确认" : "发送问诊"/);
  assert.match(pageSource, /async function handleStartNewSession[\s\S]*?if \(isCreating \|\| isSending\) \{/);
  assert.match(pageSource, /disabled=\{!authUser \|\| !selectedCaseId \|\| !isTrainingModelConfigReady \|\| isCreating \|\| isSending\}/);
  assert.match(
    pageSource,
    /aria-live="assertive"[\s\S]*?role="alert"[\s\S]*?\{errorText\}/,
  );
});

test("speech input is bounded without silently truncating transcription text", () => {
  assert.match(
    pageSource,
    /if \(audioFile\.size > AUDIO_TRANSCRIPTION_MAX_BYTES\)[\s\S]*?const result = await transcribeSpeechAudio\(audioFile\);/,
  );
  assert.match(pageSource, /return combinedTranscript;/);
  assert.doesNotMatch(pageSource, /combinedTranscript\.slice\(/);
  assert.match(pageSource, /转写内容已完整保留到输入框/);
  assert.match(pageSource, /if \(speechText\.length > SPEECH_INPUT_MAX_CHARS\)/);
});

test("app theme uses Claude-like paper palette with Chinese font fallbacks", () => {
  assert.match(globalsSource, /--background: #FAF9F5;/);
  assert.match(globalsSource, /--foreground: #141413;/);
  assert.match(globalsSource, /--card: #FFFFFF;/);
  assert.match(globalsSource, /--muted: #F5F4ED;/);
  assert.match(globalsSource, /--muted-foreground: #6B6A68;/);
  assert.match(globalsSource, /--border: #E8E6DA;/);
  assert.match(globalsSource, /--brand: #AE5630;/);
  assert.match(globalsSource, /--brand-hover: #C4633A;/);
  assert.match(globalsSource, /--destructive: #B42318;/);
  assert.match(globalsSource, /--font-ui: Inter, "Noto Sans SC", "Microsoft YaHei", Arial, sans-serif;/);
  assert.match(globalsSource, /--font-serif: "Noto Serif SC", "Source Han Serif SC", "Songti SC", Georgia, serif;/);
  assert.match(globalsSource, /--font-mono: "JetBrains Mono", "Cascadia Code", Consolas, monospace;/);
  assert.match(globalsSource, /--color-brand: var\(--brand\);/);
  assert.match(globalsSource, /--color-brand-hover: var\(--brand-hover\);/);
  assert.match(globalsSource, /--color-destructive: var\(--destructive\);/);
  assert.match(globalsSource, /body \{[\s\S]*?font-family: var\(--font-ui\);/);
  assert.match(layoutSource, /<body className="font-ui">/);
  assert.doesNotMatch(layoutSource, /next\/font\/google/);
  assert.doesNotMatch(layoutSource, /Inter\(/);
});

test("home page uses Claude-like brand tokens without legacy teal hardcoding", () => {
  assert.doesNotMatch(pageSource, /#2F6868|#2f6868/);
  assert.match(pageSource, /bg-brand\/10/);
  assert.match(pageSource, /hover:bg-brand-hover/);
  assert.match(pageSource, /focus:ring-brand\/15/);
});

test("student action buttons keep Chinese labels on one line", () => {
  assertInteractiveLabelsDoNotWrap("home page", pageSource, [
    "登录",
    "关闭菜单",
    "退出登录",
    "关闭",
    "查体项目",
    "辅助检查",
  ]);
  assertInteractiveLabelsDoNotWrap("history page", historySource, ["返回工作台", "继续训练", "删除记录", "确认删除"]);
  assertInteractiveLabelsDoNotWrap("cases page", casesSource, ["返回工作台"]);
  assertInteractiveLabelsDoNotWrap("report page", reportSource, ["返回工作台"]);
  assertInteractiveLabelsDoNotWrap("profile page", profileSource, ["返回工作台", "继续训练"]);
  assertInteractiveLabelsDoNotWrap("safety page", safetySource, ["返回工作台"]);
  assertInteractiveLabelsDoNotWrap("sources page", sourcesSource, ["返回工作台"]);
});

test("home page keeps backend patient opening utterance metadata without auto-speaking first", () => {
  assert.match(pageSource, /patient_opening_utterance: string;/);
  assert.match(pageSource, /patientOpeningUtterance: string;/);
  assert.match(pageSource, /patient_opening_utterance: string;/);
  assert.match(pageSource, /patientOpeningUtterance: caseSummary\.patient_opening_utterance,/);
  assert.doesNotMatch(pageSource, /const preparedPatientOpeningUtterance = session\?\.patient_opening_utterance \?\? selectedCase\?\.patientOpeningUtterance \?\? null;/);
  assert.doesNotMatch(pageSource, /id: "patient-opening"/);
  assert.doesNotMatch(pageSource, /text: preparedPatientOpeningUtterance,/);
  assert.doesNotMatch(pageSource, /id: "chief-complaint"/);
  assert.doesNotMatch(pageSource, /`医生您好，我这次主要是\$\{session\.chief_complaint\}。`/);
});

test("home chat keeps patient streaming before coach process hints", () => {
  assert.match(pageSource, /function getVisibleApiMessagesDuringPendingReply\(/);
  assert.match(pageSource, /pendingPatientMessage\.apiMessageIndex === undefined/);
  assert.match(pageSource, /messages\.slice\(0, pendingPatientMessage\.apiMessageIndex \+ 1\)/);
  assert.match(pageSource, /message\.role === "coach"/);
  assert.match(pageSource, /pendingPatientMessage\?\.finalText/);
  assert.match(pageSource, /getVisibleApiMessagesDuringPendingReply\(session\.messages, pendingPatientMessage\)/);
});

test("home composer supports speech input and patient reply playback through backend audio APIs", () => {
  assert.match(pageSource, /type SpeechTranscriptionResponse = Readonly<\{/);
  assert.match(pageSource, /async function transcribeSpeechAudio\(file: File\): Promise<SpeechTranscriptionResponse>/);
  assert.match(pageSource, /fetch\("\/api\/audio\/transcriptions"/);
  assert.match(pageSource, /type PatientSpeechContext = Readonly<\{/);
  assert.match(pageSource, /async function synthesizePatientSpeech\(text: string, context: PatientSpeechContext\): Promise<Blob>/);
  assert.match(pageSource, /fetch\("\/api\/audio\/speech"/);
  assert.match(pageSource, /body: JSON\.stringify\(\{[\s\S]*?input: text,[\s\S]*?session_id: context\.sessionId,[\s\S]*?message_index: context\.messageIndex,[\s\S]*?emotion: context\.emotion,[\s\S]*?\}\),/);
  assert.match(pageSource, /new MediaRecorder\(stream/);
  assert.match(pageSource, /new File\(\[audioBlob\], `osce-question-\$\{Date\.now\(\)\}\.\$\{extension\}`/);
  assert.match(pageSource, /setInputValue\(\(currentValue\) => \{/);
  assert.match(pageSource, /const isPatient = !isStudent && !isCoach;/);
  assert.match(pageSource, /function canShowPatientSpeechPlayback\(message: ChatMessage\): boolean/);
  assert.match(pageSource, /return message\.speaker === "patient" && !message\.isPending && getPatientSpeechText\(message\)\.length > 0;/);
  assert.match(pageSource, /handlePatientSpeechButtonClick\(message\)/);
  assert.match(pageSource, /aria-label=\{speechInputButtonAriaLabel\}/);
  assert.match(pageSource, /title=\{speechInputButtonTitle\}/);
  assert.match(pageSource, /<MicrophoneIcon \/>/);
  assert.match(pageSource, /<SpeakerIcon \/>/);
  assert.match(pageSource, /canShowPatientSpeechPlayback\(message\) \?/);
  assert.match(pageSource, /await synthesizePatientSpeech\(speechText, \{[\s\S]*?sessionId: session\?\.session_id,[\s\S]*?messageIndex: message\.apiMessageIndex,[\s\S]*?emotion: message\.emotion,[\s\S]*?\}\);/);
  assert.doesNotMatch(pageSource, />\s*\{speechInputButtonLabel\}\s*<\/button>/);
  assert.doesNotMatch(pageSource, /\{patientSpeechState === "loading" \? "生成中" : patientSpeechState === "playing" \? "停止" : "播放"\}/);

  const speechStopStart = pageSource.indexOf("async function handleSpeechRecordingStopped");
  const speechStopEnd = pageSource.indexOf("async function handleSpeechInputButtonClick");
  assert.ok(speechStopStart >= 0 && speechStopEnd > speechStopStart, "should define speech transcription handler before input button handler");
  const speechStopSource = pageSource.slice(speechStopStart, speechStopEnd);
  assert.match(speechStopSource, /setInputValue/);
  assert.doesNotMatch(speechStopSource, /sendHistoryMessage|handleSubmit/, "speech transcription should fill the composer instead of auto-sending");
});

test("home pending patient reply renders a collapsible agent processing timeline", () => {
  assert.match(pageSource, /type BackendProcessingTraceItem = Readonly<\{/);
  assert.match(pageSource, /processing_trace\?: readonly BackendProcessingTraceItem\[];/);
  assert.match(pageSource, /processing_duration_ms\?: number;/);
  assert.match(pageSource, /type AgentProcessingTimeline = Readonly<\{/);
  assert.match(pageSource, /startedAtMs\?: number;/);
  assert.match(pageSource, /type AgentProcessingStep = Readonly<\{[\s\S]*?metadata\?: Readonly<Record<string, unknown>>;/);
  assert.match(pageSource, /const AGENT_PROCESSING_STEP_DEFINITIONS/);
  assert.match(pageSource, /正在解析问诊意图/);
  assert.match(pageSource, /正在匹配病例事实/);
  assert.match(pageSource, /正在评估是否调用 Skill/);
  assert.match(pageSource, /正在检索教学知识库/);
  assert.match(pageSource, /教师智能体正在复核边界/);
  assert.match(pageSource, /未命中新增病例事实/);
  assert.match(pageSource, /本轮未调用 Skill/);
  assert.match(pageSource, /本轮未使用知识库/);
  assert.match(pageSource, /getAgentProcessingStepLabel\(step\)/);
  assert.match(pageSource, /function formatAgentProcessingElapsed\(elapsedMs: number \| undefined\): string/);
  assert.match(pageSource, /return "瞬时";/);
  assert.match(pageSource, /type SessionProcessingStatus = Readonly<\{/);
  assert.match(pageSource, /function fetchSessionProcessingStatus\(sessionId: string\): Promise<SessionProcessingStatus>/);
  assert.match(pageSource, /function buildPendingAgentProcessingTimeline\(processingStatus\?: SessionProcessingStatus \| null\): AgentProcessingTimeline/);
  assert.match(pageSource, /state: "pending",[\s\S]*?isOpen: false,[\s\S]*?summary: getPendingPatientProcessingSummary\(processingStatus, timelineSteps\)/);
  assert.doesNotMatch(pageSource, /if \(processingStatus\.summary\)/);
  assert.match(pageSource, /return latestVisibleStep \? `当前：\$\{stripTerminalChinesePunctuation\(getAgentProcessingStepLabel\(latestVisibleStep\)\)\}` : "当前：正在组织标准化病人回复";/);
  assert.match(pageSource, /const isPatientFallbackStep = PATIENT_REPLY_PROCESSING_STEP_IDS\.has\(currentStepId\);/);
  assert.match(pageSource, /const fallbackStepId = isPatientFallbackStep \? currentStepId : "response_wait";/);
  assert.match(pageSource, /: "正在等待标准化病人回复";/);
  assert.doesNotMatch(pageSource, /当前：等待后端返回真实流程。/);
  assert.match(pageSource, /function getBackendProcessingTraceElapsedMs\(turn: AgentTurnMemoryItem \| undefined\): number \| undefined/);
  assert.match(pageSource, /function getTimelineStepsFromBackendProcessingTrace\(trace: readonly BackendProcessingTraceItem\[] \| undefined\): readonly AgentProcessingStep\[]/);
  assert.match(pageSource, /metadata: step\.metadata/);
  assert.match(pageSource, /function getAgentProcessingStepRetrievedCount\(step: AgentProcessingStep\): number \| undefined/);
  assert.match(pageSource, /`已检索教学知识库：命中 \$\{retrievedCount\} 条`/);
  assert.match(pageSource, /`知识库 \$\{knowledgeReferenceCount\} 条`/);
  assert.match(pageSource, /const PATIENT_REPLY_PROCESSING_STEP_IDS = new Set\(\["intent", "case_context", "patient_reply", "response"\]\);/);
  assert.match(pageSource, /function buildCompletedAgentProcessingTimeline\(session: OsceSession, replyText: string\): AgentProcessingTimeline/);
  assert.match(pageSource, /function AgentProcessingTimelineView/);
  assert.match(pageSource, /open=\{timeline\.isOpen\}/);
  assert.doesNotMatch(pageSource, /AGENT_PROCESSING_STEP_INTERVAL_MS/);
  assert.doesNotMatch(pageSource, /setAgentProcessingStepIndex/);
  assert.doesNotMatch(pageSource, /agentProcessingDurationsByMessageKey/);
  assert.match(pageSource, /processingTimeline: \{[\s\S]*?\.\.\.buildPendingAgentProcessingTimeline\(\),[\s\S]*?startedAtMs: patientReplyProcessingStartedAtMs,[\s\S]*?\}/);
  assert.match(pageSource, /refreshPendingProcessingTimeline\(activeSession\.session_id, pendingPatientReplyId\)/);
  assert.match(pageSource, /window\.setInterval\(pollProcessingStatus, AGENT_PROCESSING_STATUS_POLL_INTERVAL_MS\)/);
  assert.match(pageSource, /if \(processingStatus\.state !== "running"\) \{[\s\S]*?return;[\s\S]*?\}/);
  assert.match(pageSource, /const completedTimeline = buildCompletedAgentProcessingTimeline\(updatedSession, replyText\);/);
  assert.match(pageSource, /elapsedMs: Math\.max\(completedTimeline\.elapsedMs \?\? 0, patientReplyProcessingElapsedMs\)/);
  assert.match(pageSource, /message\.processingTimeline\?\.state === "pending"/);
  assert.match(pageSource, /智能体处理中/);
  assert.match(pageSource, /智能体处理了/);
  assert.match(pageSource, /formatAgentProcessingElapsed\(timeline\.elapsedMs\)/);
  assert.match(pageSource, /const pendingElapsedMs = timeline\.state === "pending" && pendingStartedAtMs !== undefined/);
  assert.match(pageSource, /`\$\{timeline\.title\} · \$\{timeline\.summary\}\$\{pendingElapsedMs === undefined \? "" : ` · \$\{formatAgentProcessingTimerElapsed\(pendingElapsedMs\)\}`\}`/);
  assert.doesNotMatch(pageSource, /formatAgentProcessingTimestamp/);
  assert.doesNotMatch(pageSource, /step\.startedAt/);
  assert.doesNotMatch(pageSource, /step\.completedAt/);
  assert.match(pageSource, /className="group mt-3 text-sm"/);
  assert.match(pageSource, /key=\{`\$\{timeline\.state\}-\$\{timeline\.elapsedMs \?\? "no-duration"\}`\}/);
  assert.doesNotMatch(pageSource, /rounded-\[22px\] border border-\[#E5D7C3\] bg-\[#FFFCF5\]/);
  assert.match(globalsSource, /@keyframes clinical-osce-agent-process-pulse/);
  assert.match(globalsSource, /\.clinical-osce-agent-process-dot-active/);
});

test("home patient reply processing timeline excludes coach Skill and RAG work", () => {
  const completedTimelineStart = pageSource.indexOf("function buildCompletedAgentProcessingTimeline");
  const completedTimelineEnd = pageSource.indexOf("function buildCompletedCoachProcessingTimeline");
  assert.ok(completedTimelineStart >= 0, "should define completed patient timeline builder");
  assert.ok(completedTimelineEnd > completedTimelineStart, "should define coach timeline after patient timeline");

  const completedTimelineSource = pageSource.slice(completedTimelineStart, completedTimelineEnd);
  assert.match(completedTimelineSource, /getPatientReplyProcessingSteps\(backendTraceSteps\)/);
  assert.doesNotMatch(completedTimelineSource, /getLatestPassiveCoachReviewTurn/);
  assert.doesNotMatch(completedTimelineSource, /coachTurn/);
  assert.doesNotMatch(completedTimelineSource, /selectedSkillCount|knowledgeReferenceCount|`Skill|`知识库/);

  const pendingTimelineStart = pageSource.indexOf("function buildPendingAgentProcessingTimeline");
  const pendingTimelineEnd = pageSource.indexOf("function buildPendingHintProcessingTimeline");
  assert.ok(pendingTimelineStart >= 0, "should define pending patient timeline builder");
  assert.ok(pendingTimelineEnd > pendingTimelineStart, "should define hint timeline after patient timeline");

  const pendingTimelineSource = pageSource.slice(pendingTimelineStart, pendingTimelineEnd);
  assert.match(pendingTimelineSource, /getPatientReplyProcessingSteps\(statusSteps\)/);
});

test("home pending teacher hint timeline uses backend steps instead of patient reply filtering", () => {
  const hintTimelineStart = pageSource.indexOf("function buildPendingHintProcessingTimeline");
  const hintTimelineEnd = pageSource.indexOf("function getBackendProcessingTraceElapsedMs");
  assert.ok(hintTimelineStart >= 0, "should define pending teacher hint timeline builder");
  assert.ok(hintTimelineEnd > hintTimelineStart, "should define backend trace helpers after hint timeline");

  const hintTimelineSource = pageSource.slice(hintTimelineStart, hintTimelineEnd);
  assert.match(hintTimelineSource, /processingStatus\?\.steps\.map/);
  assert.match(hintTimelineSource, /withTeacherContextEvaluationStep\(timelineSteps\)/);
  assert.match(hintTimelineSource, /正在评估当前对话上下文/);
  assert.match(hintTimelineSource, /正在生成过程提示/);
  assert.match(hintTimelineSource, /title: "教师智能体处理中"/);
  assert.doesNotMatch(hintTimelineSource, /buildPendingAgentProcessingTimeline/);
  assert.doesNotMatch(hintTimelineSource, /getPatientReplyProcessingSteps/);
  assert.doesNotMatch(hintTimelineSource, /正在等待可见回复返回/);
});

test("home history input disables browser autofill history", () => {
  assert.match(pageSource, /id="history-question"[\s\S]*?autoComplete="off"[\s\S]*?autoCorrect="off"[\s\S]*?spellCheck=\{false\}/);
});

test("home inquiry composer does not show canned history shortcut or example placeholder", () => {
  assert.doesNotMatch(pageSource, />\s*问现病史\s*<\/button>/);
  assert.doesNotMatch(pageSource, /setInputValue\("什么时候开始疼的？"\)/);
  assert.doesNotMatch(pageSource, /placeholder="例如：什么时候开始疼的？疼痛在哪里？有没有恶心或腹泻？"/);
  assert.match(pageSource, /placeholder="输入问诊问题，开始诊断训练"/);
});

test("home procedure result modal shows the whole returned batch", () => {
  assert.match(pageSource, /const \[selectedProcedureResults, setSelectedProcedureResults\] = useState<readonly ProcedureResult\[]>\(\[]\);/);
  assert.match(pageSource, /function openProcedureResultGroup\(nextProcedureResults: readonly ProcedureResult\[]\)/);
  assert.match(pageSource, /const selectedProcedureResultItems = selectedProcedureResult \? \(selectedProcedureResults\.length > 0 \? selectedProcedureResults : \[selectedProcedureResult\]\) : \[];/);
  assert.match(pageSource, /openProcedureResult\(nextProcedureResult\);/);
  assert.match(pageSource, /openProcedureResultGroup\(nextProcedureResults\);/);
  assert.match(pageSource, /selectedProcedureResultItems\.length > 1 \? `已返回 \$\{selectedProcedureResultItems\.length\} 项结果` : selectedProcedureResult\.label/);
  assert.match(pageSource, /selectedProcedureResultItems\.map\(\(procedureResult\) => \(/);
  assert.doesNotMatch(pageSource, /setSelectedProcedureResult\(nextProcedureResults\[0\] \?\? null\);/);
});

test("home message failure status is not limited to backend downtime", () => {
  assert.match(pageSource, /setStatusText\("问诊未保存，请查看错误详情后重试。"\);/);
  assert.match(pageSource, /setStatusText\("本轮问诊结果暂时无法确认，当前问题已保留为待确认记录。"\);/);
  assert.doesNotMatch(pageSource, /setStatusText\("问诊发送失败，请确认后端仍在运行。"\);/);
});

test("home diagnosis submit does not report submit failure when only report retrieval fails", () => {
  assert.match(pageSource, /import \{ useRouter, useSearchParams \} from "next\/navigation";/);
  assert.match(pageSource, /const router = useRouter\(\);/);
  assert.match(pageSource, /const submittedSession = await submitDiagnosis\(activeSession\.session_id, diagnosis, reasoning\);/);
  assert.match(pageSource, /setSession\(submittedSession\);/);
  assert.match(pageSource, /setStatusText\("诊断已提交，正在生成评分报告\.\.\."\);/);
  assert.match(pageSource, /function generateSessionReport\(sessionId: string\): Promise<FeedbackReport>/);
  assert.match(pageSource, /`\/api\/sessions\/\$\{sessionId\}\/report\/generate`/);
  assert.match(pageSource, /method: "POST"/);
  assert.doesNotMatch(pageSource, /function getSessionReport/);
  assert.match(pageSource, /try \{[\s\S]*?const report = await generateSessionReport\(submittedSession\.session_id\);[\s\S]*?setFeedbackReport\(report\);[\s\S]*?router\.push\(`\/report\?session_id=\$\{encodeURIComponent\(report\.session_id \|\| submittedSession\.session_id\)\}`\);[\s\S]*?\} catch \(reportError\) \{/);
  assert.match(pageSource, /setErrorText\(`诊断已提交，但报告暂时未取回：\$\{reportMessage\}`\);/);
  assert.match(pageSource, /setStatusText\("诊断已提交；评分报告暂时未取回，可稍后从训练记录打开。"\);/);
  assert.match(pageSource, /setStatusText\("诊断提交失败，请确认后端仍在运行。"\);/);
}
);

test("history page renders Chinese case title instead of raw case id as primary label", () => {
  assert.match(historySource, /case_title: string;/);
  assert.match(historySource, /病例：\{session\.case_title \?\? session\.case_id\}/);
  assert.doesNotMatch(historySource, /病例：\{session\.case_id\}/);
});

test("report context prefers Chinese case title from backend session", () => {
  assert.match(reportSource, /case_title\?: string;/);
  assert.match(reportSource, /backendSession\?\.case_title \?\? report\?\.case_id \?\? "待读取"/);
  assert.doesNotMatch(reportSource, /<dd className="mt-1 font-medium">\{report\?\.case_id \?\? "待读取"\}<\/dd>/);
});

test("home evidence uses only facts already revealed by the student session projection", () => {
  assert.match(pageSource, /function getEvidenceItem\(factId: string, trainingProgress: TrainingProgress \| null, fallbackIndex: number\): EvidenceItem/);
  assert.match(pageSource, /trainingProgress\?\.revealed_items\.history\.find/);
  assert.match(pageSource, /detail: revealedHistoryItem\.label/);
  assert.doesNotMatch(pageSource, /trainingProgress\?\.coverage_map/);
  assert.doesNotMatch(pageSource, /evidenceByFactId/);
  assert.doesNotMatch(pageSource, /label: factId, detail: "后端已披露该结构化事实。"/);
  assert.doesNotMatch(pageSource, /未覆盖素材：\$\{item\.id\}/);
  assert.doesNotMatch(pageSource, /canonical_answer/);
});

test("home page labels collected clues from revealed metadata instead of symptom keywords", () => {
  assert.match(pageSource, /type StudentRevealedItem = Readonly<\{/);
  assert.match(pageSource, /topic\?: string \| null;/);
  assert.match(pageSource, /slot\?: string \| null;/);
  assert.match(pageSource, /function getEvidenceLabelFromRevealedItem\(item: StudentRevealedItem, fallbackIndex: number\): string/);
  assert.match(pageSource, /const topicLabel = getEvidenceTopicLabel\(item\.topic\);/);
  assert.match(pageSource, /const slotLabel = getEvidenceSlotLabel\(item\.slot\);/);
  assert.doesNotMatch(pageSource, /linked_rubric_items/);
  assert.doesNotMatch(pageSource, /status: "covered" \| "pending"/);
  assert.doesNotMatch(pageSource, /if \(\x2F持续\|胀痛\|隐痛\|加重\x2F\.test\(detail\)\) \{\s*return "疼痛性质";\s*\}/);
});

test("home evidence panel scrolls to the newest revealed clue and highlights it", () => {
  assert.match(pageSource, /const \[latestRevealedFactId, setLatestRevealedFactId\] = useState<string \| null>\(null\);/);
  assert.match(pageSource, /const previousRevealedFactIdsRef = useRef<readonly string\[] \| null>\(null\);/);
  assert.match(pageSource, /const latestEvidenceItemRef = useRef<HTMLDivElement \| null>\(null\);/);
  assert.match(pageSource, /const newestRevealedFactId = \[\.\.\.currentRevealedFactIds\]\.reverse\(\)\.find/);
  assert.match(pageSource, /setRightPanelOpenStates\(\(currentStates\) => currentStates\.evidence \? currentStates : \{ \.\.\.currentStates, evidence: true \}\);/);
  assert.match(pageSource, /latestEvidenceItemRef\.current\?\.scrollIntoView\(\{[\s\S]*?behavior: "smooth"[\s\S]*?block: "center"[\s\S]*?\}\);/);
  assert.match(pageSource, /data-latest-revealed-fact=\{isLatestRevealedFact \? "true" : undefined\}/);
  assert.match(pageSource, /clinical-osce-evidence-glow overflow-hidden/);
  assert.match(globalsSource, /@keyframes clinical-osce-evidence-glow/);
  assert.match(globalsSource, /\.clinical-osce-evidence-glow::before/);
  assert.match(globalsSource, /animation: clinical-osce-evidence-glow 1\.25s ease-in-out 2 both;/);
  assert.match(globalsSource, /background: transparent;/);
  assert.match(globalsSource, /border: 1px solid rgb\(214 165 79 \/ 0\.58\);/);
  assert.match(pageSource, /\}, 2600\);/);
  assert.match(globalsSource, /inset: 2px;/);
  assert.doesNotMatch(globalsSource, /radial-gradient\(circle at 50% 50%/);
  assert.doesNotMatch(globalsSource, /linear-gradient\(135deg/);
  assert.doesNotMatch(globalsSource, /inset: -6px;/);
  assert.doesNotMatch(globalsSource, /box-shadow: 0 0 0 10px/);
});

test("home dialogue speaker labels render as plain text labels", () => {
  assert.match(pageSource, /<p className=\{isStudent \? "text-white\/80" : isSafetyBoundary \? "flex items-center gap-2 font-medium text-red-700" : isCoach \? "text-\[#8A5A00\]" : "text-muted-foreground"\}>[\s\S]*?\{message\.label\}/);
  assert.doesNotMatch(pageSource, /const messageLabelClass = isStudent/);
  assert.doesNotMatch(pageSource, /border-white\/45 bg-transparent/);
  assert.doesNotMatch(pageSource, /border-border bg-transparent/);
  assert.doesNotMatch(pageSource, /<p className=\{messageLabelClass\}>[\s\S]*?\{message\.label\}/);
});

test("home patient messages render backend emotion metadata as a visible tag", () => {
  assert.match(pageSource, /readonly emotion\?: string \| null;/);
  assert.match(pageSource, /emotion: normalizePatientEmotion\(message\.emotion\)/);
  assert.match(pageSource, /message\.emotion \? \(/);
  assert.match(pageSource, /情绪：\{message\.emotion\}/);
});

test("home page replaces the Next dev ball with a polished OSCE floating dock", () => {
  assert.match(pageSource, /type OsceDockMenuGroup = "training" \| "system";/);
  assert.match(pageSource, /const ADMIN_APP_URL = process\.env\.NEXT_PUBLIC_CLINICAL_OSCE_ADMIN_URL \?\? "http:\/\/127\.0\.0\.1:3001";/);
  assert.match(pageSource, /const ADMIN_MODEL_CONFIG_URL = `\$\{ADMIN_APP_URL\}#model-config`;/);
  assert.match(pageSource, /const \[isOsceDockOpen, setIsOsceDockOpen\] = useState\(false\);/);
  assert.match(pageSource, /const \[osceDockMenuGroup, setOsceDockMenuGroup\] = useState<OsceDockMenuGroup \| null>\(null\);/);
  assert.match(pageSource, /const \[isApiConfigHelpOpen, setIsApiConfigHelpOpen\] = useState\(false\);/);
  assert.match(pageSource, /const osceDockSubmenuAlignmentClass = osceDockPosition\.side === "right" \? "right-full mr-2" : "left-full ml-2";/);
  assert.match(pageSource, /function selectOsceDockMenuGroup\(nextGroup: OsceDockMenuGroup\): void/);
  assert.match(pageSource, /setOsceDockMenuGroup\(\(currentGroup\) => \(currentGroup === nextGroup \? null : nextGroup\)\);/);
  assert.match(pageSource, /function closeOsceDock\(\): void/);
  assert.match(pageSource, /setOsceDockMenuGroup\(null\);[\s\S]*?setIsOsceDockOpen\(false\);/);
  assert.match(pageSource, /if \(!isOsceDockOpen\) \{[\s\S]*?setOsceDockMenuGroup\(null\);[\s\S]*?\}/);
  assert.doesNotMatch(pageSource, />\s*OSCE 快捷入口\s*</);
  assert.doesNotMatch(pageSource, /OSCE Dock/);
  assert.match(pageSource, /bg-white\/95 p-3 shadow-\[0_18px_45px_rgba\(20,20,19,0\.16\)\] backdrop-blur/);
  assert.match(pageSource, /<div className="grid w-36 gap-2">/);
  assert.match(pageSource, />\s*训练入口\s*<\/button>[\s\S]*?>\s*API 配置\s*<\/button>[\s\S]*href="\/safety"[\s\S]*?>\s*安全声明\s*<\/Link>[\s\S]*href="\/sources"[\s\S]*?>\s*数据来源\s*<\/Link>[\s\S]*?>\s*系统状态\s*<\/button>[\s\S]*?>\s*关闭菜单\s*<\/button>/);
  assert.doesNotMatch(pageSource, />\s*训练操作台\s*<\/button>[\s\S]*?>\s*系统与配置\s*<\/button>[\s\S]*?>\s*资料与说明\s*<\/button>/);
  assert.match(pageSource, /absolute top-0 \$\{osceDockSubmenuAlignmentClass\} w-48 rounded-2xl border border-border bg-white\/95 p-2 shadow-\[0_18px_45px_rgba\(20,20,19,0\.14\)\] backdrop-blur/);
  assert.match(pageSource, /osceDockMenuGroup \? \(/);
  assert.match(pageSource, /selectOsceDockMenuGroup\("training"\)/);
  assert.match(pageSource, /selectOsceDockMenuGroup\("system"\)/);
  assert.match(pageSource, /href="\/cases"/);
  assert.match(pageSource, /href="\/history"/);
  assert.match(pageSource, /href="\/profile"/);
  assert.match(pageSource, /href="\/safety"/);
  assert.match(pageSource, /href="\/sources"/);
  assert.match(pageSource, /onClick=\{\(\) => \{[\s\S]*?closeOsceDock\(\);[\s\S]*?setIsApiConfigHelpOpen\(true\);[\s\S]*?\}\}/);
  assert.doesNotMatch(pageSource, /<a className=\{osceDockActionClass\} href=\{ADMIN_MODEL_CONFIG_URL\}/);
  assert.match(pageSource, /API 配置/);
  assert.match(pageSource, /安全声明/);
  assert.match(pageSource, /数据来源/);
  assert.match(pageSource, /href=\{`\/report\?session_id=\$\{feedbackReport\.session_id\}`\}/);
  assert.match(pageSource, /onClick=\{\(\) => \{[\s\S]*?closeOsceDock\(\);[\s\S]*?void handleHintRequest\(\);[\s\S]*?\}\}/);
  assert.match(pageSource, /onClick=\{\(\) => \{[\s\S]*?closeOsceDock\(\);[\s\S]*?setIsPatientProfileOpen\(true\);[\s\S]*?\}\}/);
  assert.match(pageSource, /const osceDockActionClass = "[^"]*whitespace-nowrap/);
  assert.match(pageSource, /rounded-full border border-brand\/35 bg-\[#FFF8E8\] text-brand shadow-\[0_14px_32px_rgba\(174,86,48,0\.22\)\]/);
  assert.match(pageSource, /absolute inset-1\.5 rounded-full border border-brand\/20 bg-background\/80/);
  assert.match(pageSource, /relative z-10 flex size-8 items-center justify-center rounded-full bg-brand text-base font-semibold text-white/);
  assert.match(pageSource, />\s*临\s*<\/span>/);
  assert.match(pageSource, /type BackendConnectionStatus = "checking" \| "online" \| "offline";/);
  assert.match(pageSource, /const \[backendConnectionStatus, setBackendConnectionStatus\] = useState<BackendConnectionStatus>\("checking"\);/);
  assert.match(pageSource, /fetch\("\/api\/health", \{[\s\S]*?cache: "no-store",[\s\S]*?credentials: "same-origin",[\s\S]*?\}\)/);
  assert.doesNotMatch(pageSource, /fetch\("\/api\/health\/config"/);
  assert.match(pageSource, /const backendStatusLightClass = getBackendStatusLightClass\(backendConnectionStatus\);/);
  assert.match(pageSource, /const backendStatusHaloClass = getBackendStatusHaloClass\(backendConnectionStatus\);/);
  assert.match(pageSource, /aria-label=\{`打开 OSCE 快捷入口，\$\{backendConnectionStatusLabel\}`\}/);
  assert.match(pageSource, /absolute right-1\.5 top-1\.5 flex size-3 items-center justify-center/);
  assert.match(pageSource, /motion-safe:animate-ping/);
  assert.match(pageSource, /motion-safe:animate-pulse/);
  assert.doesNotMatch(pageSource, /absolute right-2 top-2 size-2 rounded-full bg-\[#86B993\]/);
  assert.doesNotMatch(pageSource, /absolute inset-2 rounded-full border-2 border-white\/80 bg-transparent/);
  assert.doesNotMatch(pageSource, /relative z-10">OSCE<\/span>/);
});

test("home OSCE dock opens student API config dialog instead of navigating directly to admin", () => {
  assert.match(pageSource, /type ApiConfigProvider = "custom_backend" \| "gemini" \| "vertex_gemini_adc" \| "vertex_gemini_api_key" \| "openai_compatible" \| "anthropic";/);
  assert.doesNotMatch(pageSource, /STUDENT_API_CONFIG_STORAGE_KEY/);
  assert.match(pageSource, /function createDefaultStudentApiConfig\(\): StudentApiConfig/);
  assert.match(pageSource, /apiKey: "",[\s\S]*?model: "",[\s\S]*?baseUrl: "",[\s\S]*?proxyUrl: "",/);
  assert.match(pageSource, /function createStudentApiConfigFromRuntime\(runtimeConfig: StudentApiConfigRuntimeResponse\): StudentApiConfig/);
  assert.doesNotMatch(pageSource, /window\.localStorage\.getItem\(STUDENT_API_CONFIG_STORAGE_KEY\)/);
  assert.doesNotMatch(pageSource, /window\.localStorage\.setItem\(STUDENT_API_CONFIG_STORAGE_KEY/);
  assert.match(pageSource, /function testStudentApiConfigConnection\(config: StudentApiConfig\): Promise<StudentApiConfigTestResponse>/);
  assert.match(pageSource, /function getStudentRuntimeApiConfig\(\): Promise<StudentApiConfigRuntimeResponse>/);
  assert.match(pageSource, /\/api\/model-config\/test/);
  assert.match(pageSource, /\/api\/model-config\/runtime/);
  assert.match(pageSource, /defaultModel: "gemini-3.1-pro-preview"/);
  assert.doesNotMatch(pageSource, /gemini-3\.1-flash-lite-preview/);
  assert.match(pageSource, /defaultProxyUrl: ""/);
  assert.match(pageSource, /defaultProxyUrl: "http:\/\/127\.0\.0\.1:7897"/);
  assert.match(pageSource, /id: "anthropic",[\s\S]*?label: "Anthropic",[\s\S]*?defaultModel: "claude-3-5-sonnet-latest"/);
  assert.match(pageSource, /\{isApiConfigHelpOpen \? \(/);
  assert.match(pageSource, /aria-label="关闭 API 配置说明"/);
  assert.match(pageSource, />\s*API 配置\s*</);
  assert.match(pageSource, /const isStudentApiConfigEditable = false;/);
  assert.match(pageSource, /TEST_STAGE_API_CONFIG_MESSAGE/);
  assert.match(pageSource, /测试阶段，统一使用我们提供的模型/);
  assert.match(pageSource, /主对话模型：Gemini 3\.5 Flash/);
  assert.match(pageSource, /备用对话模型：MiMo V2\.5 Pro/);
  assert.match(pageSource, /向量检索：Gemini Embedding/);
  assert.match(pageSource, /备用向量检索：本地 BAAI\/bge-small-zh-v1\.5/);
  assert.match(pageSource, /请不要高并发连续请求/);
  assert.match(pageSource, /bg-background\/70 p-4 backdrop-blur-md/);
  assert.doesNotMatch(pageSource, />\s*服务端\s*</);
  assert.doesNotMatch(pageSource, /<span>\{providerOption\.label\}<\/span>/);
  assert.doesNotMatch(pageSource, /当前渠道：\{formatRuntimeApiConfigSummary\(runtimeApiConfig\)\}/);
  assert.match(pageSource, /api_key_saved\?: boolean;/);
  assert.match(pageSource, /setStudentApiConfig\(createStudentApiConfigFromRuntime\(runtimeConfig\)\)/);
  assert.match(pageSource, /runtimeConfig\.message \?\? "未启用，使用本地确定性回退"/);
  assert.doesNotMatch(pageSource, /选择服务端并测试连通性；OpenAI 兼容、Anthropic、Vertex Gemini ADC 或 Vertex Gemini API Key 配置会同步应用到本次后端运行时/);
  assert.doesNotMatch(pageSource, /id="student-api-key-input"/);
  assert.doesNotMatch(pageSource, /id="student-api-model-input"/);
  assert.doesNotMatch(pageSource, /id="student-api-base-url-input"/);
  assert.doesNotMatch(pageSource, /id="student-api-proxy-url-input"/);
  assert.doesNotMatch(pageSource, /onClick=\{handleSaveStudentApiConfig\}/);
  assert.doesNotMatch(pageSource, />\s*保存配置\s*<\/button>/);
  assert.doesNotMatch(pageSource, />\{isTestingStudentApiConfig \? "测试中" : "测试连通性"\}<\/button>/);
  assert.doesNotMatch(pageSource, />\s*打开管理端配置\s*<\/a>/);
  assert.match(pageSource, /setIsApiConfigHelpOpen\(false\)/);
  assert.doesNotMatch(pageSource, /OpenAI 兼容、Anthropic、Vertex Gemini ADC 或 Vertex Gemini API Key 配置按当前登录账号保存在后端/);
});

test("student README documents blank diagnosis drafts and the server-managed model policy", () => {
  assert.doesNotMatch(webReadmeSource, /初始化默认诊断与推理依据/);
  assert.match(webReadmeSource, /诊断提交表单保持空白结构化草稿/);
  assert.match(webReadmeSource, /后端不得下发标准诊断作为默认值/);
  assert.match(webReadmeSource, /当前比赛 \/ 测试构建采用服务端统一托管模型配置/);
  assert.match(webReadmeSource, /学生端不提供 provider 选择、API Key 输入、保存或连通性测试/);
  assert.match(webReadmeSource, /账号配置只允许服务端批准的 HTTPS provider 主机和 direct 连接/);
  assert.match(webReadmeSource, /只有单人本机 `local-dev` 可显式开启不安全端点兼容开关/);
  assert.doesNotMatch(webReadmeSource, /运行时模型配置按当前登录账号持久化/);
  assert.doesNotMatch(webReadmeSource, /学生端配置保存到浏览器 `localStorage`/);
});

test("student and admin documentation preserves isolated local browser origins", () => {
  assert.match(webReadmeSource, /打开浏览器访问 `http:\/\/localhost:3000`/);
  assert.doesNotMatch(webReadmeSource, /打开浏览器访问 `http:\/\/127\.0\.0\.1:3000`/);
  assert.match(recordingPlanSource, /学生端：`http:\/\/localhost:3000`/);
  assert.match(recordingPlanSource, /管理端：`http:\/\/127\.0\.0\.1:3001`/);
  assert.doesNotMatch(recordingPlanSource, /学生端：`http:\/\/127\.0\.0\.1:3000`/);
});

test("home production deployment keeps student API config visible but read-only", () => {
  assert.match(pageSource, /const DEPLOYMENT_MODE = process\.env\.NEXT_PUBLIC_CLINICAL_OSCE_DEPLOYMENT_MODE \?\? "local-dev";/);
  assert.match(pageSource, /const PRODUCTION_DEPLOYMENT_MODES = new Set\(\["single-node-prod", "vertex-prod"\]\);/);
  assert.match(pageSource, /const isStudentRuntimeApiConfigEnabled = !PRODUCTION_DEPLOYMENT_MODES\.has\(DEPLOYMENT_MODE\);/);
  assert.match(pageSource, /const isStudentApiConfigEditable = false;/);
  assert.doesNotMatch(pageSource, /\{isStudentRuntimeApiConfigEnabled \? \([\s\S]*?>\s*API 配置\s*<\/button>[\s\S]*?\) : null\}/);
  assert.match(pageSource, />\s*API 配置\s*<\/button>/);
  assert.match(pageSource, /\{isApiConfigHelpOpen \? \(/);
  assert.match(pageSource, /测试阶段，统一使用我们提供的模型。/);
  assert.match(webDockerfileSource, /ARG NEXT_PUBLIC_CLINICAL_OSCE_DEPLOYMENT_MODE=local-demo/);
  assert.match(webDockerfileSource, /NEXT_PUBLIC_CLINICAL_OSCE_DEPLOYMENT_MODE=\$\{NEXT_PUBLIC_CLINICAL_OSCE_DEPLOYMENT_MODE\}/);
});

test("student report shows readable personal skill content, not only ids", () => {
  assert.match(reportModelSource, /description\?: string;/);
  assert.match(reportModelSource, /suggested_strategy\?: string;/);
  assert.match(reportSource, /候选说明/);
  assert.match(reportSource, /教学策略/);
  assert.match(reportSource, /candidate\.description/);
  assert.match(reportSource, /candidate\.suggested_strategy/);
  assert.doesNotMatch(reportSource, /candidate\.candidate_id \?\?/);
  assert.doesNotMatch(reportSource, /candidate\.skill_id \?\?/);
});

test("home page keeps only student-safe pedagogy guidance without internal debug state", () => {
  assert.match(pageSource, /type ClinicalReasoningState = Readonly<\{/);
  assert.match(pageSource, /type PedagogyState = Readonly<\{/);
  assert.match(pageSource, /clinical_reasoning_state\?: ClinicalReasoningState;/);
  assert.match(pageSource, /pedagogy_state: PedagogyState;/);
  assert.doesNotMatch(pageSource, /type TeachingPlan =/);
  assert.doesNotMatch(pageSource, /type StageCheckpoint =/);
  assert.doesNotMatch(pageSource, /type HintLadderStep =/);
  assert.doesNotMatch(pageSource, /type AgentDecisionTraceItem =/);
  assert.doesNotMatch(pageSource, /type ReflectionSummary =/);
  assert.doesNotMatch(pageSource, /safe_pending_points|pending_signal_ids|must_ask_ids|must_exam_ids|must_test_ids/);
  assert.match(pageSource, /type RightPanelKey = "evidence" \| "report";/);
  assert.doesNotMatch(pageSource, /agent: false,/);
  assert.doesNotMatch(pageSource, /rightPanelOpenStates\.agent/);
  assert.doesNotMatch(pageSource, /toggleRightPanel\("agent"\)/);
  assert.doesNotMatch(pageSource, /title="智能体教学详情"/);
  assert.doesNotMatch(pageSource, /<Panel title="智能体状态" description="展示教学策略节点的当前目标、下一步动作和安全边界。">/);
  assert.match(pageSource, /clinicalReasoningState\?\.next_best_action\?\.message/);
  assert.doesNotMatch(pageSource, /session\.pedagogy_state\.hint_ladder\.map/);
  assert.doesNotMatch(pageSource, /session\.agent_decision_trace\.slice\(-3\)\.map/);
  assert.doesNotMatch(pageSource, /智能体还未形成可展示的教学状态/);
  assert.doesNotMatch(pageSource, /最近决策轨迹/);
  assert.doesNotMatch(pageSource, /Hint Ladder/);
  assert.doesNotMatch(pageSource, /教学安全边界/);
});

test("home left sidebar uses a personal center menu for profile actions", () => {
  const leftAsideIndex = pageSource.indexOf('<aside className="hidden w-72 shrink-0 border-r border-border bg-background p-4 shadow-inner-right lg:flex lg:flex-col">');
  const leftAsideEndIndex = pageSource.indexOf("</aside>", leftAsideIndex);
  const leftAsideSource = pageSource.slice(leftAsideIndex, leftAsideEndIndex);

  assert.match(pageSource, /const \[isAccountMenuOpen, setIsAccountMenuOpen\] = useState\(false\);/);
  assert.notEqual(leftAsideIndex, -1);
  assert.match(leftAsideSource, />\s*个人中心\s*</);
  assert.match(leftAsideSource, /aria-label="打开个人中心菜单"/);
  assert.match(leftAsideSource, /aria-haspopup="menu"/);
  assert.match(leftAsideSource, /setIsAccountMenuOpen\(\(isOpen\) => !isOpen\)/);
  assert.match(leftAsideSource, />\s*测试账号\s*</);
  assert.match(leftAsideSource, /className="flex w-full items-center justify-between gap-2 rounded-xl border border-border bg-background px-3 py-2 text-sm font-medium text-foreground shadow-xs transition hover:border-brand\/30 hover:bg-accent"/);
  assert.match(leftAsideSource, /className="block rounded-lg border border-border bg-background px-3 py-2 text-center text-sm font-medium whitespace-nowrap transition hover:border-brand\/30 hover:bg-accent"[\s\S]*?href="\/history"[\s\S]*?>\s*训练记录\s*<\/Link>/);
  assert.match(leftAsideSource, /className="mt-2 block rounded-lg border border-border bg-background px-3 py-2 text-center text-sm font-medium whitespace-nowrap transition hover:border-brand\/30 hover:bg-accent"[\s\S]*?href="\/profile"[\s\S]*?>\s*学习画像\s*<\/Link>/);
  assert.match(leftAsideSource, /onClick=\{handleLogout\}/);
  assert.match(leftAsideSource, /border-\[#B42318\]\/30 bg-\[#FEF3F2\] text-\[#B42318\]/);
  assert.match(leftAsideSource, /inline-flex w-full items-center justify-center/);
  assert.doesNotMatch(leftAsideSource, />\s*退出登录\s*<\/button>[\s\S]*\{authUser \? \(/);
});

test("home shell keeps the student-facing brand compact", () => {
  const leftAsideIndex = pageSource.indexOf('<aside className="hidden w-72 shrink-0 border-r border-border bg-background p-4 shadow-inner-right lg:flex lg:flex-col">');
  const leftAsideEndIndex = pageSource.indexOf("</aside>", leftAsideIndex);
  const leftAsideSource = pageSource.slice(leftAsideIndex, leftAsideEndIndex);

  assert.notEqual(leftAsideIndex, -1);
  assert.match(leftAsideSource, /<h1 className="text-xl font-semibold tracking-tight">临境 OSCE 智能体<\/h1>/);
  assert.match(leftAsideSource, /基于公开 OSCE 病例数据的诊断学临床思维训练/);
  assert.doesNotMatch(leftAsideSource, /uppercase tracking-\[0\.24em\][\s\S]*?>OSCE<\/p>/);
  assert.doesNotMatch(leftAsideSource, /TraceOSCE/);
  assert.doesNotMatch(leftAsideSource, /训练工作台/);
});

test("home shell starts directly with the training workspace after removing the navigation bar", () => {
  const contentShellIndex = pageSource.indexOf('<div className="flex h-full min-h-0">');
  const leftAsideIndex = pageSource.indexOf('<aside className="hidden w-72 shrink-0 border-r border-border bg-background p-4 shadow-inner-right lg:flex lg:flex-col">');
  const workspaceGridIndex = pageSource.indexOf('<div className="grid min-h-0 flex-1 grid-cols-1 gap-3 overflow-hidden p-3 xl:grid-cols-[minmax(0,1fr)_320px]">');

  assert.notEqual(contentShellIndex, -1);
  assert.notEqual(leftAsideIndex, -1);
  assert.notEqual(workspaceGridIndex, -1);
  assert.ok(contentShellIndex < leftAsideIndex);
  assert.ok(leftAsideIndex < workspaceGridIndex);
  assert.doesNotMatch(pageSource, /<header[\s\S]*?<\/header>/);
  assert.doesNotMatch(pageSource, /OSCE 工作台 · 教学模拟，非真实诊疗建议/);
  assert.doesNotMatch(pageSource, /<h2 className="text-base font-semibold">\s*\{formatStage\(session\?\.stage\)\}/);
});

test("home OSCE dock can be dragged and snaps to the viewport edge", () => {
  assert.match(pageSource, /type OsceDockPosition = Readonly<\{/);
  assert.match(pageSource, /const OSCE_DOCK_POSITION_STORAGE_KEY = "clinical_osce_osce_dock_position";/);
  assert.match(pageSource, /const OSCE_DOCK_DRAG_THRESHOLD = 4;/);
  assert.match(pageSource, /function createDefaultOsceDockPosition\(\): OsceDockPosition/);
  assert.match(pageSource, /function loadOsceDockPosition\(\): OsceDockPosition/);
  assert.match(pageSource, /function saveOsceDockPosition\(position: OsceDockPosition\): void/);
  assert.match(pageSource, /window\.localStorage\.getItem\(OSCE_DOCK_POSITION_STORAGE_KEY\)/);
  assert.match(pageSource, /window\.localStorage\.setItem\(OSCE_DOCK_POSITION_STORAGE_KEY/);
  assert.match(pageSource, /const osceDockDragRef = useRef<OsceDockDragState \| null>\(null\);/);
  assert.match(pageSource, /function getSnappedOsceDockPosition/);
  assert.match(pageSource, /window\.innerWidth/);
  assert.match(pageSource, /return getSideSnappedOsceDockPosition\("right", window\.innerHeight - OSCE_DOCK_BUTTON_SIZE - OSCE_DOCK_MARGIN\);/);
  assert.match(pageSource, /const snappedPosition = getSnappedOsceDockPosition/);
  assert.match(pageSource, /side: "right",/);
  assert.match(pageSource, /bottom: `\$\{OSCE_DOCK_MARGIN\}px`,[\s\S]*?right: `\$\{OSCE_DOCK_MARGIN\}px`,/);
  assert.match(pageSource, /const snappedPosition = getSnappedOsceDockPosition\(nextX, nextY\);[\s\S]*?saveOsceDockPosition\(snappedPosition\);[\s\S]*?setOsceDockPosition\(snappedPosition\);/);
  assert.match(pageSource, /onPointerDown=\{handleOsceDockPointerDown\}/);
  assert.match(pageSource, /onPointerMove=\{handleOsceDockPointerMove\}/);
  assert.match(pageSource, /onPointerUp=\{handleOsceDockPointerUp\}/);
  assert.match(pageSource, /onPointerCancel=\{handleOsceDockPointerCancel\}/);
  assert.match(pageSource, /side === "right" \? "right-0" : "left-0"/);
  assert.match(pageSource, /touch-none cursor-grab/);
});

test("home workspace reserves side rail scrollbar gutters without layout shift", () => {
  assert.match(globalsSource, /\.student-rail-scrollbar \{/);
  assert.match(globalsSource, /scrollbar-width: thin;/);
  assert.match(globalsSource, /scrollbar-gutter: stable;/);
  assert.match(globalsSource, /scrollbar-color: transparent transparent;/);
  assert.match(globalsSource, /\.student-rail-scrollbar\.is-student-scrollbar-active \{/);
  assert.match(globalsSource, /scrollbar-width: thin;/);
  assert.match(globalsSource, /\.student-rail-scrollbar::-webkit-scrollbar \{/);
  assert.match(globalsSource, /\.student-rail-scrollbar::-webkit-scrollbar \{[\s\S]*?width: 6px;[\s\S]*?height: 6px;/);
  assert.match(globalsSource, /\.student-rail-scrollbar\.is-student-scrollbar-active::-webkit-scrollbar-thumb/);
  assert.match(pageSource, /function handleStudentRailScroll\(event: UIEvent<HTMLElement>\): void/);
  assert.match(pageSource, /is-student-scrollbar-active/);
  assert.match(pageSource, /className="min-h-0 flex-1 overflow-y-scroll student-rail-scrollbar"/);
  assert.match(pageSource, /className="flex min-h-0 flex-col gap-4 overflow-y-scroll student-rail-scrollbar"/);
  assert.match(pageSource, /overflow-y-scroll pr-1 student-rail-scrollbar/);
  assert.doesNotMatch(pageSource, /className="min-h-0 flex-1 overflow-y-auto student-rail-scrollbar"/);
  assert.doesNotMatch(pageSource, /className="flex min-h-0 flex-col gap-4 overflow-y-auto student-rail-scrollbar"/);
  assert.match(pageSource, /onScroll=\{handleStudentRailScroll\}/);
});

test("home dialogue area keeps a visible light gray scrollbar", () => {
  assert.match(globalsSource, /\.student-chat-scrollbar \{/);
  assert.match(globalsSource, /scrollbar-width: thin;/);
  assert.match(globalsSource, /scrollbar-gutter: stable;/);
  assert.match(globalsSource, /scrollbar-color: #d6d3ce transparent;/);
  assert.match(globalsSource, /\.student-chat-scrollbar::-webkit-scrollbar \{/);
  assert.match(globalsSource, /\.student-chat-scrollbar::-webkit-scrollbar-thumb \{/);
  assert.match(pageSource, /className="flex-1 space-y-4 overflow-y-scroll p-5 pb-40 student-chat-scrollbar"/);
  assert.doesNotMatch(pageSource, /className="flex-1 space-y-4 overflow-y-auto p-5 pb-40 student-rail-scrollbar"/);
});

test("case and history pages use Claude-like brand tokens without legacy teal hardcoding", () => {
  assert.doesNotMatch(casesSource, /#2F6868|#2f6868/);
  assert.doesNotMatch(historySource, /#2F6868|#2f6868/);
  assert.match(casesSource, /bg-brand\/5/);
  assert.match(casesSource, /bg-brand\/10/);
  assert.match(casesSource, /hover:bg-brand-hover/);
  assert.match(historySource, /bg-brand\/5/);
  assert.match(historySource, /bg-brand\/10/);
  assert.match(historySource, /hover:bg-brand-hover/);
});

test("safety and sources pages use Claude-like brand tokens without legacy teal hardcoding", () => {
  assert.doesNotMatch(safetySource, /#2F6868|#2f6868/);
  assert.doesNotMatch(sourcesSource, /#2F6868|#2f6868/);
  assert.match(safetySource, /bg-brand\/5/);
  assert.match(sourcesSource, /bg-brand\/5/);
});

test("report page uses Claude-like brand tokens without legacy teal hardcoding", () => {
  assert.doesNotMatch(reportSource, /#2F6868|#2f6868|rgba\(47, 104, 104/);
  assert.match(reportSource, /const REPORT_BRAND_COLOR = "var\(--brand\)";/);
  assert.match(reportSource, /const REPORT_BRAND_SCORE_TRACK_COLOR = "color-mix\(in srgb, var\(--brand\) 12%, transparent\)";/);
  assert.match(reportSource, /hover:bg-brand-hover/);
  assert.match(reportSource, /bg-brand\/5/);
  assert.match(reportSource, /bg-brand\/10/);
  assert.match(reportSource, /stroke=\{REPORT_BRAND_COLOR\}/);
  assert.match(reportSource, /fill=\{REPORT_BRAND_COLOR\}/);
});

test("report source chips are grouped by case rubric public source and evidence", () => {
  for (const source of [pageSource, reportSource]) {
    assert.match(source, /function getSourceReferenceGroupKey\(reference: string\): string/);
    assert.match(source, /title: "病例脚本"/);
    assert.match(source, /title: "rubric 条目"/);
    assert.match(source, /title: "公开来源"/);
    assert.match(source, /title: "训练证据"/);
    assert.match(source, /const groupOrder = \["case", "rubric", "source", "evidence", "other"\];/);
  }
  assert.match(reportSource, /<SourceReferenceGroups groups=\{sourceReferenceGroups\} \/>/);
});

test("report page renders a defense evidence chain from explanation source items", () => {
  assert.match(reportModelSource, /export type ExplanationSourceItem = Readonly<\{/);
  assert.match(reportModelSource, /explanation_source_items\?: readonly ExplanationSourceItem\[];/);
  assert.match(reportModelSource, /explanation_source_items: readonly ExplanationSourceItem\[];/);
  assert.match(reportSource, /type ExplanationChainDisplayItem = Readonly<\{/);
  assert.match(reportSource, /function getExplanationKindLabel\(kind: string\): string/);
  assert.match(reportSource, /function getExplanationSourceDisplayItems/);
  assert.match(reportSource, /function TraceabilityDetailsSection/);
  assert.match(reportSource, /function DefenseEvidenceChainSection/);
  assert.match(reportSource, /explanationItems=\{report\.explanation_source_items\}/);
  assert.match(reportSource, /sourceReferenceItems=\{report\.source_reference_items\}/);
  assert.match(reportSource, /结构化评分链/);
  assert.match(reportSource, /item\.source_references\.filter\(\(reference\) => reference\.startsWith\("rubric:"\)\)/);
  assert.match(reportSource, /item\.source_references\.filter\(\(reference\) => reference\.startsWith\("evidence:"\)\)/);
  assert.match(reportSource, /function TraceReferenceRows/);
  assert.match(reportSource, /评分项来源/);
  assert.match(reportSource, /训练证据来源/);
  assert.match(reportSource, /结构化来源/);
  assert.match(reportSource, /\[overflow-wrap:anywhere\]/);
  assert.doesNotMatch(reportSource, /<div className="mt-3 grid gap-3 md:grid-cols-3">/);
  assert.doesNotMatch(reportSource, /function TraceColumn/);
  assert.match(reportSource, /不参与评分裁判/);
});

test("report page exposes advanced simulated procedure audit items as collapsed non-scoring evidence", () => {
  assert.match(reportModelSource, /export type ProcedureSimulationAuditItem = Readonly<\{/);
  assert.match(reportModelSource, /approval_agent_review\?: Readonly<Record<string, unknown>>;/);
  assert.match(reportModelSource, /procedure_simulation_audit_items\?: readonly ProcedureSimulationAuditItem\[];/);
  assert.match(reportModelSource, /procedure_simulation_audit_items: readonly ProcedureSimulationAuditItem\[];/);
  assert.match(reportModelSource, /procedure_simulation_audit_items: report\.procedure_simulation_audit_items \?\? \[\],/);
  assert.match(reportSource, /function ProcedureSimulationAuditSection/);
  assert.match(reportSource, /procedureSimulationAuditItems=\{report\.procedure_simulation_audit_items\}/);
  assert.match(reportSource, /历史模拟检查记录/);
  assert.match(reportSource, /审批 Agent 记录/);
  assert.match(reportSource, /审核结论/);
  assert.match(reportSource, /只读兼容旧版报告，不进入评分/);
  assert.match(reportSource, /item\.scoring_eligible \? "可进入评分" : "不进入评分"/);
  assert.match(reportSource, /item\.source_context_references\.map/);
});

test("report page renders evidence graph coverage from backend report", () => {
  assert.match(reportModelSource, /export type EvidenceGraphNodeItem = Readonly<\{/);
  assert.match(reportModelSource, /export type EvidenceGraphEdgeItem = Readonly<\{/);
  assert.match(reportModelSource, /export type EvidenceGraphSummary = Readonly<\{/);
  assert.match(reportModelSource, /evidence_graph_summary\?: EvidenceGraphSummary \| null;/);
  assert.match(reportModelSource, /evidence_graph_summary: report\.evidence_graph_summary \?\? null,/);
  assert.match(reportSource, /function EvidenceGraphSummarySection/);
  assert.match(reportSource, /evidenceGraphSummary=\{report\.evidence_graph_summary\}/);
  assert.match(reportSource, /<EvidenceGraphSummarySection summary=\{evidenceGraphSummary\} \/>/);
  assert.match(reportSource, /结构化证据覆盖/);
  assert.match(reportSource, /summary\.covered_evidence_node_count/);
  assert.match(reportSource, /summary\.total_evidence_node_count/);
  assert.match(reportSource, /nodes=\{summary\.covered_evidence_nodes\}/);
  assert.match(reportSource, /nodes=\{summary\.missing_evidence_nodes\}/);
  assert.match(reportSource, /edges=\{summary\.covered_edges\}/);
  assert.match(reportSource, /edges=\{summary\.missing_edges\}/);
  assert.match(reportSource, /nodes\.map\(\(node\) =>/);
  assert.match(reportSource, /edges\.map\(\(edge\) =>/);
  assert.match(reportSource, /证据图谱仅用于复盘已收集和缺失的训练证据，不参与诊断裁判或评分。/);
});

test("report page renders a compact iOS-style section navigator", () => {
  assert.match(reportSource, /type ReportSectionId =/);
  assert.match(reportSource, /const reportSections: readonly ReportSection\[] =/);
  assert.match(reportSource, /function ReportSectionNavigator/);
  assert.match(reportSource, /aria-label="评分报告章节导航"/);
  assert.match(reportSource, /const \[isReportNavigatorCollapsed, setIsReportNavigatorCollapsed\]/);
  assert.match(reportSource, /aria-expanded=\{!isCollapsed\}/);
  assert.match(reportSource, /收起评分报告目录/);
  assert.match(reportSource, /展开评分报告目录/);
  assert.match(reportSource, /backdrop-blur-xl/);
  assert.match(reportSource, /<aside className="scroll-mt-6 xl:sticky xl:top-6 xl:self-start"/);
  assert.match(reportSource, /isReportNavigatorCollapsed \? "xl:grid-cols-\[76px_minmax\(0,1fr\)\]" : "xl:grid-cols-\[240px_minmax\(0,1fr\)\]"/);
  assert.match(reportSource, /xl:grid xl:overflow-visible xl:pb-0/);
  assert.match(reportSource, /max-h-\[calc\(100vh-3rem\)\]/);
  assert.doesNotMatch(reportSource, /position: fixed/);
  assert.match(reportSource, /bg-brand\/10 text-brand/);
  assert.doesNotMatch(reportSource, /bg-foreground text-background/);
  assert.match(reportSource, /report-card-scrollbar/);
  assert.match(globalsSource, /\.report-card-scrollbar/);
  assert.match(globalsSource, /scrollbar-gutter: stable;/);
  assert.match(reportSource, /window\.innerHeight \+ window\.scrollY >= document\.documentElement\.scrollHeight - 2/);
  assert.match(reportSource, /onSectionSelect\(section\.id\)/);
  assert.doesNotMatch(reportSource, /xl:grid-cols-\[320px_minmax\(0,1fr\)\]/);
  for (const label of ["总览", "复盘", "Skill", "图表", "结论", "对话", "推荐", "依据"]) {
    assert.match(reportSource, new RegExp(`label: "${label}"`));
  }
  for (const targetId of [
    "report-overview",
    "report-reflection",
    "report-personal-skill",
    "report-dimensions",
    "report-recommendations",
    "report-conversation",
    "report-evidence",
  ]) {
    assert.match(reportSource, new RegExp(`targetId: "${targetId}"`));
    assert.match(reportSource, new RegExp(`id="${targetId}"`));
  }
  assert.match(reportSource, /targetId: "report-feedback"/);
  assert.match(reportSource, /sectionId="report-feedback"/);
  assert.match(reportSource, /href=\{`#\$\{section\.targetId\}`\}/);
  assert.ok(reportSource.indexOf('label: "总览"') < reportSource.indexOf('label: "结论"'));
  assert.ok(reportSource.indexOf('label: "结论"') < reportSource.indexOf('label: "图表"'));
  assert.ok(reportSource.indexOf('label: "图表"') < reportSource.indexOf('label: "复盘"'));
  assert.ok(reportSource.indexOf('label: "复盘"') < reportSource.indexOf('label: "Skill"'));
  assert.ok(reportSource.indexOf('label: "对话"') < reportSource.indexOf('label: "推荐"'));
  assert.ok(reportSource.indexOf('label: "推荐"') < reportSource.indexOf('label: "依据"'));
  assert.doesNotMatch(reportSource, /targetId: "report-ai-evaluation"/);
  assert.ok(reportSource.indexOf('<StudentReportSummary report={report} sectionId="report-feedback"') < reportSource.indexOf("<DimensionChartSection"));
  assert.ok(reportSource.indexOf("<DimensionChartSection") < reportSource.indexOf("<AiReflectionReviewSection"));
  assert.ok(reportSource.indexOf("<AiReflectionReviewSection") < reportSource.indexOf("<PersonalTrainingSkillSection"));
  assert.ok(reportSource.indexOf('<StudentReportSummary report={report} sectionId="report-feedback"') < reportSource.indexOf("<ConversationDetailsSection"));
  assert.ok(reportSource.indexOf("<ConversationDetailsSection") < reportSource.indexOf("<CaseRecommendations"));
});

test("report section navigator keeps clicked sections selected instead of drifting to the next section", () => {
  assert.match(reportSource, /const REPORT_SECTION_ACTIVATION_OFFSET_PX = 96;/);
  assert.doesNotMatch(reportSource, /const viewportAnchor = Math\.min\(window\.innerHeight \* 0\.35, 260\);/);
  assert.match(reportSource, /const viewportAnchor = REPORT_SECTION_ACTIVATION_OFFSET_PX;/);
  assert.match(reportSource, /<StudentReportSummary report=\{report\} sectionId="report-feedback" \/>/);
  assert.match(reportSource, /function StudentReportSummary\(\{ report, sectionId \}: Readonly<\{ report: FeedbackReport; sectionId: string \}>\)/);
  assert.match(reportSource, /<section className="scroll-mt-6 rounded-2xl border border-border bg-background p-5 shadow-xs xl:col-span-2" id=\{sectionId\}>/);
  assert.doesNotMatch(reportSource, /<div className="grid gap-4 xl:grid-cols-2">\s*\{report \? \(/);
  assert.doesNotMatch(reportSource, /<div className="grid scroll-mt-6 gap-4 xl:grid-cols-2" id="report-feedback">/);
});

test("report page prioritizes student learning over repeated source proof", () => {
  const summaryStart = reportSource.indexOf("function StudentReportSummary");
  const summaryEnd = reportSource.indexOf("function HumanisticCommunicationSection", summaryStart);
  const summarySource = reportSource.slice(summaryStart, summaryEnd);

  assert.match(reportSource, /function StudentReportSummary/);
  assert.match(reportSource, /<StudentReportSummary report=\{report\} sectionId="report-feedback" \/>/);
  assert.match(reportSource, /本轮结论/);
  assert.match(reportSource, /教师复盘/);
  assert.doesNotMatch(reportSource, /教练复盘/);
  assert.match(reportSource, /推荐训练病例/);
  assert.match(summarySource, /最重要的薄弱项/);
  assert.match(summarySource, /下一轮先做这/);
  assert.doesNotMatch(summarySource, /LearningSummaryColumn/);
  assert.match(reportSource, /function TraceabilityDetailsSection/);
  assert.match(reportSource, /评分依据与来源/);
  assert.match(reportSource, /<details className=/);
  assert.match(reportSource, /<summary className=/);
  assert.match(reportSource, /结构化评分依据，不是 RAG 评分裁判/);
  assert.doesNotMatch(reportSource, /学习推荐与下一病例/);
  assert.doesNotMatch(reportSource, /根据本轮漏项检索 rubric、知识点和病例库/);
  assert.doesNotMatch(reportSource, /评分项 → 证据 → 来源/);
  assert.doesNotMatch(reportSource, /推荐训练材料与病例/);
});

test("report page renders AI reflection review and personal training skill status", () => {
  assert.match(reportModelSource, /export type AiReflectionReview = Readonly<\{/);
  assert.match(reportModelSource, /export type TeacherReflectionMajorIssue = Readonly<\{/);
  assert.match(reportModelSource, /export type TeacherCoachingReviewSection = Readonly<\{/);
  assert.match(reportModelSource, /teacher_coaching_review: readonly TeacherCoachingReviewSection\[];/);
  assert.match(reportModelSource, /teacher_coaching_review: \[],/);
  assert.match(reportModelSource, /teacher_coaching_review: review\?\.teacher_coaching_review \?\? \[],/);
  assert.match(reportModelSource, /export type TeacherReasoningTraceSummary = Readonly<\{/);
  assert.match(reportModelSource, /sequence_flags: readonly TeacherReasoningSequenceFlag\[];/);
  assert.match(reportModelSource, /evidence_chain_breakpoints: readonly TeacherEvidenceChainBreakpoint\[];/);
  assert.match(reportModelSource, /reasoning_trace_summary: TeacherReasoningTraceSummary;/);
  assert.match(reportModelSource, /reasoning_trace_summary: normalizeTeacherReasoningTraceSummary\(review\?\.reasoning_trace_summary\),/);
  assert.match(reportModelSource, /export type PersonalTrainingSkillCandidate = Readonly<\{/);
  assert.match(reportModelSource, /ai_reflection_review\?: Partial<AiReflectionReview>;/);
  assert.match(reportModelSource, /personal_skill_candidate\?: Partial<PersonalTrainingSkillCandidate>;/);
  assert.match(reportModelSource, /ai_reflection_review: normalizeAiReflectionReview\(report\.ai_reflection_review\),/);
  assert.match(reportModelSource, /personal_skill_candidate: normalizePersonalTrainingSkillCandidate\(report\.personal_skill_candidate\),/);
  assert.match(reportSource, /function AiReflectionReviewSection/);
  assert.match(reportSource, /function TeacherReasoningTraceSummarySection/);
  assert.match(reportSource, /function PersonalTrainingSkillSection/);
  assert.match(reportSource, /<AiReflectionReviewSection review=\{report\.ai_reflection_review\} trainingPointLabelResolver=\{trainingPointLabelResolver\} \/>/);
  assert.match(reportSource, /<PersonalTrainingSkillSection candidate=\{report\.personal_skill_candidate\} trainingPointLabelResolver=\{trainingPointLabelResolver\} \/>/);
  assert.match(reportSource, /教师复盘/);
  assert.match(reportSource, /总体判断/);
  assert.match(reportSource, /老师带你重走一遍临床思路/);
  assert.match(reportSource, /review\.teacher_coaching_review\.map/);
  assert.match(reportSource, /section\.teacher_comment/);
  assert.match(reportSource, /section\.why_it_matters/);
  assert.match(reportSource, /section\.next_move/);
  assert.match(reportSource, /老师指出的问题/);
  assert.match(reportSource, /为什么重要/);
  assert.match(reportSource, /正确做法/);
  assert.match(reportSource, /下一轮具体练法/);
  assert.match(reportSource, /推理链点评/);
  assert.match(reportSource, /临床思维轨迹/);
  assert.match(reportSource, /顺序问题/);
  assert.match(reportSource, /证据链断点/);
  assert.match(reportSource, /缺少证据/);
  assert.match(reportSource, /summary\.sequence_flags\.map/);
  assert.match(reportSource, /summary\.evidence_chain_breakpoints\.map/);
  assert.match(reportSource, /breakpoint\.missing_evidence_labels/);
  assert.match(reportSource, /个人训练 Skill/);
  assert.match(reportSource, /review\.source_reference_items\.map/);
  assert.match(reportSource, /candidate\.rag_evidence_items\.map/);
  assert.match(reportSource, /function getPersonalSkillScopeLabel/);
  assert.match(reportSource, /function getPersonalSkillSourceReportText/);
  assert.match(reportSource, /生成结果/);
  assert.match(reportSource, /适用范围/);
  assert.match(reportSource, /来源报告/);
  assert.match(reportModelSource, /export type TeacherAnalysisContext = Readonly<\{/);
  assert.match(reportModelSource, /clinical_thinking_profile: Readonly<Record<string, unknown>>;/);
  assert.match(reportModelSource, /teacher_analysis_context: TeacherAnalysisContext;/);
  assert.match(reportSource, /function TeacherAnalysisContextSection/);
  assert.match(reportSource, /function formatTeacherAnalysisMode/);
  assert.match(reportSource, /教师智能体分析/);
  assert.match(reportSource, /学生思维假设/);
  assert.match(reportSource, /临床思维画像/);
  assert.match(reportSource, /Skill 记忆来源/);
  assert.doesNotMatch(reportSource, /\{context\.analysis_mode\}/);
});

test("report page notifies when a pending personal skill finishes in the background", () => {
  assert.match(reportSource, /const PERSONAL_SKILL_POLL_INTERVAL_MS = 3_500;/);
  assert.match(reportSource, /function getPersonalSkillCompletionNoticeText\(status: string\): string \| null/);
  assert.match(reportSource, /if \(status === "approved"\)/);
  assert.match(reportSource, /if \(status === "blocked_by_regression"\)/);
  assert.match(reportSource, /if \(status === "generation_failed"\)/);
  assert.match(reportSource, /\["generation_pending", "generation_failed"\]\.includes\(personalSkillStatus \?\? ""\)/);
  assert.match(reportSource, /const enrichmentSessionId = sessionId/);
  assert.match(reportSource, /personalSkillEnrichmentRequestsRef\.current\.get\(enrichmentSessionId\)/);
  assert.match(reportSource, /personalSkillEnrichmentRequestsRef\.current\.set\(enrichmentSessionId, nextRequest\)/);
  assert.match(reportSource, /personalSkillEnrichmentRequestsRef\.current\.delete\(enrichmentSessionId\)/);
  assert.match(reportSource, /requestJson<FeedbackReportPayload>\(`\/api\/sessions\/\$\{enrichmentSessionId\}\/report\/enrich`, \{[\s\S]*?method: "POST"/);
  assert.match(reportSource, /const PERSONAL_SKILL_ENRICHMENT_RETRY_INTERVAL_MS = 310_000/);
  assert.match(reportSource, /requestPersonalSkillEnrichment\(startPolling\)/);
  assert.match(reportSource, /requestPersonalSkillEnrichment\(false\)/);
  assert.match(reportSource, /window\.clearTimeout\(enrichmentRetryTimer\)/);
  assert.match(reportSource, /requestJson<FeedbackReportPayload>\(`\/api\/me\/sessions\/\$\{enrichmentSessionId\}\/report`, \{[\s\S]*?timeoutMs: REPORT_REQUEST_TIMEOUT_MS/);
  assert.match(reportSource, /error instanceof RequestJsonError[\s\S]*?error\.status !== 404/);
  assert.match(reportSource, /const canGenerateReport = Boolean\(nextSession\.final_submission\)[\s\S]*?nextSession\.stage === "feedback"/);
  assert.match(reportSource, /requestJson<FeedbackReportPayload>\(`\/api\/sessions\/\$\{nextSessionId\}\/report\/generate`, \{[\s\S]*?method: "POST"/);
  assert.doesNotMatch(reportSource, /report\?enrich=true/);
  assert.match(reportSource, /const noticeText = getPersonalSkillCompletionNoticeText\(nextReport\.personal_skill_candidate\.status\);/);
  assert.match(reportSource, /if \(noticeText\) \{/);
  assert.match(reportSource, /setPersonalSkillNoticeText\(noticeText\);/);
  assert.match(reportSource, /role="status"/);
  assert.match(reportSource, /\{personalSkillNoticeText\}/);
});

test("report page keeps long AI evidence source lists collapsed with clear expand affordances", () => {
  assert.match(reportSource, /<details className="mt-3 rounded-xl border border-border bg-muted\/20 p-3">/);
  assert.match(reportSource, /<summary className="flex cursor-pointer list-none items-start justify-between gap-3">/);
  assert.match(reportSource, /复盘来源/);
  assert.match(reportSource, /默认折叠，可展开查看教师复盘引用的结构化来源。/);
  assert.match(reportSource, /RAG 证据来源/);
  assert.match(reportSource, /默认折叠，可展开查看 Skill 生成与审批使用的来源。/);
  assert.doesNotMatch(reportSource, /<h3 className="text-xs font-semibold">复盘来源<\/h3>\s*\{review\.source_reference_items\.length > 0 \?/);
  assert.doesNotMatch(reportSource, /<h3 className="text-xs font-semibold">RAG 证据来源<\/h3>\s*\{candidate\.rag_evidence_items\.length > 0 \?/);
});

test("report page derives training point labels from report metadata instead of fixed field tables", () => {
  assert.match(reportSource, /function createTrainingPointLabelResolver\(report: FeedbackReport\): \(itemId: string\) => string/);
  assert.match(reportSource, /Object\.entries\(report\.rubric_scores\)\.forEach/);
  assert.match(reportSource, /collectCoverageMapLabels\(report\.training_progress_snapshot\?\.coverage_map, labelById\);/);
  assert.match(reportSource, /report\.llm_reasoning_feedback\.forEach/);
  assert.match(reportSource, /const cognitivePatternLabels: Readonly<Record<string, string>> = \{/);
  assert.match(reportSource, /weak_problem_representation: "问题表征薄弱"/);
  assert.match(reportSource, /premature_closure_risk: "过早闭合风险"/);
  assert.match(reportSource, /const cognitivePatternLabel = cognitivePatternLabels\[itemId\]/);
  assert.match(reportSource, /const trainingPointLabelResolver = useMemo\(\(\) => report \? createTrainingPointLabelResolver\(report\) : formatTrainingPointIdentifier/);
  assert.doesNotMatch(reportSource, /const TRAINING_POINT_LABELS/);
  assert.doesNotMatch(reportSource, /ht_onset: "起病时间"/);
  assert.match(reportSource, /trainingPointLabelResolver\(pattern\)/);
  assert.match(reportSource, /trainingPointLabelResolver\(triggerItemId\)/);
  assert.doesNotMatch(reportSource, /\{pattern\}\s*<\/span>/);
  assert.doesNotMatch(reportSource, /\{triggerItemId\}\s*<\/span>/);
});

test("report clinical task trace list uses stable keys for legacy unnamed items", () => {
  assert.match(reportSource, /function getClinicalTaskTraceKey\(item: ClinicalTaskTraceItem, index: number\): string/);
  assert.match(reportSource, /item\.item_id \|\| `legacy-trace-\$\{index\}`/);
  assert.match(reportSource, /items\.slice\(0, 3\)\.map\(\(item, index\) =>/);
  assert.match(reportSource, /key=\{getClinicalTaskTraceKey\(item, index\)\}/);
  assert.doesNotMatch(reportSource, /key=\{`\$\{item\.item_id\}-\$\{item\.label\}`\}/);
});

test("report page exposes approval agent review details in expandable records", () => {
  assert.match(reportSource, /function formatApprovalAgentChangedField/);
  assert.match(reportSource, /function getApprovalAgentChangedFieldDisplay/);
  assert.match(reportSource, /function formatApprovalActionPlan/);
  assert.match(reportSource, /function formatApprovalAgentIssue/);
  assert.match(reportSource, /审批 Agent 记录/);
  assert.match(reportSource, /<details className="rounded-lg border border-border bg-muted\/25 p-3 text-xs leading-5 text-muted-foreground"/);
  assert.match(reportSource, /展开查看修改内容、门禁结果和问题清单。/);
  assert.match(reportSource, /修改内容/);
  assert.match(reportSource, /修改前/);
  assert.match(reportSource, /修改后/);
  assert.match(reportSource, /为什么改/);
  assert.match(reportSource, /把策略拆成 TeacherAgent 可执行动作/);
  assert.match(reportSource, /max-h-24 overflow-y-auto whitespace-pre-wrap break-words/);
  assert.match(reportSource, /\[overflow-wrap:anywhere\]/);
  assert.match(reportSource, /门禁与问题/);
  assert.match(reportSource, /turn\.changed_fields\.map/);
  assert.doesNotMatch(reportSource, /\{formatApprovalAgentChangedField\(changedField\)\}/);
  assert.match(reportSource, /turn\.blocking_failures\.map/);
});

test("report dimension chart keeps the right-side score list scrollable instead of stretching the card", () => {
  assert.match(reportSource, /const sectionHeadingClassName = "text-2xl font-semibold tracking-tight";/);
  assert.doesNotMatch(reportSource, /<h2 className="text-lg font-semibold">/);
  assert.match(reportSource, /<div className="mt-5 grid items-start gap-5 lg:grid-cols-\[minmax\(260px,0\.85fr\)_minmax\(0,1fr\)\]">/);
  assert.match(reportSource, /<div className="rounded-2xl border border-border bg-muted\/30 p-4">/);
  assert.match(reportSource, /<div className="grid max-h-80 content-start gap-3 overflow-y-auto pr-1 report-card-scrollbar">/);
});

test("report page keeps AI rubric reasoning as collapsed audit evidence instead of a main learning section", () => {
  assert.doesNotMatch(reportSource, /<LlmReasoningFeedback items=\{report\.llm_reasoning_feedback\} \/>/);
  assert.doesNotMatch(reportSource, /id="report-ai-evaluation"/);
  assert.match(reportSource, /function LlmReasoningAuditSection/);
  assert.match(reportSource, /llmReasoningItems=\{report\.llm_reasoning_feedback\}/);
  assert.match(reportSource, /AI 评分审计/);
  assert.match(reportSource, /默认折叠，用于查看大模型 rubric 评分过程，不作为学生主阅读内容。/);
});

test("report page recommends only follow-up cases and does not list study material cards", () => {
  assert.match(reportSource, /function CaseRecommendations/);
  assert.match(reportSource, /const caseItems = items\.filter\(\(item\) => item\.reference\.startsWith\("case:"\)\);/);
  assert.match(reportSource, /推荐训练病例/);
  assert.match(reportSource, /当前病例库暂未找到适合的下一轮训练病例。/);
  assert.doesNotMatch(reportSource, /getRecommendationKindLabel\(item\.reference\)/);
  const caseRecommendationsSource = reportSource.slice(
    reportSource.indexOf("function CaseRecommendations"),
    reportSource.indexOf("function LlmReasoningAuditSection"),
  );
  assert.doesNotMatch(caseRecommendationsSource, />\s*\{item\.reference\}\s*</);
  assert.doesNotMatch(caseRecommendationsSource, /font-mono/);
});

test("report page shows submitted material coverage map as the round conclusion", () => {
  const summaryStart = reportSource.indexOf("function StudentReportSummary");
  const summaryEnd = reportSource.indexOf("function HumanisticCommunicationSection", summaryStart);
  const summarySource = reportSource.slice(summaryStart, summaryEnd);

  assert.match(reportModelSource, /export type ReportCoverageMapItem = Readonly<\{/);
  assert.match(reportModelSource, /export type ReportTrainingProgressSnapshot = Readonly<\{/);
  assert.match(reportModelSource, /training_progress_snapshot\?: ReportTrainingProgressSnapshot \| null;/);
  assert.match(reportModelSource, /training_progress_snapshot: report\.training_progress_snapshot \?\? null,/);
  assert.match(reportSource, /const coverageMap = report\.training_progress_snapshot\?\.coverage_map;/);
  assert.match(reportSource, /function ReportCoverageMapOverview/);
  assert.match(reportSource, /function ReportCoverageMapGroup/);
  assert.match(reportSource, /问诊线索/);
  assert.match(reportSource, /查体项目/);
  assert.match(reportSource, /辅助检查/);
  assert.match(reportSource, /推理证据/);
  assert.match(reportSource, /素材覆盖/);
  assert.match(reportSource, /item\.status === "covered" \? "已覆盖" : "未覆盖"/);
  assert.doesNotMatch(reportSource, /待补充/);
  assert.match(summarySource, /const priorityGaps = \[\.\.\.report\.training_gaps\]/);
  assert.match(summarySource, /\.sort\(\(left, right\) => right\.missing_score - left\.missing_score\)/);
  assert.match(summarySource, /\.\.\.report\.next_recommendations/);
  assert.match(summarySource, /\.slice\(0, 3\);/);
  assert.match(summarySource, /本轮素材覆盖明细/);
  assert.match(summarySource, /默认折叠/);
});

test("report page keeps teacher, deep analysis, and Skill technical details collapsed by default", () => {
  const deepAnalysisSource = reportSource.slice(
    reportSource.indexOf("function DeepReportAnalysisSection"),
    reportSource.indexOf("function DeepReportInlineList"),
  );
  const teacherReviewSource = reportSource.slice(
    reportSource.indexOf("function AiReflectionReviewSection"),
    reportSource.indexOf("function TeacherAnalysisContextSection"),
  );
  const personalSkillSource = reportSource.slice(
    reportSource.indexOf("function PersonalTrainingSkillSection"),
    reportSource.indexOf("function CaseRecommendations"),
  );

  for (const sectionSource of [deepAnalysisSource, teacherReviewSource, personalSkillSource]) {
    assert.match(sectionSource, /<details>/);
    assert.match(sectionSource, /<summary className=/);
    assert.doesNotMatch(sectionSource, /<details open/);
  }
  assert.match(teacherReviewSource, /详细点评默认折叠/);
  assert.match(deepAnalysisSource, /证据链与任务明细默认折叠/);
  assert.match(personalSkillSource, /Skill 来源、生成策略与审批技术细节默认折叠/);
  assert.match(teacherReviewSource, /review\.source_reference_items\.map/);
  assert.match(personalSkillSource, /candidate\.rag_evidence_items\.map/);
});

test("home personal center links to the learning profile page", () => {
  const leftAsideIndex = pageSource.indexOf('<aside className="hidden w-72 shrink-0 border-r border-border bg-background p-4 shadow-inner-right lg:flex lg:flex-col">');
  const leftAsideEndIndex = pageSource.indexOf("</aside>", leftAsideIndex);
  const leftAsideSource = pageSource.slice(leftAsideIndex, leftAsideEndIndex);

  assert.match(leftAsideSource, /href="\/profile"[\s\S]*?>\s*学习画像\s*<\/Link>/);
});

test("profile page reads backend aggregated learning profile without per-session report requests", () => {
  assert.ok(existsSync(profilePageUrl), "profile page should exist");
  assert.match(profileSource, /export default function ProfilePage\(\)/);
  assert.match(profileSource, /fetch\("\/api\/me\/profile", \{/);
  assert.match(profileSource, /type CurrentUserProfileResponse = Readonly<\{/);
  assert.match(profileSource, /function toLearningProfile\(/);
  assert.match(profileSource, /credentials: "same-origin"/);
  assert.doesNotMatch(profileSource, /`\/api\/me\/sessions\/\$\{sessionId\}\/report`/);
  assert.doesNotMatch(profileSource, /getCurrentUserSessionReport/);
  assert.doesNotMatch(profileSource, /Promise\.all\(sessions\.map/);
  assert.match(profileSource, /训练次数/);
  assert.match(profileSource, /平均分/);
  assert.match(profileSource, /薄弱项/);
  assert.match(profileSource, /average_score: number;/);
  assert.match(profileSource, /average_max_score: number;/);
  assert.match(profileSource, /average_percentage: number;/);
  assert.match(profileSource, /sample_count: number;/);
  assert.match(profileSource, /right\.average_percentage - left\.average_percentage/);
  assert.match(profileSource, /平均完成度 \{dimension\.average_percentage\}%/);
  assert.match(profileSource, /getDimensionPercentageWidth\(dimension\.average_percentage\)/);
  assert.doesNotMatch(profileSource, /getDimensionRelativeWidth/);
  assert.doesNotMatch(profileSource, /right\.average - left\.average/);
  assert.match(profileSource, /type LearningPathItem = Readonly<\{/);
  assert.match(profileSource, /task_type_label: string;/);
  assert.match(profileSource, /case_title: string;/);
  assert.match(profileSource, /target_rubric_item_labels: readonly string\[];/);
  assert.match(profileSource, /source_reference_labels: readonly string\[];/);
  assert.match(profileSource, /case_title: string;/);
  assert.match(profileSource, /stage_label: string;/);
  assert.match(profileSource, /learning_path: readonly LearningPathItem\[];/);
  assert.match(profileSource, /learningPath: readonly LearningPathItem\[];/);
  assert.match(profileSource, /const primaryLearningTask = profile\.learningPath\[0\] \?\? null;/);
  assert.match(profileSource, /const secondaryLearningTasks = profile\.learningPath\.slice\(1, 3\);/);
  assert.match(profileSource, /下一轮训练任务/);
  assert.match(profileSource, /task\.task_type_label/);
  assert.match(profileSource, /task\.case_title/);
  assert.match(profileSource, /primaryLearningTask\.target_rubric_item_labels/);
  assert.match(profileSource, /primaryLearningTask\.source_reference_labels/);
  assert.match(profileSource, /session\.case_title/);
  assert.match(profileSource, /session\.stage_label/);
  assert.doesNotMatch(profileSource, /病例：\{task\.case_id\}/);
  assert.doesNotMatch(profileSource, /\{task\.target_rubric_items\.map/);
  assert.doesNotMatch(profileSource, /来源：\{task\.source_references\.join/);
  assert.doesNotMatch(profileSource, /当前阶段：\{session\.stage\}/);
  assert.match(profileSource, /长期 Skill 记忆/);
  assert.match(profileSource, /type EnabledSkillSummary = Readonly<\{/);
  assert.match(profileSource, /type SkillProfileItem = Readonly<\{/);
  assert.match(profileSource, /type SkillProfileSkillState = Readonly<\{/);
  assert.match(profileSource, /type SkillProfileSummary = Readonly<\{/);
  assert.match(profileSource, /skill_profile_summary: SkillProfileSummary;/);
  assert.match(profileSource, /skillProfileSummary: SkillProfileSummary;/);
  assert.match(profileSource, /const EMPTY_SKILL_PROFILE_SUMMARY: SkillProfileSummary = \{/);
  assert.match(profileSource, /skillProfileSummary: normalizeSkillProfileSummary\(payload\.skill_profile_summary\)/);
  assert.match(profileSource, /function normalizeSkillProfileSummary\(summary\?: Partial<SkillProfileSummary>\): SkillProfileSummary/);
  assert.match(profileSource, /student_visible_summary: string;/);
  assert.match(profileSource, /description: string;/);
  assert.match(profileSource, /learning_action: string;/);
  assert.match(profileSource, /activation_summary: string;/);
  assert.match(profileSource, /source_summary: string;/);
  assert.match(profileSource, /effect_status_label: string;/);
  assert.match(profileSource, /scope_label: string;/);
  assert.match(profileSource, /effect_status: string;/);
  assert.match(profileSource, /enabled_skill_count: number;/);
  assert.match(profileSource, /applied_skill_count: number;/);
  assert.match(profileSource, /enabled_skills: readonly EnabledSkillSummary\[];/);
  assert.match(profileSource, /accumulation\.enabled_skill_count/);
  assert.match(profileSource, /accumulation\.applied_skill_count/);
  assert.match(profileSource, /const sortedSkills = getRankedEnabledSkills\(accumulation\.enabled_skills\);/);
  assert.match(profileSource, /const visibleSkills = sortedSkills\.slice\(0, FEATURED_SKILL_LIMIT\);/);
  assert.match(profileSource, /const hiddenSkills = sortedSkills\.slice\(FEATURED_SKILL_LIMIT\);/);
  assert.match(profileSource, /已启用 Skill/);
  assert.match(profileSource, /应用次数/);
  assert.match(profileSource, /支持 \{skill\.support_count\} 次/);
  assert.match(profileSource, /效果状态/);
  assert.match(profileSource, /暂无已启用 Skill/);
});

test("profile page separates loading, unauthenticated and empty learning profile states", () => {
  assert.match(profileSource, /type ProfileLoadState = "loading" \| "ready" \| "unauthenticated" \| "empty" \| "error";/);
  assert.match(profileSource, /setLoadState\("unauthenticated"\)/);
  assert.match(profileSource, /setLoadState\("empty"\)/);
  assert.match(profileSource, /请先登录查看近期学习画像/);
  assert.match(profileSource, /正在读取近期学习画像/);
  assert.doesNotMatch(profileSource, /if \(response\.status === 401\) \{[\s\S]*?return EMPTY_LEARNING_PROFILE;/);
});

test("profile page names profile as short-term memory and Skill as long-term memory", () => {
  assert.match(profileSource, /近期学习画像/);
  assert.match(profileSource, /长期 Skill 记忆/);
  assert.match(profileSource, /近期训练问题/);
  assert.match(profileSource, /画像记录最近训练状态，长期 Skill 记忆沉淀反复出现的问题模式/);
});

test("profile page prioritizes the next training action in the first viewport", () => {
  assert.match(profileSource, /当前最该练什么/);
  assert.match(profileSource, /下一轮训练任务/);
  assert.match(profileSource, /primaryLearningTask \? \(/);
  assert.match(profileSource, /secondaryLearningTasks\.map/);
  assert.match(profileSource, /href="\/cases"/);
  assert.match(profileSource, /开始下一轮训练/);
  assert.doesNotMatch(profileSource, /个人训练主页/);
});

test("profile page exposes readable Skill profile orchestration summary", () => {
  assert.match(profileSource, /type SkillProfileReasoningPattern = Readonly<\{/);
  assert.match(profileSource, /type SkillProfileSequenceIssue = Readonly<\{/);
  assert.match(profileSource, /type SkillProfileEvidenceChainFocus = Readonly<\{/);
  assert.match(profileSource, /type SkillProfileReasoningSummary = Readonly<\{/);
  assert.match(profileSource, /reasoning_profile_summary: SkillProfileReasoningSummary;/);
  assert.match(profileSource, /matched_recent_reasoning_patterns: readonly SkillProfileReasoningPattern\[];/);
  assert.match(profileSource, /const EMPTY_SKILL_PROFILE_REASONING_SUMMARY: SkillProfileReasoningSummary = \{/);
  assert.match(profileSource, /reasoning_profile_summary: EMPTY_SKILL_PROFILE_REASONING_SUMMARY,/);
  assert.match(profileSource, /function SkillProfileSummarySection\(\{ summary \}: Readonly<\{ summary: SkillProfileSummary \}>\)/);
  assert.match(profileSource, /<SkillProfileSummarySection summary=\{profile\.skillProfileSummary\} \/>/);
  assert.match(profileSource, /近期训练问题/);
  assert.match(profileSource, /近期漏项/);
  assert.match(profileSource, /近期思维模式/);
  assert.match(profileSource, /顺序问题/);
  assert.match(profileSource, /证据链焦点/);
  assert.match(profileSource, /Skill 编排依据/);
  assert.match(profileSource, /function getCurrentPriorityIssues\(summary: SkillProfileSummary\): readonly CurrentPriorityIssue\[]/);
  assert.match(profileSource, /const priorityIssues = getCurrentPriorityIssues\(summary\);/);
  assert.match(profileSource, /priorityIssues\.map/);
  assert.match(profileSource, /查看完整近期问题证据/);
  assert.match(profileSource, /reasoningSummary\.current_reasoning_focus\.slice\(0, 6\)\.map/);
  assert.match(profileSource, /reasoningSummary\.sequence_issue_counts\.slice\(0, 6\)\.map/);
  assert.match(profileSource, /reasoningSummary\.evidence_chain_focus\.slice\(0, 6\)\.map/);
  assert.match(profileSource, /focus\.missing_evidence_labels/);
  assert.match(profileSource, /summary\.current_focus_items\.map/);
  assert.match(profileSource, /focusItem\.label/);
  assert.match(profileSource, /state\.matched_recent_error_items\.map/);
  assert.match(profileSource, /state\.matched_recent_reasoning_patterns\.map/);
  assert.match(profileSource, /item\.label/);
  assert.match(profileSource, /state\.selection_reason/);
  assert.match(profileSource, /state\.state_label/);
  assert.match(profileSource, /state\.effect_status_label/);
  assert.match(profileSource, /暂无近期漏项/);
});

test("profile page exposes teaching effect observation summary", () => {
  assert.match(profileSource, /type TeachingEffectAbilityAxis = Readonly<\{/);
  assert.match(profileSource, /type TeachingEffectSummary = Readonly<\{/);
  assert.match(profileSource, /teaching_effect_summary: TeachingEffectSummary;/);
  assert.match(profileSource, /function TeachingEffectSummarySection\(\{ summary \}: Readonly<\{ summary: TeachingEffectSummary \}>\)/);
  assert.match(profileSource, /<TeachingEffectSummarySection summary=\{profile\.skillProfileSummary\.teaching_effect_summary\} \/>/);
  assert.match(profileSource, /教学效果观察/);
  assert.match(profileSource, /summary\.ability_axes\.map/);
  assert.match(profileSource, /summary\.observed_changes\.map/);
  assert.match(profileSource, /summary\.next_teaching_objectives\.map/);
  assert.match(profileSource, /不把小样本观察写成已证明提升/);
});

test("training chat exposes only aggregate Skill and knowledge-reference counts", () => {
  assert.match(pageSource, /selected_skill_count: number;/);
  assert.match(pageSource, /knowledge_reference_count: number;/);
  assert.match(pageSource, /const selectedSkillCount = coachTurn\.selected_skill_count;/);
  assert.match(pageSource, /selectedSkillCount > 0 \? `Skill \$\{selectedSkillCount\} 条` : ""/);
  assert.doesNotMatch(pageSource, /type SkillSelectionReason =/);
  assert.doesNotMatch(pageSource, /selected_skill_reasons|skillSelectionReasons/);
  assert.doesNotMatch(pageSource, /本轮 Skill 依据|why_selected_label|trigger_item_labels/);
});

test("profile page gives Skill accumulation its own detailed module", () => {
  const asideStart = profileSource.indexOf("<aside");
  const asideEnd = profileSource.indexOf("</aside>", asideStart);
  const skillModuleIndex = profileSource.indexOf("<SkillAccumulationSection accumulation={profile.skillAccumulation} />");
  const recentSessionsIndex = profileSource.indexOf('<h2 className="text-sm font-semibold">最近训练</h2>');

  assert.match(profileSource, /function SkillAccumulationSection\(\{ accumulation \}: Readonly<\{ accumulation: SkillAccumulation \}>\)/);
  assert.ok(asideStart >= 0, "profile page should still have an aside for weak and strong dimensions");
  assert.ok(asideEnd > asideStart, "profile aside should close before the standalone Skill module");
  assert.ok(skillModuleIndex > asideEnd, "Skill accumulation should not be nested in the right aside");
  assert.ok(skillModuleIndex < recentSessionsIndex, "Skill accumulation should remain a first-class profile section before recent sessions");
  assert.match(profileSource, /const FEATURED_SKILL_LIMIT = 5;/);
  assert.match(profileSource, /function getRankedEnabledSkills\(skills: readonly EnabledSkillSummary\[\]\): readonly EnabledSkillSummary\[]/);
  assert.match(profileSource, /visibleSkills\.map/);
  assert.match(profileSource, /hiddenSkills\.length > 0 \? \(/);
  assert.match(profileSource, /查看全部 \{sortedSkills\.length\} 条长期 Skill/);
  assert.match(profileSource, /<details className="rounded-xl border border-border bg-background shadow-xs"/);
  assert.match(profileSource, /<summary className="cursor-pointer p-4">/);
  assert.match(profileSource, /getSkillPreviewSummary\(skill\)/);
  assert.match(profileSource, /skill\.description/);
  assert.match(profileSource, /skill\.learning_action/);
  assert.match(profileSource, /skill\.activation_summary/);
  assert.match(profileSource, /skill\.source_summary/);
  assert.match(profileSource, /skill\.effect_status_label/);
  assert.match(profileSource, /skill\.scope_label/);
});

test("profile page renders Skill memory cards without repeated action pills", () => {
  assert.match(profileSource, /function getSkillPreviewSummary\(skill: EnabledSkillSummary\): string/);
  assert.match(profileSource, /支持 \{skill\.support_count\} 次/);
  assert.doesNotMatch(profileSource, /查看 Skill 详情/);
  assert.doesNotMatch(profileSource, /展开训练策略/);
  assert.doesNotMatch(profileSource, /支持次数 \{skill\.support_count\}/);
  assert.doesNotMatch(profileSource, /className="flex flex-col items-end gap-2"/);
});

test("profile page omits empty Skill detail rows instead of rendering blank cards", () => {
  assert.match(profileSource, /function SkillDetailRow\(/);
  assert.match(profileSource, /const trimmedValue = value\.trim\(\);/);
  assert.match(profileSource, /if \(!trimmedValue\) \{/);
  assert.match(profileSource, /return null;/);
  assert.match(profileSource, /function formatSkillEffectSummary\(skill: EnabledSkillSummary\): string/);
  assert.doesNotMatch(profileSource, /当前效果：\{skill\.effect_status_label\}。/);
  assert.match(profileSource, /<SkillDetailRow label="训练目标" value=\{skill\.description\} \/>/);
  assert.match(profileSource, /<SkillDetailRow label="TeacherAgent 应用方式" value=\{skill\.learning_action\} \/>/);
  assert.match(profileSource, /<SkillDetailRow label="生效条件" value=\{skill\.activation_summary\} \/>/);
  assert.match(profileSource, /<SkillDetailRow label="来源与效果" value=\{formatSkillEffectSummary\(skill\)\} \/>/);
})

test("profile page hides raw enabled skill strategy text from students", () => {
  assert.doesNotMatch(profileSource, /触发项：\{skill\.trigger_item_id\}/);
  assert.doesNotMatch(profileSource, /\{skill\.suggested_strategy\}/);
  assert.match(profileSource, /const studentVisibleSummary = skill\.student_visible_summary\.trim\(\);/);
  assert.match(profileSource, /\{studentVisibleSummary\}/);
  assert.match(profileSource, /已启用教学策略/);
});

test("home workspace exposes OSCE workflow navigation without a separate left-column next-step card", () => {
  assert.match(pageSource, /type WorkflowStepDefinition = Readonly<\{/);
  assert.match(pageSource, /const workflowStepDefinitions: readonly WorkflowStepDefinition\[\] = \[/);
  assert.match(pageSource, /label: "进入病例"/);
  assert.match(pageSource, /label: "查看报告"/);
  assert.match(pageSource, /function getWorkflowStepStatus\(stepKey: WorkflowStepDefinition\["key"\], session: OsceSession \| null, feedbackReport: FeedbackReport \| null\): StageStatus/);
  assert.match(pageSource, /function getNextWorkflowSuggestion\(session: OsceSession \| null, feedbackReport: FeedbackReport \| null\): string/);
  assert.match(pageSource, /const pedagogicalPhase = session\.pedagogy_state\?\.clinical_reasoning_state\?\.pedagogical_phase;/);
  assert.match(pageSource, /pedagogicalPhase === "needs_physical_exam"[\s\S]*?return 2;/);
  assert.match(pageSource, /const clinicalReasoningState = session\.pedagogy_state\?\.clinical_reasoning_state;/);
  assert.match(pageSource, /已识别训练顺序缺口/);
  assert.match(pageSource, /"请先询问起病、部位、性质、程度和伴随症状。"/);
  assert.match(pageSource, /<Panel title="训练导航" description="当前病例和训练阶段。">/);
  assert.doesNotMatch(pageSource, /<p className="text-sm font-semibold text-brand">下一步建议<\/p>/);
  assert.doesNotMatch(pageSource, /\{trainingSuggestion\}/);
});

test("home workspace can resume current user's persisted backend session", () => {
  assert.match(pageSource, /credentials: "same-origin"/);
  assert.match(pageSource, /const requestedSessionId = searchParams\.get\("session_id"\);/);
  assert.match(pageSource, /function getSession\(sessionId: string\): Promise<OsceSession>/);
  assert.match(pageSource, /`\/api\/me\/sessions\/\$\{sessionId\}`/);
  assert.match(pageSource, /if \(isCheckingAuth\) \{/);
  assert.match(pageSource, /if \(!authUser\) \{/);
  assert.match(pageSource, /setStatusText\("请先登录后再开始或恢复训练。"\);/);
  assert.match(pageSource, /if \(!requestedSessionId\) \{[\s\S]*?setStatusText\([\s\S]*?selectedCaseId[\s\S]*?\? isTrainingModelConfigReady[\s\S]*?\? "已选择病例，发送问诊或点击训练操作会自动创建训练会话。"[\s\S]*?: TRAINING_MODEL_CONFIG_REQUIRED_MESSAGE[\s\S]*?: "请选择病例后再开始训练。"[\s\S]*?\);[\s\S]*?return;[\s\S]*?\}/);
  assert.match(pageSource, /const sessionIdToRestore = requestedSessionId;/);
  assert.match(pageSource, /const nextSession = await getSession\(sessionIdToRestore\);/);
  assert.match(pageSource, /function isCompletedOsceSession\(session: OsceSession \| null\): boolean \{/);
  assert.match(pageSource, /isCompletedOsceSession\(nextSession\) \? "该训练已提交诊断，训练已结束。可以查看评分报告或重新选择病例开始新训练。" : "已恢复后端训练会话，可以继续训练。"/);
  assert.match(pageSource, /`\/api\/sessions\/\$\{sessionId\}\/report\/generate`/);
  assert.match(pageSource, /async function getRequestErrorMessage\(response: Response\): Promise<string>/);
  assert.match(pageSource, /if \(response\.status === 401\) \{/);
  assert.match(pageSource, /return "请先登录后再继续训练。";/);
  assert.match(pageSource, /setIsAuthDialogOpen\(true\);/);
  assert.doesNotMatch(pageSource, /requestedSessionId\s*\? await getSession\(requestedSessionId\)\s*: await createSession\(selectedCaseId\)/);
  assert.doesNotMatch(pageSource, /throw new Error\(detail \|\| `请求失败：\$\{response\.status\}`\);/);
  assert.match(pageSource, /\}, \[authUser, isCheckingAuth, isTrainingModelConfigReady, requestedSessionId, selectedCaseId\]\);/);
});

test("home workspace treats completed sessions as read-only training records", () => {
  assert.match(pageSource, /const isCurrentSessionCompleted = isCompletedOsceSession\(session\);/);
  assert.match(pageSource, /if \(isCompletedOsceSession\(activeSession\)\) \{[\s\S]*?setErrorText\("训练已结束，请查看报告。"\);[\s\S]*?return;/);
  assert.match(pageSource, /disabled=\{!authUser \|\| !selectedCaseId \|\| !isTrainingModelConfigReady \|\| isCurrentSessionCompleted \|\| isCreating \|\| isSending \|\| hasUncertainHistoryMessage \|\| isSpeechInputBusy\}/);
  assert.match(pageSource, /const isPhysicalExamActionDisabled = !authUser[\s\S]*?\|\| isCurrentSessionCompleted/);
  assert.match(pageSource, /const isAuxiliaryTestActionDisabled = !authUser[\s\S]*?\|\| isCurrentSessionCompleted/);
  assert.match(pageSource, /disabled=\{isPhysicalExamActionDisabled\}/);
  assert.match(pageSource, /disabled=\{isAuxiliaryTestActionDisabled\}/);
});

test("home workspace starts without a default case and only prepares a case after selection", () => {
  assert.match(pageSource, /const initialCaseId = searchParams\.get\("case_id"\);/);
  assert.match(pageSource, /const \[selectedCaseId, setSelectedCaseId\] = useState<string \| null>\(initialCaseId\);/);
  assert.doesNotMatch(pageSource, /searchParams\.get\("case_id"\) \?\? DEFAULT_CASE_ID/);
  assert.match(pageSource, /const selectedCase = useMemo\([\s\S]*?selectedCaseId \? caseOptionsState\.find\(\(caseOption\) => caseOption\.id === selectedCaseId\) \?\? null : null/);
  assert.match(pageSource, /const \[isCasePreparationPromptDismissed, setIsCasePreparationPromptDismissed\] = useState\(false\);/);
  assert.match(pageSource, /setIsCasePreparationPromptDismissed\(false\);/);
  assert.match(pageSource, /function CaseSelectionPrompt\(/);
  assert.match(pageSource, /aria-label="关闭训练准备提示"/);
  assert.match(pageSource, /<div className="flex justify-center">[\s\S]*?<div className="relative w-full max-w-xl rounded-xl/);
  assert.match(pageSource, /text-center/);
  assert.match(pageSource, /\{!selectedCase && !isCasePreparationPromptDismissed \? \([\s\S]*<CaseSelectionPrompt[\s\S]*onDismiss=\{\(\) => setIsCasePreparationPromptDismissed\(true\)\}[\s\S]*\/>[\s\S]*\) : null\}/);
  assert.doesNotMatch(pageSource, /<CaseSelectionPrompt[\s\S]*selectedCase=\{selectedCase\}/);
  assert.match(pageSource, /href="\/cases"[\s\S]*?>\s*选择病例\s*<\/Link>/);
  assert.match(pageSource, /const preparedOpeningTaskCard = session\?\.opening_task_card \?\? selectedCase\?\.openingTaskCard \?\? null;/);
  assert.match(pageSource, /<OpeningTaskCardMessage openingTaskCard=\{preparedOpeningTaskCard\} \/>/);
  assert.match(pageSource, /let baseMessages: ChatMessage\[\] = \[];/);
  assert.doesNotMatch(pageSource, /id: "patient-opening"/);
  assert.doesNotMatch(pageSource, /speaker: "patient"[\s\S]{0,240}请先选择一个病例；进入病例后/);
});

test("home workspace keeps implicit session creation and exposes explicit restart action", () => {
  assert.match(pageSource, /const \[isCreating, setIsCreating\] = useState\(false\);/);
  assert.match(pageSource, /const TRAINING_MODEL_CONFIG_REQUIRED_MESSAGE = "请先在 API 配置中应用可用模型，再开始训练。";/);
  assert.match(pageSource, /const isTrainingModelConfigReady = Boolean\(runtimeApiConfig\?\.active\) \|\| \(!isStudentApiConfigEditable && backendConnectionStatus === "online"\);/);
  assert.match(pageSource, /function promptTrainingModelConfigRequired\(\): void \{[\s\S]*?setStatusText\(TRAINING_MODEL_CONFIG_REQUIRED_MESSAGE\);[\s\S]*?setErrorText\(TRAINING_MODEL_CONFIG_REQUIRED_MESSAGE\);[\s\S]*?setIsApiConfigHelpOpen\(true\);[\s\S]*?\}/);
  assert.match(pageSource, /async function handleStartNewSession\(\): Promise<void>/);
  assert.match(pageSource, /async function ensureActiveSession\([\s\S]*?expectedContextEpoch: number = trainingContextEpochRef\.current,[\s\S]*?\): Promise<OsceSession \| null>/);
  assert.match(pageSource, /if \(session\) \{[\s\S]*?return session;[\s\S]*?\}/);
  assert.match(pageSource, /if \(!selectedCaseId\) \{[\s\S]*?setStatusText\("请先选择病例，再开始训练。"\);[\s\S]*?return null;[\s\S]*?\}/);
  assert.match(pageSource, /if \(!isTrainingModelConfigReady\) \{[\s\S]*?promptTrainingModelConfigRequired\(\);[\s\S]*?return null;[\s\S]*?\}/);
  assert.match(pageSource, /setStatusText\("正在创建训练会话\.\.\."\);/);
  const ensureActiveSessionSource = pageSource.slice(
    pageSource.indexOf("async function ensureActiveSession"),
    pageSource.indexOf("async function animatePendingPatientReply"),
  );
  assert.match(ensureActiveSessionSource, /const nextSession = await createSession\(selectedCaseId, trainingDifficultyMode\);/);
  assert.match(ensureActiveSessionSource, /setSession\(nextSession\);/);
  assert.match(ensureActiveSessionSource, /return nextSession;/);
  assert.match(pageSource, /const activeSession = await ensureActiveSession\(requestContextEpoch\);/);
  assert.match(pageSource, /sendHistoryMessage\(activeSession\.session_id, message\)/);
  assert.match(pageSource, /requestPhysicalExam\(activeSession\.session_id, examCode\)/);
  assert.match(pageSource, /requestAuxiliaryTest\(activeSession\.session_id, testCode\)/);
  assert.match(pageSource, /disabled=\{!authUser \|\| !selectedCaseId \|\| !isTrainingModelConfigReady \|\| isCurrentSessionCompleted \|\| isCreating \|\| isSending \|\| hasUncertainHistoryMessage \|\| isSpeechInputBusy\}/);
  assert.ok(pageSource.indexOf("if (!isTrainingModelConfigReady)") < pageSource.indexOf("setOptimisticHistoryMessage({"));
  assert.ok(pageSource.indexOf("const activeSession = await ensureActiveSession(requestContextEpoch);") < pageSource.indexOf("setOptimisticHistoryMessage({"));
});


test("home case card points users to the case selection page", () => {
  assert.match(pageSource, /<Panel[\s\S]*title="训练导航"[\s\S]*description="当前病例和训练阶段。"/);
  assert.match(pageSource, />当前选择<\/p>/);
  assert.match(pageSource, /\{selectedCase \? \([\s\S]*?\) : \([\s\S]*?尚未选择病例/);
  assert.match(pageSource, /href="\/cases"[\s\S]*?>\s*选择病例\s*<\/Link>/);
  assert.match(pageSource, />\s*开启新会话\s*<\/button>/);
  assert.match(pageSource, /onClick=\{\(\) => void handleStartNewSession\(\)\}/);
  assert.match(pageSource, /className="flex flex-wrap items-center justify-center gap-2"/);
  assert.match(pageSource, /className="flex w-fit items-center justify-center rounded-md border border-border bg-muted\/80 px-4 py-2 text-center text-xs font-medium whitespace-nowrap text-foreground/);
  assert.match(pageSource, /className="flex w-fit items-center justify-center rounded-md border border-brand bg-brand px-4 py-2 text-center text-xs font-medium whitespace-nowrap text-white/);
  assert.doesNotMatch(pageSource, /className="mx-auto flex w-fit items-center justify-center rounded-md border border-\[#141413\] bg-\[#141413\]/);
  assert.doesNotMatch(pageSource, /const \[isCaseSelectorOpen, setIsCaseSelectorOpen\]/);
  assert.doesNotMatch(pageSource, /caseOptionsState\.map\(\(caseOption\) =>/);
  assert.doesNotMatch(pageSource, /<Panel[\s\S]*title="病例信息与选择"/);
  assert.doesNotMatch(pageSource, /<Panel[\s\S]*title="病例选择"/);
});

test("home dialogue header shows the selected case prominently", () => {
  assert.match(pageSource, /<div className="flex flex-wrap items-center gap-2">[\s\S]*?<p className="text-xs font-medium text-muted-foreground">当前病例<\/p>/);
  assert.match(pageSource, /\{selectedCase \? \([\s\S]*?\{getTrainingDifficultyLabel\(trainingDifficultyMode\)\}训练[\s\S]*?\) : null\}/);
  assert.match(pageSource, /<h2 className="mt-1 text-lg font-semibold leading-6 text-foreground">[\s\S]*?\{session\?\.case_title \?\? selectedCase\?\.title \?\? "请先选择病例"\}[\s\S]*?<\/h2>/);
  assert.doesNotMatch(pageSource, /<p>\{statusText\}<\/p>/);
  assert.doesNotMatch(pageSource, /<p className="text-sm font-semibold">医患对话<\/p>[\s\S]*?<p className="mt-1 text-xs text-muted-foreground">/);
});


test("home right sidebar starts with progress and keeps collapsible cards bounded", () => {
  assert.match(pageSource, /type RightPanelKey = "evidence" \| "report";/);
  assert.match(pageSource, /function CollapsiblePanel\(/);
  assert.match(pageSource, /maxContentHeightClass = "max-h-64"/);
  assert.match(pageSource, /overflow-y-scroll pr-1 student-rail-scrollbar/);
  assert.match(pageSource, /const \[rightPanelOpenStates, setRightPanelOpenStates\] = useState<Record<RightPanelKey, boolean>>/);
  assert.doesNotMatch(pageSource, /focus: false,/);
  assert.doesNotMatch(pageSource, /agent: false,/);
  assert.doesNotMatch(pageSource, /hypotheses: true,/);
  assert.doesNotMatch(pageSource, /rightPanelOpenStates\.hypotheses/);
  assert.doesNotMatch(pageSource, /procedures: true,/);
  assert.match(pageSource, /report: true,/);
  assert.match(pageSource, /setRightPanelOpenStates\(\(currentStates\) =>/);

  const rightAsideIndex = pageSource.indexOf('<aside className="flex min-h-0 flex-col gap-4 overflow-y-scroll student-rail-scrollbar"');
  const focusPanelIndex = pageSource.indexOf('title="教学重点与问诊提示"', rightAsideIndex);
  const evidencePanelIndex = pageSource.indexOf('title="已收集线索"', rightAsideIndex);
  assert.notEqual(rightAsideIndex, -1);
  assert.equal(focusPanelIndex, -1);
  assert.notEqual(evidencePanelIndex, -1);
  assert.doesNotMatch(pageSource, /title="训练进度与素材覆盖"/);
  assert.doesNotMatch(pageSource, />\s*管理员图谱\s*<\/p>/);
  assert.doesNotMatch(pageSource, />\s*查看素材覆盖图谱\s*<\/button>/);

  assert.match(pageSource, /<CollapsiblePanel[\s\S]*title="已收集线索"[\s\S]*maxContentHeightClass="max-h-64"/);
  assert.doesNotMatch(pageSource, /<CollapsiblePanel[\s\S]*title="教学重点与问诊提示"[\s\S]*maxContentHeightClass="max-h-80"/);
  assert.doesNotMatch(pageSource, /<CollapsiblePanel[\s\S]*title="智能体教学详情"[\s\S]*maxContentHeightClass="max-h-96"/);
  assert.doesNotMatch(pageSource, /title="查体与检查申请"/);
  assert.doesNotMatch(pageSource, /toggleRightPanel\("procedures"\)/);
  assert.doesNotMatch(pageSource, /<CollapsiblePanel[\s\S]*title="诊断假设"/);
  assert.doesNotMatch(pageSource, /toggleRightPanel\("hypotheses"\)/);
  assert.match(pageSource, /<section className="rounded-2xl border border-brand\/20 bg-card p-3 shadow-xs"[\s\S]*?"提交诊断与推理"[\s\S]*?id="diagnosis-input"/);
  assert.match(pageSource, /<CollapsiblePanel[\s\S]*title="评分报告"[\s\S]*maxContentHeightClass="max-h-96"/);
});


test("home sidebars prioritize a compact student task flow", () => {
  const leftAsideIndex = pageSource.indexOf('<aside className="hidden w-72 shrink-0 border-r border-border bg-background p-4 shadow-inner-right lg:flex lg:flex-col">');
  const leftAsideEndIndex = pageSource.indexOf("</aside>", leftAsideIndex);
  const leftAsideSource = pageSource.slice(leftAsideIndex, leftAsideEndIndex);
  const navigationPanelIndex = pageSource.indexOf('title="训练导航"', leftAsideIndex);
  const currentCaseIndex = pageSource.indexOf(">当前选择</p>", leftAsideIndex);
  const nextSuggestionIndex = pageSource.indexOf(">下一步建议</p>", leftAsideIndex);
  assert.notEqual(leftAsideIndex, -1);
  assert.notEqual(navigationPanelIndex, -1);
  assert.notEqual(currentCaseIndex, -1);
  assert.equal(nextSuggestionIndex, -1);
  assert.doesNotMatch(leftAsideSource, /title="问诊引导"|title="智能体状态"|title="当前训练重点"|title="训练重点"|title="OSCE 流程导航"/);

  const rightAsideIndex = pageSource.indexOf('<aside className="flex min-h-0 flex-col gap-4 overflow-y-scroll student-rail-scrollbar"');
  const focusPanelIndex = pageSource.indexOf('title="教学重点与问诊提示"', rightAsideIndex);
  const agentPanelIndex = pageSource.indexOf('title="智能体教学详情"', rightAsideIndex);
  const diagnosisComposerIndex = pageSource.indexOf('提交诊断与推理', rightAsideIndex);
  const evidencePanelIndex = pageSource.indexOf('title="已收集线索"', rightAsideIndex);
  const hypothesisPanelIndex = pageSource.indexOf('>诊断假设</h2>', rightAsideIndex);
  assert.equal(focusPanelIndex, -1);
  assert.equal(agentPanelIndex, -1);
  assert.notEqual(diagnosisComposerIndex, -1);
  assert.notEqual(evidencePanelIndex, -1);
  assert.equal(hypothesisPanelIndex, -1);
  assert.ok(diagnosisComposerIndex < evidencePanelIndex);
});

test("home workspace keeps the composer sticky and moves final diagnosis into the right rail", () => {
  assert.match(pageSource, /<main className="relative h-screen overflow-hidden bg-muted\/40 text-foreground">/);
  assert.match(pageSource, /<div className=\{isAuthDialogOpen \? "h-full pointer-events-none blur-sm" : "h-full"\}>/);
  assert.match(pageSource, /<div className="flex h-full min-h-0">/);
  assert.match(pageSource, /className="flex-1 space-y-4 overflow-y-scroll p-5 pb-40 student-chat-scrollbar"/);
  assert.match(pageSource, /ref=\{chatScrollContainerRef\}/);
  assert.match(pageSource, /const \[isDiagnosisComposerOpen, setIsDiagnosisComposerOpen\] = useState\(false\);/);
  assert.match(pageSource, /className="pointer-events-none absolute inset-x-0 bottom-0 z-20 isolate px-3 pb-4 pt-10"/);
  assert.match(pageSource, /aria-hidden="true" className="absolute inset-x-0 bottom-0 z-0 h-20 bg-background"/);
  assert.match(pageSource, /aria-hidden="true" className="absolute bottom-20 left-1\/2 z-0 h-10 w-full max-w-3xl -translate-x-1\/2 bg-background\/75 backdrop-blur-md \[mask-image:linear-gradient\(to_top,black,black_52%,transparent\)\]"/);
  assert.doesNotMatch(pageSource, /aria-hidden="true" className="absolute inset-x-0 bottom-20 z-0 h-10 bg-background\/75 backdrop-blur-md/);
  assert.match(pageSource, /className="pointer-events-auto relative z-10 mx-auto max-w-3xl rounded-2xl border border-border bg-background px-3 py-2 shadow-\[0_10px_30px_rgba\(20,20,19,0\.12\)\]"/);
  assert.match(pageSource, /className="pointer-events-auto relative z-10 mx-auto mb-2 flex max-w-3xl flex-wrap items-center gap-2"/);
  const quickActionRowIndex = pageSource.indexOf('className="pointer-events-auto relative z-10 mx-auto mb-2 flex max-w-3xl flex-wrap items-center gap-2"');
  const inputComposerIndex = pageSource.indexOf('className="pointer-events-auto relative z-10 mx-auto max-w-3xl rounded-2xl border border-border bg-background px-3 py-2 shadow-[0_10px_30px_rgba(20,20,19,0.12)]"');
  assert.notEqual(quickActionRowIndex, -1);
  assert.notEqual(inputComposerIndex, -1);
  assert.ok(quickActionRowIndex < inputComposerIndex);
  assert.doesNotMatch(pageSource, /rounded-xl border border-input bg-muted\/50 p-3/);
  assert.doesNotMatch(pageSource, /sticky bottom-0 z-20 bg-gradient-to-t/);
  assert.doesNotMatch(pageSource, /<p className="mx-auto mt-2 max-w-3xl text-xs leading-5 text-muted-foreground">\{statusText\}<\/p>/);
  const quickActionsSource = pageSource.slice(quickActionRowIndex, inputComposerIndex);
  assert.doesNotMatch(quickActionsSource, /填写诊断|收起诊断/);
  const rightAsideIndex = pageSource.indexOf('<aside className="flex min-h-0 flex-col gap-4 overflow-y-scroll student-rail-scrollbar"');
  const diagnosisInputIndex = pageSource.indexOf('id="diagnosis-input"', rightAsideIndex);
  const evidencePanelIndex = pageSource.indexOf('title="已收集线索"', rightAsideIndex);
  assert.notEqual(diagnosisInputIndex, -1);
  assert.notEqual(evidencePanelIndex, -1);
  assert.ok(diagnosisInputIndex < evidencePanelIndex);
  assert.match(pageSource, /\{isCurrentSessionCompleted \? "诊断已提交" : isDiagnosisComposerOpen \? "收起诊断表单" : "提交诊断与推理"\}/);
  assert.match(pageSource, /\{isDiagnosisComposerOpen \? \([\s\S]*id="diagnosis-input"[\s\S]*\) : null\}/);
});

test("home quick actions allow realistic sequence jumps but show teaching reminders", () => {
  assert.match(pageSource, /const shouldShowPhysicalExamSequenceReminder = activeSession\.revealed_facts\.length === 0;/);
  assert.match(pageSource, /const shouldShowAuxiliaryTestSequenceReminder = activeSession\.requested_exams\.length === 0;/);
  assert.match(pageSource, /OSCE 通常建议先完成核心病史采集，再进入查体。/);
  assert.match(pageSource, /现实 OSCE 中通常应先基于病史和查体形成初步判断，再选择辅助检查。/);
  assert.match(pageSource, /disabled=\{!authUser \|\| !selectedCaseId \|\| !isTrainingModelConfigReady \|\| isCurrentSessionCompleted \|\| isCreating \|\| isRequestingExam\}/);
  assert.match(pageSource, /disabled=\{!authUser \|\| !selectedCaseId \|\| !isTrainingModelConfigReady \|\| isCurrentSessionCompleted \|\| isCreating \|\| isRequestingTest\}/);
  assert.doesNotMatch(pageSource, /canRequestPhysicalExam/);
  assert.doesNotMatch(pageSource, /canRequestAuxiliaryTest/);
});

test("home quick actions group procedure choices and open viewed results in a modal", () => {
  assert.match(pageSource, /type ProcedureActionGroup = "physical_exam" \| "auxiliary_test";/);
  assert.match(pageSource, /const \[openProcedureActionGroup, setOpenProcedureActionGroup\] = useState<ProcedureActionGroup \| null>\(null\);/);
  assert.match(pageSource, /const \[selectedProcedureResult, setSelectedProcedureResult\] = useState<ProcedureResult \| null>\(null\);/);
  assert.match(pageSource, /const requestedExamCodeSet = useMemo\(\(\) => new Set\(session\?\.requested_exams \?\? \[\]\), \[session\?\.requested_exams\]\);/);
  assert.match(pageSource, /const requestedTestCodeSet = useMemo\(\(\) => new Set\(session\?\.requested_tests \?\? \[\]\), \[session\?\.requested_tests\]\);/);
  assert.match(pageSource, /const pendingPhysicalExamOptions = physicalExamOptions\.filter\(\(examOption\) => !requestedExamCodeSet\.has\(examOption\.exam_code\)\);/);
  assert.match(pageSource, /const completedPhysicalExamOptions = physicalExamOptions\.filter\(\(examOption\) => requestedExamCodeSet\.has\(examOption\.exam_code\)\);/);
  assert.match(pageSource, /const pendingAuxiliaryTestOptions = auxiliaryTestOptions\.filter\(\(testOption\) => !requestedTestCodeSet\.has\(testOption\.test_code\)\);/);
  assert.match(pageSource, /const completedAuxiliaryTestOptions = auxiliaryTestOptions\.filter\(\(testOption\) => requestedTestCodeSet\.has\(testOption\.test_code\)\);/);
  assert.match(pageSource, /\{completedPhysicalExamOptions\.length\}\/\{physicalExamOptions\.length\}/);
  assert.match(pageSource, /\{completedAuxiliaryTestOptions\.length\}\/\{auxiliaryTestOptions\.length\}/);
  assert.doesNotMatch(pageSource, /\{pendingPhysicalExamOptions\.length\}\/\{physicalExamOptions\.length\}/);
  assert.doesNotMatch(pageSource, /\{pendingAuxiliaryTestOptions\.length\}\/\{auxiliaryTestOptions\.length\}/);
  assert.match(pageSource, /aria-expanded=\{openProcedureActionGroup === "physical_exam"\}[\s\S]*?>\s*查体项目/);
  assert.match(pageSource, /aria-expanded=\{openProcedureActionGroup === "auxiliary_test"\}[\s\S]*?>\s*辅助检查/);
  assert.match(pageSource, /\{!isAdvancedTrainingMode \? \([\s\S]*aria-expanded=\{openProcedureActionGroup === "physical_exam"\}[\s\S]*aria-expanded=\{openProcedureActionGroup === "auxiliary_test"\}[\s\S]*openProcedureActionGroup === "physical_exam"[\s\S]*openProcedureActionGroup === "auxiliary_test"[\s\S]*\) : null\}/);
  assert.match(pageSource, /openProcedureActionGroup === "physical_exam" \? \(/);
  assert.match(pageSource, /openProcedureActionGroup === "auxiliary_test" \? \(/);
  assert.match(pageSource, /ref=\{procedureActionContainerRef\}/);
  assert.match(pageSource, /data-procedure-action-menu="true"/);
  assert.match(pageSource, /setOpenProcedureActionGroup\(null\);/);
  assert.match(pageSource, /className="absolute bottom-11 left-0 z-30 w-80 rounded-2xl border border-border bg-background p-3 shadow-\[0_18px_45px_rgba\(20,20,19,0\.16\)\]"/);
  assert.match(pageSource, /className="absolute bottom-11 left-32 z-30 w-80 rounded-2xl border border-border bg-background p-3 shadow-\[0_18px_45px_rgba\(20,20,19,0\.16\)\]"/);
  assert.match(pageSource, /className="mt-3 grid max-h-72 gap-2 overflow-y-scroll pr-1 student-rail-scrollbar" onScroll=\{handleStudentRailScroll\}/);
  assert.match(pageSource, />\s*已查看\s*<\/p>[\s\S]*completedPhysicalExamOptions\.map/);
  assert.match(pageSource, />\s*已查看\s*<\/p>[\s\S]*completedAuxiliaryTestOptions\.map/);
  assert.match(pageSource, /openProcedureResult\(getProcedureResultById\(`exam:\$\{examOption\.exam_code\}`\)\)/);
  assert.match(pageSource, /openProcedureResult\(getProcedureResultById\(`test:\$\{testOption\.test_code\}`\)\)/);
  assert.match(pageSource, /aria-label="关闭查体检查结果"/);
  assert.match(pageSource, /procedureResult\.result/);
  assert.doesNotMatch(pageSource, /<p className="mt-1 text-xs leading-5 text-muted-foreground">\{item\.result\}<\/p>/);
});

test("home supports intermediate procedure catalog and batch procedure requests", () => {
  assert.match(pageSource, /type TrainingDifficultyMode = "beginner" \| "intermediate" \| "advanced";/);
  assert.match(pageSource, /training_difficulty: TrainingDifficultyMode;/);
  assert.match(pageSource, /type ProcedureCatalog = Readonly/);
  assert.match(pageSource, /\/api\/procedure-catalog/);
  assert.match(pageSource, /\/api\/sessions\/\$\{sessionId\}\/physical-exams/);
  assert.match(pageSource, /\/api\/sessions\/\$\{sessionId\}\/auxiliary-tests/);
  assert.match(pageSource, /\/api\/sessions\/\$\{sessionId\}\/procedure-request/);
  assert.doesNotMatch(pageSource, /known_case_ids/);
  assert.match(pageSource, /function getTrainingDifficultyModeFromSearchParams/);
  assert.match(pageSource, /useState<TrainingDifficultyMode>\(\(\) => getTrainingDifficultyModeFromSearchParams\(searchParams\)\)/);
  assert.match(pageSource, /createSession\(selectedCaseId, trainingDifficultyMode\)/);
  assert.match(pageSource, /training_difficulty: trainingDifficultyMode/);
  assert.match(pageSource, /setTrainingDifficultyMode\(nextSession\.training_difficulty\)/);
  assert.match(pageSource, /ensureProcedureCatalog/);
  assert.match(pageSource, /selectedIntermediateExamCodes/);
  assert.match(pageSource, /selectedIntermediateTestCodes/);
  assert.match(pageSource, /advancedProcedureRequestText/);
  assert.match(pageSource, /type AdvancedProcedureRequestSummary = Readonly/);
  assert.match(pageSource, /routed_unmatched_requests\?: readonly RoutedUnmatchedProcedureRequest\[\]/);
  assert.match(pageSource, /useState<AdvancedProcedureRequestSummary \| null>\(null\)/);
  assert.match(pageSource, /const advancedProcedureRequestSummaryToShow = useMemo<AdvancedProcedureRequestSummary \| null>/);
  assert.match(pageSource, /handleAdvancedProcedureRequest/);
  assert.doesNotMatch(pageSource, /setTrainingDifficultyMode\("beginner"\);/);
  assert.doesNotMatch(pageSource, /setTrainingDifficultyMode\("intermediate"\);/);
  assert.doesNotMatch(pageSource, /setTrainingDifficultyMode\("advanced"\);/);
  assert.match(pageSource, />提交所选查体<\/button>/);
  assert.match(pageSource, />提交所选检查<\/button>/);
  assert.doesNotMatch(pageSource, /提交自由申请/);
  assert.match(pageSource, /className="flex w-fit max-w-full flex-none items-center gap-1\.5 rounded-full border border-border bg-background p-1 shadow-xs"/);
  assert.match(pageSource, /className="h-7 w-52 min-w-0 bg-transparent px-2 text-xs outline-none placeholder:text-muted-foreground sm:w-60"/);
  assert.match(pageSource, /className="h-7 rounded-full border border-brand bg-brand px-3 text-xs font-medium whitespace-nowrap text-white transition hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-50"/);
  assert.match(pageSource, /提交申请/);
  assert.match(pageSource, /查看申请内容/);
  assert.match(pageSource, /onClick=\{openAdvancedProcedureRequestSummary\}/);
  assert.match(pageSource, /disabled=\{advancedProcedureRequestSummaryToShow === null\}/);
  assert.match(pageSource, /const advancedProcedureRequestItemsToShow = useMemo<readonly ProcedureResult\[\]>/);
  assert.match(pageSource, /matchedLabels: advancedProcedureRequestItemsToShow\.map\(\(procedureItem\) => procedureItem\.label\)/);
  assert.match(pageSource, /advancedProcedureRequestItemsToShow\.map\(\(procedureItem\) => \(/);
  assert.match(pageSource, /全部已申请项目/);
  assert.doesNotMatch(pageSource, /openProcedureResultGroup\(procedureItems\)/);
  assert.doesNotMatch(pageSource, /procedureItems\.length === 0/);
  assert.match(pageSource, /未识别项目/);
  assert.match(pageSource, /not_available_for_case/);
  assert.match(pageSource, /ai_simulated_for_training/);
  assert.match(pageSource, /旧版模拟记录 · 不计分/);
  assert.match(pageSource, /formatProcedureResultText\(procedureResult\)/);
  assert.doesNotMatch(pageSource, /本次查体 \/ 检查申请/);
  assert.doesNotMatch(pageSource, /门禁状态：/);
  assert.doesNotMatch(pageSource, /依据：\{procedureResult\.sourceContextReferences/);
});

test("home quick actions are available after a case is selected and before a backend session exists", () => {
  assert.match(pageSource, /const physicalExamOptions = session\?\.physical_exam_options \?\? selectedCase\?\.physicalExamOptions \?\? \[\];/);
  assert.match(pageSource, /const auxiliaryTestOptions = session\?\.auxiliary_test_options \?\? selectedCase\?\.auxiliaryTestOptions \?\? \[\];/);
  assert.match(pageSource, /pendingPhysicalExamOptions\.map/);
  assert.match(pageSource, /pendingAuxiliaryTestOptions\.map/);
  assert.doesNotMatch(pageSource, /session\?\.physical_exam_options\.map/);
  assert.doesNotMatch(pageSource, /session\?\.auxiliary_test_options\.map/);
});

test("student auxiliary test buttons expose logistics without diagnostic-answer metadata", () => {
  assert.match(pageSource, /testOption\.cost_hint/);
  assert.match(pageSource, /testOption\.invasiveness/);
  assert.doesNotMatch(pageSource, /diagnostic_role|rules_out|getDiagnosticRoleLabel/);
});

test("home diagnosis submission absorbs the old hypothesis panel into the final reasoning form", () => {
  assert.doesNotMatch(pageSource, /function recordHypothesis\(sessionId: string, hypothesis: string\): Promise<OsceSession>/);
  assert.doesNotMatch(pageSource, /\/api\/sessions\/\$\{sessionId\}\/hypotheses/);
  assert.doesNotMatch(pageSource, /id="hypothesis-input"/);
  assert.doesNotMatch(pageSource, /记录假设/);
  assert.doesNotMatch(pageSource, />诊断假设<\/h2>/);
  assert.match(pageSource, /训练中已记录的假设/);
  assert.match(pageSource, /session\.student_hypotheses\.map/);
});


test("home diagnosis submission form collects structured OSCE reasoning fields", () => {
  assert.match(pageSource, /const \[diagnosisValue, setDiagnosisValue\] = useState\(""\);/);
  assert.match(pageSource, /const \[differentialDiagnosisValue, setDifferentialDiagnosisValue\] = useState\(""\);/);
  assert.match(pageSource, /const \[supportingEvidenceValue, setSupportingEvidenceValue\] = useState\(""\);/);
  assert.match(pageSource, /const \[exclusionEvidenceValue, setExclusionEvidenceValue\] = useState\(""\);/);
  assert.match(pageSource, /const \[nextStepValue, setNextStepValue\] = useState\(""\);/);
  assert.match(pageSource, /const \[uncertaintyValue, setUncertaintyValue\] = useState\(""\);/);
  assert.match(pageSource, /const isNextStepRequired = trainingDifficultyMode !== "beginner";/);
  assert.doesNotMatch(pageSource, /const isUncertaintyRequired = trainingDifficultyMode === "advanced";/);
  assert.doesNotMatch(pageSource, /const DEFAULT_DIAGNOSIS/);
  assert.doesNotMatch(pageSource, /const DEFAULT_REASONING/);
  assert.match(pageSource, /function buildStructuredReasoning\(/);
  assert.match(pageSource, /当前诊断假设：\$\{primaryDiagnosis\}/);
  assert.match(pageSource, /鉴别诊断：\$\{otherPossibleDiagnoses\}/);
  assert.match(pageSource, /支持依据：\$\{supportingEvidence\}/);
  assert.match(pageSource, /鉴别与排除：\$\{differentialReasoning\}/);
  assert.match(pageSource, /下一步验证计划：\$\{nextStep\}/);
  assert.match(pageSource, /证据不足或不确定点：\$\{uncertainty\}/);
  assert.match(pageSource, /id="differential-diagnosis-input"/);
  assert.match(pageSource, /placeholder="可写 1-3 个，多个用逗号分隔"/);
  assert.match(pageSource, /id="supporting-evidence-input"/);
  assert.match(pageSource, /id="exclusion-evidence-input"/);
  assert.match(pageSource, /id="next-step-input"/);
  assert.match(pageSource, /id="uncertainty-input"/);
  assert.match(pageSource, /function resizeTextareaToContent\(textarea: HTMLTextAreaElement\): void/);
  assert.match(pageSource, /const DIAGNOSIS_TEXTAREA_MAX_HEIGHT = 160;/);
  assert.match(pageSource, /Math\.min\(textarea\.scrollHeight, DIAGNOSIS_TEXTAREA_MAX_HEIGHT\)/);
  assert.match(pageSource, /resize-y max-h-40 overflow-y-auto/);
  assert.match(pageSource, /onInput=\{\(event\) => resizeTextareaToContent\(event\.currentTarget\)\}/);
  assert.doesNotMatch(pageSource, /!differentialDiagnosisValue\.trim\(\)/);
  assert.match(pageSource, /!supportingEvidenceValue\.trim\(\)/);
  assert.match(pageSource, /!exclusionEvidenceValue\.trim\(\)/);
  assert.match(pageSource, /isNextStepRequired && !nextStepValue\.trim\(\)/);
  assert.doesNotMatch(pageSource, /isUncertaintyRequired && !uncertaintyValue\.trim\(\)/);
  assert.doesNotMatch(pageSource, /setDiagnosisValue\(nextSession\.diagnosis_draft\.diagnosis\)/);
  assert.doesNotMatch(pageSource, /setSupportingEvidenceValue\(nextSession\.diagnosis_draft\.reasoning\)/);
});

test("home scoring report preview keeps the copy concise and shows revealed fact totals", () => {
  assert.match(pageSource, /const scoringPreview = useMemo/);
  assert.match(pageSource, /已披露线索：\$\{session\?\.revealed_facts\.length \?\? 0\} \/ \$\{session\?\.training_progress\.history\.total \?\? 0\} 条/);
  assert.match(pageSource, /session\?\.training_progress\.history\.total/);
  assert.doesNotMatch(pageSource, /本报告仅用于教学复盘，评分依据来自病例、rubric 与来源引用。/);
});

test("report dimension max scores are derived from rubric score metadata", () => {
  for (const source of [pageSource, reportModelSource]) {
    assert.match(source, /type RubricScoreItem = Readonly<\{/);
  }
  assert.match(reportSource, /type RubricScoreItem,/);
  for (const source of [pageSource, reportSource]) {
    assert.match(source, /function getDimensionMaxScoresFromRubricScores\(/);
    assert.match(source, /rubricScore\.dimension_id/);
    assert.match(source, /rubricScore\.max_score/);
    assert.doesNotMatch(source, /const scoreDimensionMaxScores: Readonly<Record<string, number>> = \{/);
  }
  assert.match(pageSource, /const reportDimensionMaxScores = useMemo\(\(\) => getDimensionMaxScoresFromRubricScores\(feedbackReport\?\.rubric_scores\), \[feedbackReport\?\.rubric_scores\]\);/);
  assert.match(reportSource, /const dimensionMaxScores = useMemo\(\(\) => getDimensionMaxScoresFromRubricScores\(report\?\.rubric_scores\), \[report\?\.rubric_scores\]\);/);
});


test("home workspace can request socratic hints and render coach messages", () => {
  assert.match(pageSource, /type HintResponse = OsceSession &/);
  assert.match(pageSource, /function requestHint\(sessionId: string\): Promise<HintResponse>/);
  assert.match(pageSource, /\/api\/sessions\/\$\{sessionId\}\/hint/);
  assert.match(pageSource, /const \[pendingCoachHintMessage, setPendingCoachHintMessage\] = useState<ChatMessage \| null>\(null\);/);
  assert.match(pageSource, /function buildHintContextSignature\(/);
  assert.match(pageSource, /const \[lastHintContextSignature, setLastHintContextSignature\] = useState<string \| null>\(null\);/);
  assert.match(pageSource, /const isHintRequestLocked = Boolean\([\s\S]*?lastHintContextSignature[\s\S]*?lastHintContextSignature === currentHintContextSignature[\s\S]*?\);/);
  assert.match(pageSource, /const hintButtonLabel = isRequestingHint[\s\S]*?"提示生成中"[\s\S]*?: isHintRequestLocked[\s\S]*?\? "开始问诊"[\s\S]*?: "请求提示";/);
  assert.match(pageSource, /setLastHintContextSignature\(buildHintContextSignature\(updatedSession, selectedCaseId, trainingDifficultyMode\)\);/);
  assert.match(pageSource, /message\.role === "coach"/);
  assert.match(pageSource, /const coachLabel = getCoachMessageLabel\(message\.content\);/);
  assert.match(pageSource, /label: coachLabel/);
  assert.match(pageSource, /"过程提示"/);
  assert.match(pageSource, /const pendingCoachHintId = createClientChatMessageId\("pending-coach-hint"\);/);
  assert.match(pageSource, /function buildPendingHintProcessingTimeline\(processingStatus\?: SessionProcessingStatus \| null\): AgentProcessingTimeline/);
  assert.match(pageSource, /speaker: "coach",[\s\S]*?label: "过程提示",[\s\S]*?isPending: true,[\s\S]*?processingTimeline: \{[\s\S]*?\.\.\.buildPendingHintProcessingTimeline\(\),[\s\S]*?startedAtMs: coachHintProcessingStartedAtMs,[\s\S]*?\}/);
  assert.match(pageSource, /refreshPendingProcessingTimeline\(activeSession\.session_id, pendingCoachHintId\)/);
  assert.match(pageSource, /setPendingCoachHintMessage\(\(currentMessage\) => currentMessage\?\.id === pendingCoachHintId \? null : currentMessage\);/);
  assert.match(pageSource, /onClick=\{handleHintRequest\}/);
  assert.match(pageSource, /disabled=\{!authUser \|\| !selectedCaseId \|\| !isTrainingModelConfigReady \|\| isCurrentSessionCompleted \|\| isCreating \|\| isRequestingHint \|\| isHintRequestLocked\}/);
  assert.match(pageSource, />\{hintButtonLabel\}<\/button>/);
  assert.doesNotMatch(pageSource, /继续后再提示/);
});


test("home workspace highlights safety guardrail replies", () => {
  assert.match(pageSource, /function getCoachMessageLabel\(content: string\): "安全边界" \| "答题边界" \| "问诊引导" \| "过程提示"/);
  assert.match(pageSource, /content\.includes\("本系统仅用于 OSCE 教学模拟训练"\)[\s\S]*?return "安全边界";/);
  assert.match(pageSource, /content\.includes\("不能直接告诉你标准答案"\)[\s\S]*?return "答题边界";/);
  assert.match(pageSource, /content\.includes\("病例脚本没有提供这方面信息"\)[\s\S]*?return "问诊引导";/);
  assert.match(pageSource, /const coachLabel = getCoachMessageLabel\(message\.content\);/);
  assert.match(pageSource, /processingTimeline: coachLabel === "安全边界" \? undefined : session \? buildCompletedCoachProcessingTimeline\(session, message\.content\) : undefined,/);
  assert.doesNotMatch(pageSource, /skillSelectionReasons|getSkillSelectionReasonsForReply/);
  assert.match(pageSource, /const isSafetyBoundary = isCoach && message\.label === "安全边界";/);
  assert.match(pageSource, /aria-label="安全边界提示"/);
  assert.match(pageSource, /`安全边界：\$\{session\?\.safety_flags\.length \?\? 0\} 次`/);
});

test("home workspace auto-scrolls to the newest dialogue and keeps process hints out of the case header", () => {
  assert.match(pageSource, /const chatScrollContainerRef = useRef<HTMLDivElement \| null>\(null\);/);
  assert.match(pageSource, /useEffect\(\(\) => \{[\s\S]*?chatScrollContainer\.scrollTo\(\{[\s\S]*?top: chatScrollContainer\.scrollHeight,[\s\S]*?behavior: "smooth",[\s\S]*?\}\);[\s\S]*?\}, \[chatMessages\.length, optimisticHistoryMessage\?\.text, pendingCoachHintMessage\?\.text, pendingPatientMessage\?\.text, statusText, errorText\]\);/);
  const dialogueHeaderIndex = pageSource.indexOf('<div className="border-b border-border p-4">');
  const dialogueBodyIndex = pageSource.indexOf('<div className="flex-1 space-y-4 overflow-y-scroll p-5 pb-40 student-chat-scrollbar"', dialogueHeaderIndex);
  assert.notEqual(dialogueHeaderIndex, -1);
  assert.notEqual(dialogueBodyIndex, -1);
  assert.doesNotMatch(pageSource.slice(dialogueHeaderIndex, dialogueBodyIndex), /\{statusText\}/);
  assert.doesNotMatch(pageSource.slice(dialogueHeaderIndex, dialogueBodyIndex), /已生成过程提示/);
  assert.doesNotMatch(pageSource.slice(dialogueHeaderIndex, dialogueBodyIndex), /\{trainingSuggestion\}/);
});

test("home inquiry submit shows optimistic student message and neutral streaming placeholder", () => {
  assert.match(pageSource, /const \[optimisticHistoryMessage, setOptimisticHistoryMessage\] = useState<ChatMessage \| null>\(null\);/);
  assert.match(pageSource, /const \[pendingPatientMessage, setPendingPatientMessage\] = useState<ChatMessage \| null>\(null\);/);
  assert.match(pageSource, /function getReplyMessageMetadata\(session: OsceSession, replyText: string\): Pick<ChatMessage, "speaker" \| "label" \| "apiMessageIndex">/);
  assert.match(pageSource, /session\.messages[\s\S]*?\.map\(\(message, index\) => \(\{ message, index \}\)\)[\s\S]*?\.reverse\(\)[\s\S]*?\.find/);
  assert.match(pageSource, /matchingReplyMessage\?\.message\.role === "coach"[\s\S]*?speaker: "coach",[\s\S]*?label: getCoachMessageLabel\(replyText\),[\s\S]*?apiMessageIndex: matchingReplyMessage\.index,/);
  assert.match(pageSource, /let didReplacePendingPatientMessage = false;/);
  assert.match(pageSource, /return pendingPatientMessage;/);
  assert.match(pageSource, /if \(pendingPatientMessage && !didReplacePendingPatientMessage\)/);
  assert.doesNotMatch(pageSource, /baseMessages = baseMessages\.filter\(/);
  assert.match(pageSource, /function AgentProcessingTimelineView/);
  assert.match(pageSource, /智能体处理中/);
  assert.match(pageSource, /智能体流程/);
  assert.doesNotMatch(pageSource, /aria-label="判断中"/);
  assert.match(globalsSource, /@keyframes clinical-osce-agent-process-pulse/);
  assert.match(globalsSource, /\.clinical-osce-agent-process-dot-active/);
  assert.match(pageSource, /async function animatePendingPatientReply\(messageId: string, replyText: string\): Promise<void>/);
  assert.match(pageSource, /window\.setTimeout\(resolve, PATIENT_REPLY_TYPEWRITER_DELAY_MS\)/);
  assert.match(pageSource, /replyText\.slice\(0, index\)/);
  assert.match(pageSource, /setOptimisticHistoryMessage\(\{[\s\S]*?id: optimisticQuestionId,[\s\S]*?speaker: "student",[\s\S]*?label: "学生",[\s\S]*?text: message,[\s\S]*?\}\);/);
  assert.match(pageSource, /setPendingPatientMessage\(\{[\s\S]*?id: pendingPatientReplyId,[\s\S]*?speaker: "patient",[\s\S]*?label: "标准化病人",[\s\S]*?text: "",[\s\S]*?processingTimeline: \{[\s\S]*?\.\.\.buildPendingAgentProcessingTimeline\(\),[\s\S]*?startedAtMs: patientReplyProcessingStartedAtMs,[\s\S]*?\},[\s\S]*?\}\);/);
  assert.doesNotMatch(pageSource, /setPendingPatientMessage\(\{[\s\S]*?id: pendingPatientReplyId,[\s\S]*?speaker: "coach",[\s\S]*?label: "判断中"/);
  assert.doesNotMatch(pageSource, /text: "判断中"/);
  assert.match(pageSource, /message\.processingTimeline\?\.state === "pending"/);
  assert.match(pageSource, /<AgentProcessingTimelineView timeline=\{processingTimeline \?\? buildPendingAgentProcessingTimeline\(\)\} \/>/);
  assert.match(pageSource, /setStatusText\("正在处理问诊"\);/);
  assert.match(pageSource, /const replyMessageMetadata = getReplyMessageMetadata\(updatedSession, replyText\);/);
  assert.match(pageSource, /const replyStatusLabel = replyMessageMetadata\.speaker === "coach" \? replyMessageMetadata\.label : "标准化病人回复";/);
  assert.match(pageSource, /if \(replyMessageMetadata\.speaker === "coach"\) \{[\s\S]*?setPendingPatientMessage\(\(currentMessage\) => currentMessage\?\.id === pendingPatientReplyId \? null : currentMessage\);[\s\S]*?setSession\(updatedSession\);/);
  assert.match(pageSource, /\.\.\.replyMessageMetadata,[\s\S]*?finalText: replyText,/);
  assert.match(pageSource, /const completedTimeline = buildCompletedAgentProcessingTimeline\(updatedSession, replyText\);/);
  assert.match(pageSource, /processingTimeline: \{[\s\S]*?\.\.\.completedTimeline,[\s\S]*?elapsedMs: Math\.max\(completedTimeline\.elapsedMs \?\? 0, patientReplyProcessingElapsedMs\),[\s\S]*?\}/);
  assert.match(pageSource, /await animatePendingPatientReply\(pendingPatientReplyId, updatedSession\.reply \?\? ""\);/);
  assert.match(pageSource, /setStatusText\(`已收到\$\{replyStatusLabel\}：\$\{formatIntentList\(updatedSession\.current_intents\)\}`\);/);
  assert.doesNotMatch(pageSource, /updatedSession\.current_intent(?!s)/);
  assert.ok(pageSource.indexOf("setOptimisticHistoryMessage({") < pageSource.indexOf("sendHistoryMessage(activeSession.session_id, message)"));
  assert.ok(pageSource.indexOf("setPendingPatientMessage({") < pageSource.indexOf("sendHistoryMessage(activeSession.session_id, message)"));
});

test("home inquiry submit keeps repeated identical turns as separate dialogue messages", () => {
  assert.match(pageSource, /readonly apiMessageIndex\?: number;/);
  assert.match(pageSource, /const clientChatMessageSequenceRef = useRef\(0\);/);
  assert.match(pageSource, /function createClientChatMessageId\(prefix: string\): string/);
  assert.match(pageSource, /optimisticQuestionId = createClientChatMessageId\("optimistic-student"\);/);
  assert.match(pageSource, /pendingPatientReplyId = createClientChatMessageId\("pending-patient"\);/);
  assert.doesNotMatch(pageSource, /const requestTimestamp = Date\.now\(\);/);
  assert.doesNotMatch(pageSource, /!hasMessageWithSpeakerAndText\(nextMessages, optimisticHistoryMessage\.speaker, optimisticHistoryMessage\.text\)/);
  assert.doesNotMatch(pageSource, /message\.content === pendingPatientMessage\.finalText/);
  assert.match(pageSource, /message\.apiMessageIndex === pendingPatientMessage\.apiMessageIndex/);
});

test("home secondary menus close from outside clicks and after action selection", () => {
  assert.match(pageSource, /const osceDockContainerRef = useRef<HTMLDivElement \| null>\(null\);/);
  assert.match(pageSource, /const procedureActionContainerRef = useRef<HTMLDivElement \| null>\(null\);/);
  assert.match(pageSource, /document\.addEventListener\("pointerdown", closeSecondaryMenusOnOutsidePointerDown\);/);
  assert.match(pageSource, /document\.removeEventListener\("pointerdown", closeSecondaryMenusOnOutsidePointerDown\);/);
  assert.match(pageSource, /if \(isOsceDockOpen && osceDockContainerRef\.current && !osceDockContainerRef\.current\.contains\(target\)\) \{[\s\S]*?closeOsceDock\(\);/);
  assert.match(pageSource, /if \(osceDockMenuGroup && osceDockContainerRef\.current && !osceDockContainerRef\.current\.contains\(target\)\)/);
  assert.match(pageSource, /if \(openProcedureActionGroup && procedureActionContainerRef\.current && !procedureActionContainerRef\.current\.contains\(target\)\)/);
  assert.match(pageSource, /onClick=\{\(\) => \{[\s\S]*?closeOsceDock\(\);[\s\S]*?setIsApiConfigHelpOpen\(true\);[\s\S]*?\}\}/);
  assert.match(pageSource, /href="\/safety" onClick=\{closeOsceDock\}/);
  assert.match(pageSource, /href="\/sources" onClick=\{closeOsceDock\}/);
  assert.match(pageSource, /href="\/cases" onClick=\{closeOsceDock\}/);
  assert.match(pageSource, /onClick=\{\(\) => \{[\s\S]*?closeOsceDock\(\);[\s\S]*?void handleHintRequest\(\);[\s\S]*?\}\}/);
  assert.match(pageSource, /onClick=\{\(\) => \{[\s\S]*?openProcedureResult\(getProcedureResultById\(`exam:\$\{examOption\.exam_code\}`\)\);[\s\S]*?setOpenProcedureActionGroup\(null\);[\s\S]*?\}\}/);
});


test("home current case card can show student-visible patient profile modal", () => {
  assert.match(pageSource, /type StudentVisiblePatientProfile = Readonly<\{/);
  assert.match(pageSource, /patient_profile: StudentVisiblePatientProfile;/);
  assert.match(pageSource, /const \[isPatientProfileOpen, setIsPatientProfileOpen\] = useState\(false\);/);
  const leftAsideIndex = pageSource.indexOf('<aside className="hidden w-72 shrink-0 border-r border-border bg-background p-4 shadow-inner-right lg:flex lg:flex-col">');
  const leftAsideEndIndex = pageSource.indexOf("</aside>", leftAsideIndex);
  const leftAsideSource = pageSource.slice(leftAsideIndex, leftAsideEndIndex);
  const quickActionRowIndex = pageSource.indexOf('className="pointer-events-auto relative z-10 mx-auto mb-2 flex max-w-3xl flex-wrap items-center gap-2"');
  const inputComposerIndex = pageSource.indexOf('className="pointer-events-auto relative z-10 mx-auto max-w-3xl rounded-2xl border border-border bg-background px-3 py-2 shadow-[0_10px_30px_rgba(20,20,19,0.12)]"');
  const quickActionRowSource = pageSource.slice(quickActionRowIndex, inputComposerIndex);
  assert.doesNotMatch(leftAsideSource, />\s*患者信息\s*<\/button>/);
  assert.match(quickActionRowSource, /onClick=\{\(\) => setIsPatientProfileOpen\(true\)\}/);
  assert.match(quickActionRowSource, />\s*患者信息\s*<\/button>/);
  assert.match(pageSource, /aria-label="关闭患者信息弹窗"/);
  assert.doesNotMatch(pageSource, /以上为 OSCE 教学模拟开局信息，不包含隐藏病史、查体、检查或标准诊断。/);
});


test("home floating dialogs close from backdrop clicks while preserving inner clicks", () => {
  assert.match(pageSource, /<div className="fixed inset-0 z-50 flex items-center justify-center bg-black\/30 p-4" onClick=\{closeProcedureResultModal\}>[\s\S]*?<div className="max-h-\[82vh\] w-full max-w-2xl overflow-y-auto rounded-2xl border border-border bg-background p-5 shadow-xl student-chat-scrollbar" onClick=\{\(event\) => event\.stopPropagation\(\)\}>/);
  assert.match(pageSource, /<div className="fixed inset-0 z-50 flex items-center justify-center bg-black\/30 p-4" onClick=\{\(\) => setIsPatientProfileOpen\(false\)\}>[\s\S]*?<div className="w-full max-w-sm rounded-2xl border border-border bg-background p-5 shadow-xl" onClick=\{\(event\) => event\.stopPropagation\(\)\}>/);
  assert.match(pageSource, /<div className="fixed inset-0 z-50 flex items-center justify-center bg-background\/70 p-4 backdrop-blur-md" onClick=\{\(\) => setIsApiConfigHelpOpen\(false\)\}>[\s\S]*?<div className="w-full max-w-lg rounded-2xl border border-border bg-white p-5 shadow-xl" onClick=\{\(event\) => event\.stopPropagation\(\)\}>/);
});


test("home workspace renders the opening task card without preloading hidden teaching guidance", () => {
  assert.match(pageSource, /type OpeningTaskCard = Readonly<\{/);
  assert.match(pageSource, /opening_task_card: OpeningTaskCard;/);
  assert.doesNotMatch(pageSource, /type CaseTeachingFocus =/);
  assert.doesNotMatch(pageSource, /teaching_focus:/);
  assert.doesNotMatch(pageSource, /type DerivedTeachingFocusPattern =/);
  assert.doesNotMatch(pageSource, /dynamic_teaching_focus:/);
  assert.doesNotMatch(pageSource, /const preparedTeachingFocus = session\?\.teaching_focus \?\? selectedCase\?\.teachingFocus \?\? null;/);
  assert.doesNotMatch(pageSource, /const preparedDynamicTeachingFocus = session\?\.dynamic_teaching_focus \?\? null;/);
  assert.doesNotMatch(pageSource, /<CollapsiblePanel[\s\S]*title="教学重点与问诊提示"[\s\S]*description="展开查看训练重点、误区和推荐问诊。"/);
  assert.doesNotMatch(pageSource, /preparedDynamicTeachingFocus\.patterns\.map/);
  assert.doesNotMatch(pageSource, /pattern\.why_now/);
  assert.doesNotMatch(pageSource, /<Panel title="当前训练重点" description="由病例结构、Rubric 和当前会话进度动态派生。">/);
  assert.doesNotMatch(pageSource, /<Panel title="训练重点" description="展示不会泄露标准答案的病例学习目标与常见误区。">/);
  assert.doesNotMatch(pageSource, /preparedTeachingFocus\.learning_objectives\.map/);
  assert.doesNotMatch(pageSource, /preparedTeachingFocus\.common_error_patterns\.map/);
  assert.doesNotMatch(pageSource, /preparedTeachingFocus\.recommended_training_path\.map/);
  assert.doesNotMatch(pageSource, /type InquiryGuidance =/);
  assert.doesNotMatch(pageSource, /inquiry_guidance:/);
  assert.match(pageSource, /function OpeningTaskCardMessage\(/);
  assert.match(pageSource, /<OpeningTaskCardMessage openingTaskCard=\{preparedOpeningTaskCard\} \/>[\s\S]*\{chatMessages\.map/);
  const openingTaskCardFunctionSource = pageSource.slice(
    pageSource.indexOf("function OpeningTaskCardMessage"),
    pageSource.indexOf("function HomeContent"),
  );
  assert.match(pageSource, /className="mx-auto w-full max-w-lg rounded-2xl border border-brand\/30 bg-\[#FFF8E8\] p-4"/);
  assert.doesNotMatch(pageSource, /max-w-2xl rounded-2xl border border-brand\/30 bg-\[#FFF8E8\]/);
  assert.doesNotMatch(openingTaskCardFunctionSource, /shadow-/);
  assert.match(pageSource, /className="mt-3 flex flex-wrap gap-2 text-xs leading-5"/);
  assert.match(pageSource, /openingTaskCard\.role/);
  assert.match(pageSource, /openingTaskCard\.scenario/);
  assert.match(pageSource, /openingTaskCard\.tasks\.map/);
  assert.doesNotMatch(pageSource, /<Panel title="开局任务卡"/);
  assert.doesNotMatch(pageSource, /<Panel title="问诊引导" description="优先完成不会泄露诊断的核心病史采集。">/);
  assert.doesNotMatch(pageSource, /session\?\.inquiry_guidance\.priority/);
  assert.doesNotMatch(pageSource, /session\.inquiry_guidance\.suggested_questions\.map/);
  assert.doesNotMatch(pageSource, /onClick=\{\(\) => setInputValue\(question\)\}/);
  assert.doesNotMatch(pageSource, /session\.inquiry_guidance\.categories\.map/);
});

test("home workspace centers compact coach hint cards inside the dialogue stream", () => {
  assert.match(pageSource, /const messageRowClass = isStudent \? "justify-end" : isCoach \? "justify-center" : "justify-start";/);
  assert.match(pageSource, /const messageBubbleClass = isStudent[\s\S]*?isCoach[\s\S]*?w-full max-w-lg[\s\S]*?border-\[#D8C3AF\]\/70[\s\S]*?bg-\[#F8F3EA\][\s\S]*?text-foreground/);
  assert.match(pageSource, /className=\{`flex \$\{messageRowClass\}`\}/);
  assert.match(pageSource, /className=\{messageBubbleClass\}/);
  assert.doesNotMatch(pageSource, /isCoach\s*\?\s*"border-\[#B5812A\]\/30 bg-\[#FFF8E8\] text-foreground"/);
  assert.doesNotMatch(pageSource, /isCoach[\s\S]{0,160}bg-\[#FFF8E8\]/);
});

test("home workspace consumes the versioned student-safe session projection", () => {
  assert.match(pageSource, /type TrainingProgress = Readonly<\{/);
  assert.match(pageSource, /training_progress: TrainingProgress;/);
  assert.match(pageSource, /type StudentRevealedItem = Readonly<\{/);
  assert.match(pageSource, /id: string;/);
  assert.match(pageSource, /label: string;/);
  assert.match(pageSource, /revealed_items: StudentRevealedItems;/);
  assert.match(pageSource, /payload_schema_version: "student_session\.v2";/);
  assert.match(pageSource, /collected_procedure_results: CollectedProcedureResults;/);
  assert.doesNotMatch(pageSource, /session\?\.training_progress\.next_focus \?\? workflowSuggestion/);
  assert.doesNotMatch(pageSource, /function formatProgressCount\(covered: number, total: number\): string/);
  assert.doesNotMatch(pageSource, /function CoverageMap\(|function CoverageMapSection\(/);
  assert.doesNotMatch(pageSource, /isCoverageMapOpen|canViewAdminCoverageMap|canOpenAdminCoverageMap/);
  assert.doesNotMatch(pageSource, /<Panel title="训练进度与素材覆盖"/);
  assert.doesNotMatch(pageSource, />问诊线索<\/p>/);
  assert.doesNotMatch(pageSource, />推理证据<\/p>/);
  assert.doesNotMatch(pageSource, /\{session\.training_progress\.next_focus\}/);
  assert.doesNotMatch(pageSource, /rounded-lg border border-brand\/20 bg-brand\/5 p-3 text-xs leading-5 text-brand/);
  assert.doesNotMatch(pageSource, /管理员图谱|查看素材覆盖图谱|coverage_map/);
  assert.doesNotMatch(pageSource, /待问诊素材：/);
  assert.doesNotMatch(pageSource, /待做必查体：/);
  assert.doesNotMatch(pageSource, /待做必检查：/);
  assert.doesNotMatch(pageSource, /待覆盖推理证据：/);
  assert.doesNotMatch(pageSource, /canonical_answer/);
});

test("home workspace relies on backend persisted records instead of local training history", () => {
  assert.doesNotMatch(pageSource, /saveTrainingHistoryRecord/);
  assert.doesNotMatch(pageSource, /savedHistorySessionId/);
  assert.doesNotMatch(pageSource, /toTrainingHistoryMessage/);
  assert.doesNotMatch(pageSource, /toTrainingHistoryProcedureResult/);
  assert.doesNotMatch(pageSource, /保存训练记录/);
  assert.match(pageSource, /href="\/history"[\s\S]*?>\s*训练记录\s*<\/Link>/);
});

test("report page reads current user's backend session snapshot for original dialogue", () => {
  assert.match(reportSource, /type BackendSession = Readonly<\{/);
  assert.match(reportSource, /const \[backendSession, setBackendSession\] = useState<BackendSession \| null>\(null\);/);
  assert.match(reportSource, /requestJson<FeedbackReportPayload>\(`\/api\/me\/sessions\/\$\{nextSessionId\}\/report`/);
  assert.match(reportSource, /requestJson<BackendSession>\(`\/api\/me\/sessions\/\$\{nextSessionId\}`\)/);
  assert.match(reportSource, /fetch\(path, \{/);
  assert.match(reportSource, /credentials: "same-origin"/);
  assert.doesNotMatch(reportSource, /readTrainingHistoryRecords/);
  assert.doesNotMatch(reportSource, /TrainingHistoryRecord/);
  assert.doesNotMatch(reportSource, /`\/api\/sessions\/\$\{nextSessionId\}\/report`/);
  assert.match(reportSource, /function ConversationDetailsSection/);
  assert.match(reportSource, /<details className="scroll-mt-6 rounded-2xl border border-border bg-background p-5 shadow-xs" id="report-conversation">/);
  assert.doesNotMatch(reportSource, /<details[^>]*open[^>]*id="report-conversation"/);
  assert.match(reportSource, /<summary className="flex cursor-pointer list-none items-start justify-between gap-3/);
  assert.match(reportSource, /<h2 className=\{sectionHeadingClassName\}>原始对话记录<\/h2>/);
  assert.match(reportSource, /backendSession\?\.messages\.map/);
  assert.match(reportSource, /backendProcedureResults\.map/);
  assert.match(reportSource, /从后端训练 session 读取/);
  assert.match(reportSource, /默认折叠，可展开查看完整训练过程。/);
  assert.match(reportSource, /后端 session 暂无原始对话记录/);
  assert.doesNotMatch(reportSource, /const workbenchHref = sessionId \? `\/\?session_id=\$\{sessionId\}` : "\/";/);
  assert.match(reportSource, /const workbenchHref = "\/";/);
  assert.match(reportSource, /href=\{workbenchHref\}[\s\S]*?>\s*返回工作台\s*<\/Link>/);
});

test("report page surfaces backend report failures as readable error cards", () => {
  assert.match(reportSource, /const REPORT_REQUEST_TIMEOUT_MS = /);
  assert.match(reportSource, /function formatRequestErrorMessage/);
  assert.match(reportSource, /AbortController/);
  assert.match(reportSource, /模型服务调用失败/);
  assert.match(
    reportSource,
    /requestJson<FeedbackReportPayload>\(`\/api\/me\/sessions\/\$\{nextSessionId\}\/report`, \{[\s\S]*?timeoutMs: REPORT_REQUEST_TIMEOUT_MS/,
  );
  assert.match(reportSource, /setErrorText\(formatRequestErrorMessage\(error\)\);/);
  assert.match(reportSource, /role="alert"/);
  assert.match(reportSource, /报告读取失败/);
});

test("report page uses larger section titles for scanability", () => {
  assert.match(reportSource, /const sectionHeadingClassName = "text-2xl font-semibold tracking-tight";/);
  for (const title of ["本轮结论", "教师复盘", "个人训练 Skill", "AI 评分审计", "推荐训练病例", "维度图表", "原始对话记录", "评分依据与来源"]) {
    assert.match(reportSource, new RegExp(`<h2 className=\\{sectionHeadingClassName\\}>${title}<\\/h2>`));
  }
  assert.doesNotMatch(reportSource, /<h2 className="text-lg font-semibold">/);
  assert.doesNotMatch(reportSource, /<h2 className="text-sm font-semibold">(?:本轮结论|教师复盘|个人训练 Skill|AI 评分审计|推荐训练病例|维度图表|原始对话记录|评分依据与来源)<\/h2>/);
});

test("report score status uses a non-action low score label", () => {
  assert.match(reportSource, /return "需要补强";/);
  assert.doesNotMatch(reportSource, /return "继续训练";/);
});

test("history page lists backend sessions as the only official records", () => {
  assert.match(historySource, /type PersistedSessionSummary = Readonly<\{/);
  assert.match(historySource, /training_difficulty: TrainingDifficultyMode;/);
  assert.match(historySource, /is_completed: boolean;/);
  assert.match(historySource, /can_continue: boolean;/);
  assert.match(historySource, /has_report: boolean;/);
  assert.match(historySource, /completion_status: "in_progress" \| "diagnosis_submitted" \| "report_ready";/);
  assert.match(historySource, /type PersistedSessionListResponse = Readonly<\{/);
  assert.match(historySource, /async function getCurrentUserSessions\(\): Promise<readonly PersistedSessionSummary\[\]>/);
  assert.match(historySource, /async function deleteCurrentUserSession\(sessionId: string\): Promise<void>/);
  assert.match(historySource, /function getTrainingSessionStatusLabel\(session: PersistedSessionSummary\): string \{/);
  assert.match(historySource, /fetch\("\/api\/me\/sessions", \{/);
  assert.match(historySource, /fetch\(`\/api\/me\/sessions\/\$\{sessionId\}`, \{/);
  assert.match(historySource, /method: "DELETE"/);
  assert.match(historySource, /credentials: "same-origin"/);
  assert.match(historySource, /const \[backendSessions, setBackendSessions\] = useState<readonly PersistedSessionSummary\[\]>\(\[\]\);/);
  assert.match(historySource, /const \[deletingSessionId, setDeletingSessionId\] = useState<string \| null>\(null\);/);
  assert.match(historySource, /const \[pendingDeleteSession, setPendingDeleteSession\] = useState<PersistedSessionSummary \| null>\(null\);/);
  assert.match(historySource, /setBackendSessions\(await getCurrentUserSessions\(\)\)/);
  assert.match(historySource, /setBackendSessions\(\(currentSessions\) => currentSessions\.filter\(\(session\) => session\.session_id !== sessionId\)\)/);
  assert.match(historySource, /<p className="text-sm font-semibold text-brand">后端持久记录<\/p>/);
  assert.match(historySource, /backendSessions\.map\(\(session\) =>/);
  assert.doesNotMatch(historySource, /const resumableSession = backendSessions\.find\(\(session\) => session\.can_continue\);/);
  assert.doesNotMatch(historySource, /const workbenchHref = resumableSession \? `\/\?session_id=\$\{resumableSession\.session_id\}` : "\/";/);
  assert.match(historySource, /href="\/"[\s\S]*?>\s*返回工作台\s*<\/Link>/);
  assert.match(historySource, /session\.can_continue \? \(/);
  assert.match(historySource, /href=\{`\/\?session_id=\$\{session\.session_id\}`\}[\s\S]*?>\s*继续训练\s*<\/Link>/);
  assert.match(historySource, /getTrainingDifficultyLabel\(session\.training_difficulty\)/);
  assert.match(historySource, />\s*\{getTrainingDifficultyLabel\(session\.training_difficulty\)\}训练\s*<\/span>/);
  assert.match(historySource, /训练已结束/);
  assert.match(historySource, /href=\{`\/report\?session_id=\$\{session\.session_id\}`\}/);
  assert.doesNotMatch(historySource, /href=\{`\/api\/me\/sessions\/\$\{session\.session_id\}`\}/);
  assert.doesNotMatch(historySource, />\s*查看状态\s*<\/Link>/);
  assert.match(historySource, /onClick=\{\(\) => setPendingDeleteSession\(session\)\}/);
  assert.match(historySource, /\{deletingSessionId === session\.session_id \? "删除中" : "删除记录"\}/);
  assert.match(historySource, /确认删除训练记录/);
  assert.match(historySource, /删除后将无法从训练记录继续训练或打开该记录。/);
  assert.match(historySource, /onClick=\{\(\) => handleDeleteBackendSession\(pendingDeleteSession\.session_id\)\}/);
  assert.match(historySource, /确认删除/);
  assert.doesNotMatch(historySource, /本机历史/);
  assert.doesNotMatch(historySource, /localStorage/);
  assert.doesNotMatch(historySource, /readTrainingHistoryRecords/);
  assert.doesNotMatch(historySource, /clearTrainingHistoryRecords/);
  assert.match(historySource, /import \{ deleteTrainingHistoryRecord \} from "\.\.\/training-history";/);
  assert.match(
    historySource,
    /await deleteCurrentUserSession\(sessionId\);\s+deleteTrainingHistoryRecord\(sessionId\);\s+setBackendSessions/,
  );
});

test("profile recent sessions do not offer continue actions for completed sessions", () => {
  assert.match(profileSource, /is_completed: boolean;/);
  assert.match(profileSource, /can_continue: boolean;/);
  assert.match(profileSource, /has_report: boolean;/);
  assert.match(profileSource, /session\.can_continue \? \(/);
  assert.match(profileSource, /href=\{`\/\?session_id=\$\{session\.session_id\}`\}[\s\S]*?>\s*继续训练\s*<\/Link>/);
  assert.match(profileSource, /训练已结束/);
  assert.match(profileSource, /session\.is_completed \|\| session\.has_report/);
});

test("cases page starts selected cases in a prepared workspace without exposing static teaching focus cards", () => {
  assert.match(casesSource, /type CaseContentStats = Readonly<\{/);
  assert.match(casesSource, /content_stats: CaseContentStats;/);
  assert.match(casesSource, /type TrainingDifficultyMode = "beginner" \| "intermediate" \| "advanced";/);
  assert.match(casesSource, /const TRAINING_DIFFICULTY_OPTIONS/);
  assert.match(casesSource, /label: "初级"/);
  assert.match(casesSource, /label: "中级"/);
  assert.match(casesSource, /label: "高级"/);
  assert.match(casesSource, /直接点选病例提供的核心查体与检查/);
  assert.match(casesSource, /从完整目录里勾选查体或辅助检查/);
  assert.match(casesSource, /自由输入想申请的查体或检查/);
  assert.match(casesSource, /const RECOMMENDED_CASE_ID = "appendicitis_001";/);
  assert.match(casesSource, /function getCaseTrainingItemTotal\(caseSummary: CaseSummary\): number/);
  assert.match(casesSource, /caseSummary\.content_stats\.total_training_items/);
  assert.match(casesSource, /function sortCasesByTrainingContent\(nextCases: readonly CaseSummary\[\]\): readonly CaseSummary\[\]/);
  assert.match(casesSource, /getCaseTrainingItemTotal\(rightCase\) - getCaseTrainingItemTotal\(leftCase\)/);
  assert.match(casesSource, /sortCasesByTrainingContent\(nextCases\)/);
  assert.match(casesSource, /caseSummary\.content_stats\.history_clue_count\}\s*条线索/);
  assert.match(casesSource, /caseSummary\.content_stats\.physical_exam_count\}\s*项查体/);
  assert.match(casesSource, /caseSummary\.content_stats\.auxiliary_test_count\}\s*项检查/);
  assert.match(casesSource, /caseSummary\.case_id === RECOMMENDED_CASE_ID/);
  assert.match(casesSource, />\s*推荐\s*</);
  assert.doesNotMatch(casesSource, />\s*训练病例库\s*</);
  assert.doesNotMatch(casesSource, /当前开放 \$\{cases\.length\} 个结构化病例/);
  assert.doesNotMatch(casesSource, />\s*\/api\/cases\s*</);
  assert.doesNotMatch(casesSource, /type CaseTeachingFocus =/);
  assert.doesNotMatch(casesSource, /teaching_focus:/);
  assert.doesNotMatch(casesSource, /caseSummary\.teaching_focus\.learning_objectives\.map/);
  assert.doesNotMatch(casesSource, /caseSummary\.teaching_focus\.common_error_patterns\.map/);
  assert.doesNotMatch(casesSource, />\s*教学重点\s*<\/p>/);
  assert.doesNotMatch(casesSource, />\s*常见训练误区\s*<\/p>/);
  assert.match(casesSource, /const \[selectedTrainingDifficultyByCaseId, setSelectedTrainingDifficultyByCaseId\] = useState<Record<string, TrainingDifficultyMode>>\(\{\}\);/);
  assert.match(casesSource, /const selectedTrainingDifficulty = selectedTrainingDifficultyByCaseId\[caseSummary\.case_id\] \?\? "beginner";/);
  assert.match(casesSource, /const selectedTrainingDifficultyOption = TRAINING_DIFFICULTY_OPTIONS\.find\(\(difficultyOption\) => difficultyOption\.mode === selectedTrainingDifficulty\) \?\? TRAINING_DIFFICULTY_OPTIONS\[0\];/);
  assert.match(casesSource, /TRAINING_DIFFICULTY_OPTIONS\.map\(\(difficultyOption\) =>/);
  assert.match(casesSource, /setSelectedTrainingDifficultyByCaseId\(\(currentSelection\) => \(\{ \.\.\.currentSelection, \[caseSummary\.case_id\]: difficultyOption\.mode \}\)\)/);
  assert.match(casesSource, /aria-pressed=\{isSelectedDifficulty\}/);
  assert.match(casesSource, /className="inline-flex w-fit flex-wrap gap-1 rounded-full border border-border bg-muted\/60 p-1"/);
  assert.match(casesSource, /bg-foreground text-background shadow-\[0_8px_18px_rgba\(20,20,19,0\.18\)\]/);
  assert.doesNotMatch(casesSource, /grid grid-cols-3 gap-1 rounded-full/);
  assert.match(casesSource, /\{selectedTrainingDifficultyOption\.description\}/);
  assert.match(casesSource, /difficulty=\$\{selectedTrainingDifficulty\}/);
  assert.match(casesSource, /aria-label=\{`以\$\{selectedTrainingDifficultyOption\.label\}模式进入\$\{caseSummary\.case_title\}`\}/);
  assert.doesNotMatch(casesSource, /group rounded-2xl border border-border bg-background px-3 py-2\.5/);
  assert.doesNotMatch(casesSource, /选择\{difficultyOption\.label\}并进入工作台/);
  assert.doesNotMatch(casesSource, /选择(初级|中级|高级)并进入工作台/);
  assert.doesNotMatch(casesSource, />\s*选择并进入工作台\s*<\/Link>/);
  assert.doesNotMatch(casesSource, /创建新的本地 session/);
});

test("cases page does not expose raw case details to student users", () => {
  assert.doesNotMatch(casesSource, /\/api\/cases\/\$\{encodeURIComponent\(caseId\)\}\/raw/);
  assert.doesNotMatch(casesSource, /getCaseRaw/);
  assert.doesNotMatch(casesSource, /CaseRawPayload/);
  assert.doesNotMatch(casesSource, /CaseRawDialog/);
  assert.doesNotMatch(casesSource, /查看原始数据/);
  assert.doesNotMatch(casesSource, /读取病例原始数据失败/);
});

test("home page renders login/register dialog on the existing workspace", () => {
  assert.ok(existsSync(authClientUrl), "home auth client should exist");
  assert.match(authClientSource, /export type AuthUser = Readonly<\{/);
  assert.match(authClientSource, /is_admin: boolean;/);
  assert.match(authClientSource, /export async function getCurrentUser\(\): Promise<AuthUser \| null>/);
  assert.match(authClientSource, /export async function loginUser\(email: string, password: string\): Promise<AuthUser>/);
  assert.match(authClientSource, /export async function registerUser\(email: string, password: string, displayName: string\): Promise<AuthUser>/);
  assert.match(authClientSource, /export async function logoutUser\(\): Promise<void>/);
  assert.match(pageSource, /import \{ getCurrentUser, loginUser, logoutUser \} from "\.\/auth-client";/);
  assert.match(pageSource, /import type \{ AuthUser \} from "\.\/auth-client";/);
  assert.doesNotMatch(pageSource, /const DEFAULT_AUTH_EMAIL = "student@osce\.test";/);
  assert.doesNotMatch(pageSource, /const DEFAULT_AUTH_PASSWORD = "student";/);
  assert.match(pageSource, /const \[authUser, setAuthUser\] = useState<AuthUser \| null>\(null\);/);
  assert.match(pageSource, /const \[isAuthDialogOpen, setIsAuthDialogOpen\] = useState\(false\);/);
  assert.match(pageSource, /const \[authEmail, setAuthEmail\] = useState\(""\);/);
  assert.match(pageSource, /const \[authPassword, setAuthPassword\] = useState\(""\);/);
  assert.match(pageSource, /NEXT_PUBLIC_CLINICAL_OSCE_AUTO_LOGIN_EMAIL/);
  assert.match(pageSource, /NEXT_PUBLIC_CLINICAL_OSCE_AUTO_LOGIN_PASSWORD/);
  assert.match(pageSource, /DEPLOYMENT_MODE === "local-dev"/);
  assert.match(pageSource, /loginUser\(LOCAL_AUTO_LOGIN_EMAIL, LOCAL_AUTO_LOGIN_PASSWORD\)/);
  assert.match(pageSource, /setAuthEmail\(""\);/);
  assert.match(pageSource, /setAuthPassword\(""\);/);
  assert.match(pageSource, /placeholder="输入登录邮箱"/);
  assert.match(pageSource, /<div className=\{isAuthDialogOpen \? "h-full pointer-events-none blur-sm" : "h-full"\}>/);
  assert.match(pageSource, /\{!isCheckingAuth && isAuthDialogOpen \? \(/);
  assert.match(pageSource, /backdrop-blur/);
  assert.doesNotMatch(pageSource, /<div className="fixed inset-0 z-\[60\][^"]*" onClick=\{\(\) => setIsAuthDialogOpen\(false\)\}>/);
  assert.match(pageSource, /aria-label="关闭登录弹窗"/);
  assert.match(pageSource, /onClick=\{\(\) => setIsAuthDialogOpen\(false\)\}[\s\S]*?>[\s\S]*关闭/);
  assert.doesNotMatch(pageSource, />\s*登录 \/ 注册\s*</);
  assert.doesNotMatch(pageSource, /登录后训练记录、报告和后续会话管理会逐步绑定到当前账号。/);
  assert.doesNotMatch(pageSource, /<div className="mt-5 grid grid-cols-1 gap-2 rounded-xl bg-muted p-1">/);
  assert.match(pageSource, /id="auth-email-input"/);
  assert.match(pageSource, /id="auth-password-input"/);
  assert.match(pageSource, /<form autoComplete="off" className="mt-6 space-y-4" onSubmit=\{handleAuthSubmit\}>/);
  assert.match(pageSource, /autoComplete="off"[\s\S]*?id="auth-email-input"/);
  assert.match(pageSource, /autoComplete="new-password"[\s\S]*?id="auth-password-input"/);
  assert.doesNotMatch(pageSource, /id="auth-display-name-input"/);
  assert.match(pageSource, /placeholder="输入登录邮箱"/);
  assert.match(pageSource, /placeholder="请输入密码"/);
  assert.doesNotMatch(pageSource, /placeholder="student 或 admin"/);
  assert.doesNotMatch(pageSource, /学生：student@osce\.test \/ student；管理员：admin@osce\.test \/ admin/);
  assert.match(pageSource, />\{isSubmittingAuth \? "处理中" : "登录"\}<\/button>/);
  assert.match(pageSource, />\s*退出登录\s*</);
});

test("home login dialog is fixed to the two demo accounts and hides account creation", () => {
  assert.match(pageSource, /const isAccountRegistrationEnabled = false;/);
  assert.doesNotMatch(pageSource, /authMode === "register"/);
  assert.doesNotMatch(pageSource, />\s*注册\s*<\/button>/);
  assert.match(pageSource, /<h2 className="mt-2 text-xl font-semibold">登录<\/h2>/);
  assert.match(pageSource, /const nextUser = await loginUser\(email, authPassword\);/);
  assert.doesNotMatch(pageSource, /registerUser\(email, authPassword, authDisplayName\.trim\(\)\)/);
});
