import { strict as assert } from "node:assert";
import { existsSync, readFileSync } from "node:fs";
import { test } from "node:test";

const authClientUrl = new URL("./src/app/auth-client.ts", import.meta.url);
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
const webDockerfileSource = readFileSync(new URL("./Dockerfile", import.meta.url), "utf8");
const webReadmeSource = readFileSync(new URL("./README.md", import.meta.url), "utf8");

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

test("home page does not render large safety and source panels", () => {
  assert.doesNotMatch(pageSource, /<Panel title="安全声明"/);
  assert.doesNotMatch(pageSource, /<Panel title="数据来源"/);
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
  assert.match(globalsSource, /--font-ui: Inter, "Noto Sans SC", "Microsoft YaHei", Arial, sans-serif;/);
  assert.match(globalsSource, /--font-serif: "Noto Serif SC", "Source Han Serif SC", "Songti SC", Georgia, serif;/);
  assert.match(globalsSource, /--font-mono: "JetBrains Mono", "Cascadia Code", Consolas, monospace;/);
  assert.match(globalsSource, /--color-brand: var\(--brand\);/);
  assert.match(globalsSource, /--color-brand-hover: var\(--brand-hover\);/);
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
    "登录 / 注册",
    "关闭菜单",
    "退出登录",
    "关闭",
    "查体项目",
    "辅助检查",
    "保存配置",
    "测试连通性",
  ]);
  assertInteractiveLabelsDoNotWrap("history page", historySource, ["返回工作台", "继续训练", "删除记录"]);
  assertInteractiveLabelsDoNotWrap("cases page", casesSource, ["返回工作台", "选择并进入工作台"]);
  assertInteractiveLabelsDoNotWrap("report page", reportSource, ["返回工作台"]);
  assertInteractiveLabelsDoNotWrap("profile page", profileSource, ["返回工作台", "继续训练"]);
  assertInteractiveLabelsDoNotWrap("safety page", safetySource, ["返回工作台"]);
  assertInteractiveLabelsDoNotWrap("sources page", sourcesSource, ["返回工作台"]);
});

