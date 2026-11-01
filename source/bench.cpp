#include "kernels.hpp"
#include <chrono>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <random>
#include <sstream>
#include <cstdlib>

struct PerfGate {
    std::ofstream ctl;
    std::ifstream ack;
    bool enabled=false;
    PerfGate() {
        const char* c=std::getenv("TOPK_PERF_CTL");
        const char* a=std::getenv("TOPK_PERF_ACK");
        if(c && a) {
            ctl.open(c); ack.open(a);
            if(!ctl || !ack) throw std::runtime_error("cannot open perf control FIFOs");
            enabled=true;
        }
    }
    void command(const char* s) {
        if(!enabled) return;
        ctl<<s<<'\n'<<std::flush;
        std::string response;
        if(!std::getline(ack,response)) throw std::runtime_error("perf acknowledgement EOF");
        response.erase(std::remove(response.begin(),response.end(),'\0'),response.end());
        if(response!="ack") throw std::runtime_error("perf acknowledgement failed: "+response);
    }
};

template<class T> std::vector<T> reference(std::vector<T> x,size_t k) {
    std::sort(x.begin(),x.end());
    k=std::min(k,x.size());
    return {x.end()-k,x.end()};
}
template<class T> uint64_t checksum(const std::vector<T>& x) {
    uint64_t h=1469598103934665603ULL;
    for(T v:x) {
        const auto* b=reinterpret_cast<const unsigned char*>(&v);
        for(size_t j=0;j<sizeof(T);++j) h=(h^b[j])*1099511628211ULL;
    }
    return h;
}
template<class T> std::vector<T> read_csv(const std::string& path) {
    std::ifstream f(path); if(!f) throw std::runtime_error("cannot read "+path);
    std::string line; std::getline(f,line);
    if(!line.empty() && line.back()=='\r') line.pop_back();
    if(line!="score") throw std::runtime_error("expected one-column CSV header score");
    std::vector<T> x;
    while(std::getline(f,line)) {
        if(!line.empty() && line.back()=='\r') line.pop_back();
        size_t pos=0; double d=std::stod(line,&pos);
        if(pos!=line.size() || !std::isfinite(d)) throw std::runtime_error("invalid/nonfinite score");
        if constexpr(std::is_same_v<T,int32_t>)
            if(d<std::numeric_limits<int32_t>::min() || d>std::numeric_limits<int32_t>::max() || d!=std::trunc(d))
                throw std::runtime_error("score not representable as int32");
        x.push_back(static_cast<T>(d));
    }
    return x;
}
template<class T> void run(const std::string& file,const std::string& method,size_t k,size_t reps,bool diag) {
    auto x=read_csv<T>(file);
    auto expected=reference(x,k); // Outside timed region.
    topk::Counts warm;
    if(topk::select(x,k,method,warm)!=expected) throw std::runtime_error("warmup correctness failure");
    PerfGate gate;
    std::cout<<"method,n,k,rep,ns,checksum,visited,passed,updates,batches,diagnostic\n";
    for(size_t r=0;r<reps;++r) {
        topk::Counts c;
        gate.command("enable");
        auto start=std::chrono::steady_clock::now();
        auto out=diag ? topk::select<T,true>(x,k,method,c) : topk::select<T,false>(x,k,method,c);
        auto end=std::chrono::steady_clock::now();
        gate.command("disable");
        if(out!=expected) throw std::runtime_error("correctness failure");
        auto ns=std::chrono::duration_cast<std::chrono::nanoseconds>(end-start).count();
        std::cout<<method<<','<<x.size()<<','<<k<<','<<r<<','<<ns<<','<<checksum(out)<<',';
        if(diag && method!="stl") std::cout<<c.visited<<','<<c.passed<<','<<c.updates<<','<<c.batches;
        else std::cout<<"NA,NA,NA,NA";
        std::cout<<','<<diag<<'\n';
    }
}
template<class T> size_t check_cases() {
    std::mt19937 rng(20261024); size_t checked=0;
    for(size_t n: {0u,1u,2u,3u,7u,8u,9u,15u,16u,17u,31u,64u,129u}) {
        for(int pattern=0;pattern<7;++pattern) {
            std::vector<T> x(n);
            for(size_t i=0;i<n;++i) {
                double v=pattern==0 ? double(i) : pattern==1 ? -double(i) : pattern==2 ? 3 :
                    pattern==3 ? int(rng()%7)-3 : int(rng()%100000)-50000;
                if(pattern==5) v=i%2 ? std::numeric_limits<int32_t>::max() : std::numeric_limits<int32_t>::min();
                if(pattern==6 && std::is_same_v<T,double>) v/=7.0;
                x[i]=static_cast<T>(v);
            }
            for(size_t k: {size_t(0),size_t(1),size_t(2),size_t(5),n,n+1}) {
                auto want=reference(x,k); uint64_t expected_updates=0;
                for(const auto& m:topk::methods) {
                    if(m.find("avx2")!=std::string::npos && !__builtin_cpu_supports("avx2")) continue;
                    topk::Counts c;
                    if(topk::select<T,true>(x,k,m,c)!=want) throw std::runtime_error("self-test failed: "+m);
                    if(m=="heap_scalar") expected_updates=c.updates;
                    if(m!="stl" && c.updates!=expected_updates) throw std::runtime_error("update trajectory mismatch");
                    ++checked;
                }
            }
        }
    }
    return checked;
}
size_t number(const char* p) {
    std::string s(p); if(s.empty() || s[0]=='-') throw std::runtime_error("nonnegative integer required");
    size_t pos; auto n=std::stoull(s,&pos);
    if(pos!=s.size()) throw std::runtime_error("invalid integer");
    return n;
}
int main(int argc,char** argv) {
    try {
        if(argc==2 && std::string(argv[1])=="--self-test") {
            std::cout<<"PASS "<<check_cases<int32_t>()+check_cases<double>()<<" method/case checks\n"; return 0;
        }
        if(argc==2 && std::string(argv[1])=="--version") {
            std::cout<<"compiler="<<__VERSION__<<" libstdcxx="<<__GLIBCXX__
                     <<" avx2="<<bool(__builtin_cpu_supports("avx2"))<<'\n'; return 0;
        }
        if(argc<6 || argc>7) throw std::runtime_error("usage: bench DATA.csv int32|float64 METHOD K REPS [diagnostic]");
        std::string dtype=argv[2]; bool diag=argc==7;
        if(diag && std::string(argv[6])!="diagnostic") throw std::runtime_error("expected diagnostic");
        size_t k=number(argv[4]), reps=number(argv[5]);
        if(!reps) throw std::runtime_error("REPS must be positive");
        if(dtype=="int32") run<int32_t>(argv[1],argv[3],k,reps,diag);
        else if(dtype=="float64") run<double>(argv[1],argv[3],k,reps,diag);
        else throw std::runtime_error("unsupported dtype");
    } catch(const std::exception& e) { std::cerr<<e.what()<<'\n'; return 1; }
}
