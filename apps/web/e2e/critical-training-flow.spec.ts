import { expect, test, type Page, type Response } from "@playwright/test";

const STUDENT_BASE_URL = (process.env.E2E_STUDENT_BASE_URL ?? "http://localhost:3000").replace(/\/+$/, "");
const ADMIN_BASE_URL = (process.env.E2E_ADMIN_BASE_URL ?? "http://127.0.0.1:3001").replace(/\/+$/, "");
const STUDENT_EMAIL = process.env.E2E_STUDENT_EMAIL ?? "student@e2e.test";
const STUDENT_PASSWORD = process.env.E2E_STUDENT_PASSWORD ?? "traceosce-e2e-student-only";
const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? "admin@e2e.test";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "traceosce-e2e-admin-only";
const CASE_ID = "appendicitis_001";

type TrainingActionResponse = Readonly<{
  session_id: string;
  reply?: string;
}>;

type LearningProfileResponse = Readonly<{
  profile: Readonly<{
    total_sessions: number;
    report_count: number;
    recent_sessions: readonly Readonly<{
      session_id: string;
      has_report: boolean;
    }>[];
  }>;
}>;

function isSuccessfulApiResponse(
  response: Response,
  pathPattern: RegExp,
  method = "POST",
): boolean {
  const url = new URL(response.url());
  return (
    response.request().method() === method
    && pathPattern.test(url.pathname)
    && response.ok()
  );
}

async function loginStudent(page: Page): Promise<void> {
  await page.goto(`${STUDENT_BASE_URL}/?case_id=${CASE_ID}&difficulty=beginner`);
  await expect(page.getByRole("heading", { name: "登录", exact: true })).toBeVisible();
  await page.locator("#auth-email-input").fill(STUDENT_EMAIL);
  await page.locator("#auth-password-input").fill(STUDENT_PASSWORD);

  const loginResponse = page.waitForResponse((response) =>
    isSuccessfulApiResponse(response, /^\/api\/auth\/login$/),
  );
  await page.locator("#auth-password-input").press("Enter");
  await loginResponse;

  await expect(page.getByRole("button", { name: "打开个人中心菜单" })).toBeVisible();
  await expect(page.getByLabel("输入下一句问诊问题")).toBeEnabled({ timeout: 30_000 });
}

async function askHistoryQuestion(page: Page): Promise<TrainingActionResponse> {
  const question = "什么时候开始疼的？";
  const questionInput = page.getByLabel("输入下一句问诊问题");
  await questionInput.fill(question);

  const responsePromise = page.waitForResponse((response) =>
    isSuccessfulApiResponse(response, /^\/api\/sessions\/[^/]+\/message$/),
  );
  await page.getByRole("button", { name: "发送问诊", exact: true }).click();
  const payload = await (await responsePromise).json() as TrainingActionResponse;

  expect(payload.session_id).toMatch(/^[0-9a-f-]{36}$/i);
  await expect(page.getByText(question, { exact: true })).toBeVisible();
  if (payload.reply) {
    await expect(page.getByText(payload.reply, { exact: true })).toBeVisible({ timeout: 30_000 });
  }
  return payload;
}

async function requestPhysicalExam(page: Page, sessionId: string): Promise<void> {
  await page.getByRole("button", { name: /查体项目/ }).click();
  const responsePromise = page.waitForResponse((response) =>
    isSuccessfulApiResponse(response, new RegExp(`^/api/sessions/${sessionId}/physical-exam$`)),
  );
  await page.getByRole("button", { name: "McBurney 点压痛", exact: true }).click();
  await responsePromise;

  await expect(page.getByRole("heading", { name: "查体：McBurney 点压痛", exact: true })).toBeVisible();
  const closeResultButton = page.getByRole("button", { name: "关闭查体检查结果" });
  await expect(closeResultButton).toBeVisible();
  await closeResultButton.click();
}

async function requestBloodCount(page: Page, sessionId: string): Promise<void> {
  await page.getByRole("button", { name: /辅助检查/ }).click();
  const responsePromise = page.waitForResponse((response) =>
    isSuccessfulApiResponse(response, new RegExp(`^/api/sessions/${sessionId}/auxiliary-test$`)),
  );
  await page.getByRole("button", { name: /实验室：血常规/ }).click();
  await responsePromise;

  await expect(page.getByRole("heading", { name: "检查：血常规", exact: true })).toBeVisible();
  const closeResultButton = page.getByRole("button", { name: "关闭查体检查结果" });
  await expect(closeResultButton).toBeVisible();
  await closeResultButton.click();
}

