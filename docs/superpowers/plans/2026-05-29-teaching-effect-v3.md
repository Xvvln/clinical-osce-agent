# Teaching Effect v3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a verifiable teaching-effect layer that turns OSCE reports, TeacherAgent analysis, Skill memory and student profile into observable clinical reasoning improvement signals.

**Architecture:** Keep scoring, diagnosis facts and rubric decisions deterministic. Add a teaching-effect summary layer above existing `clinical_reasoning_trace`, `ai_reflection_review`, enabled Skill and student profile data. Surface it in student profile and validate it with automated tests plus realistic browser flows.

**Tech Stack:** FastAPI, Pydantic, SQLite stores, pytest, Next.js, node test runner, Playwright/MCP browser testing.

**Verified status:** Completed on 2026-05-29. Runtime scenario validation used a non-destructive append flow to preserve existing demo data, then exercised all five available cases through real HTTP training sessions and browser report/profile checks.

---

## File Structure

- Modify: `项目开发文档.md`
  - Add the product specification for Teaching Effect v3: ability axes, TeacherAgent responsibilities, Skill memory role, student profile meaning, RAG boundary and evaluation protocol.
- Modify: `services/api/app/services/student_profile_summary_service.py`
  - Add `build_teaching_effect_summary()` and supporting helpers.
  - Reuse existing `reasoning_profile_summary`, Skill lifecycle states and report data; do not introduce scoring changes.
- Modify: `services/api/app/main.py`
  - Include `teaching_effect_summary` in `/api/me/profile`.
- Modify: `services/api/tests/test_student_profile_summary_service.py`
  - Add tests proving improvement, repeated weakness and insufficient-sample behavior.
- Modify: `services/api/tests/test_osce_sessions.py`
  - Add API-level regression that `/api/me/profile` exposes readable teaching-effect fields.
- Modify: `apps/web/src/app/profile/page.tsx`
  - Add a student-facing “教学效果观察” section that explains what changed, what remains weak and what to practice next.
- Modify: `apps/web/home-navigation-layout.test.mjs`
  - Add structural checks for the new profile section if existing test helpers can inspect profile page source.

---

### Task 1: Document Teaching Effect v3 Contract

**Files:**
- Modify: `项目开发文档.md`

- [x] **Step 1: Add v3 project document section**

Add a new section after `1.5.5A`:

```markdown
### 1.5.5B Teaching Effect v3：从功能闭环升级为教学效果闭环

...
```

It must define:

- Clinical reasoning ability axes.
- TeacherAgent training-time and post-training responsibilities.
- Skill memory as procedural teaching memory.
- Student profile as longitudinal learning model.
- RAG as teaching knowledge support, not scoring proof.
- Realistic evaluation protocol.
- Current implementation boundary.

- [x] **Step 2: Self-review the document**

Run:

```bash
rg -n "Teaching Effect v3|真实教学效果|评分裁判|样本不足" 项目开发文档.md
```

Expected: the new section exists and states boundaries explicitly.

---

### Task 2: Teaching Effect Summary Service

**Files:**
- Modify: `services/api/app/services/student_profile_summary_service.py`
- Test: `services/api/tests/test_student_profile_summary_service.py`

- [x] **Step 1: Write failing tests**

Add tests:

```python
def test_teaching_effect_summary_marks_repeated_reasoning_gap_as_active() -> None:
    summary = build_skill_profile_summary(
        reports=[
            {"case_id": "appendicitis_001", "missed_items": ["ht_migration"], "clinical_reasoning_trace": {"cognitive_patterns": [{"pattern_id": "weak_problem_representation", "label": "问题表征薄弱", "category": "problem_representation"}]}},
            {"case_id": "acs_001", "missed_items": ["ht_onset"], "clinical_reasoning_trace": {"cognitive_patterns": [{"pattern_id": "weak_problem_representation", "label": "问题表征薄弱", "category": "problem_representation"}]}},
        ],
        enabled_skills=[],
    )
    teaching_effect = summary["teaching_effect_summary"]
    assert teaching_effect["status"] == "needs_practice"
    assert teaching_effect["ability_axes"][0]["axis_id"] == "problem_representation"
```

```python
def test_teaching_effect_summary_observes_recent_improvement_without_claiming_proof() -> None:
    summary = build_skill_profile_summary(
        reports=[
            {"case_id": "appendicitis_001", "missed_items": [], "clinical_reasoning_trace": {"cognitive_patterns": []}},
            {"case_id": "appendicitis_001", "missed_items": ["ht_migration"], "clinical_reasoning_trace": {"cognitive_patterns": [{"pattern_id": "weak_problem_representation", "label": "问题表征薄弱", "category": "problem_representation"}]}},
        ],
        enabled_skills=[],
    )
    teaching_effect = summary["teaching_effect_summary"]
    assert teaching_effect["status"] == "improving_observed"
    assert "不等于统计学证明" in teaching_effect["summary"]
```

