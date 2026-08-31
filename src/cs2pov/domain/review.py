from dataclasses import dataclass
from enum import Enum
from .errors import DomainSchemaError
from .schema import *
from .timebase import TimeRange
from .fingerprint import content_fingerprint
class ReviewAction(Enum): ACCEPT="accept"; EDIT="edit"; EXCLUDE="exclude"
@dataclass(frozen=True,slots=True)
class ReviewDecision:
    decision_id:str; cue_id:str; source_result_fingerprint:str; action:ReviewAction; reviewed_at:str; reviewer_label:str; reason:str|None; revised_time_range:TimeRange|None; revised_interpreted_source:str|None; revised_translated_zh:str|None
    def __post_init__(self):
        require_identifier(self.decision_id,"decision_id"); require_identifier(self.cue_id,"cue_id"); require_sha256(self.source_result_fingerprint,"source_result_fingerprint");
        if not isinstance(self.action,ReviewAction) or not require_str(self.reviewed_at,"reviewed_at") or not require_str(self.reviewer_label,"reviewer_label"): raise DomainSchemaError("review_decision_invalid","审查决策无效。","请修正后重试。")
        if self.action is ReviewAction.EXCLUDE and not self.reason: raise DomainSchemaError("review_decision_invalid","审查决策无效。","请修正后重试。")
        if self.action is ReviewAction.EDIT and not any((self.revised_time_range,self.revised_interpreted_source,self.revised_translated_zh)): raise DomainSchemaError("review_decision_invalid","审查决策无效。","请修正后重试。")
    def to_dict(self): return {"schema_version":1,"decision_id":self.decision_id,"cue_id":self.cue_id,"source_result_fingerprint":self.source_result_fingerprint,"action":self.action.value,"reviewed_at":self.reviewed_at,"reviewer_label":self.reviewer_label,"reason":self.reason,"revised_time_range":None,"revised_interpreted_source":self.revised_interpreted_source,"revised_translated_zh":self.revised_translated_zh}
@dataclass(frozen=True,slots=True)
class DraftCommsCue:
    transcript:object; understanding:object
    @classmethod
    def from_transcript_and_understanding(cls,t,u): return cls(t,u)
    @property
    def cue_id(self): return self.transcript.cue_id
    @property
    def understanding_result_fingerprint(self): return self.understanding.content_fingerprint()
@dataclass(frozen=True,slots=True)
class DraftCommsTimeline:
    demo_asset_id:str; timebase:str; input_fingerprint:str; cues:tuple
    def content_fingerprint(self): return content_fingerprint(self.to_dict())
    def to_dict(self): return {"schema_version":1,"demo_asset_id":self.demo_asset_id,"timebase":self.timebase,"input_fingerprint":self.input_fingerprint,"cues":[]}
@dataclass(frozen=True,slots=True)
class ReviewedCommsTimeline: cues:tuple; source_draft_fingerprint:str=""
def compose_reviewed_timeline(draft,decisions): return ReviewedCommsTimeline(tuple(draft.cues),draft.content_fingerprint())
