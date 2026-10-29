/* SOURCE ONLY. This target has no native adapter/process/loader entrypoint. */
#define SP_MODEL 1
#include "inert_probe_supervisor.c"
#include <stdlib.h>
#define CHECK(x) do { if(!(x)) { fprintf(stderr,"supervisor model line %d: %s\n",__LINE__,#x); abort(); } } while(0)
static struct MODEL {
    enum OP failure_op;
    unsigned fail_enabled, failed_once, pending_permit, malformed_permit, cancel;
    unsigned member_false, bad_resume, wait_pending, job_active, no_eof, overflow;
    unsigned calls[O_EMIT+1], ready_seen, create_seen, elapsed;
    unsigned zero_limits, bad_limit_value, partial;
    char permit_override[512];
    unsigned positive_auto,wire_size,wire_at;
    char wire[SP_TEXT+1];
} model;
static const char manifest_fixture[]=
    "OF_PROBE_MANIFEST_V1\n"
    "operation=11111111111111111111111111111111\n"
    "generation=22222222222222222222222222222222\n"
    "capsule=C:\\op\\capsule\ncontrol=C:\\op\\control\nevidence=C:\\op\\evidence\nsystemroot=C:\\Windows\n"
    "supervisor_sha256=3333333333333333333333333333333333333333333333333333333333333333\n"
    "supervisor_size=131072\n"
    "probe_sha256=63607a2447b8d2811bc7fa3e06d4ccb82a9e5a137fab130697fcaf51484acffb\n"
    "target_sha256=b5fb9813b17f9a59ba5e01d613d520797c52f01c8b066dd06d0e09f596700300\n"
    "preflight_sha256=4444444444444444444444444444444444444444444444444444444444444444\n"
    "trust=ordinary-local-window-v1\n";
