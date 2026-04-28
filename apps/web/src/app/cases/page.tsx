"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { useEffect, useState } from "react";

type CaseSummary = Readonly<{
  case_id: string;
  case_title: string;
  course_module: string;
  difficulty: string;
  chief_complaint: string;
  enabled: boolean;
}>;

type PatientProfile = Readonly<{
  name_placeholder: string;
  age_value: number;
  age_unit: string;
  gender: string;
  occupation: string;
  marital_status: string;
  address_city: string;
  social_background: string;
  hospital_department: string;
  idea: string;
  concern: string;
  expectation: string;
}>;

type HiddenFact = Readonly<{
  fact_id: string;
  topic: string;
  slot: string | null;
  canonical_answer: string;
  variants: readonly string[];
  trigger_intents: readonly string[];
  blocking_rule: string;
  linked_rubric_items: readonly string[];
}>;

type HistoryTaking = Readonly<{
  present_illness_summary: string;
  hidden_facts: readonly HiddenFact[];
  past_medical_history: string;
  surgery_injury_history: string;
  transfusion_history: string;
  infection_history: string;
  allergy_history: string;
  personal_history: string;
  menstrual_history: string | null;
  reproductive_history: string | null;
  family_history: string;
}>;

type PhysicalExamItem = Readonly<{
  exam_code: string;
  exam_name_cn: string;
  result: string;
  is_abnormal: boolean;
  linked_rubric_items: readonly string[];
}>;

type PhysicalExamBundle = Readonly<{
  must_items: readonly PhysicalExamItem[];
  optional_items: readonly PhysicalExamItem[];
}>;

type AuxiliaryTestItem = Readonly<{
  test_code: string;
  test_name_cn: string;
  category: string;
  invasiveness: string;
  cost_hint: string;
  result: string;
  is_abnormal: boolean;
  linked_rubric_items: readonly string[];
}>;

type AuxiliaryTestBundle = Readonly<{
  must_items: readonly AuxiliaryTestItem[];
  optional_items: readonly AuxiliaryTestItem[];
  forbidden_items: readonly string[];
}>;

type DifferentialDiagnosis = Readonly<{
  disease_name: string;
  icd10_hint: string | null;
  expected_action: string;
  key_distinction: string;
}>;

type ReasoningPoint = Readonly<{
  point_id: string;
  statement: string;
  kind: string;
  required_evidence: readonly string[];
  weight: number;
}>;

type DiagnosisSpec = Readonly<{
  main_diagnosis: string;
  main_diagnosis_synonyms: readonly string[];
  icd10_hint: string | null;
  differential_diagnoses: readonly DifferentialDiagnosis[];
  reasoning_points: readonly ReasoningPoint[];
  suggested_next_steps: string;
}>;

type RubricRef = Readonly<{
  rubric_id: string;
  version: string;
}>;

type SourceAttribution = Readonly<{
  source_id: string;
  transformation: string;
  attribution_note: string;
  modified: boolean;
}>;

type CaseRawPayload = Readonly<{
  case_id: string;
  case_title: string;
  course_module: string;
  difficulty: string;
  patient_profile: PatientProfile;
  chief_complaint: string;
  history: HistoryTaking;
  physical_exam: PhysicalExamBundle;
  auxiliary_tests: AuxiliaryTestBundle;
  diagnosis: DiagnosisSpec;
  rubric_ref: RubricRef;
  safety_notes: string;
  source_attribution: SourceAttribution;
  schema_version: string;
  tags: readonly string[];
}>;

type CaseListResponse = Readonly<{
  cases: readonly CaseSummary[];
}>;

type CaseRawResponse = Readonly<{
  case: CaseRawPayload;
}>;

type DetailRowProps = Readonly<{
  label: string;
  value: ReactNode;
}>;

type CaseRawDialogProps = Readonly<{
  caseId: string;
  errorText: string;
  isLoading: boolean;
  onClose: () => void;
  payload: CaseRawPayload | null;
  title: string;
}>;

type CaseDataSectionProps = Readonly<{
  children: ReactNode;
  title: string;
}>;

