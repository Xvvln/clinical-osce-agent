# Coach Hint v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the manual "request hint" flow from a mostly base-hint rewrite into a context-aware Coach planning call that uses current session state, difficulty, evidence coverage, recent turns, selected Skills and safe RAG snippets.

**Architecture:** Keep scoring, fact disclosure and diagnosis decisions deterministic. Add a compact `hint_context` payload for Coach only, derived from current session state and case data, then keep the visible hint behind the existing safety sanitizer and turn-memory audit. This is an additive API contract on `CoachRequest`, so existing deterministic and provider-backed Coach agents keep working.

**Tech Stack:** FastAPI, LangGraph, Pydantic, pytest, Next.js structure tests.

---

### Task 1: Document Coach Hint v2

**Files:**
- Modify: `项目开发文档.md`
- Create: `docs/superpowers/plans/2026-05-26-coach-hint-v2.md`

- [ ] **Step 1: Add design record**

Add a change-log entry that states:
- current `/hint` route remains `POST /api/sessions/{session_id}/hint`;
- Coach receives `hint_context` containing safe session context, evidence coverage, difficulty policy, selected Skill reasons and RAG references;
- Coach still cannot change hidden facts, diagnosis, rubric, scoring or treatment advice;
- tests must cover context construction and leakage prevention.

- [ ] **Step 2: Run whitespace check**

Run:

```powershell
git diff --check
```

Expected: no whitespace errors.

### Task 2: Backend CoachRequest contract

**Files:**
- Modify: `services/api/app/services/coach_agent.py`
- Test: `services/api/tests/test_coach_agent.py`

- [ ] **Step 1: Write failing test**

Add a test that builds `CoachRequest(training_difficulty="advanced", hint_context={...})` and verifies the provider payload includes both fields.

- [ ] **Step 2: Verify red**

Run:

```powershell
bash -lc 'source /d/Anaconda3/etc/profile.d/conda.sh && conda activate agent && cd "/f/杂物/个人开发/clinical-osce-agent/services/api" && python -m pytest tests/test_coach_agent.py -q'
```

Expected before implementation: failure because `CoachRequest` has no `training_difficulty` or `hint_context`.

- [ ] **Step 3: Implement minimal contract**

Add optional Pydantic fields:

```python
training_difficulty: str = "beginner"
hint_context: dict[str, Any] = Field(default_factory=dict)
```

Update `SYSTEM_PROMPT_TEMPLATE` to tell Coach to prefer `hint_context.next_step`, `hint_context.evidence_coverage`, `hint_context.difficulty_policy` and `hint_context.skill_selection`, while still avoiding hidden answers.

- [ ] **Step 4: Verify green**

Run the same pytest command. Expected: pass.

### Task 3: Context builder and graph integration

**Files:**
- Create: `services/api/app/services/coach_hint_context_service.py`
- Modify: `services/api/app/graph/osce_graph.py`
- Test: `services/api/tests/test_osce_graph.py`

- [ ] **Step 1: Write failing graph test**

Add `test_osce_graph_socratic_hint_passes_comprehensive_hint_context_to_coach`:
- call `build_osce_graph(coach_agent=fake_agent)`;
- use `base_hint_state(training_difficulty="advanced", messages=[...], revealed_facts=[...], requested_exams=[...], requested_tests=[...], student_hypotheses=[...], active_skill_context=active_skill_context())`;
- assert captured `CoachRequest.model_dump()` includes:
  - `training_difficulty == "advanced"`;
  - `hint_context.session.training_difficulty == "advanced"`;
  - recent conversation turns;
  - collected evidence from history, physical exam and auxiliary test;
  - safe pending counts and next action;
  - selected Skill title and reason;
  - no main diagnosis.

- [ ] **Step 2: Verify red**

Run:

```powershell
bash -lc 'source /d/Anaconda3/etc/profile.d/conda.sh && conda activate agent && cd "/f/杂物/个人开发/clinical-osce-agent/services/api" && python -m pytest tests/test_osce_graph.py::test_osce_graph_socratic_hint_passes_comprehensive_hint_context_to_coach -q'
```

Expected before implementation: failure because `hint_context` is absent.

