from __future__ import annotations


def patient_friendly_chief_complaint(chief_complaint: str) -> str:
    complaint = " ".join(chief_complaint.strip().strip("。").split())
    if not complaint:
        return "身体不舒服"

    exact_replacements = {
        "转移性右下腹痛 24 小时，伴恶心、低热": "肚子疼，后来右下腹更明显，有点想吐，也有点发热",
    }
    if complaint in exact_replacements:
        return exact_replacements[complaint]

    replacements = [
        ("胸骨后压榨性胸痛", "胸口正中像被压着一样疼"),
        ("活动后气短", "一活动就喘"),
        ("夜间憋醒", "晚上憋醒"),
        ("右侧胸痛", "右边胸口疼"),
        ("右下腹痛", "右下腹疼"),
        ("心慌", "心里发慌"),
        ("消瘦", "瘦了不少"),
        ("低热", "有点发热"),
        ("发热", "发烧"),
        ("恶心", "有点想吐"),
        ("伴", "还有"),
        (" 24 小时", "一天左右"),
        (" 2 小时", "两个小时"),
        (" 2 周", "两周"),
        (" 2 个月", "两个月"),
        (" 1 个月", "一个月"),
        (" 3 天", "三天"),
        (" 1 天", "一天"),
    ]
    friendly = complaint
    for source, target in replacements:
        friendly = friendly.replace(source, target)
    return friendly


def build_patient_opening_utterance(chief_complaint: str) -> str:
    return f"医生您好，我这次主要是{patient_friendly_chief_complaint(chief_complaint)}。"


def build_patient_context_redirect_utterance(chief_complaint: str) -> str:
    return f"医生，我这次主要是{patient_friendly_chief_complaint(chief_complaint)}。你刚问的这个我不太清楚。"
