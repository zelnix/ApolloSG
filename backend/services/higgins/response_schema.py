"""The response Apollo requires from the investigation model, as a JSON-schema dict.

This is the ONLY place the required response shape is stated. It is never repeated or explained in
the prompt: the request sent through the AI gateway is the person's question, the complete case evidence,
and this schema. The provider adapter turns it into its provider's own structured-output schema
(services/higgins/adapters). `nullable: true` marks a value that may be null. Field names are the wire
(camelCase) names the validator in `validation.py` accepts, and the enums are the literal values
`contracts.py` defines — a schema drift here fails validation, which is reported honestly rather than
reshaped into a result.

Every id list is limited to the ids Apollo has actually registered for the case (`response_schema()`).
The model cannot know Apollo's ids, and with web search attached it otherwise cites search results by
ids of its own ("1.1.4") — in sourceIds, and once those were closed, in evidenceIds — which validation
rightly rejects, failing the live investigation.
"""
from __future__ import annotations

from services.higgins import outcomes

_STRING = {"type": "string"}
_STRING_LIST = {"type": "array", "items": {"type": "string"}}


def _enum(values: list[str], description: str) -> dict:
    return {"type": "string", "enum": values, "description": description}


def _id_list(ids: list[str], description: str) -> dict:
    """An array that can only hold registered ids — and must stay empty when none are registered."""
    if not ids:
        return {"type": "array", "items": _STRING, "maxItems": 0, "description": f"{description} None are registered: leave empty."}
    return {"type": "array", "items": {"type": "string", "enum": sorted(ids)}, "description": description}


def _finding(source_ids: list[str], evidence_ids: list[str]) -> dict:
    # 'observation' needs at least one evidenceId, so it is offered only when evidence is supplied.
    bases = (["observation"] if evidence_ids else []) + ["user_report", "inference"]
    return {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "One fact or inference, stated once. Each finding is a "
                                                      "distinct observation: anything describing the same underlying "
                                                      "issue is merged into one consolidated finding rather than "
                                                      "returned as several near-identical versions. Equivalent "
                                                      "hostnames (example.com and www.example.com) are the same "
                                                      "destination. A third-party search result or reputation score "
                                                      "is supporting context, not proof of wrongdoing — never the "
                                                      "sole basis for a concern-level finding."},
            "basis": _enum(bases,
                           "observation: present in the supplied evidence (requires at least one evidenceId). "
                           "user_report: stated by the person. inference: reasoned from the evidence."),
            "confidence": _enum(["low", "medium", "high"],
                                "high: an authoritative or official source directly establishes this fact. "
                                "medium: the evidence supports it but is not definitive. "
                                "low: inferred, from an unverified third-party source, or a weak signal on "
                                "its own. Confidence and risk level are independent: a high-risk scenario "
                                "with thin evidence is high risk but low confidence."),
            "evidenceIds": _id_list(evidence_ids, "Ids of the supplied evidence items this finding rests on."),
            "sourceIds": _id_list(source_ids, "Ids of registered sources, if any."),
            "supersedesFindingIds": {"type": "array", "items": _STRING, "description": "Ids of earlier findings this replaces, if any."},
        },
        "required": ["text", "basis", "confidence", "evidenceIds", "sourceIds", "supersedesFindingIds"],
    }


def _action(source_ids: list[str], capability_ids: list[str]) -> dict:
    # Device kinds exist only when the device advertises a capability; open_verified_source only when a
    # source is registered — otherwise the only answer validation can accept is 'instruction'.
    kinds = ["instruction"] + (["open_settings", "request_permission", "recheck"] if capability_ids else []) \
        + (["open_verified_source"] if source_ids else [])
    capability = {"type": "string", "nullable": True, "description": "Only for kinds that act on the device; otherwise null."}
    if capability_ids:
        capability["enum"] = sorted(capability_ids)
    return {
        "type": "object",
        "properties": {
            "kind": _enum(kinds, "Use 'instruction' unless a device capabilityId or a registered sourceId is available."),
            "label": {"type": "string", "description": "Short button label."},
            "instruction": {"type": "string", "description": "What the person does — the action only. It does not "
                                                             "restate a finding or re-explain the reasoning."},
            "capabilityId": capability,
            "sourceIds": _id_list(source_ids, "Required for open_verified_source."),
            "desiredField": {"type": "string", "nullable": True},
            "desiredValue": {"type": "string", "nullable": True},
        },
        "required": ["kind", "label", "instruction", "capabilityId", "sourceIds", "desiredField", "desiredValue"],
    }


