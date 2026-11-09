from __future__ import annotations

from backend.app.schemas import LocalModelStatusResponse
from backend.app.services.analysis import normalize_activity_analysis
from backend.app.services.llm import DayStoryPayload, LLMWindowPayload, llm_service
from backend.app.services.local_qwen import local_qwen_output_schema, local_qwen_service


def test_local_qwen_status_matches_setup_schema():
    status = LocalModelStatusResponse.model_validate(local_qwen_service.status())

    assert status.provider == "local_qwen35_4b"
    assert status.display_name == "Qwen3.5-4B-Q4_K_M+generic_v8"
    assert status.runtime_model == "unsloth/Qwen3.5-4B-GGUF:Q4_K_M"
    assert status.max_ctx_size >= status.ctx_size


def test_local_qwen_schema_keeps_benchmark_fields_constrained():
    schema = local_qwen_output_schema()

    assert schema["additionalProperties"] is False
    assert "primary_app" in schema["required"]
    assert "specific_task" in schema["required"]
    assert schema["properties"]["evidence"]["maxItems"] == 3
    assert schema["properties"]["uncertainty_notes"]["items"]["maxLength"] == 140
    assert schema["properties"]["confidence"]["maximum"] == 1


def test_qwen_benchmark_fields_map_to_product_analysis():
    analysis = normalize_activity_analysis(
        {
            "headline": "Reviewing local model settings",
            "summary": "The user is reviewing settings for the local Qwen model.",
            "activity_type": "review",
            "primary_app": "Workday Lens",
            "primary_project": "Local inference",
            "productivity": "productive",
            "focus_level": "focused",
            "user_goal": "Enable offline summaries.",
            "specific_task": "Check the local model setup option.",
            "evidence": ["Settings page names Local Qwen."],
            "uncertainty_notes": ["No inference result shown yet."],
            "unknown_fields": ["server_url"],
            "evidence_coverage_score": 0.8,
            "confidence": 0.72,
        }
    )

    assert analysis["project"] == "Local inference"
    assert analysis["goal"] == "Enable offline summaries."
    assert analysis["next_step"] == "Check the local model setup option."
    assert analysis["focus_state"] == "focused"
    assert analysis["primary_app"] == "Workday Lens"
    assert analysis["evidence"] == ["Settings page names Local Qwen."]


def test_local_qwen_prompt_keeps_benchmark_v8_guidance():
    prompt = llm_service._build_local_qwen_window_prompt(
        LLMWindowPayload(
            window_id="w1",
            session_id="s1",
            text="[12:00:00] [focus] app=Browser title=Local Dashboard\n[12:00:01] [mouse action] {\"action\":\"scrollDown\"}",
            policy=None,
            examples=[],
            context_summaries=[],
        )
    )

    assert "Silent analysis checklist before writing JSON" in prompt
    assert "Generic examples of the desired abstraction level" in prompt
    assert "Current NVDA-style Accessibility Transcript" in prompt
    assert "Return JSON only" in prompt


def test_local_qwen_payload_coercion_caps_schema_sized_fields():
    long_text = "x" * 220
    payload = llm_service._coerce_local_qwen_payload(
        {
            "headline": long_text,
            "summary": long_text,
            "evidence": [long_text, "second", "third", "fourth"],
            "unknown_fields": "not a list",
        }
    )

    assert len(payload["headline"]) <= 100
    assert len(payload["summary"]) <= 180
    assert len(payload["evidence"]) == 3
    assert all(len(item) <= 140 for item in payload["evidence"])
    assert payload["unknown_fields"] == []


def test_local_qwen_day_story_prompt_uses_full_local_schema():
    prompt = llm_service._build_local_qwen_day_story_prompt(
        DayStoryPayload(
            day="2026-07-03",
            total_segments=1,
            segments=[
                {
                    "source_level": "1d",
                    "source_role": "anchor",
                    "time_range": "9:00 AM - 5:00 PM",
                    "activity_label": "Focused work",
                    "project": "Local inference",
                    "headline": "Testing local Qwen",
                    "summary": "The day centered on validating local Qwen summaries.",
                }
            ],
        )
    )

    assert "dashboard day story" in prompt
    assert "headline, summary, activity_type, primary_app" in prompt
    assert "Return JSON only" in prompt