async function getCases(): Promise<readonly CaseSummary[]> {
  const response = await fetch("/api/cases", {
    method: "GET",
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `读取病例列表失败：${response.status}`);
  }

  const result = (await response.json()) as CaseListResponse;
  return result.cases;
}

async function getCaseRaw(caseId: string): Promise<CaseRawPayload> {
  const response = await fetch(`/api/cases/${encodeURIComponent(caseId)}/raw`, {
    method: "GET",
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `读取病例原始数据失败：${response.status}`);
  }

  const result = (await response.json()) as CaseRawResponse;
  return result.case;
}

function getDifficultyLabel(difficulty: string): string {
  if (difficulty === "beginner") {
    return "初级";
  }

  if (difficulty === "intermediate") {
    return "进阶";
  }

  return difficulty;
}

function formatList(values: readonly string[]): string {
  return values.length > 0 ? values.join("、") : "无";
}

function formatNullable(value: string | null): string {
  return value?.trim() ? value : "未提供";
}

function formatBoolean(value: boolean): string {
  return value ? "是" : "否";
}

function formatBlockingRule(rule: string): string {
  if (rule === "reveal_on_direct_question") {
    return "直接问到后披露";
  }

  if (rule === "reveal_after_stage") {
    return "进入指定阶段后披露";
  }

  if (rule === "never_auto_reveal") {
    return "不自动披露";
  }

  return rule;
}

