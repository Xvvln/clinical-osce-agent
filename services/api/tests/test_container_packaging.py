from pathlib import Path
import shlex


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_api_image_copies_only_required_public_data_assets() -> None:
    dockerfile_source = (REPO_ROOT / "services/api/Dockerfile").read_text(encoding="utf-8")
    copied_data_sources: set[str] = set()
    for raw_line in dockerfile_source.splitlines():
        line = raw_line.strip()
        if not line.startswith("COPY "):
            continue
        parts = shlex.split(line)
        for source in parts[1:-1]:
            normalized_source = source.removeprefix("./").rstrip("/")
            if normalized_source == "data" or normalized_source.startswith("data/"):
                copied_data_sources.add(normalized_source)

    assert copied_data_sources == {
        "data/cases",
        "data/rubrics",
        "data/schemas",
        "data/attribution",
        "data/rag_knowledge",
        "data/humanistic_anchor_bank.yaml",
    }


def test_api_image_installs_locked_runtime_into_project_virtualenv() -> None:
    dockerfile_source = (REPO_ROOT / "services/api/Dockerfile").read_text(encoding="utf-8")

    assert "COPY services/api/pyproject.toml services/api/uv.lock ./" in dockerfile_source
    assert dockerfile_source.count("uv sync --frozen --no-dev") == 2
    assert "uv sync --frozen --no-dev --no-install-project" in dockerfile_source
    assert "uv pip install --system" not in dockerfile_source
    assert 'PATH="/app/services/api/.venv/bin:${PATH}"' in dockerfile_source
    assert 'CMD ["python", "-m", "uvicorn"' in dockerfile_source


def test_docker_context_excludes_private_state_and_nested_secret_artifacts() -> None:
    dockerignore_patterns = {
        line.strip()
        for line in (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert {
        "**/.git",
        "**/.claude",
        "**/.codex",
        "**/.agents",
        "**/.worktrees",
        "**/.playwright-mcp",
        "**/.vscode",
        "data/runtime",
        "data/raw",
        "data/processed",
        "**/.env",
        "**/.env.*",
        "**/*.pem",
        "**/*.key",
        "**/*.sqlite",
        "**/*.sqlite3",
        "**/*.db",
        "**/*.log",
        "**/*.jsonl",
    }.issubset(dockerignore_patterns)
    assert "!.env.example" in dockerignore_patterns
