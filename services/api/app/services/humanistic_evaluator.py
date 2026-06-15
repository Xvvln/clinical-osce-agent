from __future__ import annotations

import re
import math
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol

import yaml

ROOT_DIR = Path(__file__).resolve().parents[4]
ANCHOR_BANK_PATH = ROOT_DIR / "data" / "humanistic_anchor_bank.yaml"
LOGGER = logging.getLogger(__name__)

PATIENT_EMOTION_KEYWORDS = ("担心", "担忧", "害怕", "焦虑", "怕", "紧张")
LIFE_IMPACT_KEYWORDS = ("影响", "上班", "工作", "学习", "睡眠", "生活")
UNDERSTANDING_KEYWORDS = ("不明白", "不理解", "听不懂", "为什么")


@dataclass(frozen=True)
class TrainingEvent:
    turn_index: int
    event_type: str
    role: str
    content: str
    source_id: str = ""
    label: str = ""


@dataclass
class ScoringLedger:
    awarded_item_ids: list[str] = field(default_factory=list)
    awarded_event_keys: set[str] = field(default_factory=set)

    def can_award(self, item_id: str, event_key: str) -> bool:
        return item_id not in self.awarded_item_ids

    def award(self, item_id: str, event_key: str) -> None:
        self.awarded_item_ids.append(item_id)
        self.awarded_event_keys.add(event_key)

    def to_dict(self) -> dict[str, Any]:
        return {
            "awarded_item_ids": list(self.awarded_item_ids),
            "awarded_event_keys": sorted(self.awarded_event_keys),
        }


class HumanisticEmbeddingClient(Protocol):
    def embed_texts(self, texts: Sequence[str], *, task_type: str) -> list[list[float]]:
        ...


@dataclass(frozen=True)
class SemanticReviewRequest:
    text: str
    anchor_id: str
    semantic_score: float
    threshold: float
    positive_anchor: str | None
    negative_anchor: str | None
    match_method: str


class HumanisticSemanticReviewer(Protocol):
    def review(self, request: SemanticReviewRequest) -> str:
        ...


class SemanticAnchorMatcher:
    def __init__(
        self,
        anchor_bank: Mapping[str, Any],
        *,
        embedding_client: HumanisticEmbeddingClient | None = None,
        reviewer: HumanisticSemanticReviewer | None = None,
        review_margin: float = 0.08,
    ) -> None:
        self._anchor_bank = anchor_bank
        self._embedding_client = embedding_client
        self._reviewer = reviewer
        self._review_margin = review_margin
        self._anchor_vector_cache: dict[tuple[str, str, tuple[str, ...]], list[list[float]]] = {}
        self._query_vector_cache: dict[str, list[float]] = {}

    def match(self, text: str, anchor_id: str) -> dict[str, Any]:
        if self._embedding_client is not None:
            try:
                return self._embedding_anchor_match(text, anchor_id)
            except Exception as exc:
                LOGGER.warning("Humanistic embedding anchor match failed; falling back to lexical anchors: %s", exc)
        return _lexical_anchor_match(
            text,
            anchor_id,
            self._anchor_bank,
            reviewer=self._reviewer,
            review_margin=self._review_margin,
        )

    def _embedding_anchor_match(self, text: str, anchor_id: str) -> dict[str, Any]:
        anchor = _anchor_payload(anchor_id, self._anchor_bank)
        positive_anchors = [str(item) for item in anchor.get("positive", []) if str(item)]
        negative_anchors = [str(item) for item in anchor.get("negative", []) if str(item)]
        text_vector = self._query_vector(text)
        positive_anchor, positive_score = self._best_embedding_anchor(text_vector, anchor_id, "positive", positive_anchors)
        negative_anchor, negative_score = self._best_embedding_anchor(text_vector, anchor_id, "negative", negative_anchors)
        semantic_score = max(0.0, min(1.0, positive_score - max(0.0, negative_score - 0.2)))
        threshold = float(anchor.get("threshold", 0.28) or 0.28)
        matched = semantic_score >= threshold and positive_score > negative_score
        return _apply_boundary_review(
            {
                "matched": matched,
                "semantic_score": round(semantic_score, 4),
                "positive_anchor": positive_anchor,
                "negative_anchor": negative_anchor,
                "anchor_bank_version": str(self._anchor_bank.get("version") or ""),
                "match_method": "embedding_anchor",
            },
            text=text,
            anchor_id=anchor_id,
            threshold=threshold,
            reviewer=self._reviewer,
            review_margin=self._review_margin,
        )

    def _query_vector(self, text: str) -> list[float]:
        normalized_text = str(text)
        if normalized_text not in self._query_vector_cache:
            vectors = self._embedding_client.embed_texts([normalized_text], task_type="RETRIEVAL_QUERY")  # type: ignore[union-attr]
            if len(vectors) != 1:
                raise ValueError("humanistic embedding client must return one query vector")
            self._query_vector_cache[normalized_text] = [float(value) for value in vectors[0]]
        return self._query_vector_cache[normalized_text]

    def _best_embedding_anchor(
        self,
        text_vector: list[float],
        anchor_id: str,
        polarity: str,
        anchors: list[str],
    ) -> tuple[str | None, float]:
        if not anchors:
            return None, 0.0
        anchor_vectors = self._anchor_vectors(anchor_id, polarity, anchors)
        scored = [
            (anchor, _cosine_similarity(text_vector, anchor_vector))
            for anchor, anchor_vector in zip(anchors, anchor_vectors)
        ]
        return max(scored, key=lambda item: item[1])

    def _anchor_vectors(self, anchor_id: str, polarity: str, anchors: list[str]) -> list[list[float]]:
        cache_key = (anchor_id, polarity, tuple(anchors))
        if cache_key not in self._anchor_vector_cache:
            vectors = self._embedding_client.embed_texts(anchors, task_type="RETRIEVAL_DOCUMENT")  # type: ignore[union-attr]
            if len(vectors) != len(anchors):
                raise ValueError("humanistic embedding client must return one vector for each anchor")
            self._anchor_vector_cache[cache_key] = [
                [float(value) for value in vector]
                for vector in vectors
            ]
        return self._anchor_vector_cache[cache_key]