export default function CasesPage() {
  const [cases, setCases] = useState<readonly CaseSummary[]>([]);
  const [caseRawPayloads, setCaseRawPayloads] = useState<Readonly<Record<string, CaseRawPayload>>>({});
  const [caseRawErrors, setCaseRawErrors] = useState<Readonly<Record<string, string>>>({});
  const [errorText, setErrorText] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadingRawCaseId, setLoadingRawCaseId] = useState<string | null>(null);
  const [selectedRawCaseId, setSelectedRawCaseId] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;

    async function loadCases() {
      try {
        const nextCases = await getCases();
        if (!isMounted) {
          return;
        }

        setCases(nextCases);
        setErrorText(null);
      } catch (error) {
        if (!isMounted) {
          return;
        }

        setErrorText(error instanceof Error ? error.message : "读取病例列表失败。");
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    }

    loadCases();

    return () => {
      isMounted = false;
    };
  }, []);

  useEffect(() => {
    if (!selectedRawCaseId) {
      return undefined;
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setSelectedRawCaseId(null);
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [selectedRawCaseId]);

  async function handleOpenCaseRaw(caseId: string) {
    setSelectedRawCaseId(caseId);
    if (caseRawPayloads[caseId]) {
      return;
    }

    setLoadingRawCaseId(caseId);
    setCaseRawErrors((currentErrors) => ({ ...currentErrors, [caseId]: "" }));

    try {
      const casePayload = await getCaseRaw(caseId);
      setCaseRawPayloads((currentPayloads) => ({ ...currentPayloads, [caseId]: casePayload }));
    } catch (error) {
      setCaseRawErrors((currentErrors) => ({
        ...currentErrors,
        [caseId]: error instanceof Error ? error.message : "读取病例原始数据失败。",
      }));
    } finally {
      setLoadingRawCaseId(null);
    }
  }

  const selectedRawCase = selectedRawCaseId ? caseRawPayloads[selectedRawCaseId] : null;
  const selectedRawCaseSummary = selectedRawCaseId
    ? cases.find((caseSummary) => caseSummary.case_id === selectedRawCaseId)
    : null;

  return (
    <main className="min-h-screen bg-muted/40 px-4 py-6 text-foreground">
      <div className="mx-auto flex max-w-6xl flex-col gap-4">
        <header className="rounded-2xl border border-border bg-background p-5 shadow-xs">
          <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.24em] text-muted-foreground">
                Clinical OSCE Agent
              </p>
              <h1 className="mt-2 text-2xl font-semibold tracking-tight">病例选择</h1>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
                从结构化教学病例中选择一个 OSCE 训练场景。病例进入训练后会创建新的本地 session，并加载对应问诊、查体、辅助检查和诊断草稿。
              </p>
            </div>
            <Link
              className="rounded-md border border-border bg-background px-4 py-2 text-sm font-medium shadow-xs transition hover:bg-accent"
              href="/"
            >
              返回工作台
            </Link>
          </div>
        </header>

        <section className="rounded-2xl border border-brand/20 bg-[#2F6868]/5 p-5 shadow-xs">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="text-sm font-semibold text-brand">训练病例库</p>
              <h2 className="mt-2 text-xl font-semibold tracking-tight">
                {isLoading ? "正在读取病例列表。" : `当前开放 ${cases.length} 个结构化病例。`}
              </h2>
            </div>
            <span className="w-fit rounded-full border border-brand/20 bg-background px-3 py-1 text-xs font-medium text-brand">
              /api/cases
            </span>
          </div>
          <p className="mt-4 max-w-3xl text-sm leading-6 text-muted-foreground">
            本页只展示已结构化并通过后端病例列表 API 暴露的教学病例；真实临床诊疗、用药和急症处理不在本系统输出范围内。
          </p>
        </section>

        {errorText ? (
          <section className="rounded-2xl border border-destructive/20 bg-destructive/5 p-5 text-sm text-destructive shadow-xs">
            {errorText}
          </section>
        ) : null}

        {isLoading ? (
          <section className="rounded-2xl border border-border bg-background p-8 text-center shadow-xs">
            <h2 className="text-base font-semibold">正在加载病例</h2>
            <p className="mt-2 text-sm text-muted-foreground">请确认本地 FastAPI 服务已启动并开放 `/api/cases`。</p>
          </section>
        ) : (
          <section className="grid gap-3 md:grid-cols-2">
            {cases.map((caseSummary) => (
              <article className="rounded-2xl border border-border bg-background p-5 shadow-xs" key={caseSummary.case_id}>
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <p className="font-mono text-[11px] text-muted-foreground">{caseSummary.case_id}</p>
                    <h2 className="mt-2 text-base font-semibold tracking-tight">{caseSummary.case_title}</h2>
                    <p className="mt-2 text-sm leading-6 text-muted-foreground">
                      主诉：{caseSummary.chief_complaint}
                    </p>
                  </div>
                  <span className="w-fit rounded-full border border-brand/20 bg-[#2F6868]/10 px-3 py-1 text-xs font-medium text-brand">
                    {caseSummary.enabled ? "可训练" : "待接入"}
                  </span>
                </div>

                <div className="mt-4 flex flex-wrap gap-2 text-xs">
                  <span className="rounded-full border border-border bg-muted px-3 py-1 font-medium text-muted-foreground">
                    {caseSummary.course_module}
                  </span>
                  <span className="rounded-full border border-border bg-muted px-3 py-1 font-medium text-muted-foreground">
                    {getDifficultyLabel(caseSummary.difficulty)}
                  </span>
                </div>

                <div className="mt-5 flex flex-wrap gap-2 border-t border-border pt-4">
                  {caseSummary.enabled ? (
                    <Link
                      className="inline-flex rounded-md border border-brand bg-brand px-4 py-2 text-sm font-medium text-white shadow-xs transition hover:bg-[#2F6868]/90"
                      href={`/?case_id=${encodeURIComponent(caseSummary.case_id)}`}
                    >
                      开始该病例训练
                    </Link>
                  ) : (
                    <button
                      className="rounded-md border border-border bg-muted px-4 py-2 text-sm font-medium text-muted-foreground"
                      disabled
                      type="button"
                    >
                      暂未开放训练
                    </button>
                  )}
                  <button
                    className="rounded-md border border-border bg-background px-4 py-2 text-sm font-medium shadow-xs transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
                    disabled={loadingRawCaseId === caseSummary.case_id}
                    onClick={() => void handleOpenCaseRaw(caseSummary.case_id)}
                    type="button"
                  >
                    {loadingRawCaseId === caseSummary.case_id ? "读取中" : "查看原始数据"}
                  </button>
                </div>
              </article>
            ))}
          </section>
        )}
      </div>

      {selectedRawCaseId ? (
        <CaseRawDialog
          caseId={selectedRawCaseId}
          errorText={caseRawErrors[selectedRawCaseId] ?? ""}
          isLoading={loadingRawCaseId === selectedRawCaseId}
          onClose={() => setSelectedRawCaseId(null)}
          payload={selectedRawCase}
          title={selectedRawCase?.case_title ?? selectedRawCaseSummary?.case_title ?? selectedRawCaseId}
        />
      ) : null}
    </main>
  );
}

