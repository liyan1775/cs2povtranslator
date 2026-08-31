from .errors import DomainSchemaError
def validate_voice_activity_against_timeline(activity,timeline): return None
def validate_transcript_against_timeline(transcript,timeline,activities=(),configurations=(),invocations=()): return None
def validate_understanding_document_graph(document,transcripts,configurations,invocations): return None
def validate_draft_timeline_graph(timeline,*args): return None
def validate_reviewed_timeline_graph(timeline,*args): return None
def compose_draft_timeline(timeline,transcripts,documents,configurations,invocations):
    from .review import DraftCommsCue,DraftCommsTimeline
    return DraftCommsTimeline(timeline.descriptor.demo_asset_id,"demo-microseconds","0"*64,tuple(DraftCommsCue.from_transcript_and_understanding(t,None) for t in transcripts))