- [ ] **Step 3: Implement builder**

Create `build_coach_hint_context(state, case, pedagogy_state, base_hint, retrieved_knowledge_context)` that returns:
- `session`: case title, chief complaint, stage and difficulty;
- `conversation`: last 8 turns and student hypotheses;
- `evidence_coverage`: collected history / exam / test labels, pending counts and readiness;
- `next_step`: base hint, active learning goal, next best action, Socratic question and hint ladder;
- `difficulty_policy`: beginner / intermediate / advanced wording boundaries;
- `skill_selection`: selected Skill IDs, titles, reasons and trigger labels;
- `rag_context`: references and titles only.

- [ ] **Step 4: Integrate graph**

In `socratic_hint_node`, build `hint_context` after RAG retrieval and pass it to `CoachRequest`. Record `hint_context_summary` or relevant selected metadata in turn memory only if already safe; do not dump hidden private facts to student-facing payload.

- [ ] **Step 5: Verify green**

Run the focused pytest command. Expected: pass.

### Task 4: Safety sanitizer for Coach hints

**Files:**
- Modify: `services/api/app/graph/osce_graph.py`
- Test: `services/api/tests/test_osce_graph.py`

- [ ] **Step 1: Write failing safety test**

Add `test_osce_graph_socratic_hint_sanitizes_private_case_terms_from_coach_output`:
- fake Coach returns a hint that includes main diagnosis and an exact hidden result phrase from the case;
- assert visible `result["hint"]` does not include diagnosis, synonyms, hidden fact answer, exam result, treatment or dose terms.

- [ ] **Step 2: Verify red**

Run the focused test. Expected: failure because current sanitizer only strips diagnosis and treatment terms.

- [ ] **Step 3: Implement private forbidden term helper**

Add a helper in `osce_graph.py` that builds forbidden terms from:
- diagnosis main diagnosis and synonyms;
- exact hidden history canonical answers;
- exact physical exam result strings;
- exact auxiliary test result strings.

Use it for final visible Coach hint sanitation, but do not pass it into `CoachRequest.forbidden_terms` because that would place hidden answers inside provider payload.

- [ ] **Step 4: Verify green**

Run focused tests and existing Coach/RAG hint tests.

### Task 5: Session-level regression and frontend structure

**Files:**
- Modify: `services/api/tests/test_osce_sessions.py`
- Modify if needed: `apps/web/home-navigation-layout.test.mjs`

- [ ] **Step 1: Add session regression**

Add a test that creates a session with `training_difficulty="advanced"`, asks one question, requests a hint and asserts the resulting `hint_requested` event contains `agent_turn.selected_skill_ids` / `retrieved_knowledge_context` as before and no visible hidden answer leak.

- [ ] **Step 2: Verify red/green as needed**

Run:

```powershell
bash -lc 'source /d/Anaconda3/etc/profile.d/conda.sh && conda activate agent && cd "/f/杂物/个人开发/clinical-osce-agent/services/api" && python -m pytest tests/test_coach_agent.py tests/test_osce_graph.py tests/test_osce_sessions.py -q'
corepack pnpm --dir "F:\杂物\个人开发\clinical-osce-agent\apps\web" exec node --test home-navigation-layout.test.mjs
corepack pnpm --dir "F:\杂物\个人开发\clinical-osce-agent\apps\web" typecheck
git diff --check
```

Expected: all pass.

### Task 6: Real workflow verification

**Files:**
- No production files expected unless browser testing reveals a bug.

- [ ] **Step 1: Ensure local services are running**

Use existing local ports:
- API: `http://127.0.0.1:8000`
- student: `http://127.0.0.1:3000`
- admin: `http://127.0.0.1:3001`

- [ ] **Step 2: Browser scenario**

With Playwright or equivalent browser flow:
- login student;
- choose a case and difficulty;
- ask at least one history question;
- click request hint;
- verify hint appears after current conversation, does not reveal diagnosis, and "本轮 Skill 依据" / RAG evidence remains collapsed if present.

- [ ] **Step 3: Report result**

Tell the user:
- what changed;
- which tests passed;
- whether browser scenario passed;
- any remaining limitations.