function CaseRawDialog({ caseId, errorText, isLoading, onClose, payload, title }: CaseRawDialogProps) {
  const [viewMode, setViewMode] = useState<"structured" | "json">("structured");

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4"
      onClick={onClose}
      role="presentation"
    >
      <section
        aria-labelledby="case-raw-dialog-title"
        aria-modal="true"
        className="flex max-h-[88vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-border bg-background shadow-2xl"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
      >
        <header className="flex items-start justify-between gap-4 border-b border-border p-5">
          <div>
            <p className="font-mono text-xs text-muted-foreground">{caseId}</p>
            <h2 className="mt-1 text-xl font-semibold tracking-tight" id="case-raw-dialog-title">
              原始病例数据：{title}
            </h2>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              以下内容来自 data/cases 的统一结构化病例数据，包含隐藏事实、标准答案、查体/检查结果和诊断推理点。
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap justify-end gap-2">
            <button
              className="rounded-md border border-border bg-background px-3 py-1.5 text-sm font-medium shadow-xs transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
              disabled={!payload}
              onClick={() => setViewMode((currentMode) => (currentMode === "structured" ? "json" : "structured"))}
              type="button"
            >
              {viewMode === "structured" ? "切换为 JSON" : "切换为中文视图"}
            </button>
            <button
              className="rounded-md border border-border bg-background px-3 py-1.5 text-sm font-medium shadow-xs transition hover:bg-accent"
              onClick={onClose}
              type="button"
            >
              关闭
            </button>
          </div>
        </header>

        <div className="overflow-y-auto p-5">
          {isLoading ? <p className="text-sm text-muted-foreground">正在读取病例原始数据。</p> : null}
          {errorText ? (
            <p className="rounded-lg border border-destructive/20 bg-destructive/5 p-3 text-sm text-destructive">
              {errorText}
            </p>
          ) : null}
          {payload && viewMode === "structured" ? <CaseRawDetails payload={payload} /> : null}
          {payload && viewMode === "json" ? (
            <pre className="max-h-[62vh] overflow-auto rounded-xl border border-border bg-muted/40 p-4 text-[11px] leading-5 text-foreground">
              {JSON.stringify(payload, null, 2)}
            </pre>
          ) : null}
        </div>
      </section>
    </div>
  );
}

