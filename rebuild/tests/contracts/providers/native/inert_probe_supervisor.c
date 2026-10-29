/* One ordinary C-only inert probe. SOURCE ONLY until separate Main release.
 * No target DLL is linked or loaded here. SP_MODEL excludes ALL native adapters.
 * Surviving supervisor, responsive OS and approved immutable local window required. */
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0A00
#endif
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>
#include <limits.h>
#ifndef SP_MODEL
#include <bcrypt.h>
#include <aclapi.h>
#endif

enum { SP_PATH=240, SP_TEXT=4096, SP_MANIFEST=4096, SP_HANDLES=128 };
enum LIFE { R_NONE, R_ENTERED, R_OPEN, R_CLOSED, R_FAILED };
enum RESOURCE { R_TOKEN, R_MANIFEST, R_PROBE, R_TARGET, R_SELF, R_JOB,
    R_OUT_READ, R_OUT_WRITE, R_ERR_READ, R_ERR_WRITE, R_NUL, R_PROCESS,
    R_THREAD, R_READY, R_PERMIT, R_CANCEL, R_FINAL, R_LOG_OUT, R_LOG_ERR, R_FIND,
    R_FIRST_DIR };
enum STAGE { S_INPUT=1, S_ADMISSION, S_PREPARE, S_READY, S_PERMIT,
    S_CREATE, S_MEMBER, S_RESUME, S_RUNNING, S_SETTLE, S_DISPOSE, S_FINISHED,
    S_UNKNOWN };
enum OP { O_CLOCK, O_ADMIT, O_RECHECK, O_JOB, O_SET_LIMIT, O_GET_LIMIT,
    O_PIPE_OUT, O_PIPE_ERR, O_NUL, O_ATTR_INIT, O_ATTR_HANDLES, O_ATTR_JOB,
    O_READY, O_PERMIT, O_CANCEL, O_PAUSE, O_CREATE, O_MEMBER, O_RESUME,
    O_DRAIN_OUT, O_DRAIN_ERR, O_WAIT, O_ACTIVE, O_EXIT, O_TERMINATE,
    O_ATTR_DELETE, O_CLOSE, O_EMIT };
/* Adapter return: 1 success, 2 absent/pending/EOF (operation-specific), 0 failure.
 * All API outputs land in this pre-existing static record before projection. */
struct RESOURCE_STATE { HANDLE handle; enum LIFE life; DWORD error; };
struct MANIFEST {
    char operation[33], generation[33], supervisor_hash[65], preflight[65];
    char capsule[SP_PATH], control[SP_PATH], evidence[SP_PATH], systemroot[SP_PATH];
    uint64_t supervisor_size;
};
static struct SUPERVISOR {
    struct MANIFEST manifest;
    struct RESOURCE_STATE resource[SP_HANDLES];
    PROCESS_INFORMATION pi;
    STARTUPINFOEXW startup;
    union { uint64_t align; unsigned char bytes[4096]; } attributes;
    SIZE_T attribute_bytes;
    HANDLE inherited[3], jobs[1];
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits, observed_limits;
    BOOL member;
    DWORD resume_previous, wait_result, active, exit_code, error;
    enum STAGE stage;
    unsigned failure, first_failure, first_error, unknown, permit_consumed, create_calls;
    unsigned resume_calls, terminate_calls, start_possible, created, root_signal;
    unsigned empty, exit_seen, attr_state, disposed, output_failed, current_resource;
    unsigned eof[2], output_size[2], native_calls;
    uint64_t now, last_clock, preflight_end, ready_end, work_end, settle_end;
    unsigned clock_seen, stopping, settlement_expired;
    char manifest_text[SP_MANIFEST+1], manifest_hash[65], owner[33];
    char expected_permit[512], expected_cancel[512], ready[1024], final[2048];
    char incoming[1024], output[2][SP_TEXT+1];
    WCHAR manifest_path[SP_PATH], path[3][SP_PATH], control_path[SP_PATH];
    WCHAR command[2048], environment[1024], cwd[SP_PATH];
#ifndef SP_MODEL
    BCRYPT_ALG_HANDLE algorithm;
    unsigned algorithm_open;
    FILE_ID_INFO identity[SP_HANDLES];
    unsigned char digest[32], file_bytes[524288], security[65536], token_info[1024];
    unsigned char security_hash[SP_HANDLES][32];
    WCHAR held_path[SP_HANDLES][SP_PATH];
    char custody_receipt[65536];
    WIN32_FIND_DATAW find_data;
    WIN32_FIND_STREAM_DATA stream_data;
    unsigned dir_count;
#endif
} sp;

static const char target_hash[]="b5fb9813b17f9a59ba5e01d613d520797c52f01c8b066dd06d0e09f596700300";
static const char probe_hash[]="63607a2447b8d2811bc7fa3e06d4ccb82a9e5a137fab130697fcaf51484acffb";
/* Independent literal wire fixture, not generated from target headers/results. */
static const uint32_t descriptor[142]={
    0x4942464Fu,1,568,142,6,136,1,0x8664,1,1,8,8,8,8,8,8,4,4,1,
    4,4,1,8,8,1,2,2,1,4,4,1,4,4,1,131072,86424,8,65536,14744,8,64,96,64,32,11,8,8,1,
    0x08080404,0x2000,16,16,1,1,512,4,6,36,4,0,16,32,4100,4,0,1024,2048,3072,4096,
    32,8,0,8,12,16,24,32,8,0,4,8,16,24,184,8,0,40,48,52,56,60,64,112,136,140,144,148,152,
    0,1,2,3,4,5,6,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,
    0,1,2,3,4,5,0,1,2,3,0,1,2,3,4,5,1,2,3,1,2,3
};
_Static_assert(sizeof(descriptor)==568,"independent descriptor bytes");
_Static_assert(sizeof(void *)==8,"reviewed Windows x64 only");