_QUESTION = {
    "type": "object",
    "nullable": True,
    "properties": {
        "text": {"type": "string", "description": "The question to put to the person."},
        "reasonNeeded": {"type": "string", "description": "Why the answer is needed."},
        "answerType": _enum(["text", "yes_no", "choice"], "Expected answer form."),
        "choices": {"type": "array", "items": _STRING, "description": "Choices when answerType is 'choice'."},
    },
    "required": ["text", "reasonNeeded", "answerType", "choices"],
}


def response_schema(*, evidence_ids: list[str] = (), source_ids: list[str] = (), capability_ids: list[str] = ()) -> dict:
    """The required response for one call, with every id list limited to what is registered for the case."""
    evidence_ids, source_ids, capability_ids = list(evidence_ids), list(source_ids), list(capability_ids)
    return {
        "type": "object",
        "properties": {
            "overview": {"type": "string", "description": "2-4 plain sentences: what this is and what to do now. "
                                                          "The overall conclusion only — it does not enumerate the "
                                                          "evidence, list the findings or repeat any finding's text. "
                                                          "Before assessing risk, first identify the actual sender "
                                                          "from the evidence (sender domain, return-path, email "
                                                          "headers). A promotional email from one business that "
                                                          "mentions other brands is not impersonation of those brands."},
            "explanationMarkdown": {"type": "string", "description": "The briefing shown to the person, in Markdown: "
                                                                     "why the findings matter and how they fit "
                                                                     "together. It does not restate the overview and "
                                                                     "does not re-list the findings, uncertainties, "
                                                                     "scope or actions — each of those is returned in "
                                                                     "its own field and is displayed separately. "
                                                                     "Tone must be proportionate to demonstrated risk: "
                                                                     "low-confidence findings are presented as "
                                                                     "observations, not as warnings. Do not use "
                                                                     "alarming language unless high-confidence evidence "
                                                                     "of harm exists."},
            "assessment": _enum(["concern_found", "no_concern_found_within_scope", "uncertain"],
                                "'concern_found' requires at least one finding."),
            "outcome": {"type": "string", "enum": list(outcomes.OUTCOMES), "nullable": True, "description": outcomes.CRITERIA},
            "attention": _enum(["none", "review", "action_needed", "urgent"],
                               "'action_needed'/'urgent' require attentionReason and at least one action."),
            "attentionReason": {"type": "string", "nullable": True, "description": "One sentence on why this needs the "
                                                                                   "person's attention — the concrete "
                                                                                   "consequence of acting on it, based on "
                                                                                   "what the evidence actually shows. Never "
                                                                                   "a copy of a finding or of the overview. "
                                                                                   "Null when attention is 'none'. Must not "
                                                                                   "escalate beyond what the evidence "
                                                                                   "supports."},
            "findings": {"type": "array", "items": _finding(source_ids, evidence_ids), "description": "The evidence-backed facts. Compare them "
                                                                                                      "before answering and merge any that make "
                                                                                                      "the same point."},
            "uncertainties": {"type": "array", "items": _STRING, "description": "What could not be established."},
            "scope": {"type": "string", "description": "What this investigation did and did not cover."},
            "sourceIds": _id_list(source_ids, "Registered sourceIds relied on."),
            "remainingEvidenceIds": _id_list(evidence_ids, "Supplied evidence left unexamined."),
            "actions": {"type": "array", "items": _action(source_ids, capability_ids)},
            "recommendedActionIndex": {"type": "integer", "nullable": True,
                                       "description": "Index of the primary action; required when actions are present."},
            "question": _QUESTION,
            "completion": _enum(["complete", "partial", "waiting_user"],
                                "'waiting_user' requires a question; 'partial' when evidence remains unexamined."),
            "findingsRating": {"type": "integer", "nullable": True, "minimum": 0, "maximum": 100,
                               "description": "TC Hawkeye's own Findings Rating (0-100); the model never sets this."},
            "findingsRatingBreakdown": {"type": "object", "nullable": True,
                                        "description": "TC Hawkeye's own score breakdown; the model never sets this."},
        },
        "required": ["overview", "explanationMarkdown", "assessment", "outcome", "attention", "attentionReason", "findings",
                     "uncertainties", "scope", "sourceIds", "remainingEvidenceIds", "actions", "recommendedActionIndex",
                     "completion"],
    }


# The shape with nothing registered — for calls made outside any case.
RESPONSE_SCHEMA = response_schema()
