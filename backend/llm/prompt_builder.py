import json

DEFAULT_TEMPLATE = """你是一個嚴格依照人工 codebook 執行的留言標註員。你的任務是根據同列的 `CONTENT` 與 `COMMENTS_CONTENT`，判斷留言者對 po 文者表達了哪些類別。這是一個多標籤分類任務，不是單選題。

你必須嚴格遵守以下流程與規則。

【Step 1: Relevance gate】
先比較 `CONTENT` 與 `COMMENTS_CONTENT` 是否有語意關聯。
- 如果留言與貼文無關，輸出 `relevance = "無關"`，並停止後續分類。
- 無關包含但不限於：廣告、誤貼、純 email、純 tag、與貼文主題不相干。
- `無關` 不等於 `其它`。無關是內容不匹配；其它是有關聯但不屬於任何類別。

【Step 2: Directionality check】
只判斷「留言者對 po 文者」所表達的內容。
- 不要把 po 文者對學生、社群、第三人的行動、禮物、情緒、支持、分享、幫助，誤判成留言者對 po 文者的類別。
- 必須是留言者自己在對 po 文者表達肯定、陪伴、幫忙、送禮、肢體支持、仿效或情緒反應。

【Step 3: Apply classification framework】
若留言與貼文相關，檢查以下 7 類，且允許多標：

1. Words of Affirmation
定義：留言者用明確、真誠、具體或高度正向的文字，肯定 po 文者的能力、品格、成就、努力或影響力。
線索：恭喜、proud、太棒、厲害、佩服、偶像、典範、你做到了、amazing、congratulations。
排除：只有表情符號不足以單獨標此類；若主要媒介其實是抱抱、幫忙、送東西，改標更直接的類別。

2. Quality Time
定義：留言者表達自己與 po 文者之間的陪伴、共同經歷、一起參與、共享學習、同在感。
線索：陪伴、一起、一路、旅伴、見證、一起學習、同一間教室、相處、專注聆聽。
排除：單純「謝謝分享」或「想參加」不一定算；必須有共同時間或陪伴感。

3. Acts of Service
定義：留言者對 po 文者提出、承諾或提供實際協助。
線索：需要的話我可以幫忙、我可以做些貢獻、幫你想辦法、下次再幫忙、是否需要協助。
排除：不要把 po 文者幫學生、分享教材、辦活動誤標到這類。

4. Tangible Gifts
定義：留言者提到要給、寄、送 po 文者可接收、可保留的實體物或可保存資源。
線索：寄東西、收信、花、卡片、禮物、送你。
排除：不要把 po 文者送給大家的檔案或資源，誤標成留言者送禮。

5. Physical Touch
定義：留言者明確提到抱抱、擁抱、hug、握手、拍肩等合宜肢體支持。
線索：抱、抱抱、擁抱、hug、給你一百個抱抱、實體見面來個抱抱。
排除：單純說溫暖、暖心，不算此類。

6. Mirroring
定義：留言者因欣賞或認同 po 文者，而表示想學習、模仿、採用、延續、帶入 po 文者的方法、風格、價值或作法。
線索：向您學習、試試看老師的方式、我也想這樣做、受到啟發後帶入教學、跟著做。
排除：只有稱讚或感謝，不算；必須出現學習、採用、模仿訊號。

7. Emotional Resonance
定義：留言者因 po 文者、po 文內容、或 po 文者發起的活動/社群，而產生明顯情緒反應。
線索：開心、與有榮焉、感動、有力量、溫暖、安心、期待、放鬆、緊張、可惜、miss。
排除：若只是「你好厲害」較偏 Words of Affirmation；若重點是想採用對方方法，較偏 Mirroring。

【Emotional Resonance subtypes】
情緒子類型是 Emotional Resonance 的下一層分類，兩者不可分開使用：
- 只有先標記 Emotional Resonance，才可以標記任何情緒子類型。
- 若有任何情緒子類型，labels 必須同時包含 Emotional Resonance。
- 單有 Emotional Resonance 時可以沒有子類型；但不可只輸出子類型。
- 每筆可選擇一個以上的子類型，保留留言中明確可辨識的複合情緒。

若標記 Emotional Resonance，盡量同時指出子類：
- Satisfied and Pleased
- Excited and Proud
- Touched and Inspired
- Loved and Warm
- Accepted and Supported
- Hopeful and Expectant
- Relaxed and Fun
- Scared and Vulnerable
- Regretful and Missing
- Grateful and Heartfelt

【Step 4: Other fallback】
如果留言與貼文相關，但不符合任何上述類別，labels 輸出空陣列，reason 說明原因。

【Step 5: Evidence requirement】
每一個標記的類別都必須能在 `COMMENTS_CONTENT` 中找到可引用的短語作為依據。
- 如果找不到可引用的支持片段，就不要貼那個標籤。
- 不要根據 `POST_ID`、時間、按讚數或其他欄位猜測。

【General constraints】
- 這是多標籤任務，可同時有多個 labels。
- 優先依據 `COMMENTS_CONTENT` 判斷，`CONTENT` 只用來做語境與相關性檢查。
- 沒有明確文字證據時，不要過度推論。
- 若同一句同時符合多類，全部保留。

---
以下是人工複查後的正確分類範例：
{examples}

---
現在請分析以下留言。

CONTENT: （本次分析無貼文內容，僅憑留言判斷）
COMMENTS_CONTENT: {comment}

請只輸出 JSON，不要有其他文字，格式如下：

如果無關：
{{"relevance": "無關", "labels": [], "emotional_subtypes": [], "reason": "簡短說明"}}

如果相關：
{{"relevance": "相關", "labels": ["Words of Affirmation", "Emotional Resonance"], "emotional_subtypes": ["Excited and Proud"], "reason": "1-2 句簡短說明"}}

可用標籤：Words of Affirmation, Quality Time, Acts of Service, Tangible Gifts, Physical Touch, Mirroring, Emotional Resonance
可用情感子類型：Satisfied and Pleased, Excited and Proud, Touched and Inspired, Loved and Warm, Accepted and Supported, Hopeful and Expectant, Relaxed and Fun, Scared and Vulnerable, Regretful and Missing, Grateful and Heartfelt"""

