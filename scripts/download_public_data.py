from __future__ import annotations

from pathlib import Path
import requests

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
CHUNK_SIZE = 1024 * 1024
TIMEOUT = 120
DEFAULT_HEADERS = {"User-Agent": "Mozilla/5.0"}

DOWNLOADS = {
    RAW_DIR / "fareez_osce" / "Data.zip": {
        "url": "https://ndownloader.figshare.com/files/30598530",
        "headers": {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://springernature.figshare.com/articles/dataset/Collection_of_simulated_medical_exams/16550013",
        },
    },
    RAW_DIR / "medcase_reasoning" / "train-00000-of-00001.parquet": {
        "url": "https://huggingface.co/datasets/zou-lab/MedCaseReasoning/resolve/main/data/train-00000-of-00001.parquet?download=true",
        "headers": DEFAULT_HEADERS,
    },
    RAW_DIR / "medcase_reasoning" / "val-00000-of-00001.parquet": {
        "url": "https://huggingface.co/datasets/zou-lab/MedCaseReasoning/resolve/main/data/val-00000-of-00001.parquet?download=true",
        "headers": DEFAULT_HEADERS,
    },
    RAW_DIR / "medcase_reasoning" / "test-00000-of-00001.parquet": {
        "url": "https://huggingface.co/datasets/zou-lab/MedCaseReasoning/resolve/main/data/test-00000-of-00001.parquet?download=true",
        "headers": DEFAULT_HEADERS,
    },
    RAW_DIR / "medcase_reasoning" / "medcasereasoning_core.csv": {
        "url": "https://huggingface.co/datasets/zou-lab/MedCaseReasoning/resolve/main/medcasereasoning_core.csv?download=true",
        "headers": DEFAULT_HEADERS,
    },
    RAW_DIR / "medcase_reasoning" / "medcasereasoning_core.pqt": {
        "url": "https://huggingface.co/datasets/zou-lab/MedCaseReasoning/resolve/main/medcasereasoning_core.pqt?download=true",
        "headers": DEFAULT_HEADERS,
    },
    RAW_DIR / "case_report_collective" / "train-00000-of-00001.parquet": {
        "url": "https://huggingface.co/datasets/cxyzhang/CaseReportCollective_V1.0/resolve/main/data/train-00000-of-00001.parquet?download=true",
        "headers": DEFAULT_HEADERS,
    },
}


def download_file(target: Path, url: str, headers: dict[str, str]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 0:
        print(f"skip existing: {target}")
        return

    print(f"downloading -> {target}")
    with requests.get(url, headers=headers, stream=True, timeout=TIMEOUT) as response:
        response.raise_for_status()
        with target.open("wb") as file_handle:
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                if chunk:
                    file_handle.write(chunk)


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    for target, config in DOWNLOADS.items():
        download_file(target, config["url"], config["headers"])

    print("all public downloads finished")


if __name__ == "__main__":
    main()