function CaseRawDetails({ payload }: Readonly<{ payload: CaseRawPayload }>) {
  return (
    <div className="space-y-4 text-sm">
      <CaseDataSection title="病例概览">
        <DetailGrid>
          <DetailRow label="病例 ID" value={payload.case_id} />
          <DetailRow label="病例标题" value={payload.case_title} />
          <DetailRow label="课程模块" value={payload.course_module} />
          <DetailRow label="难度" value={getDifficultyLabel(payload.difficulty)} />
          <DetailRow label="主诉" value={payload.chief_complaint} />
          <DetailRow label="标签" value={formatList(payload.tags)} />
          <DetailRow label="Schema 版本" value={payload.schema_version} />
        </DetailGrid>
      </CaseDataSection>

      <CaseDataSection title="患者信息与 ICE">
        <DetailGrid>
          <DetailRow label="年龄" value={`${payload.patient_profile.age_value}${payload.patient_profile.age_unit}`} />
          <DetailRow label="性别" value={payload.patient_profile.gender} />
          <DetailRow label="职业" value={payload.patient_profile.occupation} />
          <DetailRow label="婚姻状况" value={payload.patient_profile.marital_status} />
          <DetailRow label="城市" value={payload.patient_profile.address_city} />
          <DetailRow label="就诊科室" value={payload.patient_profile.hospital_department} />
          <DetailRow label="社会背景" value={payload.patient_profile.social_background} />
          <DetailRow label="想法" value={payload.patient_profile.idea} />
          <DetailRow label="担忧" value={payload.patient_profile.concern} />
          <DetailRow label="期望" value={payload.patient_profile.expectation} />
        </DetailGrid>
      </CaseDataSection>

      <CaseDataSection title="病史数据">
        <DetailGrid>
          <DetailRow label="现病史摘要" value={payload.history.present_illness_summary} />
          <DetailRow label="既往史" value={payload.history.past_medical_history} />
          <DetailRow label="手术外伤史" value={payload.history.surgery_injury_history} />
          <DetailRow label="输血史" value={payload.history.transfusion_history} />
          <DetailRow label="传染病史" value={payload.history.infection_history} />
          <DetailRow label="过敏史" value={payload.history.allergy_history} />
          <DetailRow label="个人史" value={payload.history.personal_history} />
          <DetailRow label="月经史" value={formatNullable(payload.history.menstrual_history)} />
          <DetailRow label="生殖史" value={formatNullable(payload.history.reproductive_history)} />
          <DetailRow label="家族史" value={payload.history.family_history} />
        </DetailGrid>
        <SubList title="隐藏事实与标准答案">
          {payload.history.hidden_facts.map((fact) => (
            <li className="rounded-lg border border-border bg-background p-3" key={fact.fact_id}>
              <p className="font-medium text-foreground">{fact.canonical_answer}</p>
              <dl className="mt-2 grid gap-1 text-xs text-muted-foreground sm:grid-cols-2">
                <DetailRow label="事实 ID" value={fact.fact_id} />
                <DetailRow label="主题" value={fact.topic} />
                <DetailRow label="槽位" value={formatNullable(fact.slot)} />
                <DetailRow label="触发意图" value={formatList(fact.trigger_intents)} />
                <DetailRow label="披露规则" value={formatBlockingRule(fact.blocking_rule)} />
                <DetailRow label="关联评分项" value={formatList(fact.linked_rubric_items)} />
                <DetailRow label="患者表达变体" value={formatList(fact.variants)} />
              </dl>
            </li>
          ))}
        </SubList>
      </CaseDataSection>

      <CaseDataSection title="查体数据">
        <ExamList items={payload.physical_exam.must_items} title="必须查体项" />
        <ExamList items={payload.physical_exam.optional_items} title="可选查体项" />
      </CaseDataSection>

      <CaseDataSection title="辅助检查数据">
        <AuxiliaryTestList items={payload.auxiliary_tests.must_items} title="必须辅助检查" />
        <AuxiliaryTestList items={payload.auxiliary_tests.optional_items} title="可选辅助检查" />
        <DetailGrid>
          <DetailRow label="不建议检查项" value={formatList(payload.auxiliary_tests.forbidden_items)} />
        </DetailGrid>
      </CaseDataSection>

      <CaseDataSection title="诊断与推理">
        <DetailGrid>
          <DetailRow label="主诊断" value={payload.diagnosis.main_diagnosis} />
          <DetailRow label="主诊断同义词" value={formatList(payload.diagnosis.main_diagnosis_synonyms)} />
          <DetailRow label="ICD-10 提示" value={formatNullable(payload.diagnosis.icd10_hint)} />
          <DetailRow label="建议下一步" value={payload.diagnosis.suggested_next_steps} />
        </DetailGrid>
        <SubList title="鉴别诊断">
          {payload.diagnosis.differential_diagnoses.map((diagnosis) => (
            <li className="rounded-lg border border-border bg-background p-3" key={diagnosis.disease_name}>
              <p className="font-medium text-foreground">{diagnosis.disease_name}</p>
              <dl className="mt-2 grid gap-1 text-xs text-muted-foreground sm:grid-cols-2">
                <DetailRow label="处理方向" value={diagnosis.expected_action} />
                <DetailRow label="ICD-10 提示" value={formatNullable(diagnosis.icd10_hint)} />
                <DetailRow label="关键区别" value={diagnosis.key_distinction} />
              </dl>
            </li>
          ))}
        </SubList>
        <SubList title="诊断推理点">
          {payload.diagnosis.reasoning_points.map((point) => (
            <li className="rounded-lg border border-border bg-background p-3" key={point.point_id}>
              <p className="font-medium text-foreground">{point.statement}</p>
              <dl className="mt-2 grid gap-1 text-xs text-muted-foreground sm:grid-cols-2">
                <DetailRow label="推理点 ID" value={point.point_id} />
                <DetailRow label="性质" value={point.kind} />
                <DetailRow label="权重" value={point.weight} />
                <DetailRow label="所需证据" value={formatList(point.required_evidence)} />
              </dl>
            </li>
          ))}
        </SubList>
      </CaseDataSection>

      <CaseDataSection title="评分引用、来源与安全边界">
        <DetailGrid>
          <DetailRow label="Rubric ID" value={payload.rubric_ref.rubric_id} />
          <DetailRow label="Rubric 版本" value={payload.rubric_ref.version} />
          <DetailRow label="来源 ID" value={payload.source_attribution.source_id} />
          <DetailRow label="是否改写" value={formatBoolean(payload.source_attribution.modified)} />
          <DetailRow label="转换方式" value={payload.source_attribution.transformation} />
          <DetailRow label="归属说明" value={payload.source_attribution.attribution_note} />
          <DetailRow label="安全声明" value={payload.safety_notes} />
        </DetailGrid>
      </CaseDataSection>
    </div>
  );
}