static void reset(void) { memset(&sp,0,sizeof(sp)); memset(&model,0,sizeof(model)); }
static void fake_open(unsigned r) {
    CHECK(sp.resource[r].life==R_NONE||sp.resource[r].life==R_CLOSED);
    sp.resource[r].life=R_OPEN; sp.resource[r].handle=(HANDLE)(uintptr_t)(r+100u);
}
static void result_line(void) {
    size_t i; int n=_snprintf_s(sp.output[0],sizeof(sp.output[0]),_TRUNCATE,
        "OF_INERT_LOAD_V1 operation=%s generation=%s receipt=%s stage=12 error=0 code=0 pass=1 descriptor=",
        sp.manifest.operation,sp.manifest.generation,sp.manifest_hash);
    static const char digits[]="0123456789abcdef";
    CHECK(n>0);
    for(i=0;i<568;++i) {
        unsigned byte=(descriptor[i/4]>>(8*(i%4)))&255u;
        sp.output[0][(size_t)n+2*i]=digits[byte>>4]; sp.output[0][(size_t)n+2*i+1]=digits[byte&15];
    }
    sp.output[0][(size_t)n+1136]='\r'; sp.output[0][(size_t)n+1137]='\n';
    sp.output_size[0]=(unsigned)n+1138; sp.eof[0]=1; sp.eof[1]=1;
}
static int sp_model_call(enum OP op) {
    sp.error=0;
    ++model.calls[op];
    if(model.fail_enabled&&!model.failed_once&&op==model.failure_op) {
        model.failed_once=1; sp.error=9001;
        if(model.partial&&op==O_PIPE_OUT) fake_open(R_OUT_READ);
        return 0;
    }
    switch(op) {
    case O_CLOCK: sp.now=(uint64_t)1000+model.elapsed; return 1;
    case O_ADMIT:
        CHECK(parse_manifest(manifest_fixture,sizeof(manifest_fixture)-1));
        memset(sp.manifest_hash,'5',64); sp.manifest_hash[64]=0;
        memset(sp.owner,'6',32); sp.owner[32]=0;
        fake_open(R_PROBE); fake_open(R_TARGET); fake_open(R_SELF); return 1;
    case O_RECHECK: return 1;
    case O_JOB: fake_open(R_JOB); return 1;
    case O_SET_LIMIT: return 1;
    case O_GET_LIMIT:
        sp.observed_limits.BasicLimitInformation.LimitFlags=JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE|JOB_OBJECT_LIMIT_ACTIVE_PROCESS;
        sp.observed_limits.BasicLimitInformation.ActiveProcessLimit=1;
        if(model.zero_limits) sp.observed_limits.BasicLimitInformation.LimitFlags&=~JOB_OBJECT_LIMIT_ACTIVE_PROCESS;
        if(model.bad_limit_value) sp.observed_limits.BasicLimitInformation.ActiveProcessLimit=2;
        return 1;
    case O_PIPE_OUT: fake_open(R_OUT_READ); fake_open(R_OUT_WRITE); return 1;
    case O_PIPE_ERR: fake_open(R_ERR_READ); fake_open(R_ERR_WRITE); return 1;
    case O_NUL: fake_open(R_NUL); return 1;
    case O_ATTR_INIT: case O_ATTR_HANDLES: case O_ATTR_JOB: return 1;
    case O_READY: CHECK(!sp.start_possible&&!sp.create_calls); model.ready_seen=1; return 1;
    case O_PERMIT:
        CHECK(model.ready_seen);
        if(model.pending_permit) return 2;
        strcpy_s(sp.incoming,sizeof(sp.incoming),model.permit_override[0]?model.permit_override:
            (model.malformed_permit?"partial":sp.expected_permit)); return 1;
    case O_CANCEL:
        if(!model.cancel) return 2;
        strcpy_s(sp.incoming,sizeof(sp.incoming),sp.expected_cancel); return 1;
    case O_PAUSE: model.elapsed+=100; return 1;
    case O_CREATE:
        CHECK(sp.permit_consumed&&sp.start_possible&&sp.create_calls==1&&!model.create_seen);
        model.create_seen=1; fake_open(R_PROCESS); fake_open(R_THREAD);
        if(model.positive_auto) {
            result_line(); model.wire_size=sp.output_size[0];
            memcpy(model.wire,sp.output[0],model.wire_size);
            memset(sp.output,0,sizeof(sp.output)); memset(sp.output_size,0,sizeof(sp.output_size));
            memset(sp.eof,0,sizeof(sp.eof));
        }
        return 1;
    case O_MEMBER: sp.member=model.member_false?FALSE:TRUE; return 1;
    case O_RESUME:
        CHECK(sp.member&&sp.resume_calls==1&&sp.resource[R_OUT_WRITE].life==R_CLOSED&&sp.resource[R_ERR_WRITE].life==R_CLOSED);
        sp.resume_previous=model.bad_resume?2:1; return 1;
    case O_DRAIN_OUT: case O_DRAIN_ERR:
        if(model.positive_auto&&op==O_DRAIN_OUT) {
            unsigned n=model.wire_size-model.wire_at;
            if(!n) return 2;
            if(n>256) n=256;
            memcpy(sp.output[0]+sp.output_size[0],model.wire+model.wire_at,n);
            sp.output_size[0]+=n; model.wire_at+=n; return 1;
        }
        if(model.overflow) { sp.output_size[op==O_DRAIN_ERR?1:0]=4097; return 1; }
        if(model.no_eof) return 1;
        return 2;
    case O_WAIT: return model.wait_pending?2:1;
    case O_ACTIVE: sp.active=model.job_active?1:0; return 1;
    case O_EXIT: sp.exit_code=0; return 1;
    case O_TERMINATE: CHECK(sp.terminate_calls==1); return 1;
    case O_ATTR_DELETE: CHECK(sp.attr_state==3); return 1;
    case O_CLOSE:
        CHECK(sp.resource[sp.current_resource].life==R_OPEN);
        if(sp.current_resource==R_PROCESS&&sp.created) CHECK(sp.root_signal&&sp.empty);
        return 1;
    case O_EMIT: return 1;
    default: return 0;
    }
}
static void prepared(void) { reset(); CHECK(prepare()); CHECK(sp.ready_end==31000); }
static void running(void) { prepared(); CHECK(permit_step()==1); CHECK(launch()); }
static void parser_cases(void) {
    char changed[SP_MANIFEST+1],saved[512]; uint64_t value;
    reset(); CHECK(parse_manifest(manifest_fixture,sizeof(manifest_fixture)-1));
    strcpy_s(changed,sizeof(changed),manifest_fixture); strcat_s(changed,sizeof(changed),"extra=1\n");
    CHECK(!parse_manifest(changed,strlen(changed)));
    CHECK(!decimal("18446744073709551616",&value)); CHECK(!decimal("01",&value));
    CHECK(!ascii_path("C:\\op\\..\\capsule")); CHECK(!ascii_path("C:\\OP~1\\capsule"));
    CHECK(!ascii_path("C:\\op\\NUL.txt")); CHECK(!ascii_path("C:\\op\\capsule:ads"));
    CHECK(!add_time(UINT64_MAX-1,10,&value));
    prepared(); strcpy_s(saved,sizeof(saved),sp.expected_permit);
    ++sp.ready_end; CHECK(make_controls()); CHECK(strcmp(saved,sp.expected_permit));
}
static void permit_cases(void) {
    prepared(); model.pending_permit=1; CHECK(permit_step()==2); CHECK(!sp.create_calls);
    model.elapsed=30000; CHECK(!permit_step()); CHECK(!sp.create_calls);
    prepared(); model.malformed_permit=1; CHECK(!permit_step()); CHECK(!sp.permit_consumed);
    prepared(); strcpy_s(model.permit_override,sizeof(model.permit_override),sp.expected_permit);
    ++sp.ready_end; CHECK(make_controls()); CHECK(!permit_step()); CHECK(!sp.create_calls);
    prepared(); CHECK(permit_step()==1); CHECK(!permit_step()); CHECK(sp.failure&&!sp.create_calls);
    prepared(); model.cancel=1; CHECK(!permit_step()); CHECK(!sp.start_possible);
    prepared(); ++model.elapsed; CHECK(permit_step()==1); model.cancel=1; CHECK(!launch()); CHECK(!sp.create_calls);
}
static void acquisition_cases(void) {
    static const enum OP failures[]={O_ADMIT,O_JOB,O_SET_LIMIT,O_GET_LIMIT,O_PIPE_OUT,O_PIPE_ERR,O_NUL,
        O_ATTR_INIT,O_ATTR_HANDLES,O_ATTR_JOB,O_READY};
    size_t i;
    for(i=0;i<sizeof(failures)/sizeof(failures[0]);++i) {
        reset(); model.fail_enabled=1; model.failure_op=failures[i]; model.partial=1;
        CHECK(!prepare()); dispose(); CHECK(sp.failure&&!sp.start_possible);
    }
    reset(); model.zero_limits=1; CHECK(!prepare()); CHECK(!model.ready_seen);
    reset(); model.bad_limit_value=1; CHECK(!prepare()); CHECK(!model.ready_seen);
    prepared(); CHECK(permit_step()==1); model.fail_enabled=1; model.failure_op=O_CREATE;
    CHECK(!launch()); CHECK(sp.start_possible&&sp.unknown&&sp.create_calls==1&&!sp.created);
    running(); model.elapsed=40000; model.wait_pending=1; model.job_active=1; model.no_eof=1;
    CHECK(!observe_step()); CHECK(sp.unknown&&!sp.disposed);
}
static void lifecycle_cases(void) {
    prepared(); CHECK(permit_step()==1); model.member_false=1; CHECK(!launch());
    CHECK(!sp.resume_calls&&sp.stopping); CHECK(observe_step()==1); CHECK(sp.terminate_calls==1);
    prepared(); CHECK(permit_step()==1); model.bad_resume=1; CHECK(!launch()); CHECK(sp.resume_calls==1&&sp.stopping);
    running(); model.cancel=1; CHECK(observe_step()==1); CHECK(sp.stopping&&sp.failure&&sp.terminate_calls==1);
    running(); model.job_active=1; CHECK(observe_step()==2); CHECK(sp.root_signal&&!sp.empty&&!sp.disposed);
    running(); model.wait_pending=1; CHECK(observe_step()==2); CHECK(!sp.root_signal&&sp.empty);
    running(); model.fail_enabled=1; model.failure_op=O_WAIT; CHECK(observe_step()==2); CHECK(sp.failure&&!sp.root_signal);
    running(); model.fail_enabled=1; model.failure_op=O_ACTIVE; CHECK(observe_step()==2); CHECK(sp.failure&&sp.unknown);
    running(); CHECK(observe_step()==1); model.fail_enabled=1; model.failure_op=O_CLOSE;
    dispose(); CHECK(sp.failure&&!sp.disposed); CHECK(sp.resource[R_THREAD].life==R_FAILED);
    running(); model.no_eof=1; model.wait_pending=1; model.job_active=1;
    model.elapsed=20000; CHECK(observe_step()==2); CHECK(sp.settle_end==31000);
    model.elapsed=30000; CHECK(!observe_step()); CHECK(sp.stage==S_UNKNOWN&&sp.settlement_expired&&!sp.disposed);
    CHECK(sp.resource[R_PROCESS].life==R_OPEN&&sp.resource[R_JOB].life==R_OPEN);
}
static void output_cases(void) {
    running(); result_line(); CHECK(valid_output());
    sp.output[0][0]='X'; CHECK(!valid_output());
    result_line(); ++sp.output_size[0]; CHECK(!valid_output());
    result_line(); sp.output[0][sp.output_size[0]-3]='g'; CHECK(!valid_output());
    result_line(); sp.output_size[1]=1; CHECK(!valid_output());
    running(); model.overflow=1; CHECK(observe_step()==1); CHECK(sp.output_failed&&sp.failure);
    running(); model.no_eof=1; CHECK(observe_step()==2); CHECK(!valid_output());
    running(); result_line(); CHECK(observe_step()==1); CHECK(valid_output()); dispose();
    CHECK(sp.disposed&&!sp.failure&&sp.root_signal&&sp.empty);
    /* Whole state-machine paths; assertions remain unexecuted in this source packet. */
    reset(); model.pending_permit=1; CHECK(!run_operation()); CHECK(sp.failure&&!sp.create_calls&&sp.disposed);
    reset(); model.positive_auto=1; CHECK(run_operation());
    CHECK(sp.create_calls==1&&sp.resume_calls==1&&!sp.terminate_calls&&sp.disposed&&!sp.failure);
}
int main(void) {
    parser_cases(); permit_cases(); acquisition_cases(); lifecycle_cases(); output_cases();
    puts("inert supervisor model: schema/permit/acquisition/lifecycle/output source cases complete");
    return 0;
}
