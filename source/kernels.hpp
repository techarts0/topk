#pragma once
#include <algorithm>
#include <bit>
#include <cstdint>
#include <cstring>
#include <functional>
#include <immintrin.h>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <vector>

namespace topk {
struct Counts { uint64_t visited=0, passed=0, updates=0, batches=0; };

// Both stores own a contiguous array. Their ordering invariants differ.
template<class T, bool Array> struct Store {
    std::vector<T> a;
    Store(const std::vector<T>& input, size_t k): a(input.begin(), input.begin()+k) {
        if constexpr(Array) std::sort(a.begin(), a.end());
        else std::make_heap(a.begin(), a.end(), std::greater<T>());
    }
    T threshold() const { return a.front(); }
    void replace(T x) {
        if constexpr(Array) {
            auto pos=std::lower_bound(a.begin()+1, a.end(), x);
            size_t n=static_cast<size_t>(pos-a.begin()-1);
            std::memmove(a.data(), a.data()+1, n*sizeof(T));
            a[n]=x;
        } else {
            // One sift-down, rather than a pop followed by a push.
            size_t p=0;
            while (2*p+1<a.size()) {
                size_t c=2*p+1;
                if(c+1<a.size() && a[c+1]<a[c]) ++c;
                if(!(a[c]<x)) break;
                a[p]=a[c]; p=c;
            }
            a[p]=x;
        }
    }
    std::vector<T> finish() {
        if constexpr(!Array) std::sort_heap(a.begin(),a.end(),std::greater<T>());
        // All methods return ascending top-k values, preserving multiplicity.
        if constexpr(!Array) std::reverse(a.begin(),a.end());
        return std::move(a);
    }
};

template<class T> constexpr size_t width=32/sizeof(T);
// Explicitly scalar mask construction isolates batching from SIMD. GCC only.
template<class T> __attribute__((noinline,optimize("no-tree-vectorize")))
uint32_t scalar_mask(const T* p,T t) {
    uint32_t m=0;
    for(size_t j=0;j<width<T>;++j) if(p[j]>t) m|=1u<<j;
    return m;
}
template<class T,bool Array,int Filter,bool Diagnostic>
std::vector<T> kernel(const std::vector<T>& input,size_t k,Counts& counts) {
    k=std::min(k,input.size());
    if(k==0) return {};
    Store<T,Array> s(input,k);
    size_t i=k;
    if constexpr(Filter!=0) {
        for(;i+width<T><=input.size();i+=width<T>) {
            T old=s.threshold();
            uint32_t mask=scalar_mask(input.data()+i,old);
            if constexpr(Diagnostic) {
                counts.visited+=width<T>; ++counts.batches;
                counts.passed+=std::popcount(mask);
            }
            // A stale threshold permits false positives, never false negatives.
            // Recheck in original arrival order with the current threshold.
            while(mask) {
                auto j=std::countr_zero(mask); mask&=mask-1;
                T x=input[i+j];
                if(x>s.threshold()) {
                    s.replace(x);
                    if constexpr(Diagnostic) ++counts.updates;
                }
            }
        }
    }
    for(;i<input.size();++i) {
        if constexpr(Diagnostic) ++counts.visited;
        if(input[i]>s.threshold()) {
            if constexpr(Diagnostic) {++counts.passed; ++counts.updates;}
            s.replace(input[i]);
        }
    }
    return s.finish();
}

// Keep the AVX2 comparison inside the hot scan loop. The v1 implementation
// called a noinline helper once per vector and paid call/return overhead for
// every four doubles; this target-specific kernel lets GCC inline it safely.
template<class T,bool Array,bool Diagnostic>
__attribute__((target("avx2")))
std::vector<T> kernel_avx2(const std::vector<T>& input,size_t k,Counts& counts) {
    k=std::min(k,input.size());
    if(k==0) return {};
    Store<T,Array> s(input,k);
    size_t i=k;
    for(;i+width<T><=input.size();i+=width<T>) {
        T old=s.threshold();
        uint32_t mask;
        if constexpr(std::is_same_v<T,int32_t>) {
            auto x=_mm256_loadu_si256(reinterpret_cast<const __m256i*>(input.data()+i));
            auto c=_mm256_cmpgt_epi32(x,_mm256_set1_epi32(old));
            mask=static_cast<uint32_t>(_mm256_movemask_ps(_mm256_castsi256_ps(c)));
        } else {
            auto x=_mm256_loadu_pd(input.data()+i);
            mask=static_cast<uint32_t>(_mm256_movemask_pd(
                _mm256_cmp_pd(x,_mm256_set1_pd(old),_CMP_GT_OQ)));
        }
        if constexpr(Diagnostic) {
            counts.visited+=width<T>; ++counts.batches;
            counts.passed+=std::popcount(mask);
        }
        // A stale threshold permits false positives, never false negatives.
        // Recheck in original arrival order with the current threshold.
        while(mask) {
            auto j=std::countr_zero(mask); mask&=mask-1;
            T x=input[i+j];
            if(x>s.threshold()) {
                s.replace(x);
                if constexpr(Diagnostic) ++counts.updates;
            }
        }
    }
    for(;i<input.size();++i) {
        if constexpr(Diagnostic) ++counts.visited;
        if(input[i]>s.threshold()) {
            if constexpr(Diagnostic) {++counts.passed; ++counts.updates;}
            s.replace(input[i]);
        }
    }
    return s.finish();
}

template<class T,bool Diagnostic=false>
std::vector<T> select(const std::vector<T>& input,size_t k,const std::string& method,Counts& c) {
    if(method.find("avx2")!=std::string::npos && !__builtin_cpu_supports("avx2"))
        throw std::runtime_error("AVX2 unavailable on this CPU/OS");
    if(method=="heap_scalar") return kernel<T,false,0,Diagnostic>(input,k,c);
    if(method=="heap_batch") return kernel<T,false,1,Diagnostic>(input,k,c);
    if(method=="heap_avx2") return kernel_avx2<T,false,Diagnostic>(input,k,c);
    if(method=="array_scalar") return kernel<T,true,0,Diagnostic>(input,k,c);
    if(method=="array_batch") return kernel<T,true,1,Diagnostic>(input,k,c);
    if(method=="array_avx2") return kernel_avx2<T,true,Diagnostic>(input,k,c);
    if(method=="stl") {
        std::vector<T> out(std::min(k,input.size()));
        std::partial_sort_copy(input.begin(),input.end(),out.begin(),out.end(),std::greater<T>());
        std::reverse(out.begin(),out.end());
        return out;
    }
    throw std::runtime_error("unknown method: "+method);
}
inline const std::vector<std::string> methods={"heap_scalar","heap_batch","heap_avx2",
    "array_scalar","array_batch","array_avx2","stl"};
}
