# RAG Report Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reposition RAG away from scoring proof and toward teaching, review, and similar-case recommendation.

**Architecture:** Keep scoring and traceability deterministic. Use direct source/knowledge resolvers for known IDs, reserve retrieval for semantic recommendations, and simplify the student report into learning-oriented sections with evidence folded behind disclosure controls.

**Tech Stack:** FastAPI/Python services, Next.js/TypeScript frontend, Node structure tests, pytest, project documentation in `项目开发文档.md`.

---

### Task 1: Recommendation Boundary

**Files:**
- Modify: `services/api/app/services/knowledge_recommender.py`
- Test: `services/api/tests/test_knowledge_recommender.py`

- [ ] Write failing tests proving known `missing_evidence` knowledge recommendations do not call retrieval and semantic case search can drive next-case recommendation.
- [ ] Run `python -m pytest tests/test_knowledge_recommender.py -q` and confirm the new tests fail for the current implementation.
- [ ] Implement a deterministic knowledge resolver for known evidence IDs.
- [ ] Use retrieval only to rank candidate `case:` recommendations, with deterministic module/file-order fallback.
- [ ] Re-run `python -m pytest tests/test_knowledge_recommender.py -q`.

### Task 2: Student Report Information Architecture

**Files:**
- Modify: `apps/web/src/app/report/page.tsx`
- Modify: `apps/web/home-navigation-layout.test.mjs`

- [ ] Write failing structure tests for the new report wording: `本轮结论`, `下一轮训练计划`, `教练复盘`, and folded `评分依据与来源`.
- [ ] Remove student-facing wording that suggests RAG proves missed scoring items.
- [ ] Keep source/reference details accessible but collapsed by default.
- [ ] Re-run web structure tests and typecheck.

### Task 3: Admin And Evaluation Wording

**Files:**
- Modify: `apps/admin/src/app/page.tsx`
- Modify: `apps/admin/admin-skill-review.test.mjs`

- [ ] Write failing structure tests separating `结构化追溯覆盖` from `RAG 检索评测`.
- [ ] Update admin copy so source references are presented as deterministic traceability, while retrieval metrics are for knowledge/material/case recall.
- [ ] Re-run admin structure tests and typecheck.

### Task 4: Documentation

**Files:**
- Modify: `项目开发文档.md`

- [ ] Document the updated boundary: scoring and漏项 use deterministic evidence matching; RAG supports Coach Agent, review/audit agents, learning resources, and similar-case recommendation.
- [ ] Document current implementation facts, current boundaries, delayed work, and verification commands.

### Task 5: Verification

**Commands:**
- Backend focused: `source /d/Anaconda3/etc/profile.d/conda.sh && conda activate agent && cd "/f/杂物/个人开发/clinical-osce-agent/services/api" && python -m pytest tests/test_knowledge_recommender.py tests/test_osce_graph.py -q`
- Web structure: `corepack pnpm --dir "F:\杂物\个人开发\clinical-osce-agent\apps\web" exec node --test home-navigation-layout.test.mjs`
- Web typecheck: `corepack pnpm --dir "F:\杂物\个人开发\clinical-osce-agent\apps\web" typecheck`
- Admin structure: `corepack pnpm --dir "F:\杂物\个人开发\clinical-osce-agent\apps\admin" exec node --test admin-skill-review.test.mjs`
- Admin typecheck: `corepack pnpm --dir "F:\杂物\个人开发\clinical-osce-agent\apps\admin" typecheck`
- Whitespace: `git -C "F:\杂物\个人开发\clinical-osce-agent" diff --check`
- Browser smoke if UI changed: use Playwright, then close every page.
