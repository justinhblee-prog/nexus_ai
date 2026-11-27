"""Validated Korean fallback scripts for short-form video production."""


def fallback_script(channel_name, topic):
    subject = (str(topic or "").strip() or "오늘의 핵심 이슈")[:120]
    title = f"{subject} 핵심 정리 #Shorts"
    sentences = [
        f"지금 {subject}이 주목받는 이유를 짧게 정리해 보겠습니다.",
        "먼저 확인해야 할 사실과 배경부터 살펴보겠습니다.",
        "핵심은 서로 다른 정보와 의견을 구분해서 보는 것입니다.",
        "첫째, 확인된 근거가 무엇인지 살펴보세요.",
        "둘째, 아직 확인되지 않은 부분은 단정하지 않는 것이 중요합니다.",
        "새로운 정보가 나오면 내용을 다시 확인하고 업데이트하겠습니다.",
    ]
    return title, sentences, ""


def normalize_script_payload(data, channel_name, topic):
    if not isinstance(data, dict):
        return fallback_script(channel_name, topic)
    title = data.get("title")
    sentences = data.get("sentences")
    if not isinstance(title, str) or not title.strip() or not isinstance(sentences, list):
        return fallback_script(channel_name, topic)
    cleaned = [str(sentence).strip() for sentence in sentences if str(sentence).strip()]
    if not 4 <= len(cleaned) <= 8:
        return fallback_script(channel_name, topic)
    image_prompt = data.get("image_prompt", "")
    return title.strip()[:100], cleaned, str(image_prompt or "").strip()[:2000]
