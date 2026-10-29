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
    unsigned root_preheld,scope_seen,metadata_bad,descriptor_bad,owner_bad,dacl_missing,kind_mismatch;
    DWORD acl_mask[SP_HANDLES];
    unsigned untrusted[SP_HANDLES],ace_type[SP_HANDLES],ace_flags[SP_HANDLES];
    unsigned id_version[SP_HANDLES],security_version[SP_HANDLES];
    unsigned initial_id[SP_HANDLES],initial_security[SP_HANDLES],ace_checks;
    unsigned scope_fail_early,scope_fail_evidence,scope_fail_after_parents,file_attempts,outer_diagnostics;
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
static int model_output_file(unsigned which,const WCHAR *leaf) {
    WCHAR parent[SP_PATH],path[SP_PATH];
    if(!emission_parent_path(which,parent)||swprintf_s(path,SP_PATH,L"%ls\\%ls",parent,leaf)<0||
       !file_emission_allowed(path)) return 0;
    ++model.file_attempts; /* Synthetic effect only, AFTER the actual common gate. */
    return 1;
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
        if(model.root_preheld) {
            WCHAR path[SP_PATH];
            CHECK(operation_root_path(path)); fake_open(R_FIRST_DIR); sp.dir_count=1;
            if(!authorize_path(R_FIRST_DIR,path,1,0,P_CHAIN_DIRECTORY,1)) return 0;
        }
        return 1;
    case O_OPERATION_ROOT: {
        WCHAR path[SP_PATH]; int initial=sp.policy[R_FIRST_DIR].registered?0:1;
        if(!operation_root_path(path)) return 0;
        if(initial) { fake_open(R_FIRST_DIR); sp.dir_count=1; }
        if(!authorize_path(R_FIRST_DIR,path,1,1,P_STRICT_DIRECTORY,initial)) return 0;
        return register_operation_root(R_FIRST_DIR);
    }
    case O_SCOPE_ADMIT: {
        WCHAR path[SP_PATH];
        if(!require_operation_root()) return 0;
        if(model.scope_fail_early) return 0;
        fake_open(R_PROBE); fake_open(R_TARGET); fake_open(R_SELF);
        fake_open(R_FIRST_DIR+1); sp.dir_count=2;
        if(!emission_parent_path(0,path)||!authorize_path(R_FIRST_DIR+1,path,1,1,P_STRICT_DIRECTORY,1)) return 0;
        fake_open(R_FIRST_DIR+2); sp.dir_count=3;
        if(model.scope_fail_evidence) {
            model.acl_mask[R_FIRST_DIR+2]=0x4u; model.untrusted[R_FIRST_DIR+2]=1;
        }
        if(!emission_parent_path(1,path)||!authorize_path(R_FIRST_DIR+2,path,1,1,P_STRICT_DIRECTORY,1)) return 0;
        if(model.scope_fail_after_parents||!establish_emission_admission()) return 0;
        ++model.scope_seen;
        return model_output_file(1,L"custody.before.txt");
    }
    case O_POLICY_VALIDATE: {
        unsigned r=sp.current_resource; struct POLICY_STATE *p=&sp.policy[r];
        CHECK(p->pending&&p->registered&&p->retained_handle==sp.resource[r].handle);
        if(model.metadata_bad||model.kind_mismatch) return 0;
        /* Emulate immutable Win32 metadata, before the ACTUAL common predicate.
         * This is not execution of the excluded native filesystem adapter. */
        if(!sp.policy_initial&&(model.id_version[r]!=model.initial_id[r]||
            model.security_version[r]!=model.initial_security[r])) return 0;
        if(!policy_header_valid(!model.descriptor_bad,!model.owner_bad,!model.dacl_missing,1)) return 0;
        ++model.ace_checks;
        if(!policy_ace_allowed(p->role,(int)p->directory,(int)p->endpoint,
            model.ace_type[r],model.ace_flags[r],model.acl_mask[r],!model.untrusted[r])) return 0;
        if(sp.policy_initial) {
            model.initial_id[r]=model.id_version[r]; model.initial_security[r]=model.security_version[r];
        }
        return 1;
    }
    case O_RECHECK: return revalidate_cached_directories();
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
    case O_READY:
        if(!require_operation_root()) return 0;
        CHECK(model.scope_seen==1&&!sp.start_possible&&!sp.create_calls);
        model.ready_seen=1; return model_output_file(0,L"ready.txt");
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
    case O_EMIT:
        return model_output_file(1,L"child.stdout")&&model_output_file(1,L"child.stderr")&&
            model_output_file(1,L"custody.after.txt")&&model_output_file(1,L"final.txt");
    case O_OUTER_DIAGNOSTIC: ++model.outer_diagnostics; return 1;
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
    static const enum OP failures[]={O_ADMIT,O_OPERATION_ROOT,O_SCOPE_ADMIT,O_POLICY_VALIDATE,
        O_JOB,O_SET_LIMIT,O_GET_LIMIT,O_PIPE_OUT,O_PIPE_ERR,O_NUL,
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
/* Focused successor cases use actual common policy/cache/order functions.
 * Trustee classification and native metadata are injected, never Windows proof. */
static void ancestor_predicate_cases(void) {
    static const struct { const char *sid; int trusted; } trustees[]={
        {"S-1-5-11",0},{"S-1-5-32-545",0}
    };
    static const DWORD dangerous[]={0x2u,0x10u,0x40u,0x100u,0x10000u,0x40000u,
        0x80000u,0x40000000u,0x10000000u};
    static const enum POLICY_ROLE roles[]={P_CHAIN_DIRECTORY,P_STRICT_DIRECTORY,P_FILE};
    size_t i,j,k;
    CHECK(!strcmp(policy_role_name(P_CHAIN_DIRECTORY),"EXISTING_CHAIN_DIRECTORY"));
    CHECK(policy_mask(P_CHAIN_DIRECTORY)==0x500D0152u);
    CHECK(policy_mask(P_STRICT_DIRECTORY)==0x500D0156u&&policy_mask(P_FILE)==0x500D0156u);
    for(i=0;i<sizeof(trustees)/sizeof(trustees[0]);++i) {
        CHECK(trustees[i].sid[0]=='S'&&!trustees[i].trusted);
        CHECK(policy_ace_allowed(P_CHAIN_DIRECTORY,1,0,0,0,0x4u,trustees[i].trusted));
        CHECK(!policy_ace_allowed(P_STRICT_DIRECTORY,1,1,0,0,0x4u,trustees[i].trusted));
        CHECK(!policy_ace_allowed(P_FILE,0,0,0,0,0x4u,trustees[i].trusted));
        for(j=0;j<sizeof(dangerous)/sizeof(dangerous[0]);++j)
            for(k=0;k<sizeof(roles)/sizeof(roles[0]);++k) {
                int directory=roles[k]!=P_FILE,endpoint=roles[k]==P_STRICT_DIRECTORY;
                CHECK(!policy_ace_allowed(roles[k],directory,endpoint,0,0,dangerous[j],trustees[i].trusted));
                CHECK(!policy_ace_allowed(roles[k],directory,endpoint,0,0,dangerous[j]|0x4u,trustees[i].trusted));
            }
    }
    for(k=0;k<sizeof(roles)/sizeof(roles[0]);++k) {
        int directory=roles[k]!=P_FILE,endpoint=roles[k]==P_STRICT_DIRECTORY;
        CHECK(policy_ace_allowed(roles[k],directory,endpoint,0,0,0x001200a9u,0));
    }
    CHECK(!policy_ace_allowed(P_UNKNOWN,1,0,0,0,0,0));
    CHECK(!policy_ace_allowed((enum POLICY_ROLE)99,1,0,0,0,0,0));
    CHECK(!policy_ace_allowed(P_CHAIN_DIRECTORY,0,0,0,0,0,0));
    CHECK(!policy_ace_allowed(P_CHAIN_DIRECTORY,1,1,0,0,0,0));
    CHECK(!policy_ace_allowed(P_FILE,1,0,0,0,0,0));
    CHECK(!policy_ace_allowed(P_FILE,0,1,0,0,0,0));
    CHECK(!policy_ace_allowed(P_STRICT_DIRECTORY,0,0,0,0,0,0));
    CHECK(!policy_ace_allowed(P_STRICT_DIRECTORY,2,0,0,0,0,0));
    CHECK(policy_header_valid(1,1,1,0)&&policy_header_valid(1,1,1,128));
    CHECK(!policy_header_valid(0,1,1,1)&&!policy_header_valid(1,0,1,1));
    CHECK(!policy_header_valid(1,1,0,1)&&!policy_header_valid(1,1,1,129));
    /* OI|CI|NO_PROPAGATE remains effective here; IO is not current-object access.
     * No inheritance engine is simulated: the resulting child's ACE is separate. */
    CHECK(policy_ace_allowed(P_CHAIN_DIRECTORY,1,0,0,7,0x4u,0));
    CHECK(!policy_ace_allowed(P_STRICT_DIRECTORY,1,1,0,7,0x4u,0));
    CHECK(policy_ace_allowed(P_STRICT_DIRECTORY,1,1,0,8,0x500d0156u,0));
    CHECK(!policy_ace_allowed(P_STRICT_DIRECTORY,1,1,0,16,0x4u,0));
    CHECK(!policy_ace_allowed(P_FILE,0,0,0,16,0x4u,0));
    CHECK(!policy_ace_allowed(P_STRICT_DIRECTORY,1,1,5,0,0,1));
    CHECK(!policy_ace_allowed(P_CHAIN_DIRECTORY,1,0,9,8,0,1));
    CHECK(policy_ace_allowed(P_STRICT_DIRECTORY,1,1,1,0,0x4u,0));
    CHECK(!policy_ace_allowed(P_STRICT_DIRECTORY,1,1,0,0,0x4u,0));
}
static void weak_cache(void) {
    reset(); fake_open(R_FIRST_DIR);
    CHECK(authorize_path(R_FIRST_DIR,L"C:\\op",1,0,P_CHAIN_DIRECTORY,1));
}
static void ancestor_cache_cases(void) {
    unsigned before,ace_before; HANDLE retained;
    reset(); fake_open(R_FIRST_DIR);
    model.acl_mask[R_FIRST_DIR]=0x4u; model.untrusted[R_FIRST_DIR]=1;
    CHECK(authorize_path(R_FIRST_DIR,L"C:\\op",1,0,P_CHAIN_DIRECTORY,1));
    retained=sp.resource[R_FIRST_DIR].handle;
    CHECK(!authorize_path(R_FIRST_DIR,L"C:\\op",1,1,P_STRICT_DIRECTORY,0));
    CHECK(sp.policy[R_FIRST_DIR].role==P_STRICT_DIRECTORY&&sp.policy[R_FIRST_DIR].failed&&sp.policy[R_FIRST_DIR].pending);
    CHECK(!sp.policy[R_FIRST_DIR].authorized&&sp.failure&&sp.resource[R_FIRST_DIR].handle==retained);
    before=model.calls[O_POLICY_VALIDATE];
    CHECK(!authorize_path(R_FIRST_DIR,L"C:\\op",1,0,P_CHAIN_DIRECTORY,0));
    CHECK(model.calls[O_POLICY_VALIDATE]==before&&sp.policy[R_FIRST_DIR].role==P_STRICT_DIRECTORY);
    reset(); fake_open(R_FIRST_DIR);
    CHECK(authorize_path(R_FIRST_DIR,L"C:\\op",1,1,P_STRICT_DIRECTORY,1));
    retained=sp.resource[R_FIRST_DIR].handle;
    CHECK(authorize_path(R_FIRST_DIR,L"C:\\op",1,0,P_CHAIN_DIRECTORY,0));
    CHECK(sp.policy[R_FIRST_DIR].role==P_STRICT_DIRECTORY&&sp.policy[R_FIRST_DIR].endpoint);
    CHECK(sp.policy[R_FIRST_DIR].validations==2&&sp.resource[R_FIRST_DIR].handle==retained);
    weak_cache(); model.id_version[R_FIRST_DIR]=1; ace_before=model.ace_checks;
    CHECK(!authorize_path(R_FIRST_DIR,L"C:\\op",1,1,P_STRICT_DIRECTORY,0));
    CHECK(sp.policy[R_FIRST_DIR].role==P_STRICT_DIRECTORY&&model.ace_checks==ace_before&&sp.failure);
    weak_cache(); model.security_version[R_FIRST_DIR]=1; ace_before=model.ace_checks;
    CHECK(!authorize_path(R_FIRST_DIR,L"C:\\op",1,1,P_STRICT_DIRECTORY,0));
    CHECK(sp.policy[R_FIRST_DIR].role==P_STRICT_DIRECTORY&&model.ace_checks==ace_before&&sp.failure);
    weak_cache(); before=model.calls[O_POLICY_VALIDATE];
    sp.resource[R_FIRST_DIR].handle=(HANDLE)(uintptr_t)9999;
    CHECK(!authorize_path(R_FIRST_DIR,L"C:\\op",1,1,P_STRICT_DIRECTORY,0));
    CHECK(model.calls[O_POLICY_VALIDATE]==before&&sp.policy[R_FIRST_DIR].role==P_STRICT_DIRECTORY&&sp.failure);
    weak_cache(); before=model.calls[O_POLICY_VALIDATE];
    CHECK(!authorize_path(R_FIRST_DIR,L"C:\\other",1,1,P_STRICT_DIRECTORY,0));
    CHECK(model.calls[O_POLICY_VALIDATE]==before&&sp.failure);
    weak_cache(); CHECK(!authorize_path(R_FIRST_DIR,L"C:\\op",1,0,P_UNKNOWN,0));
    CHECK(sp.policy[R_FIRST_DIR].failed&&sp.failure);
    weak_cache(); sp.policy[R_FIRST_DIR].role=P_UNKNOWN;
    CHECK(!authorize_path(R_FIRST_DIR,L"C:\\op",1,0,P_CHAIN_DIRECTORY,0)); CHECK(sp.failure);
    weak_cache(); CHECK(!authorize_path(R_FIRST_DIR,L"C:\\op",0,0,P_FILE,0));
    CHECK(sp.policy[R_FIRST_DIR].failed&&sp.failure);
    weak_cache(); CHECK(!authorize_path(R_FIRST_DIR,L"C:\\op",1,0,P_CHAIN_DIRECTORY,1));
    CHECK(sp.policy[R_FIRST_DIR].failed&&sp.failure); /* no changed-baseline adoption */
    weak_cache(); model.metadata_bad=1;
    CHECK(!authorize_path(R_FIRST_DIR,L"C:\\op",1,0,P_CHAIN_DIRECTORY,0)); CHECK(sp.failure);
    weak_cache(); model.descriptor_bad=1;
    CHECK(!authorize_path(R_FIRST_DIR,L"C:\\op",1,0,P_CHAIN_DIRECTORY,0)); CHECK(sp.failure);
    weak_cache(); model.owner_bad=1;
    CHECK(!authorize_path(R_FIRST_DIR,L"C:\\op",1,0,P_CHAIN_DIRECTORY,0)); CHECK(sp.failure);
    weak_cache(); model.dacl_missing=1;
    CHECK(!authorize_path(R_FIRST_DIR,L"C:\\op",1,0,P_CHAIN_DIRECTORY,0)); CHECK(sp.failure);
    weak_cache(); model.kind_mismatch=1;
    CHECK(!authorize_path(R_FIRST_DIR,L"C:\\op",1,0,P_CHAIN_DIRECTORY,0)); CHECK(sp.failure);
    weak_cache(); model.ace_type[R_FIRST_DIR]=5;
    CHECK(!authorize_path(R_FIRST_DIR,L"C:\\op",1,0,P_CHAIN_DIRECTORY,0)); CHECK(sp.failure);
}
static void ancestor_order_cases(void) {
    int endpoint=0; WCHAR root[SP_PATH];
    CHECK(chain_endpoint(L"C:\\op\\capsule",3,1,&endpoint)&&!endpoint);
    CHECK(chain_endpoint(L"C:\\op\\capsule",13,1,&endpoint)&&endpoint);
    CHECK(chain_endpoint(L"C:\\op\\capsule\\bin.exe",13,0,&endpoint)&&endpoint);
    CHECK(chain_endpoint(L"C:\\op\\capsule\\bin.exe",5,0,&endpoint)&&!endpoint);
    CHECK(chain_endpoint(L"C:\\file",3,0,&endpoint)&&endpoint);
    CHECK(!chain_endpoint(L"C:\\op",5,0,&endpoint));
    CHECK(!chain_endpoint(L"C:\\op",3,2,&endpoint));
    CHECK(!chain_endpoint(L"C:\\op",4,1,&endpoint));
    reset(); CHECK(parse_manifest(manifest_fixture,sizeof(manifest_fixture)-1));
    wcscpy_s(sp.manifest_path,SP_PATH,L"D:\\elsewhere\\manifest.txt");
    CHECK(operation_root_path(root)&&!wcscmp(root,L"C:\\op"));
    CHECK(!os_call(O_SCOPE_ADMIT)); CHECK(!os_call(O_READY)); CHECK(!model.scope_seen&&!model.ready_seen);
    reset(); model.root_preheld=1; model.acl_mask[R_FIRST_DIR]=0x4u; model.untrusted[R_FIRST_DIR]=1;
    CHECK(!prepare()); CHECK(sp.failure&&sp.policy[R_FIRST_DIR].role==P_STRICT_DIRECTORY);
    CHECK(sp.policy[R_FIRST_DIR].failed&&!model.scope_seen&&!model.ready_seen&&!sp.create_calls);
    reset(); model.root_preheld=1; CHECK(prepare());
    CHECK(sp.policy[R_FIRST_DIR].role==P_STRICT_DIRECTORY&&sp.policy[R_FIRST_DIR].validations==2);
    CHECK(require_operation_root()&&model.scope_seen==1&&model.ready_seen&&!sp.create_calls);
    CHECK(revalidate_cached_directories());
    CHECK(sp.policy[R_FIRST_DIR].role==P_STRICT_DIRECTORY&&sp.policy[R_FIRST_DIR].validations==3);
    model.security_version[R_FIRST_DIR]=1;
    CHECK(!revalidate_cached_directories()&&sp.failure&&!require_operation_root());
    reset(); CHECK(parse_manifest(manifest_fixture,sizeof(manifest_fixture)-1));
    fake_open(R_FIRST_DIR); CHECK(authorize_path(R_FIRST_DIR,L"C:\\wrong",1,1,P_STRICT_DIRECTORY,1));
    CHECK(!register_operation_root(R_FIRST_DIR)&&!require_operation_root()&&sp.failure);
}
static void emission_admission_cases(void) {
    unsigned before;
    reset(); model.root_preheld=1; model.acl_mask[R_FIRST_DIR]=0x4u; model.untrusted[R_FIRST_DIR]=1;
    CHECK(!prepare()&&sp.manifest.evidence[0]); dispose();
    CHECK(finalize_output());
    CHECK(!model.file_attempts&&model.outer_diagnostics==1&&!model.calls[O_EMIT]);
    CHECK(!model_output_file(1,L"final.txt")); /* Direct emission gate also refuses. */
    reset(); model.scope_fail_early=1; CHECK(!prepare()); dispose();
    CHECK(finalize_output()); CHECK(!model.file_attempts&&model.outer_diagnostics==1&&!model.calls[O_EMIT]);
    reset(); model.scope_fail_evidence=1; CHECK(!prepare());
    CHECK(sp.policy[R_FIRST_DIR].authorized&&sp.policy[R_FIRST_DIR+2].failed);
    dispose(); CHECK(finalize_output()); CHECK(!model.file_attempts&&model.outer_diagnostics==1);
    reset(); model.scope_fail_after_parents=1; CHECK(!prepare()); dispose();
    CHECK(finalize_output()); CHECK(!model.file_attempts&&model.outer_diagnostics==1);
    reset(); CHECK(prepare()); CHECK(sp.emission.phase==E_LIVE&&emission_admission_valid());
    CHECK(!file_emission_allowed(L"C:\\op\\capsule\\final.txt"));
    CHECK(!model_output_file(1,L"unlisted.txt"));
    before=model.file_attempts; dispose();
    CHECK(sp.disposed&&sp.emission.phase==E_CLOSED&&!require_operation_root()&&emission_admission_valid());
    CHECK(!model_output_file(0,L"ready.txt"));
    CHECK(finalize_output()); CHECK(model.file_attempts==before+4&&!model.outer_diagnostics&&!sp.failure);
    /* Unrelated failed outcome does not erase admitted diagnostics or become PASS. */
    reset(); CHECK(prepare()); before=model.file_attempts; fail(590); dispose();
    CHECK(sp.failure&&sp.emission.phase==E_CLOSED&&emission_admission_valid());
    CHECK(finalize_output()); CHECK(sp.failure&&model.file_attempts==before+4&&!model.outer_diagnostics);
    reset(); CHECK(prepare()); before=model.file_attempts;
    model.fail_enabled=1; model.failure_op=O_CLOSE; dispose();
    CHECK(!sp.disposed&&sp.emission.phase==E_REFUSED&&!emission_admission_valid());
    CHECK(finalize_output()); CHECK(model.file_attempts==before&&model.outer_diagnostics==1);
    reset(); CHECK(prepare()); before=model.file_attempts;
    model.security_version[R_FIRST_DIR+2]=1; CHECK(!revalidate_cached_directories()); dispose();
    CHECK(sp.emission.phase==E_REFUSED&&!emission_admission_valid());
    CHECK(finalize_output()); CHECK(model.file_attempts==before&&model.outer_diagnostics==1);
}
int main(int argc,char **argv) {
    if(argc==2&&!strcmp(argv[1],"--ancestor-acl")) {
        ancestor_predicate_cases(); ancestor_cache_cases(); ancestor_order_cases(); emission_admission_cases();
        puts("inert supervisor ancestor ACL model: predicate/cache/order/emission cases complete");
        return 0;
    }
    if(argc!=1) return 2;
    parser_cases(); permit_cases(); acquisition_cases(); lifecycle_cases(); output_cases();
    puts("inert supervisor model: schema/permit/acquisition/lifecycle/output source cases complete");
    return 0;
}