test("home page replaces the Next dev ball with a polished OSCE floating dock", () => {
  assert.match(pageSource, /type OsceDockMenuGroup = "training" \| "system";/);
  assert.match(pageSource, /const ADMIN_MODEL_CONFIG_URL = `\$\{ADMIN_APP_URL\}#model-config`;/);
  assert.match(pageSource, /const \[isOsceDockOpen, setIsOsceDockOpen\] = useState\(false\);/);
  assert.match(pageSource, /const \[osceDockMenuGroup, setOsceDockMenuGroup\] = useState<OsceDockMenuGroup \| null>\(null\);/);
  assert.match(pageSource, /const \[isApiConfigHelpOpen, setIsApiConfigHelpOpen\] = useState\(false\);/);
  assert.match(pageSource, /const osceDockSubmenuAlignmentClass = osceDockPosition\.side === "right" \? "right-full mr-2" : "left-full ml-2";/);
  assert.match(pageSource, /aria-label="打开 OSCE 快捷入口"/);
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
  assert.match(pageSource, /absolute right-2 top-2 size-2 rounded-full bg-\[#86B993\]/);
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
  assert.match(pageSource, /\{isApiConfigHelpOpen && isStudentRuntimeApiConfigEnabled \? \(/);
  assert.match(pageSource, /aria-label="关闭 API 配置说明"/);
  assert.match(pageSource, />\s*API 配置\s*</);
  assert.match(pageSource, />\s*服务端\s*</);
  assert.match(pageSource, /label: "自定义后端"/);
  assert.match(pageSource, /label: "Gemini Developer API"/);
  assert.match(pageSource, /label: "Vertex Gemini ADC"/);
  assert.match(pageSource, /label: "Vertex Gemini API Key"/);
  assert.match(pageSource, /label: "OpenAI 兼容"/);
  assert.match(pageSource, /label: "Anthropic"/);
  assert.match(pageSource, /<span>\{providerOption\.label\}<\/span>/);
  assert.match(pageSource, /runtimeApiConfig\?\.active && runtimeApiConfig\.provider === providerOption\.id/);
  assert.match(pageSource, />\s*当前\s*<\/span>/);
  assert.match(pageSource, /当前渠道：\{formatRuntimeApiConfigSummary\(runtimeApiConfig\)\}/);
  assert.match(pageSource, /api_key_saved\?: boolean;/);
  assert.match(pageSource, /setStudentApiConfig\(createStudentApiConfigFromRuntime\(runtimeConfig\)\)/);
  assert.match(pageSource, /密钥已保存，留空会沿用当前账号的已保存密钥。/);
  assert.match(pageSource, /runtimeConfig\.message \?\? "未启用，使用本地确定性回退"/);
  assert.match(pageSource, /grid grid-cols-1 gap-2 sm:grid-cols-2/);
  assert.doesNotMatch(pageSource, /选择服务端并测试连通性；OpenAI 兼容、Anthropic、Vertex Gemini ADC 或 Vertex Gemini API Key 配置会同步应用到本次后端运行时/);
  assert.match(pageSource, /id="student-api-key-input"/);
  assert.match(pageSource, /disabled=\{studentApiConfig\.provider === "vertex_gemini_adc"\}/);
  assert.match(pageSource, /studentApiConfig\.provider !== "vertex_gemini_api_key"/);
  assert.match(pageSource, /id="student-api-model-input"/);
  assert.match(pageSource, /id="student-api-base-url-input"/);
  assert.match(pageSource, /id="student-api-proxy-url-input"/);
  assert.match(pageSource, /onClick=\{handleSaveStudentApiConfig\}/);
  assert.match(pageSource, /onClick=\{\(\) => void handleTestStudentApiConfig\(\)\}/);
  assert.match(pageSource, />\s*保存配置\s*<\/button>/);
  assert.match(pageSource, />\{isTestingStudentApiConfig \? "测试中" : "测试连通性"\}<\/button>/);
  assert.doesNotMatch(pageSource, />\s*打开管理端配置\s*<\/a>/);
  assert.match(pageSource, /setIsApiConfigHelpOpen\(false\)/);
  assert.match(pageSource, /OpenAI 兼容、Anthropic、Vertex Gemini ADC 或 Vertex Gemini API Key 配置按当前登录账号保存在后端/);
});

test("student README documents blank diagnosis drafts and all runtime model providers", () => {
  assert.doesNotMatch(webReadmeSource, /初始化默认诊断与推理依据/);
  assert.match(webReadmeSource, /诊断提交表单保持空白结构化草稿/);
  assert.match(webReadmeSource, /后端不得下发标准诊断作为默认值/);
  assert.match(webReadmeSource, /Vertex Gemini API Key/);
  assert.match(webReadmeSource, /运行时模型配置按当前登录账号持久化/);
  assert.doesNotMatch(webReadmeSource, /学生端配置保存到浏览器 `localStorage`/);
});

test("home production deployment hides student runtime API config entry", () => {
  assert.match(pageSource, /const DEPLOYMENT_MODE = process\.env\.NEXT_PUBLIC_CLINICAL_OSCE_DEPLOYMENT_MODE \?\? "local-dev";/);
  assert.match(pageSource, /const PRODUCTION_DEPLOYMENT_MODES = new Set\(\["single-node-prod", "vertex-prod"\]\);/);
  assert.match(pageSource, /const isStudentRuntimeApiConfigEnabled = !PRODUCTION_DEPLOYMENT_MODES\.has\(DEPLOYMENT_MODE\);/);
  assert.match(pageSource, /\{isStudentRuntimeApiConfigEnabled \? \([\s\S]*?>\s*API 配置\s*<\/button>[\s\S]*?\) : null\}/);
  assert.match(pageSource, /\{isApiConfigHelpOpen && isStudentRuntimeApiConfigEnabled \? \(/);
  assert.match(webDockerfileSource, /ARG NEXT_PUBLIC_CLINICAL_OSCE_DEPLOYMENT_MODE=local-demo/);
  assert.match(webDockerfileSource, /NEXT_PUBLIC_CLINICAL_OSCE_DEPLOYMENT_MODE=\$\{NEXT_PUBLIC_CLINICAL_OSCE_DEPLOYMENT_MODE\}/);
});

test("home page keeps agent pedagogy details behind a collapsible panel", () => {
  assert.match(pageSource, /type TeachingPlan = Readonly<\{/);
  assert.match(pageSource, /type StageCheckpoint = Readonly<\{/);
  assert.match(pageSource, /type HintLadderStep = Readonly<\{/);
  assert.match(pageSource, /type PedagogyState = Readonly<\{/);
  assert.match(pageSource, /type AgentDecisionTraceItem = Readonly<\{/);
  assert.match(pageSource, /type ReflectionSummary = Readonly<\{/);
  assert.match(pageSource, /teaching_plan: TeachingPlan;/);
  assert.match(pageSource, /stage_checkpoint: StageCheckpoint;/);
  assert.match(pageSource, /hint_ladder: readonly HintLadderStep\[];/);
  assert.match(pageSource, /pedagogy_state: PedagogyState;/);
  assert.match(pageSource, /agent_decision_trace: readonly AgentDecisionTraceItem\[];/);
  assert.match(pageSource, /reflection_summary: ReflectionSummary \| null;/);
  assert.match(pageSource, /type RightPanelKey = "focus" \| "agent" \| "evidence" \| "hypotheses" \| "report";/);
  assert.match(pageSource, /agent: false,/);
  assert.match(pageSource, /<CollapsiblePanel[\s\S]*title="智能体教学详情"[\s\S]*description="展开查看教学策略、阶段检查点和决策轨迹。"[\s\S]*isOpen=\{rightPanelOpenStates\.agent\}/);
  assert.doesNotMatch(pageSource, /<Panel title="智能体状态" description="展示教学策略节点的当前目标、下一步动作和安全边界。">/);
  assert.match(pageSource, /session\.pedagogy_state\.active_learning_goal/);
  assert.match(pageSource, /session\.pedagogy_state\.next_best_action/);
  assert.match(pageSource, /session\.pedagogy_state\.coaching_mode/);
  assert.match(pageSource, /session\.pedagogy_state\.safety_mode/);
  assert.match(pageSource, /session\.pedagogy_state\.teaching_plan\.selected_strategy/);
  assert.match(pageSource, /session\.pedagogy_state\.stage_checkpoint\.status/);
  assert.match(pageSource, /session\.pedagogy_state\.hint_ladder\.map/);
  assert.match(pageSource, /trace\.observe\.checkpoint_status/);
  assert.match(pageSource, /trace\.decide\.selected_strategy/);
  assert.match(pageSource, /trace\.act\.hint_ladder_levels/);
  assert.match(pageSource, /trace\.reflect\.safety_mode/);
  assert.match(pageSource, /session\.agent_decision_trace\.slice\(-3\)\.map/);
  assert.match(pageSource, /智能体还未形成可展示的教学状态/);
  assert.match(pageSource, /最近决策轨迹/);
  assert.match(pageSource, /阶段检查点/);
  assert.match(pageSource, /Hint Ladder/);
  assert.match(pageSource, /教学安全边界/);
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
  assert.match(reportSource, /function DefenseEvidenceChainSection/);
  assert.match(reportSource, /<DefenseEvidenceChainSection explanationItems=\{report\.explanation_source_items\} sourceReferenceItems=\{report\.source_reference_items\} \/>/);
  assert.match(reportSource, /评分项 → 证据 → 来源/);
  assert.match(reportSource, /item\.source_references\.filter\(\(reference\) => reference\.startsWith\("rubric:"\)\)/);
  assert.match(reportSource, /item\.source_references\.filter\(\(reference\) => reference\.startsWith\("evidence:"\)\)/);
  assert.match(reportSource, /不参与评分裁判/);
});

test("report page renders evidence graph coverage from backend report", () => {
  assert.match(reportModelSource, /export type EvidenceGraphNodeItem = Readonly<\{/);
  assert.match(reportModelSource, /export type EvidenceGraphEdgeItem = Readonly<\{/);
  assert.match(reportModelSource, /export type EvidenceGraphSummary = Readonly<\{/);
  assert.match(reportModelSource, /evidence_graph_summary\?: EvidenceGraphSummary \| null;/);
  assert.match(reportModelSource, /evidence_graph_summary: report\.evidence_graph_summary \?\? null,/);
  assert.match(reportSource, /function EvidenceGraphSummarySection/);
  assert.match(reportSource, /<EvidenceGraphSummarySection summary=\{report\.evidence_graph_summary\} \/>/);
  assert.match(reportSource, /证据图谱覆盖/);
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
  assert.match(profileSource, /type LearningPathItem = Readonly<\{/);
  assert.match(profileSource, /learning_path: readonly LearningPathItem\[];/);
  assert.match(profileSource, /learningPath: readonly LearningPathItem\[];/);
  assert.match(profileSource, /profile\.learningPath\.map/);
  assert.match(profileSource, /个性化学习路径/);
  assert.match(profileSource, /target_rubric_items/);
  assert.match(profileSource, /source_references/);
  assert.match(profileSource, /Skill 积累/);
  assert.match(profileSource, /type EnabledSkillSummary = Readonly<\{/);
  assert.match(profileSource, /student_visible_summary: string;/);
  assert.match(profileSource, /effect_status: string;/);
  assert.match(profileSource, /enabled_skill_count: number;/);
  assert.match(profileSource, /applied_skill_count: number;/);
  assert.match(profileSource, /enabled_skills: readonly EnabledSkillSummary\[];/);
  assert.match(profileSource, /profile\.skillAccumulation\.enabled_skill_count/);
  assert.match(profileSource, /profile\.skillAccumulation\.applied_skill_count/);
  assert.match(profileSource, /profile\.skillAccumulation\.enabled_skills\.map/);
  assert.match(profileSource, /已启用 Skill/);
  assert.match(profileSource, /应用次数/);
  assert.match(profileSource, /支持次数/);
  assert.match(profileSource, /效果状态/);
  assert.match(profileSource, /暂无已启用 Skill/);
});

test("profile page hides raw enabled skill strategy text from students", () => {
  assert.doesNotMatch(profileSource, /触发项：\{skill\.trigger_item_id\}/);
  assert.doesNotMatch(profileSource, /\{skill\.suggested_strategy\}/);
  assert.match(profileSource, /\{skill\.student_visible_summary\}/);
  assert.match(profileSource, /已启用教学策略/);
});

test("home workspace exposes OSCE workflow navigation and next-step guidance", () => {
  assert.match(pageSource, /type WorkflowStepDefinition = Readonly<\{/);
  assert.match(pageSource, /const workflowStepDefinitions: readonly WorkflowStepDefinition\[\] = \[/);
  assert.match(pageSource, /label: "进入病例"/);
  assert.match(pageSource, /label: "查看报告"/);
  assert.match(pageSource, /function getWorkflowStepStatus\(stepKey: WorkflowStepDefinition\["key"\], session: OsceSession \| null, feedbackReport: FeedbackReport \| null\): StageStatus/);
  assert.match(pageSource, /function getNextWorkflowSuggestion\(session: OsceSession \| null, feedbackReport: FeedbackReport \| null\): string/);
  assert.match(pageSource, /"请先询问起病、部位、性质、程度和伴随症状。"/);
  assert.match(pageSource, /<Panel title="训练导航" description="当前病例、阶段和下一步。">/);
  assert.match(pageSource, /<p className="text-sm font-semibold text-brand">下一步建议<\/p>/);
});

test("home workspace can resume current user's persisted backend session", () => {
  assert.match(pageSource, /credentials: "same-origin"/);
  assert.match(pageSource, /const requestedSessionId = searchParams\.get\("session_id"\);/);
  assert.match(pageSource, /function getSession\(sessionId: string\): Promise<OsceSession>/);
  assert.match(pageSource, /`\/api\/me\/sessions\/\$\{sessionId\}`/);
  assert.match(pageSource, /if \(isCheckingAuth\) \{/);
  assert.match(pageSource, /if \(!authUser\) \{/);
  assert.match(pageSource, /setStatusText\("请先登录后再开始或恢复训练。"\);/);
  assert.match(pageSource, /if \(!requestedSessionId\) \{[\s\S]*?setStatusText\([\s\S]*?selectedCaseId[\s\S]*?\? isTrainingModelConfigReady[\s\S]*?\? "已选择病例，发送问诊或点击训练操作后开始新会话。"[\s\S]*?: TRAINING_MODEL_CONFIG_REQUIRED_MESSAGE[\s\S]*?: "请选择病例后再开始训练。"[\s\S]*?\);[\s\S]*?return;[\s\S]*?\}/);
  assert.match(pageSource, /const sessionIdToRestore = requestedSessionId;/);
  assert.match(pageSource, /const nextSession = await getSession\(sessionIdToRestore\);/);
  assert.match(pageSource, /setStatusText\("已恢复后端训练会话，可以继续训练。"\);/);
  assert.match(pageSource, /`\/api\/me\/sessions\/\$\{sessionId\}\/report`/);
  assert.match(pageSource, /async function getRequestErrorMessage\(response: Response\): Promise<string>/);
  assert.match(pageSource, /if \(response\.status === 401\) \{/);
  assert.match(pageSource, /return "请先登录后再继续训练。";/);
  assert.match(pageSource, /setIsAuthDialogOpen\(true\);/);
  assert.doesNotMatch(pageSource, /requestedSessionId\s*\? await getSession\(requestedSessionId\)\s*: await createSession\(selectedCaseId\)/);
  assert.doesNotMatch(pageSource, /throw new Error\(detail \|\| `请求失败：\$\{response\.status\}`\);/);
  assert.match(pageSource, /\}, \[authUser, isCheckingAuth, isTrainingModelConfigReady, requestedSessionId, selectedCaseId\]\);/);
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
  assert.match(pageSource, /\{!session && !isCasePreparationPromptDismissed \? \([\s\S]*<CaseSelectionPrompt[\s\S]*selectedCase=\{selectedCase\}[\s\S]*onDismiss=\{\(\) => setIsCasePreparationPromptDismissed\(true\)\}[\s\S]*\/>[\s\S]*\) : null\}/);
  assert.match(pageSource, /href="\/cases"[\s\S]*?>\s*选择病例\s*<\/Link>/);
  assert.match(pageSource, /const preparedOpeningTaskCard = session\?\.opening_task_card \?\? selectedCase\?\.openingTaskCard \?\? null;/);
  assert.match(pageSource, /<OpeningTaskCardMessage openingTaskCard=\{preparedOpeningTaskCard\} \/>/);
  assert.match(pageSource, /let baseMessages: ChatMessage\[\] = \[\];/);
  assert.match(pageSource, /if \(!session\) \{\s*baseMessages = \[\];\s*\}/);
  assert.doesNotMatch(pageSource, /speaker: "patient"[\s\S]{0,240}请先选择一个病例；进入病例后/);
});

test("home workspace creates a new backend session only after a selected-case training action", () => {
  assert.match(pageSource, /const \[isCreating, setIsCreating\] = useState\(false\);/);
  assert.match(pageSource, /const TRAINING_MODEL_CONFIG_REQUIRED_MESSAGE = "请先在 API 配置中应用可用模型，再开始训练。";/);
  assert.match(pageSource, /const isTrainingModelConfigReady = Boolean\(runtimeApiConfig\?\.active\);/);
  assert.match(pageSource, /function promptTrainingModelConfigRequired\(\): void \{[\s\S]*?setStatusText\(TRAINING_MODEL_CONFIG_REQUIRED_MESSAGE\);[\s\S]*?setErrorText\(TRAINING_MODEL_CONFIG_REQUIRED_MESSAGE\);[\s\S]*?setIsApiConfigHelpOpen\(true\);[\s\S]*?\}/);
  assert.match(pageSource, /async function ensureActiveSession\(\): Promise<OsceSession \| null>/);
  assert.match(pageSource, /if \(session\) \{[\s\S]*?return session;[\s\S]*?\}/);
  assert.match(pageSource, /if \(!selectedCaseId\) \{[\s\S]*?setStatusText\("请先选择病例，再开始训练。"\);[\s\S]*?return null;[\s\S]*?\}/);
  assert.match(pageSource, /if \(!isTrainingModelConfigReady\) \{[\s\S]*?promptTrainingModelConfigRequired\(\);[\s\S]*?return null;[\s\S]*?\}/);
  assert.match(pageSource, /const nextSession = await createSession\(selectedCaseId\);/);
  assert.match(pageSource, /const activeSession = await ensureActiveSession\(\);/);
  assert.match(pageSource, /sendHistoryMessage\(activeSession\.session_id, message\)/);
  assert.match(pageSource, /requestPhysicalExam\(activeSession\.session_id, examCode\)/);
  assert.match(pageSource, /requestAuxiliaryTest\(activeSession\.session_id, testCode\)/);
  assert.match(pageSource, /disabled=\{!authUser \|\| !selectedCaseId \|\| !isTrainingModelConfigReady \|\| isCreating \|\| isSending\}/);
  assert.ok(pageSource.indexOf("if (!isTrainingModelConfigReady)") < pageSource.indexOf("setOptimisticHistoryMessage({"));
});


test("home case card points users to the case selection page", () => {
  assert.match(pageSource, /<Panel[\s\S]*title="训练导航"[\s\S]*description="当前病例、阶段和下一步。"/);
  assert.match(pageSource, />当前选择<\/p>/);
  assert.match(pageSource, /\{selectedCase \? \([\s\S]*?\) : \([\s\S]*?尚未选择病例/);
  assert.match(pageSource, /href="\/cases"[\s\S]*?>\s*选择病例\s*<\/Link>/);
  assert.match(pageSource, /className="mx-auto flex w-fit items-center justify-center rounded-md border border-\[#141413\] bg-\[#141413\] px-4 py-2 text-center text-xs font-medium whitespace-nowrap text-white/);
  assert.doesNotMatch(pageSource, /className="block rounded-md border border-brand bg-brand px-3 py-2 text-center text-xs font-medium whitespace-nowrap text-white/);
  assert.doesNotMatch(pageSource, /const \[isCaseSelectorOpen, setIsCaseSelectorOpen\]/);
  assert.doesNotMatch(pageSource, /caseOptionsState\.map\(\(caseOption\) =>/);
  assert.doesNotMatch(pageSource, /<Panel[\s\S]*title="病例信息与选择"/);
  assert.doesNotMatch(pageSource, /<Panel[\s\S]*title="病例选择"/);
});


test("home right sidebar starts with progress and keeps collapsible cards bounded", () => {
  assert.match(pageSource, /type RightPanelKey = "focus" \| "agent" \| "evidence" \| "hypotheses" \| "report";/);
  assert.match(pageSource, /function CollapsiblePanel\(/);
  assert.match(pageSource, /maxContentHeightClass = "max-h-64"/);
  assert.match(pageSource, /overflow-y-scroll pr-1 student-rail-scrollbar/);
  assert.match(pageSource, /const \[rightPanelOpenStates, setRightPanelOpenStates\] = useState<Record<RightPanelKey, boolean>>/);
  assert.match(pageSource, /focus: false,/);
  assert.match(pageSource, /agent: false,/);
  assert.doesNotMatch(pageSource, /procedures: true,/);
  assert.match(pageSource, /report: true,/);
  assert.match(pageSource, /setRightPanelOpenStates\(\(currentStates\) =>/);

  const rightAsideIndex = pageSource.indexOf('<aside className="flex min-h-0 flex-col gap-4 overflow-y-scroll student-rail-scrollbar"');
  const focusPanelIndex = pageSource.indexOf('title="教学重点与问诊提示"', rightAsideIndex);
  const evidencePanelIndex = pageSource.indexOf('title="已收集线索"', rightAsideIndex);
  assert.notEqual(rightAsideIndex, -1);
  assert.notEqual(focusPanelIndex, -1);
  assert.notEqual(evidencePanelIndex, -1);
  assert.ok(focusPanelIndex < evidencePanelIndex);
  assert.doesNotMatch(pageSource, /title="训练进度与素材覆盖"/);
  assert.match(pageSource, />\s*管理员图谱\s*<\/p>/);
  assert.match(pageSource, />\s*查看素材覆盖图谱\s*<\/button>/);

  assert.match(pageSource, /<CollapsiblePanel[\s\S]*title="已收集线索"[\s\S]*maxContentHeightClass="max-h-64"/);
  assert.match(pageSource, /<CollapsiblePanel[\s\S]*title="教学重点与问诊提示"[\s\S]*maxContentHeightClass="max-h-80"/);
  assert.match(pageSource, /<CollapsiblePanel[\s\S]*title="智能体教学详情"[\s\S]*maxContentHeightClass="max-h-96"/);
  assert.doesNotMatch(pageSource, /title="查体与检查申请"/);
  assert.doesNotMatch(pageSource, /toggleRightPanel\("procedures"\)/);
  assert.match(pageSource, /<CollapsiblePanel[\s\S]*title="诊断假设"[\s\S]*maxContentHeightClass="max-h-48"/);
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
  assert.notEqual(nextSuggestionIndex, -1);
  assert.doesNotMatch(leftAsideSource, /title="问诊引导"|title="智能体状态"|title="当前训练重点"|title="训练重点"|title="OSCE 流程导航"/);

  const rightAsideIndex = pageSource.indexOf('<aside className="flex min-h-0 flex-col gap-4 overflow-y-scroll student-rail-scrollbar"');
  const focusPanelIndex = pageSource.indexOf('title="教学重点与问诊提示"', rightAsideIndex);
  const agentPanelIndex = pageSource.indexOf('title="智能体教学详情"', rightAsideIndex);
  const evidencePanelIndex = pageSource.indexOf('title="已收集线索"', rightAsideIndex);
  const hypothesisPanelIndex = pageSource.indexOf('title="诊断假设"', rightAsideIndex);
  assert.notEqual(focusPanelIndex, -1);
  assert.notEqual(agentPanelIndex, -1);
  assert.notEqual(evidencePanelIndex, -1);
  assert.notEqual(hypothesisPanelIndex, -1);
  assert.ok(focusPanelIndex < agentPanelIndex);
  assert.ok(agentPanelIndex < evidencePanelIndex);
  assert.ok(evidencePanelIndex < hypothesisPanelIndex);
});

test("home workspace keeps the composer sticky and final diagnosis collapsed", () => {
  assert.match(pageSource, /<main className="relative h-screen overflow-hidden bg-muted\/40 text-foreground">/);
  assert.match(pageSource, /<div className=\{isAuthDialogOpen \? "h-full pointer-events-none blur-sm" : "h-full"\}>/);
  assert.match(pageSource, /<div className="flex h-full min-h-0">/);
  assert.match(pageSource, /className="flex-1 space-y-4 overflow-y-scroll p-5 pb-40 student-chat-scrollbar"/);
  assert.match(pageSource, /ref=\{chatScrollContainerRef\}/);
  assert.match(pageSource, /const \[isDiagnosisComposerOpen, setIsDiagnosisComposerOpen\] = useState\(false\);/);
  assert.match(pageSource, /className="pointer-events-none absolute inset-x-0 bottom-0 z-20 px-3 pb-4 pt-10"/);
  assert.match(pageSource, /className="pointer-events-auto mx-auto max-w-3xl rounded-full border border-border bg-background px-3 py-2 shadow-\[0_10px_30px_rgba\(20,20,19,0\.12\)\]"/);
  assert.match(pageSource, /className="pointer-events-auto relative mx-auto mb-2 flex max-w-3xl flex-wrap items-center gap-2"/);
  const quickActionRowIndex = pageSource.indexOf('className="pointer-events-auto relative mx-auto mb-2 flex max-w-3xl flex-wrap items-center gap-2"');
  const inputComposerIndex = pageSource.indexOf('className="pointer-events-auto mx-auto max-w-3xl rounded-full border border-border bg-background px-3 py-2 shadow-[0_10px_30px_rgba(20,20,19,0.12)]"');
  assert.notEqual(quickActionRowIndex, -1);
  assert.notEqual(inputComposerIndex, -1);
  assert.ok(quickActionRowIndex < inputComposerIndex);
  assert.doesNotMatch(pageSource, /rounded-xl border border-input bg-muted\/50 p-3/);
  assert.doesNotMatch(pageSource, /sticky bottom-0 z-20 bg-gradient-to-t/);
  assert.doesNotMatch(pageSource, /<p className="mx-auto mt-2 max-w-3xl text-xs leading-5 text-muted-foreground">\{statusText\}<\/p>/);
  assert.match(pageSource, />\{isDiagnosisComposerOpen \? "收起诊断" : "填写诊断"\}<\/button>/);
  assert.match(pageSource, /\{isDiagnosisComposerOpen \? \([\s\S]*id="diagnosis-input"[\s\S]*\) : null\}/);
});

test("home quick actions allow realistic sequence jumps but show teaching reminders", () => {
  assert.match(pageSource, /const shouldShowPhysicalExamSequenceReminder = activeSession\.training_progress\.history\.covered === 0;/);
  assert.match(pageSource, /const shouldShowAuxiliaryTestSequenceReminder = activeSession\.training_progress\.physical_exam\.requested === 0;/);
  assert.match(pageSource, /OSCE 通常建议先完成核心病史采集，再进入查体。/);
  assert.match(pageSource, /现实 OSCE 中通常应先基于病史和查体形成初步判断，再选择辅助检查。/);
  assert.match(pageSource, /disabled=\{!authUser \|\| !selectedCaseId \|\| !isTrainingModelConfigReady \|\| isCreating \|\| isRequestingExam\}/);
  assert.match(pageSource, /disabled=\{!authUser \|\| !selectedCaseId \|\| !isTrainingModelConfigReady \|\| isCreating \|\| isRequestingTest\}/);
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
  assert.match(pageSource, /setSelectedProcedureResult\(getProcedureResultById\(`exam:\$\{examOption\.exam_code\}`\)\)/);
  assert.match(pageSource, /setSelectedProcedureResult\(getProcedureResultById\(`test:\$\{testOption\.test_code\}`\)\)/);
  assert.match(pageSource, /aria-label="关闭查体检查结果"/);
  assert.match(pageSource, /selectedProcedureResult\.result/);
  assert.doesNotMatch(pageSource, /<p className="mt-1 text-xs leading-5 text-muted-foreground">\{item\.result\}<\/p>/);
});

test("home quick actions are available after a case is selected and before a backend session exists", () => {
  assert.match(pageSource, /const physicalExamOptions = session\?\.physical_exam_options \?\? selectedCase\?\.physicalExamOptions \?\? \[\];/);
  assert.match(pageSource, /const auxiliaryTestOptions = session\?\.auxiliary_test_options \?\? selectedCase\?\.auxiliaryTestOptions \?\? \[\];/);
  assert.match(pageSource, /pendingPhysicalExamOptions\.map/);
  assert.match(pageSource, /pendingAuxiliaryTestOptions\.map/);
  assert.doesNotMatch(pageSource, /session\?\.physical_exam_options\.map/);
  assert.doesNotMatch(pageSource, /session\?\.auxiliary_test_options\.map/);
});

test("student auxiliary test buttons expose cost, invasiveness, and diagnostic role metadata", () => {
  assert.match(pageSource, /diagnostic_role: string;/);
  assert.match(pageSource, /rules_out: readonly string\[];/);
  assert.match(pageSource, /getDiagnosticRoleLabel\(testOption\.diagnostic_role\)/);
  assert.match(pageSource, /testOption\.cost_hint/);
  assert.match(pageSource, /testOption\.invasiveness/);
  assert.match(pageSource, /testOption\.rules_out\.length > 0/);
});

test("home diagnosis hypothesis panel can record in-progress hypotheses", () => {
  assert.match(pageSource, /function recordHypothesis\(sessionId: string, hypothesis: string\): Promise<OsceSession>/);
  assert.match(pageSource, /\/api\/sessions\/\$\{sessionId\}\/hypotheses/);
  assert.match(pageSource, /id="hypothesis-input"/);
  assert.match(pageSource, />\{isRecordingHypothesis \? "记录中" : "记录假设"\}<\/button>/);
});


test("home diagnosis submission form collects structured OSCE reasoning fields", () => {
  assert.match(pageSource, /const \[diagnosisValue, setDiagnosisValue\] = useState\(""\);/);
  assert.match(pageSource, /const \[differentialDiagnosisValue, setDifferentialDiagnosisValue\] = useState\(""\);/);
  assert.match(pageSource, /const \[supportingEvidenceValue, setSupportingEvidenceValue\] = useState\(""\);/);
  assert.match(pageSource, /const \[exclusionEvidenceValue, setExclusionEvidenceValue\] = useState\(""\);/);
  assert.match(pageSource, /const \[nextStepValue, setNextStepValue\] = useState\(""\);/);
  assert.doesNotMatch(pageSource, /const DEFAULT_DIAGNOSIS/);
  assert.doesNotMatch(pageSource, /const DEFAULT_REASONING/);
  assert.match(pageSource, /function buildStructuredReasoning\(/);
  assert.match(pageSource, /鉴别诊断：\$\{differentialDiagnosis\}/);
  assert.match(pageSource, /支持依据：\$\{supportingEvidence\}/);
  assert.match(pageSource, /排除依据：\$\{exclusionEvidence\}/);
  assert.match(pageSource, /下一步方向：\$\{nextStep\}/);
  assert.match(pageSource, /id="differential-diagnosis-input"/);
  assert.match(pageSource, /placeholder="至少 2 个合理鉴别诊断"/);
  assert.match(pageSource, /id="supporting-evidence-input"/);
  assert.match(pageSource, /id="exclusion-evidence-input"/);
  assert.match(pageSource, /id="next-step-input"/);
  assert.match(pageSource, /function resizeTextareaToContent\(textarea: HTMLTextAreaElement\): void/);
  assert.match(pageSource, /const DIAGNOSIS_TEXTAREA_MAX_HEIGHT = 160;/);
  assert.match(pageSource, /Math\.min\(textarea\.scrollHeight, DIAGNOSIS_TEXTAREA_MAX_HEIGHT\)/);
  assert.match(pageSource, /resize-y max-h-40 overflow-y-auto/);
  assert.match(pageSource, /onInput=\{\(event\) => resizeTextareaToContent\(event\.currentTarget\)\}/);
  assert.match(pageSource, /!differentialDiagnosisValue\.trim\(\)/);
  assert.match(pageSource, /!supportingEvidenceValue\.trim\(\)/);
  assert.match(pageSource, /!exclusionEvidenceValue\.trim\(\)/);
  assert.match(pageSource, /!nextStepValue\.trim\(\)/);
  assert.doesNotMatch(pageSource, /setDiagnosisValue\(nextSession\.diagnosis_draft\.diagnosis\)/);
  assert.doesNotMatch(pageSource, /setSupportingEvidenceValue\(nextSession\.diagnosis_draft\.reasoning\)/);
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
  assert.match(pageSource, /message\.role === "coach"/);
  assert.match(pageSource, /label: getCoachMessageLabel\(message\.content\)/);
  assert.match(pageSource, /"过程提示"/);
  assert.match(pageSource, /onClick=\{handleHintRequest\}/);
  assert.match(pageSource, />\{isRequestingHint \? "提示生成中" : "请求提示"\}<\/button>/);
});


test("home workspace highlights safety guardrail replies", () => {
  assert.match(pageSource, /function getCoachMessageLabel\(content: string\): "安全边界" \| "答题边界" \| "问诊引导" \| "过程提示"/);
  assert.match(pageSource, /content\.includes\("本系统仅用于 OSCE 教学模拟训练"\)[\s\S]*?return "安全边界";/);
  assert.match(pageSource, /content\.includes\("不能直接告诉你标准答案"\)[\s\S]*?return "答题边界";/);
  assert.match(pageSource, /content\.includes\("病例脚本没有提供这方面信息"\)[\s\S]*?return "问诊引导";/);
  assert.match(pageSource, /`安全边界：\$\{session\?\.safety_flags\.length \?\? 0\} 次`/);
});

test("home workspace auto-scrolls to the newest dialogue and keeps status in the dialogue header", () => {
  assert.match(pageSource, /const chatScrollContainerRef = useRef<HTMLDivElement \| null>\(null\);/);
  assert.match(pageSource, /useEffect\(\(\) => \{[\s\S]*?chatScrollContainer\.scrollTo\(\{[\s\S]*?top: chatScrollContainer\.scrollHeight,[\s\S]*?behavior: "smooth",[\s\S]*?\}\);[\s\S]*?\}, \[chatMessages\.length, optimisticHistoryMessage\?\.text, pendingPatientMessage\?\.text, statusText, errorText\]\);/);
  assert.match(pageSource, /<div className="max-w-sm rounded-lg border border-brand\/20 bg-brand\/5 px-3 py-2 text-xs leading-5 text-brand">[\s\S]*?\{statusText\}[\s\S]*?\{errorText \? <p className="mt-1 text-red-600">\{errorText\}<\/p> : null\}/);
  const dialogueHeaderIndex = pageSource.indexOf('<div className="border-b border-border p-4">');
  const dialogueBodyIndex = pageSource.indexOf('<div className="flex-1 space-y-4 overflow-y-scroll p-5 pb-40 student-chat-scrollbar"', dialogueHeaderIndex);
  assert.notEqual(dialogueHeaderIndex, -1);
  assert.notEqual(dialogueBodyIndex, -1);
  assert.doesNotMatch(pageSource.slice(dialogueHeaderIndex, dialogueBodyIndex), /\{trainingSuggestion\}/);
});

test("home inquiry submit shows optimistic student message and neutral streaming placeholder", () => {
  assert.match(pageSource, /const \[optimisticHistoryMessage, setOptimisticHistoryMessage\] = useState<ChatMessage \| null>\(null\);/);
  assert.match(pageSource, /const \[pendingPatientMessage, setPendingPatientMessage\] = useState<ChatMessage \| null>\(null\);/);
  assert.match(pageSource, /function hasMessageWithSpeakerAndText\([\s\S]*?messages: readonly ChatMessage\[],[\s\S]*?speaker: ChatMessage\["speaker"\],[\s\S]*?text: string,[\s\S]*?\): boolean/);
  assert.match(pageSource, /function getReplyMessageMetadata\(session: OsceSession, replyText: string\): Pick<ChatMessage, "speaker" \| "label">/);
  assert.match(pageSource, /const matchingReplyMessage = \[\.\.\.session\.messages\]\.reverse\(\)\.find/);
  assert.match(pageSource, /matchingReplyMessage\?\.role === "coach"[\s\S]*?speaker: "coach",[\s\S]*?label: getCoachMessageLabel\(replyText\),/);
  assert.match(pageSource, /message\.speaker === pendingPatientMessage\.speaker && message\.text === pendingPatientMessage\.finalText/);
  assert.doesNotMatch(pageSource, /message\.speaker === "patient" && message\.text === pendingPatientMessage\.finalText/);
  assert.match(pageSource, /function PendingThinkingIndicator\(\)/);
  assert.match(pageSource, /aria-label="判断中"/);
  assert.match(pageSource, />判断中<\/span>/);
  assert.doesNotMatch(pageSource, /aria-label="思考中"/);
  assert.match(globalsSource, /@keyframes clinical-osce-thinking-dot/);
  assert.match(globalsSource, /\.clinical-osce-thinking-dot/);
  assert.match(pageSource, /async function animatePendingPatientReply\(messageId: string, replyText: string\): Promise<void>/);
  assert.match(pageSource, /window\.setTimeout\(resolve, PATIENT_REPLY_TYPEWRITER_DELAY_MS\)/);
  assert.match(pageSource, /replyText\.slice\(0, index\)/);
  assert.match(pageSource, /setOptimisticHistoryMessage\(\{[\s\S]*?id: optimisticQuestionId,[\s\S]*?speaker: "student",[\s\S]*?label: "学生",[\s\S]*?text: message,[\s\S]*?\}\);/);
  assert.match(pageSource, /setPendingPatientMessage\(\{[\s\S]*?id: pendingPatientReplyId,[\s\S]*?speaker: "coach",[\s\S]*?label: "判断中",[\s\S]*?text: "判断中",[\s\S]*?\}\);/);
  assert.doesNotMatch(pageSource, /setPendingPatientMessage\(\{[\s\S]*?id: pendingPatientReplyId,[\s\S]*?speaker: "patient",[\s\S]*?label: "标准化病人",[\s\S]*?text: "思考中"/);
  assert.doesNotMatch(pageSource, /text: "思考中\.\.\."/);
  assert.match(pageSource, /message\.isPending && !message\.finalText \? <PendingThinkingIndicator \/> : message\.text/);
  assert.match(pageSource, /setStatusText\("正在处理问诊"\);/);
  assert.match(pageSource, /const replyMessageMetadata = getReplyMessageMetadata\(updatedSession, replyText\);/);
  assert.match(pageSource, /const replyStatusLabel = replyMessageMetadata\.speaker === "coach" \? replyMessageMetadata\.label : "标准化病人回复";/);
  assert.match(pageSource, /\.\.\.replyMessageMetadata,[\s\S]*?finalText: replyText,/);
  assert.match(pageSource, /await animatePendingPatientReply\(pendingPatientReplyId, updatedSession\.reply \?\? ""\);/);
  assert.match(pageSource, /setStatusText\(`已收到\$\{replyStatusLabel\}：\$\{updatedSession\.current_intent \?\? "未识别意图"\}`\);/);
  assert.doesNotMatch(pageSource, /setStatusText\(`已收到标准化病人回复：\$\{updatedSession\.current_intent \?\? "未识别意图"\}`\);/);
  assert.ok(pageSource.indexOf("setOptimisticHistoryMessage({") < pageSource.indexOf("sendHistoryMessage(activeSession.session_id, message)"));
  assert.ok(pageSource.indexOf("setPendingPatientMessage({") < pageSource.indexOf("sendHistoryMessage(activeSession.session_id, message)"));
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
  assert.match(pageSource, /onClick=\{\(\) => \{[\s\S]*?setSelectedProcedureResult\(getProcedureResultById\(`exam:\$\{examOption\.exam_code\}`\)\);[\s\S]*?setOpenProcedureActionGroup\(null\);[\s\S]*?\}\}/);
});


test("home current case card can show student-visible patient profile modal", () => {
  assert.match(pageSource, /type StudentVisiblePatientProfile = Readonly<\{/);
  assert.match(pageSource, /patient_profile: StudentVisiblePatientProfile;/);
  assert.match(pageSource, /const \[isPatientProfileOpen, setIsPatientProfileOpen\] = useState\(false\);/);
  assert.match(pageSource, /onClick=\{\(\) => setIsPatientProfileOpen\(true\)\}/);
  assert.match(pageSource, />\s*患者信息\s*<\/button>/);
  assert.match(pageSource, /aria-label="关闭患者信息弹窗"/);
  assert.match(pageSource, /以上为 OSCE 教学模拟开局信息，不包含隐藏病史、查体、检查或标准诊断。/);
});


test("home workspace renders opening task card and keeps teaching guidance in collapsible details", () => {
  assert.match(pageSource, /type OpeningTaskCard = Readonly<\{/);
  assert.match(pageSource, /opening_task_card: OpeningTaskCard;/);
  assert.match(pageSource, /type CaseTeachingFocus = Readonly<\{/);
  assert.match(pageSource, /teaching_focus: CaseTeachingFocus;/);
  assert.match(pageSource, /type DerivedTeachingFocusPattern = Readonly<\{/);
  assert.match(pageSource, /dynamic_teaching_focus: DerivedTeachingFocus;/);
  assert.match(pageSource, /const preparedTeachingFocus = session\?\.teaching_focus \?\? selectedCase\?\.teachingFocus \?\? null;/);
  assert.match(pageSource, /const preparedDynamicTeachingFocus = session\?\.dynamic_teaching_focus \?\? null;/);
  assert.match(pageSource, /<CollapsiblePanel[\s\S]*title="教学重点与问诊提示"[\s\S]*description="展开查看训练重点、误区和推荐问诊。"/);
  assert.match(pageSource, /preparedDynamicTeachingFocus\.patterns\.map/);
  assert.match(pageSource, /pattern\.why_now/);
  assert.doesNotMatch(pageSource, /<Panel title="当前训练重点" description="由病例结构、Rubric 和当前会话进度动态派生。">/);
  assert.doesNotMatch(pageSource, /<Panel title="训练重点" description="展示不会泄露标准答案的病例学习目标与常见误区。">/);
  assert.match(pageSource, /preparedTeachingFocus\.learning_objectives\.map/);
  assert.match(pageSource, /preparedTeachingFocus\.common_error_patterns\.map/);
  assert.match(pageSource, /preparedTeachingFocus\.recommended_training_path\.map/);
  assert.match(pageSource, /type InquiryGuidance = Readonly<\{/);
  assert.match(pageSource, /inquiry_guidance: InquiryGuidance;/);
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
  assert.match(pageSource, /session\?\.inquiry_guidance\.priority/);
  assert.match(pageSource, /session\.inquiry_guidance\.suggested_questions\.map/);
  assert.match(pageSource, /onClick=\{\(\) => setInputValue\(question\)\}/);
  assert.match(pageSource, /session\.inquiry_guidance\.categories\.map/);
});

test("home workspace centers compact coach hint cards inside the dialogue stream", () => {
  assert.match(pageSource, /const messageRowClass = isStudent \? "justify-end" : isCoach \? "justify-center" : "justify-start";/);
  assert.match(pageSource, /const messageBubbleClass = isStudent[\s\S]*?isCoach[\s\S]*?w-full max-w-lg[\s\S]*?border-\[#B5812A\]\/30[\s\S]*?bg-\[#FFF8E8\][\s\S]*?text-foreground/);
  assert.match(pageSource, /className=\{`flex \$\{messageRowClass\}`\}/);
  assert.match(pageSource, /className=\{messageBubbleClass\}/);
  assert.doesNotMatch(pageSource, /isCoach\s*\?\s*"border-\[#B5812A\]\/30 bg-\[#FFF8E8\] text-foreground"/);
});

test("home workspace keeps backend progress data and exposes compact admin coverage map", () => {
  assert.match(pageSource, /type TrainingProgress = Readonly<\{/);
  assert.match(pageSource, /training_progress: TrainingProgress;/);
  assert.match(pageSource, /type CoverageMapItem = Readonly<\{/);
  assert.match(pageSource, /id: string;/);
  assert.match(pageSource, /label: string;/);
  assert.match(pageSource, /status: "covered" \| "pending";/);
  assert.match(pageSource, /type CoverageMapPayload = Readonly<\{/);
  assert.match(pageSource, /coverage_map: CoverageMapPayload;/);
  assert.match(pageSource, /session\?\.training_progress\.next_focus \?\? workflowSuggestion/);
  assert.doesNotMatch(pageSource, /function formatProgressCount\(covered: number, total: number\): string/);
  assert.match(pageSource, /function CoverageMap\(/);
  assert.match(pageSource, /function CoverageMapSection\(/);
  assert.match(pageSource, /const \[isCoverageMapOpen, setIsCoverageMapOpen\] = useState\(false\);/);
  assert.doesNotMatch(pageSource, /<Panel title="训练进度与素材覆盖"/);
  assert.doesNotMatch(pageSource, />问诊线索<\/p>/);
  assert.doesNotMatch(pageSource, />推理证据<\/p>/);
  assert.doesNotMatch(pageSource, /\{session\.training_progress\.next_focus\}/);
  assert.doesNotMatch(pageSource, /rounded-lg border border-brand\/20 bg-brand\/5 p-3 text-xs leading-5 text-brand/);
  assert.match(pageSource, />\s*管理员图谱\s*<\/p>/);
  assert.match(pageSource, />\s*查看素材覆盖图谱\s*<\/button>/);
  assert.match(pageSource, /onClick=\{\(\) => setIsCoverageMapOpen\(true\)\}/);
  assert.match(pageSource, /管理员图谱 · 素材覆盖/);
  assert.match(pageSource, /aria-label="关闭素材覆盖图谱"/);
  assert.match(pageSource, /item\.status === "covered" \? item\.label : `未覆盖素材：\$\{item\.id\}`/);
  assert.match(pageSource, /trainingProgress\.coverage_map\.history/);
  assert.match(pageSource, /trainingProgress\.coverage_map\.physical_exam/);
  assert.match(pageSource, /trainingProgress\.coverage_map\.auxiliary_test/);
  assert.match(pageSource, /trainingProgress\.coverage_map\.reasoning/);
  assert.doesNotMatch(pageSource, /function buildCoverageMapItems/);
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
  assert.match(reportSource, /requestJson<FeedbackReportPayload>\(`\/api\/me\/sessions\/\$\{nextSessionId\}\/report`\)/);
  assert.match(reportSource, /requestJson<BackendSession>\(`\/api\/me\/sessions\/\$\{nextSessionId\}`\)/);
  assert.match(reportSource, /fetch\(path, \{/);
  assert.match(reportSource, /credentials: "same-origin"/);
  assert.doesNotMatch(reportSource, /readTrainingHistoryRecords/);
  assert.doesNotMatch(reportSource, /TrainingHistoryRecord/);
  assert.doesNotMatch(reportSource, /`\/api\/sessions\/\$\{nextSessionId\}\/report`/);
  assert.match(reportSource, /<h2 className="text-sm font-semibold">原始对话记录<\/h2>/);
  assert.match(reportSource, /backendSession\?\.messages\.map/);
  assert.match(reportSource, /backendProcedureResults\.map/);
  assert.match(reportSource, /从后端训练 session 读取/);
  assert.match(reportSource, /后端 session 暂无原始对话记录/);
  assert.match(reportSource, /const workbenchHref = sessionId \? `\/\?session_id=\$\{sessionId\}` : "\/";/);
  assert.match(reportSource, /href=\{workbenchHref\}[\s\S]*?>\s*返回工作台\s*<\/Link>/);
});

test("history page lists backend sessions as the only official records", () => {
  assert.match(historySource, /type PersistedSessionSummary = Readonly<\{/);
  assert.match(historySource, /type PersistedSessionListResponse = Readonly<\{/);
  assert.match(historySource, /async function getCurrentUserSessions\(\): Promise<readonly PersistedSessionSummary\[\]>/);
  assert.match(historySource, /async function deleteCurrentUserSession\(sessionId: string\): Promise<void>/);
  assert.match(historySource, /fetch\("\/api\/me\/sessions", \{/);
  assert.match(historySource, /fetch\(`\/api\/me\/sessions\/\$\{sessionId\}`, \{/);
  assert.match(historySource, /method: "DELETE"/);
  assert.match(historySource, /credentials: "same-origin"/);
  assert.match(historySource, /const \[backendSessions, setBackendSessions\] = useState<readonly PersistedSessionSummary\[\]>\(\[\]\);/);
  assert.match(historySource, /const \[deletingSessionId, setDeletingSessionId\] = useState<string \| null>\(null\);/);
  assert.match(historySource, /setBackendSessions\(await getCurrentUserSessions\(\)\)/);
  assert.match(historySource, /setBackendSessions\(\(currentSessions\) => currentSessions\.filter\(\(session\) => session\.session_id !== sessionId\)\)/);
  assert.match(historySource, /<p className="text-sm font-semibold text-brand">后端持久记录<\/p>/);
  assert.match(historySource, /backendSessions\.map\(\(session\) =>/);
  assert.match(historySource, /const workbenchHref = backendSessions\[0\] \? `\/\?session_id=\$\{backendSessions\[0\]\.session_id\}` : "\/";/);
  assert.match(historySource, /href=\{workbenchHref\}[\s\S]*?>\s*返回工作台\s*<\/Link>/);
  assert.match(historySource, /href=\{`\/\?session_id=\$\{session\.session_id\}`\}/);
  assert.match(historySource, />\s*继续训练\s*<\/Link>/);
  assert.match(historySource, /href=\{`\/report\?session_id=\$\{session\.session_id\}`\}/);
  assert.match(historySource, /onClick=\{\(\) => handleDeleteBackendSession\(session\.session_id\)\}/);
  assert.match(historySource, /\{deletingSessionId === session\.session_id \? "删除中" : "删除记录"\}/);
  assert.doesNotMatch(historySource, /本机历史/);
  assert.doesNotMatch(historySource, /localStorage/);
  assert.doesNotMatch(historySource, /readTrainingHistoryRecords/);
  assert.doesNotMatch(historySource, /clearTrainingHistoryRecords/);
  assert.doesNotMatch(historySource, /deleteTrainingHistoryRecord/);
});

test("cases page starts selected cases in a prepared workspace without creating sessions", () => {
  assert.match(casesSource, /type CaseTeachingFocus = Readonly<\{/);
  assert.match(casesSource, /teaching_focus: CaseTeachingFocus;/);
  assert.match(casesSource, /caseSummary\.teaching_focus\.learning_objectives\.map/);
  assert.match(casesSource, /caseSummary\.teaching_focus\.common_error_patterns\.map/);
  assert.match(casesSource, />\s*教学重点\s*<\/p>/);
  assert.match(casesSource, />\s*常见训练误区\s*<\/p>/);
  assert.match(casesSource, /href=\{`\/\?case_id=\$\{encodeURIComponent\(caseSummary\.case_id\)\}`\}/);
  assert.match(casesSource, />\s*选择并进入工作台\s*<\/Link>/);
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
  assert.match(authClientSource, /export async function getCurrentUser\(\): Promise<AuthUser \| null>/);
  assert.match(authClientSource, /export async function loginUser\(email: string, password: string\): Promise<AuthUser>/);
  assert.match(authClientSource, /export async function registerUser\(email: string, password: string, displayName: string\): Promise<AuthUser>/);
  assert.match(authClientSource, /export async function logoutUser\(\): Promise<void>/);
  assert.match(pageSource, /import \{ getCurrentUser, loginUser, logoutUser, registerUser \} from "\.\/auth-client";/);
  assert.match(pageSource, /import type \{ AuthUser \} from "\.\/auth-client";/);
  assert.match(pageSource, /const DEFAULT_AUTH_EMAIL = "1@1\.test";/);
  assert.match(pageSource, /const DEFAULT_AUTH_PASSWORD = "1";/);
  assert.match(pageSource, /const \[authUser, setAuthUser\] = useState<AuthUser \| null>\(null\);/);
  assert.match(pageSource, /const \[isAuthDialogOpen, setIsAuthDialogOpen\] = useState\(false\);/);
  assert.match(pageSource, /const \[authEmail, setAuthEmail\] = useState\(DEFAULT_AUTH_EMAIL\);/);
  assert.match(pageSource, /const \[authPassword, setAuthPassword\] = useState\(DEFAULT_AUTH_PASSWORD\);/);
  assert.match(pageSource, /setAuthEmail\(DEFAULT_AUTH_EMAIL\);/);
  assert.match(pageSource, /setAuthPassword\(DEFAULT_AUTH_PASSWORD\);/);
  assert.match(pageSource, /<div className=\{isAuthDialogOpen \? "h-full pointer-events-none blur-sm" : "h-full"\}>/);
  assert.match(pageSource, /\{!isCheckingAuth && isAuthDialogOpen \? \(/);
  assert.match(pageSource, /backdrop-blur/);
  assert.match(pageSource, />\s*登录 \/ 注册\s*</);
  assert.match(pageSource, /id="auth-email-input"/);
  assert.match(pageSource, /id="auth-password-input"/);
  assert.match(pageSource, /id="auth-display-name-input"/);
  assert.match(pageSource, />\{isSubmittingAuth \? "处理中" : authMode === "login" \? "登录" : "注册"\}<\/button>/);
  assert.match(pageSource, />\s*退出登录\s*</);
});
