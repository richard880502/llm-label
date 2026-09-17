from unittest.mock import Mock, patch

from backend.assistant.openclaw import _output_text, send_to_openclaw
from backend.routers.assistant import _extract_action


def test_output_text_collects_assistant_message_parts():
    payload = {
        "output": [
            {"type": "reasoning", "content": []},
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": "第一段"},
                    {"type": "output_text", "text": "第二段"},
                ],
            },
        ]
    }
    assert _output_text(payload) == "第一段\n第二段"


@patch("backend.assistant.openclaw.httpx.post")
def test_send_to_openclaw_uses_stable_user_and_previous_response(mock_post):
    response = Mock()
    response.json.return_value = {
        "id": "resp_2",
        "output": [{"type": "message", "content": [{"type": "output_text", "text": "完成"}]}],
    }
    response.raise_for_status.return_value = None
    mock_post.return_value = response

    text, response_id = send_to_openclaw(
        conversation_key="llm-label:3:alice",
        message="目前進度？",
        instructions="project context",
        previous_response_id="resp_1",
    )

    assert (text, response_id) == ("完成", "resp_2")
    body = mock_post.call_args.kwargs["json"]
    assert body["user"] == "llm-label:3:alice"
    assert body["previous_response_id"] == "resp_1"
    assert body["instructions"] == "project context"


def test_extract_action_keeps_markdown_and_validates_proposal():
    reply = """## 建議先試跑\n\n確認後會抽樣 10 筆。\n<assistant_action>{"type":"create_task","target":"pending","slot":1,"run_kind":"trial","sample_size":10}</assistant_action>"""

    content, action = _extract_action(reply)

    assert content == "## 建議先試跑\n\n確認後會抽樣 10 筆。"
    assert action == {
        "type": "create_task",
        "target": "pending",
        "slot": 1,
        "run_kind": "trial",
        "sample_size": 10,
    }


def test_extract_action_rejects_unapproved_action_type():
    reply = '不要執行<assistant_action>{"type":"delete_project","project_id":1}</assistant_action>'

    content, action = _extract_action(reply)

    assert content == "不要執行"
    assert action is None