static void fail(unsigned reason) {
    if (!sp.failure) { sp.first_failure=reason; sp.first_error=sp.error; }
    sp.failure=1;
}
static int add_time(uint64_t start, uint64_t delta, uint64_t *end) {
    if (start>UINT64_MAX-delta) { fail(100); return 0; }
    *end=start+delta; return 1;
}
static int lower_hex(const char *p,size_t count) {
    size_t i; unsigned nonzero=0;
    if (strlen(p)!=count) return 0;
    for(i=0;i<count;++i) {
        if (!((p[i]>='0'&&p[i]<='9')||(p[i]>='a'&&p[i]<='f'))) return 0;
        nonzero|=(unsigned)(p[i]!='0');
    }
    return nonzero!=0;
}
static int decimal(const char *p,uint64_t *out) {
    uint64_t value=0; size_t n=0;
    if (!p[0] || (p[0]=='0'&&p[1])) return 0;
    while(p[n]) {
        unsigned digit=(unsigned char)p[n]-(unsigned)'0';
        if(digit>9 || n>=20 || value>(UINT64_MAX-digit)/10u) return 0;
        value=value*10u+digit; ++n;
    }
    *out=value; return 1;
}
static int ascii_path(const char *p) {
    size_t n=strlen(p),i,start=3;
    if(n<4 || n>=SP_PATH || p[0]<'A'||p[0]>'Z'||p[1]!=':'||p[2]!='\\') return 0;
    for(i=3;i<=n;++i) {
        unsigned char c=(unsigned char)p[i];
        if(c=='\\'||c==0) {
            size_t len=i-start,j; char base[9]={0};
            if(!len||p[i-1]=='.'||p[i-1]==' ') return 0;
            for(j=0;j<len&&j<8&&p[start+j]!='.';++j) {
                char b=p[start+j]; base[j]=(b>='a'&&b<='z')?(char)(b-'a'+'A'):b;
            }
            if(!strcmp(base,"CON")||!strcmp(base,"PRN")||!strcmp(base,"AUX")||!strcmp(base,"NUL")||
                (!strncmp(base,"COM",3)&&base[3]>='1'&&base[3]<='9'&&!base[4])||
                (!strncmp(base,"LPT",3)&&base[3]>='1'&&base[3]<='9'&&!base[4])) return 0;
            start=i+1;
        } else if(c<32||c>126||strchr("/:*?\"<>|~",c)) return 0;
    }
    return 1;
}
static int field(const char **cursor,const char *key,char *out,size_t cap) {
    const char *p=*cursor; size_t k=strlen(key),n=0;
    if(strncmp(p,key,k)) return 0;
    p+=k;
    while(p[n]&&p[n]!='\n') { if((unsigned char)p[n]<32||(unsigned char)p[n]>126||n+1>=cap) return 0; ++n; }
    if(p[n]!='\n') return 0;
    memcpy(out,p,n); out[n]=0; *cursor=p+n+1; return 1;
}
static int parse_manifest(const char *text,size_t bytes) {
    const char *p=text; char size[24],fixed[80]; struct MANIFEST m;
    memset(&m,0,sizeof(m));
    if(bytes>SP_MANIFEST||strlen(text)!=bytes||strncmp(p,"OF_PROBE_MANIFEST_V1\n",21)) return 0;
    p+=21;
    if(!field(&p,"operation=",m.operation,sizeof(m.operation))||!lower_hex(m.operation,32)||
       !field(&p,"generation=",m.generation,sizeof(m.generation))||!lower_hex(m.generation,32)||
       !field(&p,"capsule=",m.capsule,sizeof(m.capsule))||!ascii_path(m.capsule)||
       !field(&p,"control=",m.control,sizeof(m.control))||!ascii_path(m.control)||
       !field(&p,"evidence=",m.evidence,sizeof(m.evidence))||!ascii_path(m.evidence)||
       !field(&p,"systemroot=",m.systemroot,sizeof(m.systemroot))||!ascii_path(m.systemroot)||
       !field(&p,"supervisor_sha256=",m.supervisor_hash,sizeof(m.supervisor_hash))||!lower_hex(m.supervisor_hash,64)||
       !field(&p,"supervisor_size=",size,sizeof(size))||!decimal(size,&m.supervisor_size)||
       m.supervisor_size<4096||m.supervisor_size>524288u||
       !field(&p,"probe_sha256=",fixed,sizeof(fixed))||strcmp(fixed,probe_hash)||
       !field(&p,"target_sha256=",fixed,sizeof(fixed))||strcmp(fixed,target_hash)||
       !field(&p,"preflight_sha256=",m.preflight,sizeof(m.preflight))||!lower_hex(m.preflight,64)||
       !field(&p,"trust=",fixed,sizeof(fixed))||strcmp(fixed,"ordinary-local-window-v1")||*p) return 0;
    /* Fixed sibling directory names; capsule cannot overlap control/evidence. */
    { size_t n=strlen(m.capsule); const char *leaf=strrchr(m.capsule,'\\');
      if(!leaf||strcmp(leaf,"\\capsule")||n<8||strlen(m.control)!=n||
          strncmp(m.capsule,m.control,n-7)||strcmp(m.control+n-7,"control")||
          strlen(m.evidence)!=n+1||strncmp(m.capsule,m.evidence,n-7)||strcmp(m.evidence+n-7,"evidence")) return 0; }
    sp.manifest=m; return 1;
}
static int make_controls(void) {
    int n=_snprintf_s(sp.expected_permit,sizeof(sp.expected_permit),_TRUNCATE,
        "OF_PROBE_PERMIT_V1\noperation=%s\ngeneration=%s\nmanifest=%s\nowner=%s\nexpiry=%llu\n",
        sp.manifest.operation,sp.manifest.generation,sp.manifest_hash,sp.owner,(unsigned long long)sp.ready_end);
    if(n<0) return 0;
    n=_snprintf_s(sp.expected_cancel,sizeof(sp.expected_cancel),_TRUNCATE,
        "OF_PROBE_CANCEL_V1\noperation=%s\ngeneration=%s\nmanifest=%s\nowner=%s\nexpiry=%llu\n",
        sp.manifest.operation,sp.manifest.generation,sp.manifest_hash,sp.owner,(unsigned long long)sp.ready_end);
    if(n<0) return 0;
    n=_snprintf_s(sp.ready,sizeof(sp.ready),_TRUNCATE,
        "OF_PROBE_READY_V1\noperation=%s\ngeneration=%s\nmanifest=%s\nowner=%s\nexpiry=%llu\nsupervisor=%s\npreflight=%s\n",
        sp.manifest.operation,sp.manifest.generation,sp.manifest_hash,sp.owner,(unsigned long long)sp.ready_end,
        sp.manifest.supervisor_hash,sp.manifest.preflight);
    return n>0;
}
#ifdef SP_MODEL
static int sp_model_call(enum OP op);
#define os_call(op) sp_model_call(op)
#else
static int native_call(enum OP op);
#define os_call(op) native_call(op)
#endif
static int checked(enum OP op) {
    int result=os_call(op);
    if(result!=1) { fail(200u+(unsigned)op); return 0; }
    return 1;
}
static int clock_read(void) {
    if(!checked(O_CLOCK)) return 0;
    if(sp.clock_seen&&sp.now<sp.last_clock) { sp.now=sp.last_clock; fail(101); return 0; }
    sp.clock_seen=1; sp.last_clock=sp.now; return 1;
}
static void stop_now(unsigned reason) {
    uint64_t origin;
    fail(reason);
    if(sp.stopping) return;
    sp.stopping=1;
    origin=(sp.work_end&&sp.work_end<sp.now)?sp.work_end:sp.now;
    if(!add_time(origin,10000,&sp.settle_end)) { sp.unknown=1; sp.settle_end=sp.now; }
}
static int cancelled(void) {
    int result=os_call(O_CANCEL);
    if(result==2) return 0;
    if(result!=1||strcmp(sp.incoming,sp.expected_cancel)) { fail(301); return 1; }
    fail(302); return 1;
}
static int drain(unsigned which) {
    int result; unsigned before=sp.output_size[which];
    if(sp.eof[which]) return 1;
    result=os_call(which?O_DRAIN_ERR:O_DRAIN_OUT);
    if(sp.output_size[which]>SP_TEXT || sp.output_size[which]<before ||
       sp.output_size[which]-before>256u || sp.output_size[0]+sp.output_size[1]>8192u||!result) {
        sp.output_failed=1; fail(303); return 0;
    }
    if(result==2) sp.eof[which]=1;
    return 1;
}
static unsigned unhex(char c) {
    if(c>='0'&&c<='9') return (unsigned)(c-'0');
    if(c>='a'&&c<='f') return (unsigned)(c-'a')+10u;
    return 256;
}
static int valid_output(void) {
    char prefix[384]; size_t at,i; int n;
    if(sp.output_size[1]||sp.output_failed||!sp.eof[0]||!sp.eof[1]) return 0;
    n=_snprintf_s(prefix,sizeof(prefix),_TRUNCATE,
        "OF_INERT_LOAD_V1 operation=%s generation=%s receipt=%s stage=12 error=0 code=0 pass=1 descriptor=",
        sp.manifest.operation,sp.manifest.generation,sp.manifest_hash);
    if(n<0) return 0;
    at=(size_t)n;
    if(memcmp(sp.output[0],prefix,at)) return 0;
    /* MSVC text-mode stdout emits CRLF; a single LF is also a complete line.
     * No other whitespace, trailing bytes or duplicate line is accepted. */
    if(!((sp.output_size[0]==at+1137u&&sp.output[0][at+1136]=='\n')||
        (sp.output_size[0]==at+1138u&&sp.output[0][at+1136]=='\r'&&sp.output[0][at+1137]=='\n'))) return 0;
    for(i=0;i<142;++i) {
        unsigned b; uint32_t word=0;
        for(b=0;b<4;++b) {
            unsigned a=unhex(sp.output[0][at+8*i+2*b]),c=unhex(sp.output[0][at+8*i+2*b+1]);
            if(a>15||c>15) return 0;
            word|=(uint32_t)((a<<4)|c)<<(8*b);
        }
        if(word!=descriptor[i]) return 0;
    }
    return 1;
}
static int close_one(unsigned index) {
    struct RESOURCE_STATE *r=&sp.resource[index];
    if(r->life==R_NONE||r->life==R_CLOSED) return 1;
    if(r->life!=R_OPEN) { fail(304); return 0; }
    sp.current_resource=index;
    if(!checked(O_CLOSE)) { r->life=R_FAILED; return 0; }
    r->life=R_CLOSED; return 1; /* Numeric handles retained, no destructive retry. */
}
static void dispose(void) {
    unsigned i;
    sp.stage=S_DISPOSE;
    if(sp.attr_state==2) {
        sp.attr_state=3;
        if(checked(O_ATTR_DELETE)) sp.attr_state=4;
    }
    if(sp.attr_state&&sp.attr_state!=4) fail(305);
    /* No pending synchronous read/wait exists at this point. */
    close_one(R_THREAD); close_one(R_PROCESS);
    close_one(R_OUT_WRITE); close_one(R_ERR_WRITE); close_one(R_NUL);
    close_one(R_OUT_READ); close_one(R_ERR_READ); close_one(R_JOB);
    for(i=0;i<SP_HANDLES;++i) close_one(i);
    sp.disposed=1;
    for(i=0;i<SP_HANDLES;++i)
        if(sp.resource[i].life!=R_NONE&&sp.resource[i].life!=R_CLOSED) sp.disposed=0;
    if(!sp.disposed) fail(306);
}
/* Steps are also the model harness entrypoints: no second implementation. */
static int prepare(void) {
    static const enum OP setup[]={ O_JOB,O_SET_LIMIT,O_GET_LIMIT,O_PIPE_OUT,O_PIPE_ERR,O_NUL,
        O_ATTR_INIT,O_ATTR_HANDLES,O_ATTR_JOB };
    size_t i;
    sp.stage=S_ADMISSION;
    if(!clock_read()||!add_time(sp.now,10000,&sp.preflight_end)||!checked(O_ADMIT)) return 0;
    if(!clock_read()||sp.now>=sp.preflight_end) { fail(330); return 0; }
    sp.stage=S_PREPARE;
    for(i=0;i<sizeof(setup)/sizeof(setup[0]);++i) {
        if(setup[i]==O_ATTR_INIT) sp.attr_state=1;
        if(!checked(setup[i])) return 0;
        if(setup[i]==O_ATTR_INIT) sp.attr_state=2;
        if(!clock_read()||sp.now>=sp.preflight_end) { fail(307); return 0; }
    }
    if(sp.observed_limits.BasicLimitInformation.LimitFlags!=
        (JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE|JOB_OBJECT_LIMIT_ACTIVE_PROCESS)||
        sp.observed_limits.BasicLimitInformation.ActiveProcessLimit!=1) { fail(308); return 0; }
    if(!add_time(sp.now,30000,&sp.ready_end)||!make_controls()) { fail(309); return 0; }
    sp.stage=S_READY; return checked(O_READY);
}
static int permit_step(void) {
    int result;
    if(sp.failure||sp.permit_consumed) { fail(310); return 0; }
    if(!clock_read()||sp.now>=sp.ready_end||cancelled()) { fail(311); return 0; }
    result=os_call(O_PERMIT);
    if(result==2) return 2;
    if(result!=1||strcmp(sp.incoming,sp.expected_permit)) { fail(312); return 0; }
    sp.permit_consumed=1; sp.stage=S_PERMIT;
    return 1;
}
static int launch(void) {
    if(sp.failure||!sp.permit_consumed||sp.create_calls) { fail(313); return 0; }
    if(!clock_read()||sp.now>=sp.ready_end||cancelled()||!checked(O_RECHECK)||
        !clock_read()||sp.now>=sp.ready_end) { fail(314); return 0; }
    if(!add_time(sp.now,20000,&sp.work_end)) return 0;
    sp.start_possible=1; ++sp.create_calls; sp.stage=S_CREATE;
    if(!checked(O_CREATE)) { sp.unknown=1; stop_now(315); return 0; }
    sp.created=1;
    /* Parent write copies close after creation, before the sole resume. */
    close_one(R_OUT_WRITE); close_one(R_ERR_WRITE);
    sp.stage=S_MEMBER;
    if(!checked(O_MEMBER)||!sp.member||sp.failure||!clock_read()||sp.now>=sp.work_end||cancelled()) {
        stop_now(316); return 0;
    }
    ++sp.resume_calls; sp.stage=S_RESUME;
    if(!checked(O_RESUME)||sp.resume_previous!=1) { stop_now(317); return 0; }
    sp.stage=S_RUNNING; return 1;
}
static int observe_step(void) {
    int result;
    if(!clock_read()) { sp.unknown=1; stop_now(318); }
    if(!sp.stopping && (sp.failure||sp.now>=sp.work_end||cancelled())) stop_now(319);
    if(sp.stopping&&!sp.terminate_calls) { ++sp.terminate_calls; checked(O_TERMINATE); }
    drain(0); drain(1);
    if(!sp.root_signal&&sp.created) {
        result=os_call(O_WAIT);
        if(!result) stop_now(320);
        else if(result==1) sp.root_signal=1;
    }
    if(!checked(O_ACTIVE)) { sp.unknown=1; stop_now(321); }
    else sp.empty=(sp.active==0);
    if(sp.root_signal&&!sp.exit_seen) {
        if(checked(O_EXIT)) sp.exit_seen=1; else stop_now(322);
    }
    if(sp.created&&sp.root_signal&&sp.empty&&sp.exit_seen&&
        ((sp.eof[0]&&sp.eof[1])||sp.output_failed)) return 1;
    if(sp.failure&&!sp.stopping) stop_now(323);
    if(sp.stopping&&sp.now>=sp.settle_end) {
        sp.unknown=1; sp.settlement_expired=1; sp.stage=S_UNKNOWN; return 0;
    }
    if(!sp.stopping&&sp.root_signal&&sp.empty) {
        /* EOF must settle within the original work deadline, never a new window. */
        if(sp.now>=sp.work_end) stop_now(324);
    }
    return 2;
}
static int run_operation(void) {
    int result;
    if(!prepare()) { dispose(); return 0; }
    do { result=permit_step(); if(result==2&&!checked(O_PAUSE)) result=0; } while(result==2);
    if(!result) { dispose(); return 0; }
    launch();
    if(sp.start_possible) {
        do { result=observe_step(); if(result==2&&!checked(O_PAUSE)) stop_now(325); } while(result==2);
        if(!result) return 0; /* Ownership remains retained in S_UNKNOWN. */
    }
    if(!sp.created||!sp.root_signal||!sp.empty||!sp.exit_seen||sp.exit_code||!valid_output()) fail(326);
    if(!checked(O_RECHECK)) fail(327);
    if(!clock_read()||sp.now>=(sp.stopping?sp.settle_end:sp.work_end)) fail(328);
    dispose();
    if(!clock_read()||sp.now>=(sp.stopping?sp.settle_end:sp.work_end)) fail(329);
    sp.stage=S_FINISHED;
    return !sp.failure&&!sp.unknown&&sp.disposed;
}