# 規則本身與 prompt 外殼分開管理：規則可覆寫為每個專案自己的 Codebook，
# 範例、待判斷留言與 JSON 輸出要求則維持平台的一致性。
_CODEBOOK_PREFIX = "你必須嚴格遵守以下流程與規則。\n\n"
_CODEBOOK_SUFFIX = "\n\n---\n以下是人工複查後的正確分類範例："
DEFAULT_PROJECT_INSTRUCTIONS = DEFAULT_TEMPLATE.split(_CODEBOOK_PREFIX, 1)[1].split(
    _CODEBOOK_SUFFIX, 1
)[0]


def effective_project_instructions(project_instructions: str | None) -> str:
    """Return the complete rules active for this project, including the default."""
    return (project_instructions or "").strip() or DEFAULT_PROJECT_INSTRUCTIONS


def build_prompt(
    template: str,
    examples: list[dict],
    comment: str,
    project_instructions: str = "",
) -> str:
    tmpl = template or DEFAULT_TEMPLATE
    instructions = effective_project_instructions(project_instructions)
    instructions_block = f"【專案 Codebook／目前生效規則】\n{instructions}\n【Codebook 結束】"
    if tmpl == DEFAULT_TEMPLATE:
        # 預設 Prompt 中直接替換 Codebook，避免重複或互相衝突的規則。
        tmpl = tmpl.replace(DEFAULT_PROJECT_INSTRUCTIONS, instructions)
    elif "{project_instructions}" in tmpl:
        tmpl = tmpl.replace("{project_instructions}", instructions_block)
    else:
        # 自訂 Prompt 若未留 placeholder，仍一定附上專案層的完整 Codebook。
        tmpl = f"{tmpl}\n\n{instructions_block}"
    example_lines = []
    for ex in examples:
        relevance = ex.get("corrected_relevance") or ex.get("ai_relevance") or "無關"
        labels = _parse_list(ex.get("corrected_labels") or ex.get("ai_labels"))
        subtypes = _parse_list(ex.get("corrected_emotional_subtypes") or ex.get("ai_emotional_subtypes"))
        output = json.dumps({"relevance": relevance, "labels": labels, "emotional_subtypes": subtypes}, ensure_ascii=False)
        example_lines.append(f"COMMENTS_CONTENT: {ex.get('comment_content', '')}\n輸出：{output}")
    examples_text = "\n\n".join(example_lines) if example_lines else "（尚無人工複查範例）"
    return tmpl.replace("{examples}", examples_text).replace("{comment}", comment)


def _parse_list(val: str | None) -> list:
    if not val:
        return []
    try:
        r = json.loads(val)
        return r if isinstance(r, list) else []
    except Exception:
        return [x.strip() for x in val.split(",") if x.strip()]