async function submitDiagnosisAndOpenReport(page: Page, sessionId: string): Promise<void> {
  await page.getByRole("button", { name: /提交诊断与推理/ }).click();
  await page.locator("#diagnosis-input").fill("急性阑尾炎");
  await page.locator("#supporting-evidence-input").fill("转移性右下腹痛、McBurney 点压痛和血常规异常支持急性阑尾炎。");
  await page.locator("#exclusion-evidence-input").fill("需与泌尿系结石等右下腹痛病因鉴别，结合尿常规和影像进一步排除。");

  const submitResponse = page.waitForResponse((response) =>
    isSuccessfulApiResponse(response, new RegExp(`^/api/sessions/${sessionId}/submit-diagnosis$`)),
  );
  await page.getByRole("button", { name: "提交诊断", exact: true }).click();
  await submitResponse;

  await page.waitForURL(
    (url) => url.pathname === "/report" && url.searchParams.get("session_id") === sessionId,
    { timeout: 90_000 },
  );
  await expect(page.getByRole("heading", { name: "评分报告", exact: true })).toBeVisible();
  await expect(page.getByText("OSCE 训练总分", { exact: true })).toBeVisible();
}

async function loginAdminAndVerifySession(page: Page, sessionId: string): Promise<void> {
  await page.goto(ADMIN_BASE_URL);
  await expect(page.getByRole("heading", { name: "管理员登录", exact: true })).toBeVisible();
  await page.getByPlaceholder("输入管理员邮箱").fill(ADMIN_EMAIL);
  await page.getByPlaceholder("输入管理员账号密码").fill(ADMIN_PASSWORD);

  const loginResponse = page.waitForResponse((response) =>
    isSuccessfulApiResponse(response, /^\/api\/auth\/login$/),
  );
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await loginResponse;

  const trainingSectionButton = page.getByRole("button", { name: "训练管理", exact: true });
  await expect(trainingSectionButton).toBeVisible({ timeout: 30_000 });
  await trainingSectionButton.click();

  const sessionCell = page.getByText(sessionId, { exact: true }).first();
  await expect(sessionCell).toBeVisible({ timeout: 30_000 });
  await sessionCell.click();
  await expect(page.getByRole("button", { name: "读取报告", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "读取报告", exact: true }).click();
  await expect(page.getByText("评分报告", { exact: true }).last()).toBeVisible();
}

async function verifyLearningProfile(page: Page, sessionId: string): Promise<void> {
  const profileResponse = page.waitForResponse((response) =>
    isSuccessfulApiResponse(response, /^\/api\/me\/profile$/, "GET"),
  );
  await page.goto(`${STUDENT_BASE_URL}/profile`);
  const payload = await (await profileResponse).json() as LearningProfileResponse;

  expect(payload.profile.total_sessions).toBeGreaterThanOrEqual(1);
  expect(payload.profile.report_count).toBeGreaterThanOrEqual(1);
  expect(
    payload.profile.recent_sessions.some((session) =>
      session.session_id === sessionId && session.has_report,
    ),
  ).toBe(true);

  await expect(page.getByRole("heading", { name: "近期学习画像", exact: true })).toBeVisible();
  await expect(page.getByText(sessionId, { exact: true })).toBeVisible();
  const reportMetric = page.getByText("已生成报告", { exact: true }).locator("..");
  await expect(
    reportMetric.getByText(String(payload.profile.report_count), { exact: true }),
  ).toBeVisible();
}

test("学生完整训练可追踪到记录和管理端，且双端登录互不覆盖", async ({ context }) => {
  const studentPage = await context.newPage();
  const adminPage = await context.newPage();

  await loginStudent(studentPage);
  const { session_id: sessionId } = await askHistoryQuestion(studentPage);
  await requestPhysicalExam(studentPage, sessionId);
  await requestBloodCount(studentPage, sessionId);
  await submitDiagnosisAndOpenReport(studentPage, sessionId);
  await verifyLearningProfile(studentPage, sessionId);

  await studentPage.goto(`${STUDENT_BASE_URL}/history`);
  await expect(studentPage.getByRole("heading", { name: "训练记录", exact: true })).toBeVisible();
  await expect(studentPage.getByText(sessionId, { exact: true })).toBeVisible();
  await expect(studentPage.getByText("报告已生成", { exact: true })).toBeVisible();

  await loginAdminAndVerifySession(adminPage, sessionId);

  await studentPage.bringToFront();
  await studentPage.reload();
  await expect(studentPage.getByText(sessionId, { exact: true })).toBeVisible();
  await expect(studentPage.getByText("已从后端数据库读取当前账号的训练记录。", { exact: true })).toBeVisible();
});