#ifndef SP_MODEL
/* All native code is absent, not merely runtime-disabled, in the injected target. */
static HANDLE *handle_at(unsigned index) {
    if(index==R_PROCESS) return &sp.pi.hProcess;
    if(index==R_THREAD) return &sp.pi.hThread;
    return &sp.resource[index].handle;
}
static int wide(const char *ascii,WCHAR *out,size_t cap) {
    size_t n=strlen(ascii),i;
    if(n>=cap) return 0;
    for(i=0;i<=n;++i) out[i]=(WCHAR)(unsigned char)ascii[i];
    return 1;
}
static int join(const char *dir,const char *leaf,WCHAR *out) {
    char text[SP_PATH];
    if(_snprintf_s(text,sizeof(text),_TRUNCATE,"%s\\%s",dir,leaf)<0) return 0;
    return ascii_path(text)&&wide(text,out,SP_PATH);
}
static void hex_bytes(const unsigned char *bytes,size_t n,char *out) {
    static const char digits[]="0123456789abcdef"; size_t i;
    for(i=0;i<n;++i) { out[i*2]=digits[bytes[i]>>4]; out[i*2+1]=digits[bytes[i]&15]; }
    out[n*2]=0;
}
static int hash_data(const void *bytes,ULONG n,unsigned char out[32]) {
    NTSTATUS result=BCryptHash(sp.algorithm,NULL,0,(PUCHAR)bytes,n,out,32);
    if(result<0) { sp.error=(DWORD)result; return 0; }
    return 1;
}
static int native_close(unsigned index) {
    BOOL result=(index==R_FIND)?FindClose(*handle_at(index)):CloseHandle(*handle_at(index));
    if(!result) { sp.error=GetLastError(); sp.resource[index].error=sp.error; }
    return result!=0;
}
static int open_file(unsigned index,const WCHAR *path,DWORD access,DWORD share,DWORD creation,DWORD flags) {
    struct RESOURCE_STATE *r=&sp.resource[index];
    if(r->life!=R_NONE&&r->life!=R_CLOSED) return 0;
    r->life=R_ENTERED;
    r->handle=CreateFileW(path,access,share,NULL,creation,flags,NULL);
    if(r->handle==INVALID_HANDLE_VALUE) {
        sp.error=GetLastError(); r->error=sp.error; r->life=R_NONE; return 0;
    }
    r->life=R_OPEN; return 1;
}
static int read_exact(unsigned index,void *bytes,DWORD count) {
    DWORD got=0;
    if(!ReadFile(*handle_at(index),bytes,count,&got,NULL)) { sp.error=GetLastError(); return 0; }
    return got==count;
}
static int read_small(unsigned index,const WCHAR *path,char *bytes,DWORD cap,int missing_ok) {
    LARGE_INTEGER size;
    if(!open_file(index,path,GENERIC_READ|READ_CONTROL,FILE_SHARE_READ,OPEN_EXISTING,FILE_FLAG_OPEN_REPARSE_POINT))
        return missing_ok&&sp.error==ERROR_FILE_NOT_FOUND?2:0;
    if(!GetFileSizeEx(*handle_at(index),&size)) { sp.error=GetLastError(); return 0; }
    if(size.QuadPart<=0||size.QuadPart>=(LONGLONG)cap) return 0;
    if(!read_exact(index,bytes,(DWORD)size.QuadPart)) return 0;
    bytes[(size_t)size.QuadPart]=0;
    if(strlen(bytes)!=(size_t)size.QuadPart) return 0;
    return 1;
}
static int trusted_sid(PSID sid) {
    unsigned char system_sid[SECURITY_MAX_SID_SIZE],admins_sid[SECURITY_MAX_SID_SIZE];
    DWORD n=sizeof(system_sid),m=sizeof(admins_sid);
    static const struct { BYTE revision,count; SID_IDENTIFIER_AUTHORITY authority; DWORD sub[6]; } installer={
        1,6,{{0,0,0,0,0,5}},{80,956008885u,3418522649u,1831038044u,1853292631u,2271478464u}};
    if(!IsValidSid(sid)||!CreateWellKnownSid(WinLocalSystemSid,NULL,system_sid,&n)||
       !CreateWellKnownSid(WinBuiltinAdministratorsSid,NULL,admins_sid,&m)) return 0;
    return EqualSid(sid,((TOKEN_USER *)sp.token_info)->User.Sid)||EqualSid(sid,system_sid)||
        EqualSid(sid,admins_sid)||EqualSid(sid,(PSID)&installer);
}
static int security_check(unsigned index,int initial) {
    DWORD needed=0; PSID owner=NULL; PACL acl=NULL; BOOL defaulted=FALSE,present=FALSE;
    ACL_SIZE_INFORMATION info; unsigned i; unsigned char digest[32];
    const DWORD mutation=GENERIC_ALL|GENERIC_WRITE|WRITE_DAC|WRITE_OWNER|DELETE|
        FILE_WRITE_DATA|FILE_APPEND_DATA|FILE_WRITE_EA|FILE_WRITE_ATTRIBUTES|FILE_DELETE_CHILD;
    if(!GetKernelObjectSecurity(*handle_at(index),OWNER_SECURITY_INFORMATION|DACL_SECURITY_INFORMATION,
        (PSECURITY_DESCRIPTOR)sp.security,sizeof(sp.security),&needed)) { sp.error=GetLastError(); return 0; }
    if(!needed||needed>sizeof(sp.security)||!IsValidSecurityDescriptor(sp.security)||
        !GetSecurityDescriptorOwner(sp.security,&owner,&defaulted)||!trusted_sid(owner)||
        !GetSecurityDescriptorDacl(sp.security,&present,&acl,&defaulted)||!present||!acl||
        !GetAclInformation(acl,&info,sizeof(info),AclSizeInformation)||info.AceCount>128) return 0;
    for(i=0;i<info.AceCount;++i) {
        ACE_HEADER *header=NULL;
        if(!GetAce(acl,i,(LPVOID *)&header)) return 0;
        if(header->AceType==ACCESS_DENIED_ACE_TYPE) continue;
        if(header->AceType!=ACCESS_ALLOWED_ACE_TYPE) return 0;
        if(!(header->AceFlags&INHERIT_ONLY_ACE)) {
            ACCESS_ALLOWED_ACE *ace=(ACCESS_ALLOWED_ACE *)header;
            if((ace->Mask&mutation)&&!trusted_sid((PSID)&ace->SidStart)) return 0;
        }
    }
    if(!hash_data(sp.security,needed,digest)) return 0;
    if(initial) memcpy(sp.security_hash[index],digest,32);
    else if(memcmp(sp.security_hash[index],digest,32)) return 0;
    return 1;
}
static int identity_check(unsigned index,const WCHAR *path,int directory,int initial) {
    WCHAR normalized[SP_PATH+4]; FILE_ATTRIBUTE_TAG_INFO tag; FILE_STANDARD_INFO standard;
    FILE_ID_INFO id; DWORD n;
    if(!GetFileInformationByHandleEx(*handle_at(index),FileAttributeTagInfo,&tag,sizeof(tag))||
       !GetFileInformationByHandleEx(*handle_at(index),FileStandardInfo,&standard,sizeof(standard))||
       !GetFileInformationByHandleEx(*handle_at(index),FileIdInfo,&id,sizeof(id))) { sp.error=GetLastError(); return 0; }
    if((tag.FileAttributes&FILE_ATTRIBUTE_REPARSE_POINT)||tag.ReparseTag||
       standard.Directory!=(BOOLEAN)(directory!=0)||standard.DeletePending||(!directory&&standard.NumberOfLinks!=1)) return 0;
    n=GetFinalPathNameByHandleW(*handle_at(index),normalized,SP_PATH+4,FILE_NAME_NORMALIZED|VOLUME_NAME_DOS);
    if(!n||n>=SP_PATH+4||wcsncmp(normalized,L"\\\\?\\",4)||_wcsicmp(normalized+4,path)) return 0;
    /* Short aliases rejected lexically; matching canonical long path still uses file ID. */
    if(initial) { sp.identity[index]=id; wcscpy_s(sp.held_path[index],SP_PATH,path); }
    else if(memcmp(&sp.identity[index],&id,sizeof(id))) return 0;
    return security_check(index,initial);
}
static int hold_chain(const WCHAR *path,int directory) {
    WCHAR component[SP_PATH],root[4]; size_t n=wcslen(path),end=3,i; unsigned r;
    if(n>=SP_PATH||path[1]!=L':'||path[2]!=L'\\') return 0;
    root[0]=path[0]; root[1]=L':'; root[2]=L'\\'; root[3]=0;
    if(GetDriveTypeW(root)!=DRIVE_FIXED) return 0;
    for(;;) {
        if(end==n&&!directory) break;
        memcpy(component,path,end*sizeof(WCHAR)); component[end]=0;
        for(r=R_FIRST_DIR;r<R_FIRST_DIR+sp.dir_count;++r) if(!_wcsicmp(sp.held_path[r],component)) break;
        if(r==R_FIRST_DIR+sp.dir_count) {
            if(sp.dir_count>=SP_HANDLES-R_FIRST_DIR) return 0;
            ++sp.dir_count; /* Reserve root before the native acquisition. */
            if(!open_file(r,component,FILE_READ_ATTRIBUTES|READ_CONTROL,FILE_SHARE_READ|FILE_SHARE_WRITE,
                OPEN_EXISTING,FILE_FLAG_BACKUP_SEMANTICS|FILE_FLAG_OPEN_REPARSE_POINT)||
                !identity_check(r,component,1,1)) return 0;
        }
        if(end==n) break;
        i=end; if(i<n&&path[i]==L'\\') ++i;
        while(i<n&&path[i]!=L'\\') ++i;
        end=i;
    }
    return 1;
}
static int streams_only_default(const WCHAR *path) {
    int valid; DWORD error;
    sp.resource[R_FIND].life=R_ENTERED;
    sp.resource[R_FIND].handle=FindFirstStreamW(path,FindStreamInfoStandard,&sp.stream_data,0);
    if(sp.resource[R_FIND].handle==INVALID_HANDLE_VALUE) { sp.error=GetLastError(); sp.resource[R_FIND].life=R_NONE; return 0; }
    sp.resource[R_FIND].life=R_OPEN;
    valid=!wcscmp(sp.stream_data.cStreamName,L"::$DATA");
    if(FindNextStreamW(sp.resource[R_FIND].handle,&sp.stream_data)) valid=0;
    else { error=GetLastError(); if(error!=ERROR_HANDLE_EOF) valid=0; }
    if(!close_one(R_FIND)) valid=0;
    return valid;
}
static int directory_listing(const char *dir,int capsule) {
    WCHAR pattern[SP_PATH]; unsigned count=0,seen=0; int valid=1; DWORD error;
    if(!join(dir,"*",pattern)) {
        /* '*' is forbidden in ordinary paths, permitted only in this fixed enumeration suffix. */
        WCHAR base[SP_PATH]; if(!wide(dir,base,SP_PATH)||swprintf_s(pattern,SP_PATH,L"%ls\\*",base)<0) return 0;
    }
    sp.resource[R_FIND].life=R_ENTERED;
    sp.resource[R_FIND].handle=FindFirstFileW(pattern,&sp.find_data);
    if(sp.resource[R_FIND].handle==INVALID_HANDLE_VALUE) { sp.error=GetLastError(); sp.resource[R_FIND].life=R_NONE; return 0; }
    sp.resource[R_FIND].life=R_OPEN;
    do {
        const WCHAR *name=sp.find_data.cFileName;
        if(++count>64) { valid=0; break; }
        if(!wcscmp(name,L".")||!wcscmp(name,L"..")) continue;
        if(!capsule || (sp.find_data.dwFileAttributes&(FILE_ATTRIBUTE_DIRECTORY|FILE_ATTRIBUTE_REPARSE_POINT))) { valid=0; break; }
        if(!wcscmp(name,L"inert_load_probe.exe")) seen|=1;
        else if(!wcscmp(name,L"owned_slot_inert_exports.dll")) seen|=2;
        else if(!wcscmp(name,L"inert_probe_supervisor.exe")) seen|=4;
        else { valid=0; break; }
    } while(FindNextFileW(sp.resource[R_FIND].handle,&sp.find_data));
    error=GetLastError();
    if(valid&&error!=ERROR_NO_MORE_FILES) valid=0;
    if(!close_one(R_FIND)) valid=0;
    return valid&&(!capsule||seen==7);
}
static const unsigned char *range_at(size_t offset,size_t count,size_t size) {
    if(offset>size||count>size-offset) return NULL;
    return sp.file_bytes+offset;
}
static const unsigned char *rva_at(DWORD rva,size_t count,size_t size,const IMAGE_NT_HEADERS64 *nt) {
    const IMAGE_SECTION_HEADER *section; unsigned i;
    size_t first=(size_t)((const unsigned char *)&nt->OptionalHeader-sp.file_bytes)+nt->FileHeader.SizeOfOptionalHeader;
    section=(const IMAGE_SECTION_HEADER *)range_at(first,(size_t)nt->FileHeader.NumberOfSections*sizeof(*section),size);
    if(!section) return NULL;
    for(i=0;i<nt->FileHeader.NumberOfSections;++i) {
        if(rva>=section[i].VirtualAddress && rva-section[i].VirtualAddress<section[i].SizeOfRawData) {
            DWORD delta=rva-section[i].VirtualAddress;
            if(count>section[i].SizeOfRawData-delta) return NULL;
            return range_at((size_t)section[i].PointerToRawData+delta,count,size);
        }
    }
    return NULL;
}
static int pe_inventory(size_t size,unsigned binary) {
    const IMAGE_DOS_HEADER *dos=(const IMAGE_DOS_HEADER *)range_at(0,sizeof(*dos),size);
    const IMAGE_NT_HEADERS64 *nt; IMAGE_DATA_DIRECTORY imports,exports; unsigned i;
    if(!dos||dos->e_magic!=IMAGE_DOS_SIGNATURE||dos->e_lfanew<0) return 0;
    nt=(const IMAGE_NT_HEADERS64 *)range_at((size_t)dos->e_lfanew,sizeof(*nt),size);
    if(!nt||nt->Signature!=IMAGE_NT_SIGNATURE||nt->FileHeader.Machine!=IMAGE_FILE_MACHINE_AMD64||
       nt->OptionalHeader.Magic!=IMAGE_NT_OPTIONAL_HDR64_MAGIC||nt->FileHeader.NumberOfSections>32||
       nt->FileHeader.SizeOfOptionalHeader!=sizeof(IMAGE_OPTIONAL_HEADER64)||
       nt->OptionalHeader.NumberOfRvaAndSizes!=IMAGE_NUMBEROF_DIRECTORY_ENTRIES||
       !(nt->OptionalHeader.DllCharacteristics&IMAGE_DLLCHARACTERISTICS_GUARD_CF)||
       nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT].VirtualAddress||
       nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_COM_DESCRIPTOR].VirtualAddress) return 0;
    imports=nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    for(i=0;i<16;++i) {
        const IMAGE_IMPORT_DESCRIPTOR *entry=(const IMAGE_IMPORT_DESCRIPTOR *)rva_at(imports.VirtualAddress+i*(DWORD)sizeof(*entry),sizeof(*entry),size,nt);
        const unsigned char *name; size_t n;
        if(!entry) return 0;
        if(!entry->Name) break;
        name=rva_at(entry->Name,1,size,nt); if(!name) return 0;
        n=(size_t)(name-sp.file_bytes);
        if(!range_at(n,64,size)||!memchr(name,0,64)) return 0;
        if(_stricmp((const char *)name,"KERNEL32.dll") &&
           (binary!=2 || (_stricmp((const char *)name,"ADVAPI32.dll")&&_stricmp((const char *)name,"bcrypt.dll")))) return 0;
    }
    if(i==0||i==16||(binary!=2&&i!=1)) return 0;
    exports=nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_EXPORT];
    if(binary!=1) return !exports.VirtualAddress&&!exports.Size;
    {
        const IMAGE_EXPORT_DIRECTORY *ex=(const IMAGE_EXPORT_DIRECTORY *)rva_at(exports.VirtualAddress,sizeof(*ex),size,nt);
        const DWORD *names,*functions; const WORD *ordinals;
        static const char *const expected_names[]={"of_inert_apply_v1","of_inert_descriptor_v1","of_inert_init_v1","of_inert_snapshot_v1"};
        if(!ex||ex->NumberOfFunctions!=4||ex->NumberOfNames!=4) return 0;
        names=(const DWORD *)rva_at(ex->AddressOfNames,16,size,nt);
        functions=(const DWORD *)rva_at(ex->AddressOfFunctions,16,size,nt);
        ordinals=(const WORD *)rva_at(ex->AddressOfNameOrdinals,8,size,nt);
        if(!names||!functions||!ordinals) return 0;
        for(i=0;i<4;++i) {
            const char *name=(const char *)rva_at(names[i],strlen(expected_names[i])+1,size,nt);
            DWORD address;
            if(!name||strcmp(name,expected_names[i])||ordinals[i]>=4) return 0;
            address=functions[ordinals[i]];
            if(!rva_at(address,1,size,nt)||
                (address>=exports.VirtualAddress&&address-exports.VirtualAddress<exports.Size)) return 0;
        }
    }
    return 1;
}
static int binary_check(unsigned i,int initial) {
    static const unsigned indices[3]={R_PROBE,R_TARGET,R_SELF};
    uint64_t expected_size=i==0?141824u:(i==1?118272u:sp.manifest.supervisor_size);
    const char *expected_hash=i==0?probe_hash:(i==1?target_hash:sp.manifest.supervisor_hash);
    unsigned r=indices[i]; LARGE_INTEGER length,zero; char actual[65]; zero.QuadPart=0;
    if(initial&&!open_file(r,sp.path[i],GENERIC_READ|READ_CONTROL,FILE_SHARE_READ,OPEN_EXISTING,FILE_FLAG_OPEN_REPARSE_POINT)) return 0;
    if(!identity_check(r,sp.path[i],0,initial)||!GetFileSizeEx(*handle_at(r),&length)||
       length.QuadPart!=(LONGLONG)expected_size||expected_size>sizeof(sp.file_bytes)||
       !SetFilePointerEx(*handle_at(r),zero,NULL,FILE_BEGIN)||
       !read_exact(r,sp.file_bytes,(DWORD)expected_size)||!hash_data(sp.file_bytes,(ULONG)expected_size,sp.digest)) return 0;
    hex_bytes(sp.digest,32,actual);
    return !strcmp(actual,expected_hash)&&pe_inventory((size_t)expected_size,i)&&(!initial||streams_only_default(sp.path[i]));
}
static int write_new(unsigned index,const char *dir,const char *leaf,const void *bytes,DWORD length) {
    WCHAR path[SP_PATH]; DWORD written=0; int ok;
    if(!join(dir,leaf,path)||!open_file(index,path,GENERIC_WRITE,FILE_SHARE_READ,CREATE_NEW,FILE_ATTRIBUTE_NORMAL)) return 0;
    ok=WriteFile(*handle_at(index),bytes,length,&written,NULL)!=0&&written==length;
    if(!ok) sp.error=GetLastError();
    if(!FlushFileBuffers(*handle_at(index))) { sp.error=GetLastError(); ok=0; }
    if(!close_one(index)) ok=0;
    return ok;
}
static int custody_receipt(const char *leaf) {
    size_t used=0; unsigned i;
    for(i=0;i<SP_HANDLES;++i) if(sp.held_path[i][0]) {
        char id[33],acl[65]; int n;
        hex_bytes(sp.identity[i].FileId.Identifier,16,id); hex_bytes(sp.security_hash[i],32,acl);
        n=_snprintf_s(sp.custody_receipt+used,sizeof(sp.custody_receipt)-used,_TRUNCATE,
            "slot=%u volume=%llu id=%s acl_sha256=%s path=%ls\n",i,
            (unsigned long long)sp.identity[i].VolumeSerialNumber,id,acl,sp.held_path[i]);
        if(n<0) return 0; used+=(size_t)n;
    }
    return write_new(R_FINAL,sp.manifest.evidence,leaf,sp.custody_receipt,(DWORD)used);
}
static int native_admit(void) {
    DWORD needed=0,n; WCHAR actual[SP_PATH],system[SP_PATH],parent[SP_PATH]; unsigned i; NTSTATUS status;
    status=BCryptOpenAlgorithmProvider(&sp.algorithm,BCRYPT_SHA256_ALGORITHM,NULL,0);
    if(status<0) { sp.error=(DWORD)status; return 0; }
    sp.algorithm_open=1;
    sp.resource[R_TOKEN].life=R_ENTERED;
    if(!OpenProcessToken(GetCurrentProcess(),TOKEN_QUERY,&sp.resource[R_TOKEN].handle)) { sp.error=GetLastError(); sp.resource[R_TOKEN].life=R_NONE; return 0; }
    sp.resource[R_TOKEN].life=R_OPEN;
    if(!GetTokenInformation(sp.resource[R_TOKEN].handle,TokenUser,sp.token_info,sizeof(sp.token_info),&needed)) return 0;
    if(!hold_chain(sp.manifest_path,0)||read_small(R_MANIFEST,sp.manifest_path,sp.manifest_text,sizeof(sp.manifest_text),0)!=1||
       !identity_check(R_MANIFEST,sp.manifest_path,0,1)||!parse_manifest(sp.manifest_text,strlen(sp.manifest_text))||
       !hash_data(sp.manifest_text,(ULONG)strlen(sp.manifest_text),sp.digest)) return 0;
    hex_bytes(sp.digest,32,sp.manifest_hash);
    status=BCryptGenRandom(NULL,sp.digest,16,BCRYPT_USE_SYSTEM_PREFERRED_RNG);
    if(status<0) { sp.error=(DWORD)status; return 0; }
    hex_bytes(sp.digest,16,sp.owner);
    if(!lower_hex(sp.owner,32)||!wide(sp.manifest.systemroot,system,SP_PATH)) return 0;
    n=GetWindowsDirectoryW(actual,SP_PATH); if(!n||n>=SP_PATH||_wcsicmp(actual,system)) return 0;
    if(!hold_chain(system,1)||!join(sp.manifest.systemroot,"System32",system)||!hold_chain(system,1)) return 0;
    if(!join(sp.manifest.capsule,"inert_load_probe.exe",sp.path[0])||
       !join(sp.manifest.capsule,"owned_slot_inert_exports.dll",sp.path[1])||
       !join(sp.manifest.capsule,"inert_probe_supervisor.exe",sp.path[2])) return 0;
    n=GetModuleFileNameW(NULL,actual,SP_PATH); if(!n||n>=SP_PATH||_wcsicmp(actual,sp.path[2])) return 0;
    for(i=0;i<3;++i) if(!hold_chain(sp.path[i],0)||!binary_check(i,1)) return 0;
    if(!wide(sp.manifest.control,parent,SP_PATH)||!hold_chain(parent,1)||
       !wide(sp.manifest.evidence,parent,SP_PATH)||!hold_chain(parent,1)||
       !directory_listing(sp.manifest.capsule,1)||!directory_listing(sp.manifest.control,0)||
       !directory_listing(sp.manifest.evidence,0)||!wide(sp.manifest.evidence,sp.cwd,SP_PATH)) return 0;
    /* Fixed alphabet excludes quotes and trailing slash; quoted values cannot escape. */
    if(swprintf_s(sp.command,2048,L"\"%ls\" --artifact \"%ls\" --operation %hs --generation %hs --receipt %hs",
        sp.path[0],sp.path[1],sp.manifest.operation,sp.manifest.generation,sp.manifest_hash)<0) return 0;
    {
        int a=swprintf_s(sp.environment,1024,L"SystemRoot=%hs",sp.manifest.systemroot),b;
        if(a<0) return 0;
        b=swprintf_s(sp.environment+a+1,1024-(size_t)a-1,L"WINDIR=%hs",sp.manifest.systemroot);
        if(b<0||(size_t)a+(size_t)b+2>=1024) return 0;
        sp.environment[(size_t)a+(size_t)b+2]=0; /* sorted Unicode double-NUL block */
    }
    return custody_receipt("custody.before.txt");
}
static int native_recheck(void) {
    unsigned i;
    for(i=R_FIRST_DIR;i<R_FIRST_DIR+sp.dir_count;++i)
        if(!identity_check(i,sp.held_path[i],1,0)) return 0;
    if(!identity_check(R_MANIFEST,sp.manifest_path,0,0)||!directory_listing(sp.manifest.capsule,1)) return 0;
    for(i=0;i<3;++i) if(!binary_check(i,0)) return 0;
    return 1;
}
static int native_pipe(unsigned read_index,unsigned write_index) {
    SECURITY_ATTRIBUTES sa={sizeof(sa),NULL,TRUE}; DWORD flags=0;
    sp.resource[read_index].life=R_ENTERED; sp.resource[write_index].life=R_ENTERED;
    if(!CreatePipe(&sp.resource[read_index].handle,&sp.resource[write_index].handle,&sa,0)) {
        sp.error=GetLastError(); return 0; /* Undefined partial outputs not closed. */
    }
    sp.resource[read_index].life=R_OPEN; sp.resource[write_index].life=R_OPEN;
    if(!SetHandleInformation(*handle_at(read_index),HANDLE_FLAG_INHERIT,0)||
       !GetHandleInformation(*handle_at(read_index),&flags)||(flags&HANDLE_FLAG_INHERIT)||
       !GetHandleInformation(*handle_at(write_index),&flags)||!(flags&HANDLE_FLAG_INHERIT)) return 0;
    return 1;
}
static int native_drain(unsigned which) {
    DWORD available=0,got=0,n; unsigned r=which?R_ERR_READ:R_OUT_READ;
    if(!PeekNamedPipe(*handle_at(r),NULL,0,NULL,&available,NULL)) {
        sp.error=GetLastError(); return sp.error==ERROR_BROKEN_PIPE?2:0;
    }
    if(!available) return 1;
    if(available>SP_TEXT-sp.output_size[which]) return 0;
    n=available<256?available:256;
    if(!ReadFile(*handle_at(r),sp.output[which]+sp.output_size[which],n,&got,NULL)||!got||got>n) { sp.error=GetLastError(); return 0; }
    sp.output_size[which]+=got; return 1;
}
static int native_emit(void) {
    int n,ok=1; const char *state;
    if(!write_new(R_LOG_OUT,sp.manifest.evidence,"child.stdout",sp.output[0],sp.output_size[0])||
       !write_new(R_LOG_ERR,sp.manifest.evidence,"child.stderr",sp.output[1],sp.output_size[1])) ok=0;
    if(!sp.unknown&&!custody_receipt("custody.after.txt")) ok=0;
    if(!ok) fail(400);
    if(sp.work_end&&!sp.unknown&&(!clock_read()||sp.now>=(sp.stopping?sp.settle_end:sp.work_end))) { fail(404); ok=0; }
    state=sp.unknown?"UNKNOWN":(sp.failure?"FAILED":"SETTLED");
    n=_snprintf_s(sp.final,sizeof(sp.final),_TRUNCATE,
        "OF_PROBE_FINAL_V1\noperation=%s\ngeneration=%s\nmanifest=%s\nowner=%s\nexpiry=%llu\nstate=%s\n"
        "first_failure=%u\nfirst_error=%u\nunknown=%u\ncreated=%u\nroot_signal=%u\njob_empty=%u\nexit_seen=%u\nexit=%lu\n"
        "job_flags=%lu\njob_limit=%lu\nmember=%u\ncreates=%u\nresumes=%u\nterminates=%u\n"
        "preflight_end=%llu\nready_end=%llu\nwork_end=%llu\nsettle_end=%llu\nlast_clock=%llu\n"
        "disposed=%u\nstdout_bytes=%u\nstderr_bytes=%u\ncandidate=%u\n",
        sp.manifest.operation,sp.manifest.generation,sp.manifest_hash,sp.owner,(unsigned long long)sp.ready_end,state,
        sp.first_failure,sp.first_error,sp.unknown,sp.created,sp.root_signal,sp.empty,sp.exit_seen,(unsigned long)sp.exit_code,
        (unsigned long)sp.observed_limits.BasicLimitInformation.LimitFlags,
        (unsigned long)sp.observed_limits.BasicLimitInformation.ActiveProcessLimit,sp.member?1u:0u,
        sp.create_calls,sp.resume_calls,sp.terminate_calls,(unsigned long long)sp.preflight_end,
        (unsigned long long)sp.ready_end,(unsigned long long)sp.work_end,(unsigned long long)sp.settle_end,
        (unsigned long long)sp.last_clock,
        sp.disposed,sp.output_size[0],sp.output_size[1],!sp.failure&&!sp.unknown&&sp.disposed?1u:0u);
    if(n<0||!write_new(R_FINAL,sp.manifest.evidence,"final.txt",sp.final,(DWORD)n)) { fail(401); ok=0; }
    if(sp.work_end&&!sp.unknown&&(!clock_read()||sp.now>=(sp.stopping?sp.settle_end:sp.work_end))) { fail(405); ok=0; }
    /* candidate in file is not success: final file close and stdout confirmation required. */
    if(printf("OF_PROBE_CONFIRM_V1 operation=%s generation=%s manifest=%s owner=%s pass=%u unknown=%u\n",
        sp.manifest.operation,sp.manifest.generation,sp.manifest_hash,sp.owner,
        !sp.failure&&!sp.unknown&&sp.disposed?1u:0u,sp.unknown)<0||fflush(stdout)==EOF) { fail(402); ok=0; }
    return ok;
}
static int native_dispatch(enum OP op) {
    BOOL result; DWORD size,flags; JOBOBJECT_BASIC_ACCOUNTING_INFORMATION accounting;
    ++sp.native_calls;
    switch(op) {
    case O_CLOCK: sp.now=GetTickCount64(); return 1;
    case O_ADMIT: return native_admit();
    case O_RECHECK: return native_recheck();
    case O_JOB:
        sp.resource[R_JOB].life=R_ENTERED; sp.resource[R_JOB].handle=CreateJobObjectW(NULL,NULL);
        if(!sp.resource[R_JOB].handle) { sp.error=GetLastError(); sp.resource[R_JOB].life=R_NONE; return 0; }
        sp.resource[R_JOB].life=R_OPEN;
        return GetHandleInformation(*handle_at(R_JOB),&flags)&&!(flags&HANDLE_FLAG_INHERIT);
    case O_SET_LIMIT:
        memset(&sp.limits,0,sizeof(sp.limits));
        sp.limits.BasicLimitInformation.LimitFlags=JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE|JOB_OBJECT_LIMIT_ACTIVE_PROCESS;
        sp.limits.BasicLimitInformation.ActiveProcessLimit=1;
        return SetInformationJobObject(*handle_at(R_JOB),JobObjectExtendedLimitInformation,&sp.limits,sizeof(sp.limits))!=0;
    case O_GET_LIMIT:
        return QueryInformationJobObject(*handle_at(R_JOB),JobObjectExtendedLimitInformation,&sp.observed_limits,sizeof(sp.observed_limits),NULL)!=0;
    case O_PIPE_OUT: return native_pipe(R_OUT_READ,R_OUT_WRITE);
    case O_PIPE_ERR: return native_pipe(R_ERR_READ,R_ERR_WRITE);
    case O_NUL: {
        SECURITY_ATTRIBUTES sa={sizeof(sa),NULL,TRUE};
        sp.resource[R_NUL].life=R_ENTERED;
        sp.resource[R_NUL].handle=CreateFileW(L"NUL",GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_WRITE,&sa,OPEN_EXISTING,0,NULL);
        if(sp.resource[R_NUL].handle==INVALID_HANDLE_VALUE) { sp.error=GetLastError(); sp.resource[R_NUL].life=R_NONE; return 0; }
        sp.resource[R_NUL].life=R_OPEN;
        return GetHandleInformation(*handle_at(R_NUL),&flags)&&(flags&HANDLE_FLAG_INHERIT);
    }
    case O_ATTR_INIT:
        sp.attribute_bytes=0;
        result=InitializeProcThreadAttributeList(NULL,2,0,&sp.attribute_bytes);
        if(result||GetLastError()!=ERROR_INSUFFICIENT_BUFFER||sp.attribute_bytes>sizeof(sp.attributes.bytes)) return 0;
        sp.startup.lpAttributeList=(LPPROC_THREAD_ATTRIBUTE_LIST)sp.attributes.bytes;
        return InitializeProcThreadAttributeList(sp.startup.lpAttributeList,2,0,&sp.attribute_bytes)!=0;
    case O_ATTR_HANDLES:
        sp.inherited[0]=*handle_at(R_NUL); sp.inherited[1]=*handle_at(R_OUT_WRITE); sp.inherited[2]=*handle_at(R_ERR_WRITE);
        return UpdateProcThreadAttribute(sp.startup.lpAttributeList,0,PROC_THREAD_ATTRIBUTE_HANDLE_LIST,sp.inherited,sizeof(sp.inherited),NULL,NULL)!=0;
    case O_ATTR_JOB:
        sp.jobs[0]=*handle_at(R_JOB);
        return UpdateProcThreadAttribute(sp.startup.lpAttributeList,0,PROC_THREAD_ATTRIBUTE_JOB_LIST,sp.jobs,sizeof(sp.jobs),NULL,NULL)!=0;
    case O_READY: return write_new(R_READY,sp.manifest.control,"ready.txt",sp.ready,(DWORD)strlen(sp.ready));
    case O_PERMIT: case O_CANCEL:
        if(!join(sp.manifest.control,op==O_PERMIT?"permit.txt":"cancel.txt",sp.control_path)) return 0;
        size=(DWORD)read_small(op==O_PERMIT?R_PERMIT:R_CANCEL,sp.control_path,sp.incoming,sizeof(sp.incoming),1);
        if(size==1) {
            unsigned r=op==O_PERMIT?R_PERMIT:R_CANCEL;
            if(!identity_check(r,sp.control_path,0,1)||!close_one(r)) return 0;
        }
        return (int)size;
    case O_PAUSE: Sleep(100); return 1;
    case O_CREATE:
        sp.startup.StartupInfo.cb=sizeof(sp.startup);
        sp.startup.StartupInfo.dwFlags=STARTF_USESTDHANDLES;
        sp.startup.StartupInfo.hStdInput=sp.inherited[0];
        sp.startup.StartupInfo.hStdOutput=sp.inherited[1]; sp.startup.StartupInfo.hStdError=sp.inherited[2];
        sp.resource[R_PROCESS].life=R_ENTERED; sp.resource[R_THREAD].life=R_ENTERED;
        result=CreateProcessW(sp.path[0],sp.command,NULL,NULL,TRUE,
            CREATE_SUSPENDED|CREATE_NO_WINDOW|CREATE_UNICODE_ENVIRONMENT|EXTENDED_STARTUPINFO_PRESENT,
            sp.environment,sp.cwd,&sp.startup.StartupInfo,&sp.pi);
        if(!result) { sp.error=GetLastError(); return 0; /* Failed PI remains undefined/unusable. */ }
        sp.resource[R_PROCESS].life=R_OPEN; sp.resource[R_THREAD].life=R_OPEN;
        return sp.pi.hProcess&&sp.pi.hThread;
    case O_MEMBER: return IsProcessInJob(sp.pi.hProcess,*handle_at(R_JOB),&sp.member)!=0;
    case O_RESUME: sp.resume_previous=ResumeThread(sp.pi.hThread); return sp.resume_previous!=MAXDWORD;
    case O_DRAIN_OUT: return native_drain(0);
    case O_DRAIN_ERR: return native_drain(1);
    case O_WAIT:
        sp.wait_result=WaitForSingleObject(sp.pi.hProcess,0);
        if(sp.wait_result==WAIT_OBJECT_0) return 1;
        if(sp.wait_result==WAIT_TIMEOUT) return 2;
        sp.error=GetLastError(); return 0;
    case O_ACTIVE:
        if(!QueryInformationJobObject(*handle_at(R_JOB),JobObjectBasicAccountingInformation,&accounting,sizeof(accounting),NULL)) return 0;
        sp.active=accounting.ActiveProcesses; return 1;
    case O_EXIT: return GetExitCodeProcess(sp.pi.hProcess,&sp.exit_code)!=0;
    case O_TERMINATE: return TerminateJobObject(*handle_at(R_JOB),0xE001u)!=0;
    case O_ATTR_DELETE: DeleteProcThreadAttributeList(sp.startup.lpAttributeList); return 1;
    case O_CLOSE: return native_close(sp.current_resource);
    case O_EMIT: return native_emit();
    default: return 0;
    }
}
static int native_call(enum OP op) {
    int result;
    sp.error=0; SetLastError(ERROR_SUCCESS);
    result=native_dispatch(op);
    if(result) sp.error=0; /* Expected absent/pending/EOF is not a failure error. */
    else if(!sp.error) {
        sp.error=GetLastError();
        if(!sp.error) sp.error=ERROR_INVALID_DATA;
    }
    return result;
}
int wmain(int argc,WCHAR **argv) {
    char path[SP_PATH]; size_t i,n; int pass;
    sp.stage=S_INPUT;
    if(argc!=3||wcscmp(argv[1],L"--manifest")) return 2;
    n=wcsnlen_s(argv[2],SP_PATH); if(n>=SP_PATH) return 2;
    for(i=0;i<=n;++i) { if(argv[2][i]>126) return 2; path[i]=(char)argv[2][i]; }
    if(!ascii_path(path)||!wide(path,sp.manifest_path,SP_PATH)) return 2;
    pass=run_operation();
    if(sp.algorithm_open) {
        NTSTATUS status=BCryptCloseAlgorithmProvider(sp.algorithm,0);
        if(status<0) { sp.error=(DWORD)status; fail(403); } else sp.algorithm_open=0;
    }
    /* Reopen-free custody receipt formatting no longer needs the crypto provider. */
    if(sp.manifest.evidence[0]) checked(O_EMIT);
    if(sp.work_end&&!sp.unknown&&(!clock_read()||sp.now>=(sp.stopping?sp.settle_end:sp.work_end))) fail(406);
    if(sp.unknown&&!sp.disposed) {
        /* No retry/relaunch. Retain exact handles for separately directed safe settlement.
         * Operator must retain tool session; killing this owner is outside supported cancel. */
        for(;;) Sleep(1000);
    }
    return pass&&!sp.failure?0:1;
}
#endif
