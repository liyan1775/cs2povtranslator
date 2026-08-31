from dataclasses import dataclass
from .schema import *
from .fingerprint import content_fingerprint
from .errors import DomainSchemaError
@dataclass(frozen=True,slots=True)
class UnderstandingResult:
    cue_id:str; round_id:str; asr_original:str; interpreted_source:str; translated_zh:str; confidence:float; evidence:tuple[str,...]; warnings:tuple[str,...]; model_invocation_record_id:str
    def __post_init__(self):
        for v,p in ((self.cue_id,"cue_id"),(self.round_id,"round_id"),(self.model_invocation_record_id,"model_invocation_record_id")): require_identifier(v,p)
        for v,p in ((self.asr_original,"asr_original"),(self.interpreted_source,"interpreted_source"),(self.translated_zh,"translated_zh")): require_str(v,p)
        require_probability(self.confidence,"confidence"); object.__setattr__(self,"evidence",tuple(self.evidence)); object.__setattr__(self,"warnings",tuple(self.warnings));
        if not self.evidence or any(not isinstance(x,str) or not x for x in self.evidence): raise DomainSchemaError("domain_field_invalid","证据无效。","请修正后重试。")
    def to_dict(self): return {"schema_version":1,"cue_id":self.cue_id,"round_id":self.round_id,"asr_original":self.asr_original,"interpreted_source":self.interpreted_source,"translated_zh":self.translated_zh,"confidence":self.confidence,"evidence":list(self.evidence),"warnings":list(self.warnings),"model_invocation_record_id":self.model_invocation_record_id}
    def content_fingerprint(self): return content_fingerprint(self.to_dict())
    @classmethod
    def from_dict(cls,d):
        d=require_mapping(d,"result"); require_current_schema(d,"result"); require_exact_keys(d,{"schema_version","cue_id","round_id","asr_original","interpreted_source","translated_zh","confidence","evidence","warnings","model_invocation_record_id"},set(),"result"); return cls(d["cue_id"],d["round_id"],d["asr_original"],d["interpreted_source"],d["translated_zh"],d["confidence"],tuple(d["evidence"]),tuple(d["warnings"]),d["model_invocation_record_id"])
@dataclass(frozen=True,slots=True)
class RoundUnderstandingDocument:
    round_id:str; input_fingerprint:str; model_configuration_snapshot_id:str; invocation_record_id:str|None; results:tuple[UnderstandingResult,...]
    def __post_init__(self):
        require_identifier(self.round_id,"round_id"); require_sha256(self.input_fingerprint,"input_fingerprint"); require_identifier(self.model_configuration_snapshot_id,"model_configuration_snapshot_id"); object.__setattr__(self,"results",tuple(self.results));
        if any(r.round_id!=self.round_id for r in self.results) or (self.results and self.invocation_record_id is None): raise DomainSchemaError("round_reference_invalid","回合文档无效。","请修正后重试。")
        if self.invocation_record_id is not None: require_identifier(self.invocation_record_id,"invocation_record_id")
    def to_dict(self): return {"schema_version":1,"round_id":self.round_id,"input_fingerprint":self.input_fingerprint,"model_configuration_snapshot_id":self.model_configuration_snapshot_id,"invocation_record_id":self.invocation_record_id,"results":[r.to_dict() for r in self.results]}
    @classmethod
    def from_dict(cls,d):
        d=require_mapping(d,"round_understanding"); require_current_schema(d,"round_understanding"); require_exact_keys(d,{"schema_version","round_id","input_fingerprint","model_configuration_snapshot_id","invocation_record_id","results"},set(),"round_understanding");
        if not isinstance(d["results"],(list,tuple)): raise DomainSchemaError("domain_field_invalid","结果无效。","请修正后重试。")
        return cls(d["round_id"],d["input_fingerprint"],d["model_configuration_snapshot_id"],d["invocation_record_id"],tuple(UnderstandingResult.from_dict(x) for x in d["results"]))
def validate_understanding_against_transcript(result,cue):
    if result.cue_id!=cue.cue_id or result.round_id!=cue.round_id or result.asr_original!=cue.asr_original: raise DomainSchemaError("cue_reference_invalid","提示来源不匹配。","请重新生成。")