def build_training_event_stream(session: Any) -> list[TrainingEvent]:
    events: list[TrainingEvent] = []
    for index, message in enumerate(_mapping_list(getattr(session, "messages", [])), start=1):
        role = str(message.get("role") or "").strip()
        content = str(message.get("content") or "").strip()
        if role not in {"student", "patient", "coach"} or not content:
            continue
        events.append(TrainingEvent(turn_index=index, event_type=f"{role}_utterance", role=role, content=content))
        if role == "patient" and _contains_any(content, PATIENT_EMOTION_KEYWORDS):
            events.append(
                TrainingEvent(
                    turn_index=index,
                    event_type="patient_emotion_signal",
                    role=role,
                    content=content,
                    label="患者表达担忧或焦虑",
                )
            )

    next_turn_index = max([event.turn_index for event in events], default=0) + 1
    for action in _mapping_list(getattr(session, "action_timeline", [])):
        action_type = str(action.get("action_type") or "").strip()
        if action_type not in {"physical_exam_requested", "auxiliary_test_requested", "diagnosis_submitted"}:
            continue
        raw_turn_index = action.get("turn_index")
        turn_index = int(raw_turn_index) if str(raw_turn_index).isdigit() else next_turn_index
        events.append(
            TrainingEvent(
                turn_index=turn_index,
                event_type=action_type,
                role="system",
                content=str(action.get("label") or action.get("source_id") or action_type),
                source_id=str(action.get("source_id") or ""),
                label=str(action.get("label") or ""),
            )
        )
        next_turn_index = max(next_turn_index, turn_index + 1)
    return sorted(events, key=lambda item: (item.turn_index, _event_sort_order(item.event_type)))


def load_anchor_bank(path: Path = ANCHOR_BANK_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"version": "humanistic_anchor_bank_missing", "anchors": {}}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {
        "version": str(payload.get("version") or "humanistic_anchor_bank_v1"),
        "anchors": payload.get("anchors") if isinstance(payload.get("anchors"), dict) else {},
    }


def semantic_anchor_match(text: str, anchor_id: str, anchor_bank: Mapping[str, Any]) -> dict[str, Any]:
    return _lexical_anchor_match(text, anchor_id, anchor_bank)


def build_humanistic_embedding_client_from_environment() -> HumanisticEmbeddingClient | None:
    try:
        from app.services.vertex_embedding_retriever import build_vertex_embedding_client_from_environment

        vertex_client = build_vertex_embedding_client_from_environment()
    except Exception as exc:
        LOGGER.warning("Humanistic Vertex embedding client initialization failed: %s", exc)
        vertex_client = None
    if vertex_client is not None:
        return vertex_client

    try:
        from app.services.local_embedding_retriever import build_local_embedding_client_from_environment

        return build_local_embedding_client_from_environment()
    except Exception as exc:
        LOGGER.warning("Humanistic local embedding client initialization failed: %s", exc)
        return None


def _lexical_anchor_match(
    text: str,
    anchor_id: str,
    anchor_bank: Mapping[str, Any],
    *,
    reviewer: HumanisticSemanticReviewer | None = None,
    review_margin: float = 0.08,
) -> dict[str, Any]:
    anchor = _anchor_payload(anchor_id, anchor_bank)
    positive_anchors = [str(item) for item in anchor.get("positive", []) if str(item)]
    negative_anchors = [str(item) for item in anchor.get("negative", []) if str(item)]
    positive_anchor, positive_score = _best_anchor_score(text, positive_anchors)
    negative_anchor, negative_score = _best_anchor_score(text, negative_anchors)
    semantic_score = max(0.0, min(1.0, positive_score - max(0.0, negative_score - 0.2)))
    threshold = float(anchor.get("threshold", 0.28) or 0.28)
    matched = semantic_score >= threshold and positive_score > negative_score
    return _apply_boundary_review({
        "matched": matched,
        "semantic_score": round(semantic_score, 4),
        "positive_anchor": positive_anchor,
        "negative_anchor": negative_anchor,
        "anchor_bank_version": str(anchor_bank.get("version") or ""),
        "match_method": "semantic_anchor",
    }, text=text, anchor_id=anchor_id, threshold=threshold, reviewer=reviewer, review_margin=review_margin)