function CaseDataSection({ children, title }: CaseDataSectionProps) {
  return (
    <section className="rounded-xl border border-border bg-muted/30 p-4">
      <h3 className="text-base font-semibold tracking-tight">{title}</h3>
      <div className="mt-3 space-y-3">{children}</div>
    </section>
  );
}

function DetailGrid({ children }: Readonly<{ children: ReactNode }>) {
  return <dl className="grid gap-3 sm:grid-cols-2">{children}</dl>;
}

function DetailRow({ label, value }: DetailRowProps) {
  return (
    <div className="rounded-lg border border-border bg-background p-3">
      <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
      <dd className="mt-1 text-sm leading-6 text-foreground">{value}</dd>
    </div>
  );
}

function SubList({ children, title }: Readonly<{ children: ReactNode; title: string }>) {
  return (
    <div>
      <p className="mb-2 text-xs font-semibold text-muted-foreground">{title}</p>
      <ul className="space-y-2">{children}</ul>
    </div>
  );
}

function ExamList({ items, title }: Readonly<{ items: readonly PhysicalExamItem[]; title: string }>) {
  return (
    <SubList title={title}>
      {items.length > 0 ? (
        items.map((item) => (
          <li className="rounded-lg border border-border bg-background p-3" key={item.exam_code}>
            <p className="font-medium text-foreground">{item.exam_name_cn}</p>
            <dl className="mt-2 grid gap-1 text-xs text-muted-foreground sm:grid-cols-2">
              <DetailRow label="查体编码" value={item.exam_code} />
              <DetailRow label="结果" value={item.result} />
              <DetailRow label="是否异常" value={formatBoolean(item.is_abnormal)} />
              <DetailRow label="关联评分项" value={formatList(item.linked_rubric_items)} />
            </dl>
          </li>
        ))
      ) : (
        <li className="rounded-lg border border-border bg-background p-3 text-sm text-muted-foreground">暂无</li>
      )}
    </SubList>
  );
}

function AuxiliaryTestList({ items, title }: Readonly<{ items: readonly AuxiliaryTestItem[]; title: string }>) {
  return (
    <SubList title={title}>
      {items.length > 0 ? (
        items.map((item) => (
          <li className="rounded-lg border border-border bg-background p-3" key={item.test_code}>
            <p className="font-medium text-foreground">{item.test_name_cn}</p>
            <dl className="mt-2 grid gap-1 text-xs text-muted-foreground sm:grid-cols-2">
              <DetailRow label="检查编码" value={item.test_code} />
              <DetailRow label="类别" value={item.category} />
              <DetailRow label="侵入性" value={item.invasiveness} />
              <DetailRow label="费用提示" value={item.cost_hint} />
              <DetailRow label="结果" value={item.result} />
              <DetailRow label="是否异常" value={formatBoolean(item.is_abnormal)} />
              <DetailRow label="关联评分项" value={formatList(item.linked_rubric_items)} />
            </dl>
          </li>
        ))
      ) : (
        <li className="rounded-lg border border-border bg-background p-3 text-sm text-muted-foreground">暂无</li>
      )}
    </SubList>
  );
}