- [x] **Step 2: Run tests to verify they fail**

Run:

```bash
source /d/Anaconda3/etc/profile.d/conda.sh && conda activate agent && cd "/f/杂物/个人开发/clinical-osce-agent/services/api" && python -m pytest tests/test_student_profile_summary_service.py -q
```

Expected: fails because `teaching_effect_summary` does not exist.

- [x] **Step 3: Implement summary generation**

Add:

```python
def build_teaching_effect_summary(reports, skill_states, reasoning_profile_summary):
    ...
```

The summary must include:

- `status`
- `summary`
- `ability_axes`
- `observed_changes`
- `next_teaching_objectives`
- `evidence_boundary`

- [x] **Step 4: Run tests to verify green**

Run the same pytest command. Expected: pass.

---

### Task 3: API and Student UI Exposure

**Files:**
- Modify: `services/api/app/main.py`
- Modify: `apps/web/src/app/profile/page.tsx`
- Test: `services/api/tests/test_osce_sessions.py`

- [x] **Step 1: Write API test**

Add a profile API assertion that `skill_profile_summary.teaching_effect_summary` exists, has Chinese labels and does not claim proven improvement with small samples.

- [x] **Step 2: Run test to verify it fails**

Run:

```bash
source /d/Anaconda3/etc/profile.d/conda.sh && conda activate agent && cd "/f/杂物/个人开发/clinical-osce-agent/services/api" && python -m pytest tests/test_osce_sessions.py::test_current_user_profile_includes_teaching_effect_summary -q
```

Expected: fail before API or fixture changes.

- [x] **Step 3: Add frontend section**

Add a profile section titled `教学效果观察`. It should show:

- current status;
- repeated clinical reasoning gaps;
- recent improvement if observed;
- next teaching objective;
- explicit “样本不足时不宣称提升”.

- [x] **Step 4: Verify API and UI structure**

Run backend test and web structural test:

```bash
source /d/Anaconda3/etc/profile.d/conda.sh && conda activate agent && cd "/f/杂物/个人开发/clinical-osce-agent/services/api" && python -m pytest tests/test_student_profile_summary_service.py tests/test_osce_sessions.py::test_current_user_profile_includes_teaching_effect_summary -q
corepack pnpm --dir "F:\杂物\个人开发\clinical-osce-agent\apps\web" exec node --test home-navigation-layout.test.mjs report-model-normalization.test.mjs
```

---

### Task 4: Realistic Scenario Evaluation

**Files:**
- Runtime only: `data/runtime/`
- No commit of runtime SQLite, logs or backups.

- [x] **Step 1: Use non-destructive runtime validation**

Existing demo records were preserved. Validation appended fresh student sessions and did not commit runtime SQLite, logs, or generated runtime data.

- [x] **Step 2: Run realistic flows**

Use student account to complete:

- appendicitis beginner with incomplete history and weak differential;
- pneumonia beginner with adequate history but weak safety boundary;
- heart failure intermediate with premature tests;
- hyperthyroid intermediate with incomplete differential;
- ACS advanced with free procedure request.

- [x] **Step 3: Verify generated artifacts**

Check:

- every report opens;
- `clinical_reasoning_trace` exists;
- TeacherAgent review is student-facing and not just missed-items;
- each completed session can generate personal Skill;
- profile shows `teaching_effect_summary`;
- follow-up session records `training_skill_applied`;
- admin side sees sessions, reports, candidates and audits.

- [x] **Step 4: Browser validation**

Use Playwright/MCP browser testing to visit:

- student workbench;
- report page;
- profile page;
- admin sessions;
- admin Skill review.

Capture remaining UI or content issues.

---

### Task 5: Final Verification and Commit

**Files:**
- All modified source and tests.

- [x] **Step 1: Run focused tests**

```bash
source /d/Anaconda3/etc/profile.d/conda.sh && conda activate agent && cd "/f/杂物/个人开发/clinical-osce-agent/services/api" && python -m pytest tests/test_student_profile_summary_service.py tests/test_personal_training_skill_service.py tests/test_clinical_reasoning_trace_service.py tests/test_osce_sessions.py -q
```

- [x] **Step 2: Run frontend structural checks**

```bash
corepack pnpm --dir "F:\杂物\个人开发\clinical-osce-agent\apps\web" exec node --test home-navigation-layout.test.mjs report-model-normalization.test.mjs
```

- [x] **Step 3: Run whitespace check**

```bash
git -C "F:\杂物\个人开发\clinical-osce-agent" diff --check
```

- [x] **Step 4: Inspect diff and commit only relevant files**

```bash
git -C "F:\杂物\个人开发\clinical-osce-agent" status --short
git -C "F:\杂物\个人开发\clinical-osce-agent" diff --stat
```

Do not stage `data/runtime/`, `.env`, cache folders, `.next`, logs or SQLite runtime files.