def detect_missed_opportunities(events: list[TrainingEvent]) -> list[dict[str, Any]]:
    missed: list[dict[str, Any]] = []
    emotion_signals = [event for event in events if event.event_type == "patient_emotion_signal"]
    for signal in emotion_signals:
        next_student = _next_student_event(events, signal.turn_index, window=2)
        if next_student and _contains_any(next_student.content, ("理解", "担心", "焦虑", "害怕", "一起", "一步步")):
            continue
        missed.append(
            {
                "opportunity_id": f"relationship_empathy_missing:{signal.turn_index}",
                "gap_type": "relationship_empathy_missing",
                "stage": "history_taking",
                "trigger_evidence": signal.content,
                "expected_response": "患者表达担忧后，应先回应情绪，再继续医学问诊。",
                "next_training_action": "下一轮患者表达焦虑或担忧后，先用一句话承认情绪并说明会一起处理。",
            }
        )
    return missed


def _anchor_payload(anchor_id: str, anchor_bank: Mapping[str, Any]) -> Mapping[str, Any]:
    anchors = anchor_bank.get("anchors", {})
    anchor = anchors.get(anchor_id, {}) if isinstance(anchors, Mapping) else {}
    return anchor if isinstance(anchor, Mapping) else {}


def _apply_boundary_review(
    result: dict[str, Any],
    *,
    text: str,
    anchor_id: str,
    threshold: float,
    reviewer: HumanisticSemanticReviewer | None,
    review_margin: float,
) -> dict[str, Any]:
    if reviewer is None:
        return result
    semantic_score = float(result.get("semantic_score") or 0.0)
    if abs(semantic_score - threshold) > review_margin:
        return result
    status = _normalized_review_status(
        reviewer.review(
            SemanticReviewRequest(
                text=text,
                anchor_id=anchor_id,
                semantic_score=semantic_score,
                threshold=threshold,
                positive_anchor=result.get("positive_anchor"),
                negative_anchor=result.get("negative_anchor"),
                match_method=str(result.get("match_method") or ""),
            )
        )
    )
    result["llm_review_status"] = status
    if status == "accepted":
        result["matched"] = True
    elif status == "rejected":
        result["matched"] = False
    return result


def _normalized_review_status(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"accepted", "rejected", "uncertain"}:
        return normalized
    return "uncertain"


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(left_value * right_value for left_value, right_value in zip(left, right)) / (left_norm * right_norm)


def event_key(event: TrainingEvent) -> str:
    return f"{event.turn_index}:{event.event_type}:{event.content}"


def _best_anchor_score(text: str, anchors: list[str]) -> tuple[str | None, float]:
    if not anchors:
        return None, 0.0
    scored = [(anchor, _text_similarity(text, anchor)) for anchor in anchors]
    return max(scored, key=lambda item: item[1])


def _text_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens)
    containment = overlap / min(len(left_tokens), len(right_tokens))
    jaccard = overlap / len(left_tokens | right_tokens)
    synonym_boost = _semantic_hint_boost(left, right)
    return min(1.0, containment * 0.62 + jaccard * 0.28 + synonym_boost)


def _semantic_hint_boost(left: str, right: str) -> float:
    pairs = [
        ("担心", "担忧"),
        ("理解", "焦虑"),
        ("一起", "合作"),
        ("可以吗", "同意"),
        ("检查", "查体"),
        ("生活", "工作"),
        ("影响", "睡眠"),
    ]
    boost = 0.0
    for first, second in pairs:
        if (first in left and second in right) or (second in left and first in right):
            boost += 0.08
    return min(boost, 0.24)


def _tokens(text: str) -> set[str]:
    normalized = re.sub(r"\s+", "", text.lower())
    tokens = set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{1,2}", normalized))
    for phrase in [
        "担心",
        "担忧",
        "害怕",
        "焦虑",
        "理解",
        "一起",
        "一步步",
        "可以吗",
        "同意",
        "检查",
        "查体",
        "腹部",
        "不舒服",
        "生活",
        "影响",
        "目的",
        "隐私",
        "选择",
    ]:
        if phrase in normalized:
            tokens.add(phrase)
    return tokens


def _next_student_event(events: list[TrainingEvent], turn_index: int, *, window: int) -> TrainingEvent | None:
    for event in events:
        if event.role == "student" and turn_index < event.turn_index <= turn_index + window:
            return event
    return None


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _mapping_list(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _event_sort_order(event_type: str) -> int:
    return {
        "student_utterance": 1,
        "patient_utterance": 2,
        "patient_emotion_signal": 3,
        "physical_exam_requested": 4,
        "auxiliary_test_requested": 4,
        "diagnosis_submitted": 5,
    }.get(event_type, 9)
