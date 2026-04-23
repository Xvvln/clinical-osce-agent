from fastapi import FastAPI

app = FastAPI(
    title="Clinical OSCE Agent API",
    version="0.1.0",
    description="Backend scaffold for the Clinical Reasoning OSCE Agent.",
)


@app.get("/")
def read_root() -> dict[str, str]:
    return {
        "name": "clinical-osce-agent",
        "message": "OSCE backend scaffold is running.",
    }


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
